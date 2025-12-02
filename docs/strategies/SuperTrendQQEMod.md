# SuperTrend + QQE MOD + Trend A Strategy

## Overview

SuperTrend QQE MOD 是一个多指标联合确认的趋势跟踪策略，结合了三个强大的技术指标来过滤假信号并提高交易胜率。该策略同时支持做多和做空，使用 SuperTrend 的动态轨道线作为止损依据，并采用 2:1 的风险收益比设置止盈目标。

## Key Components

### 1. SuperTrend Indicator

SuperTrend 是基于 ATR（平均真实波幅）的趋势跟踪指标，提供明确的趋势方向和动态支撑/阻力位。

**Parameters:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| periods | 10 | ATR 计算周期 |
| multiplier | 3.3 | ATR 乘数 |

**Outputs:**
- `trend`: 趋势方向（1=上涨，-1=下跌）
- `up`: 上涨趋势时的支撑线（用作做多止损）
- `dn`: 下跌趋势时的阻力线（用作做空止损）

### 2. Trend A Indicator

Trend A 基于 Heikin Ashi 蜡烛图的双重平滑移动平均线，用于确认趋势方向和强度。

**Parameters:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| ma_type | EMA | 移动平均类型 |
| ma_period | 77 | 第一次平滑周期 |
| ma_period_smoothing | 21 | 第二次平滑周期 |

**Outputs:**
- `trend > 0`: 绿色蜡烛（看涨）
- `trend < 0`: 红色蜡烛（看跌）

### 3. QQE MOD Indicator

QQE MOD 是一个基于 RSI 的动量指标，结合布林带提供额外的信号过滤。

**Parameters:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| rsi_length_secondary | 10 | 次级 RSI 周期 |
| rsi_smoothing | 5 | RSI 平滑因子 |
| qqe_factor | 1.61 | QQE 波动因子 |
| threshold | 3.0 | 信号阈值 |

**Outputs:**
- `qqe_up_signal`: 做多信号（RSI 突破上轨）
- `qqe_down_signal`: 做空信号（RSI 跌破下轨）

## Trading Logic

### Entry Conditions

| Direction | SuperTrend | Trend A | QQE MOD |
|-----------|------------|---------|---------|
| **Long** | trend == 1 (Up Trend) | trend > 0 (Green) | Up Signal Active |
| **Short** | trend == -1 (Down Trend) | trend < 0 (Red) | Down Signal Active |

三个条件必须同时满足才会触发入场信号。

### Entry Rules

1. **三指标联合确认**：SuperTrend、Trend A、QQE MOD 必须同时满足条件
2. **无挂单限制**：只有在没有挂单的情况下才允许进场
3. **单向单笔限制**：Trend A 一个方向只允许有一笔订单
   - 当 Trend A 为绿色时进场做多后，必须等待 Trend A 转为红色再转回绿色才能再次做多
   - 当 Trend A 为红色时进场做空后，必须等待 Trend A 转为绿色再转回红色才能再次做空

### Exit Conditions

| Direction | Stop Loss | Take Profit |
|-----------|-----------|-------------|
| **Long** | SuperTrend Up Line | Entry + 2 × (Entry - Stop Loss) |
| **Short** | SuperTrend Down Line | Entry - 2 × (Stop Loss - Entry) |

风险收益比固定为 1:2，即止盈距离是止损距离的两倍。

## Configuration Examples

### Backtrader (Python)

```python
from trader.strategy.super_trend_qqe_mod import SuperTrendQQEMODStrategy

cerebro.addstrategy(
    SuperTrendQQEMODStrategy,
    st_periods=10,
    st_multiplier=3.3,
    ta_ma_period=77,
    ta_ma_period_smoothing=21,
    qqe_rsi_length_secondary=10,
    risk_reward_ratio=2.0,
)
```

### TradingView (Pine Script)

```pine
// Default parameters are already optimized:
// SuperTrend: periods=10, multiplier=3.3
// Trend A: ma_period=77, ma_period_smoothing=21
// QQE MOD: rsi_length_secondary=10
// Risk/Reward Ratio: 2.0
```

## Usage Guidelines

### Recommended Timeframes

| Timeframe | Suitability | Notes |
|-----------|-------------|-------|
| 15m | Good | 日内交易，信号频繁 |
| 1H | Excellent | 短线交易的最佳平衡 |
| 4H | Excellent | 波段交易的理想选择 |
| 1D | Good | 中长线持仓 |

### Best Market Conditions

1. **趋势市场**：策略在明确趋势中表现最佳
2. **中高波动性**：需要足够的价格波动来触发信号
3. **流动性充足**：确保订单能够顺利执行

### Risk Management

1. **仓位控制**：建议单次交易不超过账户的 2-5%
2. **止损纪律**：严格执行 SuperTrend 轨道线止损
3. **避免过度交易**：等待三个指标完全确认后再入场

## Visual Indicators

### Chart Display

- **绿色线**：SuperTrend Up Line（上涨趋势支撑）
- **红色线**：SuperTrend Down Line（下跌趋势阻力）
- **绿色三角**：做多入场信号
- **红色三角**：做空入场信号
- **橙色线**：当前止损价位
- **蓝色线**：当前止盈价位

### QQE MOD Subplot

- **柱状图**：RSI 动量强度
- **青色柱**：做多信号区域
- **红色柱**：做空信号区域

## Alert Conditions

| Alert | Condition |
|-------|-----------|
| Long Entry Signal | 三指标联合做多条件满足 |
| Short Entry Signal | 三指标联合做空条件满足 |

## Performance Considerations

1. **预热期**：由于使用了多个移动平均，策略需要约 100 根 K 线的预热期
2. **信号频率**：严格的三指标确认会降低信号频率，但提高质量
3. **滑点影响**：在快速市场中，实际止损可能与预期有偏差

## Limitations

1. **震荡市不适用**：在横盘整理时可能产生连续亏损
2. **趋势反转**：可能在趋势末期入场导致止损
3. **参数敏感性**：不同品种可能需要调整参数

## Customization

### 调整风险收益比

```python
# 更保守的设置（1:1.5）
risk_reward_ratio=1.5

# 更激进的设置（1:3）
risk_reward_ratio=3.0
```

### 调整信号灵敏度

```python
# 更灵敏的 SuperTrend（更多信号）
st_periods=7
st_multiplier=2.5

# 更稳定的 SuperTrend（更少信号）
st_periods=14
st_multiplier=4.0
```

## Backtesting Results

建议在以下条件下进行回测：

1. 至少 1 年的历史数据
2. 包含不同市场状态（趋势和震荡）
3. 考虑手续费和滑点
4. 使用合理的初始资金和仓位大小

## Disclaimer

本策略仅供教育和研究目的。在实盘交易前，请务必：
1. 进行充分的回测验证
2. 使用模拟账户测试
3. 了解相关风险
4. 根据个人风险承受能力调整参数

过往表现不代表未来收益。

