"""
Test ChainerTrader indicator logic with BTC-USDT 1h data.

This test validates the ChainerTrader indicator's core logic:
- MA Cross signal generation (golden cross / death cross)
- Entry/Exit confirmation mechanism
- Stop loss and breakeven management

This implementation mirrors the Pine Script indicator logic exactly.
See: src/pine_scripts/indicators/chainer_trader.pine

Data preparation (run before test):
    python -m trader --exchange '{"ty":"BINANCE","api_key":"","api_secret":""}' \
      --db mongodb://localhost:27017/ \
      --tasks '[{"task_type":"UPDATE_KLINES","symbol":"BTC-USDT","interval":"1h","start_time":"2025-01-01 00:00:00"}]'
"""

import csv
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import backtrader as bt
import matplotlib.pyplot as plt
import numpy as np
from dotenv import load_dotenv
from matplotlib.path import Path
from matplotlib.ticker import ScalarFormatter
from pymongo import MongoClient

from trader.database.kline import KlineCol
from trader.exchange.binance.data import BinanceData
from trader.libraries.chainer_trader import ChainerTraderLib

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SYMBOL_INTERVAL = "BTCUSDT-1h"
START_TIME = int(datetime.now().timestamp()) - 3600 * 24 * 30  # 30 days ago
END_TIME = int(datetime.now().timestamp())
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "output")


@dataclass
class SignalRecord:
    """Record of signals for visualization and CSV export."""
    bar_index: int
    timestamp: int
    datetime_str: str
    dt: datetime
    open: float
    high: float
    low: float
    close: float
    fast_sma: float
    slow_sma: float
    entry_signal: bool = False
    exit_signal: bool = False
    entry_confirm: bool = False
    entry_fail: bool = False
    exit_confirm: bool = False
    exit_fail: bool = False
    stop_price: Optional[float] = None
    stop_hit: bool = False
    has_trade: bool = False
    pending_entry: bool = False
    pending_exit: bool = False
    breakeven_step: int = 0


class ChainerTraderTestStrategy(bt.Strategy):
    """
    Test strategy that implements ChainerTrader indicator logic.
    
    This mirrors the Pine Script indicator exactly:
    - Entry signal: Golden cross (fast SMA crosses above slow SMA)
    - Exit signal: Death cross (fast SMA crosses below slow SMA)
    - Entry confirmation: close > key bar high (for LONG)
    - Entry fail: close < key bar low (for LONG)
    - Exit confirmation: close < key bar low (for LONG)
    - Exit fail: close > key bar high (for LONG)
    """
    
    params = (
        ("fast_length", 9),
        ("slow_length", 21),
        ("direction", "LONG"),
        ("entry_need_confirm", True),
        ("exit_need_confirm", True),
        ("enable_breakeven", True),
        ("stoploss_atr_mult", 1.0),
        ("risk_reward_ratio", 2.0),
    )
    
    def __init__(self):
        # SMA indicators
        self.fast_sma = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.fast_length
        )
        self.slow_sma = bt.indicators.SimpleMovingAverage(
            self.data.close, period=self.p.slow_length
        )
        
        # ATR for stop loss calculation (disable plotting)
        self.atr = bt.indicators.ATR(self.data, period=14)
        self.atr.plotinfo.plot = False
        
        # ChainerTrader library (uses backtrader data/indicators)
        self.chainer = ChainerTraderLib(self.data, self.atr)
        
        # Disable SMA plotting (we'll draw our own)
        self.fast_sma.plotinfo.plot = False
        self.slow_sma.plotinfo.plot = False
        
        # Trade state (mirrors Pine Script)
        self.trade_id = 0
        self.has_trade = False
        self.pending_entry = False
        self.pending_exit = False
        
        # Key bar indices and levels
        self.entry_key_bar_index = None
        self.entry_key_high = None
        self.entry_key_low = None
        self.exit_key_bar_index = None
        self.exit_key_high = None
        self.exit_key_low = None
        
        # Stop and entry prices
        self.initial_stop = None
        self.stop_price = None
        self.entry_price = None
        self.breakeven_step = 0
        
        # Signal records for CSV export and plotting
        self.records: List[SignalRecord] = []
    
    def get_entry_signal(self) -> bool:
        """Golden cross: fast SMA crosses above slow SMA."""
        if len(self) < 2:
            return False
        return self.fast_sma[-1] <= self.slow_sma[-1] and self.fast_sma[0] > self.slow_sma[0]
    
    def get_exit_signal(self) -> bool:
        """Death cross: fast SMA crosses below slow SMA."""
        if len(self) < 2:
            return False
        return self.fast_sma[-1] >= self.slow_sma[-1] and self.fast_sma[0] < self.slow_sma[0]
    
    def calculate_stop_price(self, bar_index: int) -> Optional[float]:
        """Calculate stop price using ChainerTrader library."""
        return self.chainer.stop_price(
            self.p.direction,
            bar_index,
            self.p.stoploss_atr_mult,
        )
    
    def entry_confirm(self) -> int:
        """Check entry confirmation using ChainerTrader library."""
        if self.entry_key_bar_index is None:
            return 0
        return self.chainer.entry_confirm(self.p.direction, self.entry_key_bar_index)
    
    def exit_confirm(self) -> int:
        """Check exit confirmation using ChainerTrader library."""
        if self.exit_key_bar_index is None:
            return 0
        return self.chainer.exit_confirm(self.p.direction, self.exit_key_bar_index)
    
    def calculate_breakeven(self) -> Optional[float]:
        """Calculate breakeven stop price using ChainerTrader library."""
        if self.entry_price is None or self.initial_stop is None:
            return None
        close = self.data.close[0]
        return ChainerTraderLib.breakeven_price(
            self.p.direction,
            float(self.entry_price),
            float(self.initial_stop),
            float(close),
        )
    
    def check_stop_hit(self) -> bool:
        """Check if stop loss was hit using ChainerTrader library."""
        if not self.has_trade or self.stop_price is None:
            return False
        return ChainerTraderLib.stop_hit(
            self.p.direction,
            float(self.stop_price),
            float(self.data.low[0]),
            float(self.data.high[0]),
        )
    
    def next(self):
        bar_idx = len(self) - 1
        current_time = bt.num2date(self.data.datetime[0])
        timestamp = int(current_time.timestamp())
        dt_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Reset per-bar signals
        entry_signal = False
        exit_signal = False
        entry_confirm_signal = False
        entry_fail_signal = False
        exit_confirm_signal = False
        exit_fail_signal = False
        stop_hit_signal = False
        
        # Skip if not enough data for SMA
        if len(self) < self.p.slow_length:
            self._record(bar_idx, timestamp, dt_str, current_time, entry_signal, exit_signal,
                        entry_confirm_signal, entry_fail_signal,
                        exit_confirm_signal, exit_fail_signal, stop_hit_signal)
            return
        
        # Get raw signals
        raw_entry = self.get_entry_signal()
        raw_exit = self.get_exit_signal()
        
        # Direction-aware signals
        if self.p.direction == "LONG":
            entry_signal = raw_entry
            exit_signal = raw_exit
        else:
            entry_signal = raw_exit
            exit_signal = raw_entry
        
        # ========== Entry Signal Processing ==========
        # 这个测试主要是为了显示指标，只要有进场信号就标记
        if entry_signal:
            logger.info(f"[{dt_str}] Entry Signal (E) at bar={bar_idx}")
            
            # 重置之前的交易状态，开始新的信号
            self.trade_id += 1
            self.entry_key_bar_index = bar_idx
            
            # Get key levels from helper (for logging)
            _, _, key_high, key_low = self.chainer.key_levels_by_bar_index(bar_idx)
            self.entry_key_high = key_high
            self.entry_key_low = key_low
            
            self.initial_stop = self.calculate_stop_price(bar_idx)
            self.stop_price = self.initial_stop
            self.entry_price = None
            self.breakeven_step = 0
            
            # 重置之前的待处理状态
            self.pending_entry = False
            self.pending_exit = False
            self.has_trade = False
            
            stop_str = f"{self.stop_price:.2f}" if self.stop_price else "N/A"
            logger.info(f"  -> Trade #{self.trade_id}: key_high={key_high:.2f}, "
                       f"key_low={key_low:.2f}, SL={stop_str}")
            
            if self.p.entry_need_confirm:
                self.pending_entry = True
                logger.info("  -> Waiting for confirmation...")
            else:
                self.has_trade = True
                self.entry_price = self.data.close[0]
                logger.info(f"  -> Immediate entry at {self.entry_price:.2f}")
        
        # ========== Entry Confirmation ==========
        if self.pending_entry:
            confirm_status = self.entry_confirm()
            
            if confirm_status == 1:
                entry_confirm_signal = True
                self.pending_entry = False
                self.has_trade = True
                self.entry_price = self.data.close[0]
                self.breakeven_step = 0
                _, _, key_high, _ = self.chainer.key_levels_by_bar_index(self.entry_key_bar_index)
                logger.info(f"[{dt_str}] Entry CONFIRMED (flag): close={self.data.close[0]:.2f} > key_high={key_high:.2f}")
                
            elif confirm_status == -1:
                entry_fail_signal = True
                self.pending_entry = False
                self.has_trade = False
                _, _, _, key_low = self.chainer.key_levels_by_bar_index(self.entry_key_bar_index)
                logger.info(f"[{dt_str}] Entry FAILED (X): close={self.data.close[0]:.2f} < key_low={key_low:.2f}")
                
                self.entry_key_bar_index = None
                self.entry_key_high = None
                self.entry_key_low = None
                self.initial_stop = None
                self.stop_price = None
                self.entry_price = None
        
        # ========== Exit Signal Processing ==========
        # 这个测试主要是为了显示指标，只要有出场信号就标记
        if exit_signal:
            logger.info(f"[{dt_str}] Exit Signal (X) at bar={bar_idx}")
            
            # 只要有出场信号就标记，不依赖交易状态
            self.exit_key_bar_index = bar_idx
            
            # Get key levels from helper (for logging)
            _, _, key_high, key_low = self.chainer.key_levels_by_bar_index(bar_idx)
            self.exit_key_high = key_high
            self.exit_key_low = key_low
            
            logger.info(f"  -> key_high={key_high:.2f}, key_low={key_low:.2f}")
            
            if self.p.exit_need_confirm:
                self.pending_exit = True
                logger.info("  -> Waiting for confirmation...")
            else:
                logger.info("  -> Immediate exit")
                self._reset_trade()
        
        # ========== Exit Confirmation ==========
        if self.pending_exit:
            confirm_status = self.exit_confirm()
            
            if confirm_status == 1:
                exit_confirm_signal = True
                _, _, _, key_low = self.chainer.key_levels_by_bar_index(self.exit_key_bar_index)
                logger.info(f"[{dt_str}] Exit CONFIRMED (flag): close={self.data.close[0]:.2f} < key_low={key_low:.2f}")
                self._reset_trade()
                
            elif confirm_status == -1:
                exit_fail_signal = True
                _, _, key_high, _ = self.chainer.key_levels_by_bar_index(self.exit_key_bar_index)
                logger.info(f"[{dt_str}] Exit FAILED (X): close={self.data.close[0]:.2f} > key_high={key_high:.2f}")
                self.pending_exit = False
                self.exit_key_bar_index = None
                self.exit_key_high = None
                self.exit_key_low = None
        
        # ========== Breakeven Management ==========
        # 保本逻辑在K线完成时检查，使用收盘价判断是否达到保本条件
        # 仅在有利方向上移动止损，确保保本线单调递增（LONG）或单调递减（SHORT）
        if self.has_trade and self.p.enable_breakeven and self.entry_price is not None:
            new_stop = self.calculate_breakeven()
            if new_stop is not None:
                long_dir = self.p.direction == "LONG"
                # 仅在有利方向上移动止损
                should_update = (
                    (long_dir and (self.stop_price is None or new_stop > self.stop_price)) or
                    (not long_dir and (self.stop_price is None or new_stop < self.stop_price))
                )
                
                if should_update:
                    self.breakeven_step += 1
                    self.stop_price = new_stop
                    logger.info(f"[{dt_str}] Breakeven #{self.breakeven_step}: new_stop={self.stop_price:.2f}")
        
        # ========== Stop Loss Check ==========
        if self.check_stop_hit():
            stop_hit_signal = True
            logger.info(f"[{dt_str}] STOP HIT (SL): low={self.data.low[0]:.2f} <= stop={self.stop_price:.2f}")
            self._reset_trade()
        
        self._record(bar_idx, timestamp, dt_str, current_time, entry_signal, exit_signal,
                    entry_confirm_signal, entry_fail_signal,
                    exit_confirm_signal, exit_fail_signal, stop_hit_signal)
    
    def _reset_trade(self):
        """Reset all trade state."""
        self.has_trade = False
        self.pending_entry = False
        self.pending_exit = False
        self.entry_key_bar_index = None
        self.entry_key_high = None
        self.entry_key_low = None
        self.exit_key_bar_index = None
        self.exit_key_high = None
        self.exit_key_low = None
        self.initial_stop = None
        self.stop_price = None
        self.entry_price = None
        self.breakeven_step = 0
    
    def _record(self, bar_idx, timestamp, dt_str, dt, entry_signal, exit_signal,
                entry_confirm, entry_fail, exit_confirm, exit_fail, stop_hit):
        """Record current bar's data."""
        record = SignalRecord(
            bar_index=bar_idx,
            timestamp=timestamp,
            datetime_str=dt_str,
            dt=dt,
            open=self.data.open[0],
            high=self.data.high[0],
            low=self.data.low[0],
            close=self.data.close[0],
            fast_sma=self.fast_sma[0] if len(self.fast_sma) > 0 else float('nan'),
            slow_sma=self.slow_sma[0] if len(self.slow_sma) > 0 else float('nan'),
            entry_signal=entry_signal,
            exit_signal=exit_signal,
            entry_confirm=entry_confirm,
            entry_fail=entry_fail,
            exit_confirm=exit_confirm,
            exit_fail=exit_fail,
            stop_price=self.stop_price if self.has_trade or self.pending_entry else None,
            stop_hit=stop_hit,
            has_trade=self.has_trade,
            pending_entry=self.pending_entry,
            pending_exit=self.pending_exit,
            breakeven_step=self.breakeven_step,
        )
        self.records.append(record)


def get_klines_from_db():
    """Load klines from MongoDB."""
    db_uri = os.environ.get("TRADER_DB", "mongodb://localhost:27017/")
    db_name = os.environ.get("TRADER_DB_NAME", "trader")
    
    client = MongoClient(db_uri)
    db = client[db_name]
    
    log = logging.getLogger(__name__)
    kline_col = KlineCol(db, log)
    
    klines = kline_col.get_klines(SYMBOL_INTERVAL, START_TIME, END_TIME)
    client.close()
    
    return klines


def save_chainer_csv(path: str, records: List[SignalRecord]):
    """Save ChainerTrader signal data to CSV."""
    if len(records) == 0:
        print("No data available to export.")
        return
    
    with open(path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            "datetime", "bar_index", "timestamp", "open", "high", "low", "close",
            "fast_sma", "slow_sma", "entry_signal", "exit_signal",
            "entry_confirm", "entry_fail", "exit_confirm", "exit_fail",
            "stop_price", "stop_hit", "has_trade", "pending_entry", "pending_exit",
            "breakeven_step",
        ])
        
        for r in records:
            writer.writerow([
                r.datetime_str, r.bar_index, r.timestamp, r.open, r.high, r.low, r.close,
                r.fast_sma, r.slow_sma,
                1 if r.entry_signal else 0,
                1 if r.exit_signal else 0,
                1 if r.entry_confirm else 0,
                1 if r.entry_fail else 0,
                1 if r.exit_confirm else 0,
                1 if r.exit_fail else 0,
                r.stop_price if r.stop_price else "",
                1 if r.stop_hit else 0,
                1 if r.has_trade else 0,
                1 if r.pending_entry else 0,
                1 if r.pending_exit else 0,
                r.breakeven_step,
            ])
    
    print(f"CSV exported: {path}")


def plot_chainer_trader(records: List[SignalRecord], output_file: str):
    """
    Plot ChainerTrader signals using matplotlib.
    
    Mimics Pine Script's plotshape() functions:
    - Entry Signal (E): green label below bar
    - Exit Signal (X): red label above bar  
    - Entry Confirm: green flag above bar
    - Entry Fail: green X below bar
    - Exit Confirm: red flag above bar
    - Exit Fail: red X above bar
    - Stop Hit (SL): red circle below bar
    - Stop Loss line: red dashed line during trade
    """
    if len(records) == 0:
        print("No data to plot.")
        return
    
    # Create flag marker path (similar to TradingView's shape.flag)
    # Flag shape: pole with rectangular flag
    # Coordinates normalized to unit square, will be scaled by markersize
    flag_verts = [
        (0.0, 0.0),    # Bottom of pole (start)
        (0.0, 1.0),    # Top of pole
        (0.0, 0.7),    # Top of flag (left edge)
        (0.5, 0.7),    # Top-right of flag
        (0.5, 0.4),    # Bottom-right of flag
        (0.0, 0.4),    # Bottom-left of flag (back to pole)
        (0.0, 0.0),    # Close path
    ]
    flag_codes = [
        Path.MOVETO,   # Move to pole bottom
        Path.LINETO,   # Draw pole to top
        Path.MOVETO,   # Move to flag top-left
        Path.LINETO,   # Draw to flag top-right
        Path.LINETO,   # Draw to flag bottom-right
        Path.LINETO,   # Draw to flag bottom-left
        Path.CLOSEPOLY, # Close path
    ]
    flag_path = Path(flag_verts, flag_codes)
    
    fig, ax = plt.subplots(figsize=(24, 12))
    
    n = len(records)
    x = np.arange(n)
    
    # Extract OHLC data
    opens = np.array([r.open for r in records])
    highs = np.array([r.high for r in records])
    lows = np.array([r.low for r in records])
    closes = np.array([r.close for r in records])
    
    # Draw candlesticks
    colors = ['green' if c >= o else 'red' for o, c in zip(opens, closes)]
    
    # Draw wicks (high-low lines)
    for i in range(n):
        ax.vlines(i, lows[i], highs[i], color=colors[i], linewidth=0.8)
    
    # Draw bodies
    body_width = 0.6
    for i in range(n):
        bottom = min(opens[i], closes[i])
        height = abs(closes[i] - opens[i])
        if height < 0.01:
            height = 0.01
        ax.bar(i, height, bottom=bottom, width=body_width, 
               color=colors[i], edgecolor=colors[i], linewidth=0.5)
    
    # Draw SMA lines
    fast_sma = np.array([r.fast_sma for r in records])
    slow_sma = np.array([r.slow_sma for r in records])
    
    valid_fast = ~np.isnan(fast_sma)
    valid_slow = ~np.isnan(slow_sma)
    
    ax.plot(x[valid_fast], fast_sma[valid_fast], color='teal', linewidth=1.5, label='Fast SMA (9)')
    ax.plot(x[valid_slow], slow_sma[valid_slow], color='orange', linewidth=1.5, label='Slow SMA (21)')
    
    # Draw stop loss line segments (only during active trades or pending entry)
    stop_x = []
    stop_y = []
    for i, r in enumerate(records):
        if r.stop_price is not None:
            stop_x.append(i)
            stop_y.append(r.stop_price)
        else:
            if len(stop_x) > 0:
                ax.plot(stop_x, stop_y, color='red', linewidth=1.5, linestyle='--', alpha=0.8)
                stop_x = []
                stop_y = []
    if len(stop_x) > 0:
        ax.plot(stop_x, stop_y, color='red', linewidth=1.5, linestyle='--', alpha=0.8)
    
    # Calculate offset for markers
    price_range = max(highs) - min(lows)
    offset = price_range * 0.015
    
    # Draw signal markers (mimicking Pine Script plotshape)
    # NOTE: breakeven_step 会在每笔“新交易/新段止损线”开始时从 0 重新计数；
    # 如果不重置 last_be_step，会导致每笔交易的 BE 1 被上一笔的 last_be_step=1 挡掉。
    last_be_step = 0
    for i, r in enumerate(records):
        # Reset BE label tracker when breakeven_step resets (new trade/segment)
        if r.breakeven_step < last_be_step:
            last_be_step = r.breakeven_step

        # Entry Signal (E) - green label below bar
        if r.entry_signal:
            ax.annotate('E', xy=(i, r.low - offset), 
                       fontsize=9, fontweight='bold', ha='center', va='top',
                       color='white',
                       bbox=dict(boxstyle='round,pad=0.2', facecolor='green', edgecolor='none', alpha=0.9))
            # Draw SL label at stop price
            if r.stop_price:
                ax.annotate(f'SL {r.stop_price:.2f}', xy=(i, r.stop_price - offset * 0.5),
                           fontsize=7, ha='center', va='top',
                           color='white',
                           bbox=dict(boxstyle='round,pad=0.15', facecolor='red', edgecolor='none', alpha=0.9))
        
        # Exit Signal (X) - red label above bar
        if r.exit_signal:
            ax.annotate('X', xy=(i, r.high + offset),
                       fontsize=9, fontweight='bold', ha='center', va='bottom',
                       color='white',
                       bbox=dict(boxstyle='round,pad=0.2', facecolor='red', edgecolor='none', alpha=0.9))
        
        # Entry Confirm - green flag above bar
        if r.entry_confirm:
            ax.plot(i, r.high + offset * 1.5, marker=flag_path, markersize=25,
                   color='lime', markeredgecolor='green', markeredgewidth=1.0)
        
        # Entry Fail - green X below bar
        if r.entry_fail:
            ax.plot(i, r.low - offset * 1.5, marker='X', markersize=10,
                   color='green', markeredgecolor='darkgreen', markeredgewidth=1)
        
        # Exit Confirm - red flag above bar
        if r.exit_confirm:
            ax.plot(i, r.high + offset * 2, marker=flag_path, markersize=25,
                   color='salmon', markeredgecolor='red', markeredgewidth=1.0)
        
        # Exit Fail - red X above bar  
        if r.exit_fail:
            ax.plot(i, r.high + offset * 1.5, marker='X', markersize=10,
                   color='red', markeredgecolor='darkred', markeredgewidth=1)
        
        # Stop Hit (SL) - red circle below bar
        if r.stop_hit:
            ax.annotate(
                'SL',
                xy=(i, r.low - offset * 2),
                fontsize=9,
                fontweight='bold',
                ha='center',
                va='top',
                color='white',
                bbox=dict(
                    boxstyle='circle,pad=0.3',
                    facecolor='darkred',
                    edgecolor='none',
                    alpha=0.9,
                ),
            )

        # Breakeven labels: BE 1, BE 2, ...
        # 仅在 breakeven_step 递增的那根 K线上画一次
        # 为避免被坐标轴下边界裁剪，标签画在保本线之上
        if r.breakeven_step > last_be_step and r.stop_price:
            ax.annotate(
                f'BE {r.breakeven_step}',
                xy=(i, r.stop_price + offset * 0.4),
                fontsize=8,
                ha='center',
                va='bottom',
                color='white',
                bbox=dict(
                    boxstyle='round,pad=0.2',
                    facecolor='orange',
                    edgecolor='none',
                    alpha=0.9,
                ),
            )
            last_be_step = r.breakeven_step
    
    # Format x-axis with dates
    # Show date labels every ~50 bars
    tick_interval = max(1, n // 15)
    tick_positions = list(range(0, n, tick_interval))
    tick_labels = [records[i].datetime_str[5:16] for i in tick_positions]  # MM-DD HH:MM
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, rotation=45, ha='right', fontsize=8)
    
    # Format y-axis
    formatter = ScalarFormatter(useOffset=False)
    formatter.set_scientific(False)
    ax.yaxis.set_major_formatter(formatter)
    
    # Labels and title
    ax.set_xlabel('Date', fontsize=10)
    ax.set_ylabel('Price (USDT)', fontsize=10)
    ax.set_title('ChainerTrader Indicator - BTC/USDT 1H', fontsize=14, fontweight='bold')
    
    # Legend
    ax.legend(loc='upper left', fontsize=10)
    
    # Grid
    ax.grid(True, alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)
    
    # Set x limits with padding
    ax.set_xlim(-2, n + 2)

    # ------------------------------------------------------------------
    # Interactive crosshair + K线信息提示
    # ------------------------------------------------------------------
    # 初始位置放在最后一根K线
    vline = ax.axvline(
        x=n - 1,
        color='gray',
        linestyle='--',
        linewidth=0.8,
        alpha=0.7,
        visible=False,
    )
    hline = ax.axhline(
        y=closes[-1],
        color='gray',
        linestyle='--',
        linewidth=0.8,
        alpha=0.7,
        visible=False,
    )
    # 放到右上角，避免遮挡左侧图例
    info_text = ax.text(
        0.98,
        0.98,
        '',
        transform=ax.transAxes,
        va='top',
        ha='right',
        fontsize=9,
        bbox=dict(
            boxstyle='round,pad=0.3',
            facecolor='white',
            edgecolor='gray',
            alpha=0.85,
        ),
        visible=False,
    )

    def on_move(event):
        # 只在主坐标轴内响应
        if event.inaxes is not ax or event.xdata is None:
            if info_text.get_visible():
                info_text.set_visible(False)
                vline.set_visible(False)
                hline.set_visible(False)
                fig.canvas.draw_idle()
            return

        # 将鼠标 x 坐标映射到最近一根 K 线索引
        idx = int(round(event.xdata))
        if idx < 0 or idx >= n:
            return

        r = records[idx]

        # 更新十字线位置
        # set_xdata/set_ydata 需要序列
        vline.set_xdata([idx, idx])
        hline.set_ydata([event.ydata, event.ydata])
        vline.set_visible(True)
        hline.set_visible(True)

        # 在左上角展示该 K 线的时间和 OHLC
        info_text.set_text(
            f'{r.datetime_str}\n'
            f'O:{r.open:.2f}  H:{r.high:.2f}  '
            f'L:{r.low:.2f}  C:{r.close:.2f}'
        )
        info_text.set_visible(True)

        fig.canvas.draw_idle()

    fig.canvas.mpl_connect('motion_notify_event', on_move)

    plt.tight_layout()

    # Save and show
    fig.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Chart saved: {output_file}")

    plt.show()


def test_chainer_trader(main=False):
    """Test ChainerTrader indicator logic with BTC-USDT 1h data."""
    klines = get_klines_from_db()
    
    if klines is None or len(klines) == 0:
        print(f"No klines found for {SYMBOL_INTERVAL}. Please download data first.")
        return
    
    print(f"Loaded {len(klines)} klines from {SYMBOL_INTERVAL}")
    print(f"Date range: {klines[0].open_datetime()} - {klines[-1].open_datetime()}")
    print()
    
    cerebro = bt.Cerebro()
    
    cerebro.addstrategy(
        ChainerTraderTestStrategy,
        fast_length=9,
        slow_length=21,
        direction="LONG",
        entry_need_confirm=True,
        exit_need_confirm=True,
        enable_breakeven=True,
        stoploss_atr_mult=1.0,
        risk_reward_ratio=2.0,
    )
    
    data = BinanceData(klines)
    cerebro.adddata(data, name="BTCUSDT")
    
    cerebro.broker.setcash(100000.0)
    
    results = cerebro.run()
    strategy = results[0]
    
    # Print signal statistics
    records = strategy.records
    entry_signals = sum(1 for r in records if r.entry_signal)
    exit_signals = sum(1 for r in records if r.exit_signal)
    entry_confirms = sum(1 for r in records if r.entry_confirm)
    entry_fails = sum(1 for r in records if r.entry_fail)
    exit_confirms = sum(1 for r in records if r.exit_confirm)
    exit_fails = sum(1 for r in records if r.exit_fail)
    stop_hits = sum(1 for r in records if r.stop_hit)
    
    print()
    print("=" * 50)
    print("Signal Statistics")
    print("=" * 50)
    print(f"Entry Signals (E): {entry_signals}")
    print(f"Exit Signals (X): {exit_signals}")
    print(f"Entry Confirms (flag): {entry_confirms}")
    print(f"Entry Fails (X): {entry_fails}")
    print(f"Exit Confirms (flag): {exit_confirms}")
    print(f"Exit Fails (X): {exit_fails}")
    print(f"Stop Hits (SL): {stop_hits}")
    
    if main:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        output_file = os.path.join(OUTPUT_DIR, "test_chainer_trader_btcusdt.png")
        csv_file = os.path.join(OUTPUT_DIR, "test_chainer_trader_btcusdt.csv")
        
        save_chainer_csv(csv_file, records)
        plot_chainer_trader(records, output_file)


if __name__ == "__main__":
    test_chainer_trader(True)
