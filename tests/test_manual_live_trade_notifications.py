import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from trader.common.config import Config
from trader.common.logger import Logger
from trader.common.message import Message, MessageType
from trader.notify.notify_manager import NotifyManager
from trader.notify.trade_notification import (
    ManualNotifySmokeKline,
    ManualTradeAccountState,
    ManualTradeNotificationEvent,
    normalize_live_execution_mode,
    build_manual_notify_smoke_event,
    render_manual_trade_email,
)
from trader.strategy.trader_result import TraderResult
from trader.task.task_config import TaskConfig, parse_task_config
from trader.task.task_type import TaskType
from trader.task.trader_task import TraderTask
from trader.utils.operate import Operate, OperateType
from trader.utils.symbol_interval import Interval, SymbolInterval


def _result_with_operation(op: Operate) -> TraderResult:
    return TraderResult(
        0.0,
        0.0,
        timedelta(0),
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0,
        0,
        [op],
        0.0,
        10,
    )


def _manual_task(free=1000.0, manual_start_position=0.0) -> TraderTask:
    cfg = Config(cash=10000.0)
    tcfg = TaskConfig(
        id=7,
        ttype=TaskType.TRADER,
        symbol_interval=SymbolInterval("BTC-USDT", Interval.INTERVAL_1m),
        strategies=["always_buy"],
        free=free,
        live_execution_mode="manual_notify",
        manual_start_position=manual_start_position,
    )
    return TraderTask(tcfg, cfg, Logger(cfg), db_manager=None, exchange=ExplodingExchange())


class ExplodingExchange:
    def __init__(self):
        self.new_order_calls = []

    def get_account_balance(self, asset):
        raise AssertionError(f"manual mode must not read exchange balance for {asset}")

    def new_order(self, *args, **kwargs):
        self.new_order_calls.append((args, kwargs))
        raise AssertionError("manual mode must not place exchange orders")


class RecordingNotice:
    tp = SimpleNamespace(name="MAIL_TEST")

    def __init__(self):
        self.sent = []

    def send(self, content, title="Trader"):
        self.sent.append((title, content))
        return None


def test_parse_task_config_accepts_manual_notify_mode_and_start_position():
    tasks = parse_task_config(
        json.dumps(
            [
                {
                    "task_type": "TRADER",
                    "symbol": "BTC-USDT",
                    "interval": "1m",
                    "strategy": "macd_triple_divergence",
                    "free": 2500,
                    "live_execution_mode": "manual_notify",
                    "manual_start_position": 0.125,
                }
            ]
        )
    )

    assert len(tasks) == 1
    assert tasks[0].live_execution_mode == "manual_notify"
    assert tasks[0].manual_start_position == 0.125
    assert tasks[0].to_dict()["live_execution_mode"] == "manual_notify"
    assert tasks[0].to_dict()["manual_start_position"] == 0.125


def test_parse_task_config_accepts_staged_auto_trade_options():
    tasks = parse_task_config(
        json.dumps(
            [
                {
                    "task_type": "TRADER",
                    "symbol": "BTC-USDT",
                    "interval": "1m",
                    "strategy": "macd_triple_divergence",
                    "free": 2500,
                    "live_execution_mode": "small_live_auto",
                    "live_trade_max_notional": 15,
                    "live_short_execution": "margin_cross",
                }
            ]
        )
    )

    assert len(tasks) == 1
    assert tasks[0].live_execution_mode == "small_live_auto"
    assert tasks[0].live_trade_max_notional == 15.0
    assert tasks[0].live_short_execution == "margin_cross"
    assert tasks[0].to_dict()["live_trade_max_notional"] == 15.0
    assert tasks[0].to_dict()["live_short_execution"] == "margin_cross"


def test_normalize_live_execution_mode_preserves_staged_modes_and_rejects_unknown():
    assert normalize_live_execution_mode("small_live_auto") == "small_live_auto"
    assert normalize_live_execution_mode("full_live_auto") == "full_live_auto"

    with pytest.raises(ValueError, match="paper_auto is no longer supported"):
        normalize_live_execution_mode("paper_auto")

    with pytest.raises(ValueError, match="unsupported live_execution_mode"):
        normalize_live_execution_mode("surprise")


def test_manual_buy_operation_creates_entry_notification_and_updates_local_state():
    task = _manual_task(free=1000.0)
    ret = _result_with_operation(Operate(OperateType.BUY, 1714281600, 100.0))

    events = task.handle_manual_trade_notifications(ret)

    assert len(events) == 1
    event = events[0]
    assert event.action == "ENTRY"
    assert event.side == "BUY"
    assert event.market == "BTCUSDT"
    assert event.strategy == "always_buy"
    assert event.suggested_amount == 1000.0
    assert event.suggested_quantity == 10.0
    assert event.local_state.cash_after == 0.0
    assert event.local_state.position_after == 10.0
    assert task.exchange.new_order_calls == []


def test_manual_sell_operation_creates_exit_notification_from_local_position_without_balance_sync():
    task = _manual_task(free=500.0, manual_start_position=0.25)
    ret = _result_with_operation(Operate(OperateType.SELL, 1714281660, 120.0))

    events = task.handle_manual_trade_notifications(ret)

    assert len(events) == 1
    event = events[0]
    assert event.action == "EXIT"
    assert event.side == "SELL"
    assert event.suggested_quantity == 0.25
    assert event.suggested_amount == 30.0
    assert event.trigger_reason == "signal_exit"
    assert event.local_state.cash_after == 530.0
    assert event.local_state.position_after == 0.0
    assert task.exchange.new_order_calls == []


def test_process_result_preserves_current_operation_as_latest_after_history_merge():
    async def _test():
        task = _manual_task(free=500.0, manual_start_position=0.25)
        previous = _result_with_operation(Operate(OperateType.BUY, 1714281600, 100.0))
        current = _result_with_operation(Operate(OperateType.SELL, 1714281660, 120.0))
        saved = []

        async def add_tasks(tasks):
            saved.extend(tasks)

        task.db_manager = SimpleNamespace(
            task=SimpleNamespace(
                get_task=lambda task_id: SimpleNamespace(tret=previous),
                add_tasks=add_tasks,
            )
        )

        await task.process_result(current)

        assert [op.otype for op in current.opts] == [OperateType.BUY, OperateType.SELL]
        assert saved == [task.ts]

    asyncio.run(_test())


def test_manual_notification_event_includes_risk_references_without_advanced_order_claims():
    event = ManualTradeNotificationEvent(
        market="BTCUSDT",
        interval="1m",
        strategy="risk_strategy",
        strategy_id="7",
        task_id=9,
        mode="manual_notify",
        action="ENTRY",
        side="LONG",
        signal_time=1714281600,
        signal_price=100.0,
        suggested_amount=1000.0,
        suggested_quantity=10.0,
        trigger_reason="signal_entry",
        local_state=ManualTradeAccountState(cash_before=1000.0, cash_after=0.0, position_before=0.0, position_after=10.0),
        stop_loss=92.0,
        take_profit=116.0,
        risk_reward_ratio=2.0,
        signal_event_id="macd-triple-1",
        breakeven_new_stop=100.0,
        breakeven_step=1,
    )

    content = render_manual_trade_email(event)

    assert "<html" in content
    assert "手动实盘操作建议" in content
    assert "BTCUSDT" in content
    assert "1m" in content
    assert "manual_notify" in content
    assert "策略ID" in content
    assert "macd-triple-1" in content
    assert "操作建议" in content
    assert "进场" in content
    assert "LONG" in content
    assert "1000.000000" in content
    assert "10.00000000" in content
    assert "风险参考" in content
    assert "92.000000" in content
    assert "116.000000" in content
    assert "100.000000" in content
    assert "保本触发 step" in content
    assert "2.000000" in content
    assert "不是交易所成交确认" in content
    assert "已经提交交易所止损" not in content
    assert "OCO" not in content


def test_manual_notification_email_formats_nested_metadata_as_collapsible_json():
    event = ManualTradeNotificationEvent(
        market="BTCUSDT",
        interval="1d",
        strategy="macd_triple_divergence",
        strategy_id="7",
        task_id=9,
        mode="manual_notify",
        action="ENTRY",
        side="LONG",
        signal_time=1714281600,
        signal_price=100.0,
        suggested_amount=1000.0,
        suggested_quantity=10.0,
        trigger_reason="signal_entry",
        local_state=ManualTradeAccountState(cash_before=1000.0, cash_after=0.0, position_before=0.0, position_after=10.0),
        divergence_metadata={
            "conditions": {"price_lower_lows": {"passed": True, "values": [1, 2, 3]}},
            "direction": "LONG",
        },
    )

    content = render_manual_trade_email(event)

    assert "<details" in content
    assert "<summary>conditions</summary>" in content
    assert "json-block" in content
    assert "{&quot;conditions&quot;" not in content
    assert "price_lower_lows" in content
    assert "  &quot;passed&quot;: true" in content


def test_manual_risk_update_operation_creates_notification_without_changing_local_position():
    task = _manual_task(free=500.0, manual_start_position=0.25)
    op = Operate(OperateType.RISK_UPDATE, 1714281660, 120.0)
    op.trigger_reason = "breakeven_move"
    op.stop_loss = 118.0
    op.breakeven_old_stop = 100.0
    op.breakeven_new_stop = 118.0
    op.breakeven_step = 2

    events = task.handle_manual_trade_notifications(_result_with_operation(op))

    assert len(events) == 1
    event = events[0]
    assert event.action == "RISK_UPDATE"
    assert event.side == "RISK_UPDATE"
    assert event.trigger_reason == "breakeven_move"
    assert event.stop_loss == 118.0
    assert event.breakeven_new_stop == 118.0
    assert event.breakeven_step == 2
    assert event.local_state.cash_before == 500.0
    assert event.local_state.cash_after == 500.0
    assert event.local_state.position_before == 0.25
    assert event.local_state.position_after == 0.25


def test_notify_manager_sends_manual_trade_notification_events():
    notice = RecordingNotice()
    manager = NotifyManager(Config(), Logger(Config()))
    manager.notice = [notice]
    event = ManualTradeNotificationEvent(
        market="ETHUSDT",
        strategy="manual_strategy",
        task_id=3,
        mode="manual_notify",
        action="EXIT",
        side="SELL",
        signal_time=1714281660,
        signal_price=2000.0,
        suggested_amount=400.0,
        suggested_quantity=0.2,
        trigger_reason="stop_loss",
        local_state=ManualTradeAccountState(cash_before=0.0, cash_after=400.0, position_before=0.2, position_after=0.0),
    )
    msg = Message(MessageType.STAT, SimpleNamespace(manual_trade_notifications=[event]))

    manager.handler(msg)

    assert len(notice.sent) == 1
    title, content = notice.sent[0]
    assert title == "[手动实盘] ETHUSDT 出场 SELL @ 2000.000000"
    assert "ETHUSDT" in content
    assert "出场" in content
    assert "stop_loss" in content


def test_notify_manager_manual_notification_smoke_reports_delivery_status():
    manager = NotifyManager(Config(), Logger(Config()))
    notice = RecordingNotice()
    manager.notice = [notice]
    event = build_manual_notify_smoke_event(ManualNotifySmokeKline(open_time=1714281600, close=123.45))

    sent = manager.send_manual_trade_notification(event)

    assert sent == [{"notice_type": "MAIL_TEST", "recipient": None, "ok": True, "error": None}]
    assert len(notice.sent) == 1


def test_notify_manager_does_not_fallback_to_raw_operate_when_manual_notifications_are_empty():
    notice = RecordingNotice()
    manager = NotifyManager(Config(), Logger(Config()))
    manager.notice = [notice]
    op = Operate(OperateType.CLOSE, 1714281660, 2000.0)
    msg = Message(
        MessageType.STAT,
        SimpleNamespace(
            manual_trade_notifications=[],
            tret=SimpleNamespace(opts=[op]),
        ),
    )

    manager.handler(msg)

    assert notice.sent == []


def test_notify_manager_legacy_operate_notification_is_html_not_raw_dict():
    notice = RecordingNotice()
    manager = NotifyManager(Config(), Logger(Config()))
    manager.notice = [notice]
    op = Operate(OperateType.CLOSE, 1714281660, 2000.0)
    msg = Message(MessageType.STAT, SimpleNamespace(tret=SimpleNamespace(opts=[op])))

    manager.handler(msg)

    assert len(notice.sent) == 1
    title, content = notice.sent[0]
    assert title == "[策略信号] CLOSE @ 2000.000000"
    assert "<html" in content
    assert "策略信号提醒" in content
    assert "{'type': 'CLOSE'" not in content


def test_manual_task_notification_maps_dashboard_correlation_fields_from_operation():
    task = _manual_task(free=1000.0)
    op = Operate(OperateType.BUY, 1714281600, 100.0)
    op.signal_event_id = "macd-triple-1"
    op.stop_loss = 95.0
    op.take_profit = 110.0
    op.breakeven_new_stop = 100.0
    op.breakeven_step = 1

    events = task.handle_manual_trade_notifications(_result_with_operation(op))

    assert len(events) == 1
    event = events[0]
    assert event.strategy_id == str(task.tcfg.id)
    assert event.interval == "1m"
    assert event.signal_event_id == "macd-triple-1"
    assert event.stop_loss == 95.0
    assert event.take_profit == 110.0
    assert event.breakeven_new_stop == 100.0
    assert event.breakeven_step == 1


def test_notice_config_accepts_multiple_recipients():
    from trader.notify.notify_type import parse_notice_config

    notices = parse_notice_config(
        json.dumps(
            [
                {
                    "type": "MAIL_LARK",
                    "sender": "sender@example.com",
                    "password": "smtp-auth-code",
                    "recipient": ["first@example.com", "second@example.com"],
                }
            ]
        )
    )

    assert len(notices) == 1
    assert notices[0].recipients == ["first@example.com", "second@example.com"]
    assert notices[0].recipient == "first@example.com,second@example.com"


def test_notice_config_ignores_unknown_notice_type():
    from trader.notify.notify_type import parse_notice_config

    notices = parse_notice_config(
        json.dumps(
            [
                {
                    "type": "LARK_GMAIL",
                    "sender": "sender@example.com",
                    "password": "smtp-auth-code",
                    "recipient": "recipient@example.com",
                }
            ]
        )
    )

    assert notices == []


def test_notice_config_missing_file_path_reports_exact_missing_file(tmp_path):
    from trader.notify.notify_type import parse_notice_config

    missing_path = tmp_path / "notice.json"

    with pytest.raises(FileNotFoundError, match="notice config file not found"):
        parse_notice_config(str(missing_path))


def test_notify_mail_sends_to_multiple_recipients(monkeypatch):
    from trader.notify.notify_type import NotifyMail, NotifyType

    sent = {}

    class FakeSMTP:
        def __init__(self, server, port):
            sent["server"] = server
            sent["port"] = port

        def login(self, sender, password):
            sent["login"] = (sender, password)

        def sendmail(self, sender, recipients, message):
            sent["sendmail"] = (sender, recipients, message)

        def quit(self):
            sent["quit"] = True

    monkeypatch.setattr("smtplib.SMTP_SSL", FakeSMTP)
    notice = NotifyMail(
        NotifyType.MAIL_LARK,
        "smtp.larksuite.com",
        465,
        sender="sender@example.com",
        password="smtp-auth-code",
        recipients=["first@example.com", "second@example.com"],
    )

    err = notice.send("content", "subject")

    assert err is None
    assert sent["sendmail"][1] == ["first@example.com", "second@example.com"]
    assert "To: first@example.com,second@example.com" in sent["sendmail"][2]


def test_notify_mail_sends_html_content_as_html_mime(monkeypatch):
    from trader.notify.notify_type import NotifyMail, NotifyType

    sent = {}

    class FakeSMTP:
        def __init__(self, server, port):
            pass

        def login(self, sender, password):
            pass

        def sendmail(self, sender, recipients, message):
            sent["message"] = message

        def quit(self):
            pass

    monkeypatch.setattr("smtplib.SMTP_SSL", FakeSMTP)
    notice = NotifyMail(
        NotifyType.MAIL_LARK,
        "smtp.larksuite.com",
        465,
        sender="sender@example.com",
        password="smtp-auth-code",
        recipients=["first@example.com"],
    )

    err = notice.send("<!doctype html><html><body>content</body></html>", "subject")

    assert err is None
    assert "Content-Type: text/html" in sent["message"]


def test_real_email_smoke_event_is_generated_by_minimal_one_minute_strategy():
    event = build_manual_notify_smoke_event(ManualNotifySmokeKline(open_time=1714281600, close=123.45))

    assert event.market == "SMOKEUSDT"
    assert event.strategy == "always_trigger_1m_smoke"
    assert event.action == "ENTRY"
    assert event.side == "BUY"
    assert event.signal_time == 1714281600
    assert event.signal_price == 123.45


@pytest.mark.skipif(
    not pytest.importorskip("os").environ.get("TRADER_MANUAL_NOTIFY_E2E_NOTICE"),
    reason="requires TRADER_MANUAL_NOTIFY_E2E_NOTICE with real mail credentials",
)
def test_real_email_smoke_requires_explicit_notice_configuration():
    from trader.notify.trade_notification import run_real_email_smoke

    result = run_real_email_smoke()

    assert result["sent"] is True
    assert result["recipient"]
    assert result["subject"] == "manual trade notification smoke"
