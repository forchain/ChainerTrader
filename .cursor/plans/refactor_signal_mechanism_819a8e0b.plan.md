---
name: 重构信号机制
overview: 将 ChainerTrader 框架的信号机制从"进场/出场信号 + 方向"重构为"做多/做空信号 + 运行模式"，使信号语义固定清晰，支持三种运行模式（做多模式、做空模式、多空模式）。
todos:
  - id: lib-pine
    content: 重构 Pine Script 库：重命名确认函数 entryConfirm->longConfirm, exitConfirm->shortConfirm
    status: completed
  - id: strategy-pine
    content: 重构 Pine Script 策略：参数和信号函数变更，实现三种模式逻辑
    status: completed
  - id: indicator-pine
    content: 重构 Pine Script 指标：与策略相同的变更
    status: completed
  - id: base-strategy-py
    content: 重构 Python base_strategy.py：参数、信号函数和 _process_signals 方法
    status: completed
  - id: template-py
    content: 更新 Python 模板策略 chainer_trader.py
    status: completed
  - id: tests
    content: 更新测试文件以适配新的信号机制
    status: completed
---

# 重构 ChainerTrader 信号机制

## 核心概念变更

**现有设计（容易歧义）：**

- `getEntrySignal()` / `getExitSignal()` + `direction` (LONG/SHORT) + `allow_short`
- 信号含义随方向变化：SHORT 方向下，进场信号变成平仓，出场信号变成开仓

**新设计（清晰明确）：**

- `getLongSignal()` / `getShortSignal()` + `mode` (LONG_ONLY/SHORT_ONLY/BOTH)
- 信号语义固定：做多信号永远代表做多条件，做空信号永远代表做空条件

## 三种运行模式

| 模式 | 做多信号触发 | 做空信号触发 | 离场方式 |

|------|-------------|-------------|---------|

| LONG_ONLY | 开多单 | 平多单 | 做空信号/止损/止盈/保本 |

| SHORT_ONLY | 平空单 | 开空单 | 做多信号/止损/止盈/保本 |

| BOTH | 开多单 | 开空单 | 止损/止盈/保本 |

## 参数变更

### 移除

- `chainer_direction` - 不再需要
- `chainer_allow_short` - 被 mode 替代

### 新增

- `chainer_mode` - 运行模式，可选值：`LONG_ONLY`、`SHORT_ONLY`、`BOTH`

## 文件修改

### 1. Pine Script 库 - [src/pine_scripts/libraries/chainer_trader.pine](src/pine_scripts/libraries/chainer_trader.pine)

- `entryConfirm` -> `longConfirm` (确认做多信号)
- `exitConfirm` -> `shortConfirm` (确认做空信号)
- 保留原有函数作为别名以保持向后兼容（可选）

关键代码变更：

```pine
// 新函数命名更清晰
export longConfirm(int keyBarIndex) =>
    // close > key_high = 确认成功, close < key_low = 确认失败
    ...

export shortConfirm(int keyBarIndex) =>
    // close < key_low = 确认成功, close > key_high = 确认失败
    ...
```

### 2. Pine Script 策略 - [src/pine_scripts/strategies/chainer_trader.pine](src/pine_scripts/strategies/chainer_trader.pine)

参数变更：

```pine
// 移除
// chainer_allow_short = input.bool(...)
// chainer_direction = input.string(...)

// 新增
chainer_mode = input.string(title="Trading Mode", defval="LONG_ONLY", options=["LONG_ONLY", "SHORT_ONLY", "BOTH"], group="Chainer Framework")
```

信号函数变更：

```pine
// 旧
getEntrySignal() => ta.crossover(fast, slow)   // 金叉
getExitSignal() => ta.crossunder(fast, slow)   // 死叉

// 新
getLongSignal() => ta.crossover(fast, slow)    // 金叉 = 做多信号
getShortSignal() => ta.crossunder(fast, slow)  // 死叉 = 做空信号
```

信号处理逻辑重构：

```pine
longSignal = getLongSignal()
shortSignal = getShortSignal()

if chainer_mode == "LONG_ONLY"
    // 做多信号开多，做空信号平多
    if longSignal and no_position: open_long()
    if shortSignal and has_long: close_long()
else if chainer_mode == "SHORT_ONLY"
    // 做空信号开空，做多信号平空
    if shortSignal and no_position: open_short()
    if longSignal and has_short: close_short()
else  // BOTH
    // 做多信号开多，做空信号开空，离场靠止损/止盈/保本
    if longSignal and no_position: open_long()
    if shortSignal and no_position: open_short()
```

### 3. Pine Script 指标 - [src/pine_scripts/indicators/chainer_trader.pine](src/pine_scripts/indicators/chainer_trader.pine)

与策略文件相同的变更。

### 4. Python 基础策略 - [src/trader/strategy/base_strategy.py](src/trader/strategy/base_strategy.py)

参数变更 (约第 42-43 行)：

```python
# 移除
# ("chainer_allow_short", True),
# ("chainer_direction", "LONG"),

# 新增
("chainer_mode", "LONG_ONLY"),  # LONG_ONLY, SHORT_ONLY, BOTH
```

信号函数变更 (约第 743-759 行)：

```python
# 旧
def get_entry_signal(self) -> bool: ...
def get_exit_signal(self) -> bool: ...

# 新
def get_long_signal(self) -> bool: ...
def get_short_signal(self) -> bool: ...
```

`_process_signals` 方法重构 (约第 761-821 行)：

```python
def _process_signals(self) -> None:
    long_signal = self.get_long_signal()
    short_signal = self.get_short_signal()
    mode = str(self.params.chainer_mode).upper()
    
    if mode == "LONG_ONLY":
        # 做多信号进场，做空信号离场
        if long_signal and no_active_trade:
            self.enter_trade(direction="LONG", ...)
        if short_signal and has_long_position:
            self.exit_trade(...)
    elif mode == "SHORT_ONLY":
        # 做空信号进场，做多信号离场
        if short_signal and no_active_trade:
            self.enter_trade(direction="SHORT", ...)
        if long_signal and has_short_position:
            self.exit_trade(...)
    elif mode == "BOTH":
        # 双向交易，信号只用于开仓
        if long_signal and no_active_trade:
            self.enter_trade(direction="LONG", ...)
        if short_signal and no_active_trade:
            self.enter_trade(direction="SHORT", ...)
        # 离场通过止损/止盈/保本机制
```

`_process_trade_engine` 方法也需要相应更新 (约第 823-889 行)。

### 5. Python 模板策略 - [src/trader/strategy/chainer_trader.py](src/trader/strategy/chainer_trader.py)

参数和方法变更：

```python
params = (
    ("name", "ChainerTrader"),
    ("fast_length", 9),
    ("slow_length", 21),
    # 移除 chainer_allow_short, chainer_direction
    ("chainer_mode", "LONG_ONLY"),  # 新增
    ...
)

# 旧
def get_entry_signal(self) -> bool: ...
def get_exit_signal(self) -> bool: ...

# 新
def get_long_signal(self) -> bool:
    """金叉 = 做多信号"""
    return self.fast_sma[-1] <= self.slow_sma[-1] and self.fast_sma[0] > self.slow_sma[0]

def get_short_signal(self) -> bool:
    """死叉 = 做空信号"""
    return self.fast_sma[-1] >= self.slow_sma[-1] and self.fast_sma[0] < self.slow_sma[0]
```

### 6. 测试文件更新

**[tests/test_entry_exit_ma_cross.py](tests/test_entry_exit_ma_cross.py)：**

- 修改 `_MACrossEntryExitStrategy` 使用新的参数和方法
- 更新测试用例以覆盖三种模式

**[tests/test_chainer_atr_stoploss.py](tests/test_chainer_atr_stoploss.py)：**

- 更新参数名称

## 向后兼容性考虑

- 库函数可以保留旧名称作为别名
- 在 base_strategy.py 中可以添加参数兼容层（如果检测到旧参数，自动转换为新参数并发出警告）

## 测试计划

1. 单元测试：覆盖三种模式的进场/离场逻辑
2. 集成测试：验证 Pine Script 和 Python 策略行为一致
3. 回归测试：确保现有的止损/止盈/保本机制正常工作