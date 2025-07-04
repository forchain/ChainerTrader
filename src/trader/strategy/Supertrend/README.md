# Supertrend Strategy

这是一个基于Supertrend、QQE和Heikin Ashi指标的综合趋势跟踪策略，从Pine Script版本转换为Python实现。

## 策略概述

Supertrend策略结合了三个强大的技术指标来识别和跟踪市场趋势：

1. **Supertrend指标**：基于ATR的趋势跟踪指标
2. **QQE指标**：RSI的改进版本，提供更准确的超买超卖信号
3. **Heikin Ashi移动平均线**：用于趋势确认和过滤

## 主要特性

### 多指标确认
- **Supertrend**：主要趋势方向指示器
- **QQE**：动量确认和过滤
- **Heikin Ashi MA**：趋势强度确认

### 风险管理
- 基于ATR的动态止损
- 多重信号确认减少假信号
- 趋势跟踪机制

### 参数配置
- 可配置的ATR周期和倍数
- 灵活的QQE参数设置
- 多种移动平均线类型支持

## 参数说明

### 基础参数
- `name`: 策略名称 (默认: 'Supertrend')
- `period`: 基础周期 (默认: 12)

### Supertrend参数
- `atr_period`: ATR周期 (默认: 9)
- `atr_multiplier`: ATR倍数 (默认: 3.9)
- `change_atr_method`: 是否改变ATR计算方法 (默认: True)
- `source_type`: 价格源类型 ('hl2', 'close', 'high', 'low') (默认: 'hl2')

### QQE参数
- `rsi_length_primary`: 主要RSI长度 (默认: 6)
- `rsi_smoothing_primary`: 主要RSI平滑 (默认: 5)
- `qqe_factor_primary`: 主要QQE因子 (默认: 3.0)
- `threshold_primary`: 主要阈值 (默认: 3.0)
- `rsi_length_secondary`: 次要RSI长度 (默认: 6)
- `rsi_smoothing_secondary`: 次要RSI平滑 (默认: 5)
- `qqe_factor_secondary`: 次要QQE因子 (默认: 1.61)
- `threshold_secondary`: 次要阈值 (默认: 3.0)

### 布林带参数
- `bollinger_length`: 布林带长度 (默认: 50)
- `bollinger_multiplier`: 布林带倍数 (默认: 0.35)

### Heikin Ashi MA参数
- `ma_type`: 移动平均线类型 (默认: EMA)
- `ma_period`: 移动平均线周期 (默认: 9)
- `alma_offset`: ALMA偏移 (默认: 0.85)
- `alma_sigma`: ALMA标准差 (默认: 6)

## 使用方法

### 基本使用
```python
import backtrader as bt
from trader.strategy.Supertrend import SupertrendStrategy

# 创建Cerebro引擎
cerebro = bt.Cerebro()

# 添加策略
cerebro.addstrategy(SupertrendStrategy)

# 添加数据
data = bt.feeds.YourDataFeed(...)
cerebro.adddata(data)

# 运行回测
cerebro.run()
```

### 自定义参数
```python
# 使用自定义参数
cerebro.addstrategy(
    SupertrendStrategy,
    atr_period=14,
    atr_multiplier=3.0,
    rsi_length_primary=14,
    qqe_factor_primary=4.0
)
```

## 交易逻辑

### 买入条件
- Supertrend从下跌转为上涨
- QQE主要指标在布林带上轨之上
- QQE次要指标超过正阈值
- Heikin Ashi显示看涨趋势

### 卖出条件
- Supertrend从上涨转为下跌
- QQE主要指标在布林带下轨之下
- QQE次要指标低于负阈值
- Heikin Ashi显示看跌趋势

### 止损条件
- 价格跌破Supertrend上轨（买入时）
- 价格突破Supertrend下轨（卖出时）

## 指标详解

### Supertrend指标
Supertrend是一个趋势跟踪指标，基于ATR（平均真实波幅）计算：
- **上轨** = 价格源 - ATR倍数 × ATR
- **下轨** = 价格源 + ATR倍数 × ATR
- 当价格突破上轨时，趋势转为上涨
- 当价格跌破下轨时，趋势转为下跌

### QQE指标
QQE（Quantitative Qualitative Estimation）是RSI的改进版本：
- 使用平滑的RSI值
- 基于RSI的ATR计算动态带
- 提供更准确的超买超卖信号
- 减少RSI的滞后性

### Heikin Ashi移动平均线
Heikin Ashi是一种改进的K线图：
- 使用修改的开盘价、收盘价、最高价、最低价
- 更好地显示趋势方向
- 减少市场噪音

## 与原Pine Script版本的差异

1. **实现语言**：从Pine Script转换为Python
2. **框架**：使用backtrader框架
3. **数据结构**：使用Python列表和numpy数组
4. **可视化**：移除了图表绘制功能，专注于策略逻辑
5. **指标计算**：简化了部分复杂计算，保持核心逻辑

## 注意事项

1. 策略需要足够的历史数据来计算所有指标
2. 参数设置需要根据具体的交易品种和市场条件进行调整
3. 建议在实盘交易前进行充分的回测验证
4. 多重信号确认可能导致信号延迟，但能减少假信号

## 文件结构

```
Supertrend/
├── __init__.py              # 包初始化文件
├── Supertrend.py           # 主要策略实现
├── Supertrend.pine         # 原始Pine Script版本
└── README.md              # 说明文档
```

## 性能优化建议

1. **参数优化**：使用遗传算法或网格搜索优化参数
2. **时间框架**：在不同时间框架上测试策略表现
3. **市场条件**：在趋势市场和震荡市场中分别测试
4. **风险管理**：根据账户规模调整仓位大小 