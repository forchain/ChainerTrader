---
name: ChainerTrader v2
overview: 将 v1 的 entry/exit 公共功能升级为 v2：统一命名为 chainer_trader、参数加 chainer_ 前缀、关键K改用 bar_index 引用、确认逻辑下沉到 Pine library，并增加做空支持（可配置禁用）。Backtrader 与 TradingView 行为/日志尽量对齐，且仍保持单活跃交易以保证稳定。
todos:
  - id: tv-rename-lib
    content: 将 Pine library 从 entry_exit 重命名/替换为 chainer_trader，并把关键K引用改为 keyBarIndex + valuewhen；把确认与禁用逻辑下沉到库，同时加入 SHORT 计算
    status: completed
  - id: tv-rename-indicator
    content: 将 Pine indicator 重命名/替换为 chainer_trader，链者参数统一加 chainer_ 前缀；确认逻辑全部调用库；新增 chainer_allow_short 与方向 demo；debug 参数改为 chainer_debug_start_time
    status: completed
    dependencies:
      - tv-rename-lib
  - id: bt-bar-index-api
    content: 修改 BaseStrategy：enter_trade/exit_trade 改为 key_bar_index 参数（移除 key_kline_idx）；按 bar_index 计算 kline 引用；新增 chainer_allow_short 并实现 SHORT 的确认/止损/保本/止损触发逻辑
    status: completed
  - id: bt-update-tests-v2
    content: 更新 tests/test_entry_exit_ma_cross.py：改用 key_bar_index=self.bar_idx()；新增 SHORT 相关用例与禁用做空用例
    status: completed
    dependencies:
      - bt-bar-index-api
---

# v2：升级为通用 `chainer_trader` 公共功能（支持做空）

## 目标与约束

- **重命名**：按你选择的 `rename_only`，v1 的 `entry_exit` 会被 v2 的 `chainer_trader` 替换/重命名（旧脚本需要同步改 import/indicator 名称）。
- **参数前缀**：所有链者特有参数使用 `chainer_` 前缀。
- **关键K引用**：TradingView 与 Backtrader 都用 **关键K的 `bar_index`**（而非相对 idx）来引用关键K。
- **确认下沉**：TradingView 侧“确认规则”从 indicator 移入 library；indicator 只负责触发 key 的 `bar_index` 并消费 library 产出的确认状态/止损/保本结果。
- **做空支持**：默认支持；通过 `chainer_allow_short` 允许禁用（禁用时传入做空报错/拒绝）。
- **稳定优先**：仍保持 **单活跃交易**（任意时刻最多 1 笔未平仓交易对象）。

## TradingView（Pine v6）

### 1) 重命名并扩展库：`EntryExit` → `ChainerTrader`

- 目标文件（替换/重命名）：
- `src/pine_scripts/libraries/entry_exit.pine` → `src/pine_scripts/libraries/chainer_trader.pine`
- 改造点：
- **输入 key 的方式**：所有需要关键K的函数入参改为 `int keyBarIndex`。
- **用 `bar_index == keyBarIndex` + `ta.valuewhen(...)` 获取 keyK 的 high/low/time**（避免动态历史引用限制）。
- **确认逻辑下沉**：提供 `export` 函数用于进场/出场确认推进，并在确认失败时在库内记录“禁用 keyBarIndex”（单活跃交易下用 `var int bannedEntryKeyBarIndex` / `bannedExitKeyBarIndex` 即可）。
- **做空**：所有计算（确认/止损/保本/止损触发条件）支持 `direction`（LONG/SHORT）。

### 2) 重命名并改造指标：`MA Cross EntryExit` → `ChainerTrader (MA Cross demo)`

- 目标文件（替换/重命名）：
- `src/pine_scripts/indicators/ma_cross_entry_exit.pine` → `src/pine_scripts/indicators/chainer_trader.pine`
- 改造点：
- 指标名称改为 `ChainerTrader`（内部可保留 MA Cross demo 用于测试/验证）。
- 新增/重命名参数（均带 `chainer_` 前缀）：
- `chainer_allow_short`（bool，默认 true）
- `chainer_entry_need_confirm`、`chainer_exit_need_confirm`
- `chainer_stoploss_atr_mult`、`chainer_enable_breakeven`、`chainer_risk_reward_ratio`
- `chainer_debug_start_time`（替代 debugStartTime）
- **确认/禁用 key** 的判定全部改为调用 `ChainerTrader` library 的确认函数（indicator 不再自己实现确认条件与禁用集）。
- **关键K传递**：上穿/下穿触发时，传 `bar_index` 给库函数。
- **做空演示**：增加一个 demo 输入（例如 `tradeDirection`）用于选择 LONG/SHORT（但当 `chainer_allow_short=false` 且选择 SHORT 时输出错误状态/不触发）。

## Backtrader（Python）

### 3) `BaseStrategy` API：关键K改为 `bar_index`，并加入做空开关

- 文件：[`src/trader/strategy/base_strategy.py`](src/trader/strategy/base_strategy.py)
- 改造点：
- `enter_trade(..., key_bar_index: int, direction: str='LONG', ...)`
- `exit_trade(..., key_bar_index: int, ...)`
- 彻底移除 `key_kline_idx`（按你选择的 `bar_index_only`）。
- 新增 `params`：`chainer_allow_short`（默认 True），并在传入 SHORT 且禁用时抛错。
- `_kline_ref` 由 bar_index 计算 `shift = key_bar_index - self.bar_idx()`；若 `shift > 0`（未来）直接报错。
- 做空对称实现：
- **进场确认**：SHORT 确认 `close < key_low`，失败 `close > key_high`
- **出场确认**：SHORT 确认 `close > key_high`，失败 `close < key_low`
- **止损价**：SHORT 使用 `key_high + atr_mult*ATR`
- **止损触发**：SHORT `close >= stop_price`
- **保本阶梯**：SHORT 以 `risk = initial_stop - entry_price`，价格每下降 `n*RR*risk`，止损下移到 `entry_price - (n-1)*RR*risk`

## 测试

### 4) 更新 Backtrader 单测与日志对齐

- 文件：`tests/test_entry_exit_ma_cross.py`
- 改造点：
- 触发入场/出场时传 `key_bar_index=self.bar_idx()`。
- 新增 SHORT 用例：
- SHORT 的确认成功/失败
- SHORT 的保本移动止损与止损触发
- `chainer_allow_short=false` 时 SHORT 报错

## 文件清单（v2 rename_only）

- 替换/重命名：
- `src/pine_scripts/libraries/entry_exit.pine` → `src/pine_scripts/libraries/chainer_trader.pine`
- `src/pine_scripts/indicators/ma_cross_entry_exit.pine` → `src/pine_scripts/indicators/chainer_trader.pine`
- 修改：
- `src/trader/strategy/base_strategy.py`
- `tests/test_entry_exit_ma_cross.py`