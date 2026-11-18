from email import message_from_string

from trader.adapters.outbound.email.sender import EmailNotificationSender
from trader.core.notification.domain import ManualTradeAccountState, ManualTradeNotificationEvent, Notice
from trader.core.notification.interfaces import NotificationSender
from trader.core.notification.rendering import manual_trade_email_subject, render_manual_trade_email, render_operate_email
from trader.core.notification.use_cases import (
    SendManualTradeNotification,
    SendOperateNotification,
    notice_from_entry,
    notices_from_entries,
)
from trader.core.shared.domain import Operate, OperateType


class FakeTransport:
    def __init__(self):
        self.messages = []
        self.error = None

    def send(self, notice: Notice, message: str) -> None:
        if self.error is not None:
            raise self.error
        self.messages.append((notice, message))


class FakeSender:
    def __init__(self, notice_type: str, recipient: str | None = None, error: Exception | None = None):
        self.notice_type = notice_type
        self.recipient = recipient
        self.error = error
        self.sent = []

    def send(self, content: str, title: str = "Trader"):
        self.sent.append((title, content))
        return self.error


def _event() -> ManualTradeNotificationEvent:
    return ManualTradeNotificationEvent(
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
    )


def _notice() -> Notice:
    return Notice(
        notice_type="MAIL_LARK",
        server="smtp.larksuite.com",
        port=465,
        sender="sender@example.com",
        password="smtp-auth-code",
        recipients=("first@example.com", "second@example.com"),
    )


def test_render_manual_trade_email_is_a_pure_function_without_smtp():
    event = _event()

    content = render_manual_trade_email(event)
    subject = manual_trade_email_subject(event)

    assert subject == "[手动实盘] BTCUSDT 1m 进场 LONG @ 100.000000"
    assert "<html" in content
    assert "手动实盘操作建议" in content
    assert "风险参考" in content
    assert "92.000000" in content
    assert "不是交易所成交确认" in content


def test_render_operate_email_is_a_pure_html_function():
    content = render_operate_email(Operate(OperateType.CLOSE, 1714281660, 2000.0))

    assert "<html" in content
    assert "策略信号提醒" in content
    assert "CLOSE" in content
    assert "2000.000000" in content


def test_email_sender_implements_the_notification_port_through_a_fake_transport():
    transport = FakeTransport()
    sender = EmailNotificationSender(_notice(), transport=transport)

    assert isinstance(sender, NotificationSender)
    assert sender.notice_type == "MAIL_LARK"
    assert sender.recipient == "first@example.com,second@example.com"

    error = sender.send("<!doctype html><html><body>content</body></html>", "subject")

    assert error is None
    notice, raw_message = transport.messages[0]
    assert notice is sender.notice
    assert "Subject: subject" in raw_message
    assert "To: first@example.com,second@example.com" in raw_message
    assert message_from_string(raw_message).get_payload(decode=True).decode("utf-8") == "<!doctype html><html><body>content</body></html>"


def test_email_sender_returns_transport_errors_without_raising():
    transport = FakeTransport()
    transport.error = RuntimeError("smtp down")
    sender = EmailNotificationSender(_notice(), transport=transport)

    error = sender.send("content", "subject")

    assert isinstance(error, RuntimeError)
    assert str(error) == "smtp down"


def test_send_manual_trade_notification_use_case_reports_delivery_per_sender():
    ok = FakeSender("MAIL_TEST", "first@example.com")
    failed = FakeSender("MAIL_BROKEN", "second@example.com", RuntimeError("boom"))

    results = SendManualTradeNotification([ok, failed]).execute(_event())

    assert [result.to_dict() for result in results] == [
        {"notice_type": "MAIL_TEST", "recipient": "first@example.com", "ok": True, "error": None},
        {"notice_type": "MAIL_BROKEN", "recipient": "second@example.com", "ok": False, "error": "boom"},
    ]
    assert ok.sent[0][0] == "[手动实盘] BTCUSDT 1m 进场 LONG @ 100.000000"
    assert "手动实盘操作建议" in ok.sent[0][1]


def test_send_operate_notification_use_case_sends_the_rendered_signal_not_raw_data():
    sender = FakeSender("MAIL_TEST")

    results = SendOperateNotification([sender]).execute(Operate(OperateType.CLOSE, 1714281660, 2000.0))

    assert [result.ok for result in results] == [True]
    title, content = sender.sent[0]
    assert title == "[策略信号] CLOSE @ 2000.000000"
    assert "策略信号提醒" in content
    assert "{'type': 'CLOSE'" not in content


def test_notice_from_entry_builds_a_notice_with_the_default_mail_server():
    notice = notice_from_entry(
        {
            "type": "MAIL_LARK",
            "sender": "sender@example.com",
            "password": "smtp-auth-code",
            "recipients": ["first@example.com", "second@example.com"],
        }
    )

    assert notice == Notice(
        notice_type="MAIL_LARK",
        server="smtp.larksuite.com",
        port=465,
        sender="sender@example.com",
        password="smtp-auth-code",
        recipients=("first@example.com", "second@example.com"),
    )
    assert notice.recipient == "first@example.com,second@example.com"


def test_notices_from_entries_skips_unknown_types_and_placeholder_passwords():
    notices = notices_from_entries(
        [
            {"type": "LARK_GMAIL", "sender": "a@example.com", "password": "secret"},
            {"type": "MAIL_QQ", "sender": "b@example.com", "password": "your_smtp_auth_code"},
            {"type": "MAIL_163", "sender": "c@example.com", "password": "secret", "recipient": "d@example.com"},
        ]
    )

    assert [notice.notice_type for notice in notices] == ["MAIL_163"]
    assert notices[0].recipients == ("d@example.com",)
