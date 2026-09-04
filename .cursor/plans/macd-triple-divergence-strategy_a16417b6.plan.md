---
name: macd-triple-divergence-strategy
overview: 实现基于 MACD 柱状图三段顶/底背离的 ChainerTrader 策略，同时提供 Backtrader(Python) 与 TradingView PineScript 版本，只需实现多空信号并保持与现有 Chainer 框架兼容。
todos:
  - id: design-divergence-rules
    content: 精确定义 MACD 柱状图三段顶/底背离的波段划分与价格/MACD 关系判定规则，并确定初始参数（opp_ratio、zero_eps、price_eps、macd_eps）。
    status: completed
  - id: implement-python-strategy
    content: 在 src/trader/strategy 中实现 MACDTripleDivergenceStrategy，基于 BaseStrategy 实现 get_long_signal/get_short_signal 与特殊止损逻辑。
    status: completed
  - id: implement-pinescript-indicator-strategy
    content: 在 src/pine_scripts/indicators 与 src/pine_scripts/strategies 中分别实现对齐的 PineScript 版本，只替换 getLongSignal/getShortSignal 并加入特殊止损信号。
    status: completed
  - id: sync-and-validate-signals
    content: 在相同历史数据下对比 Backtrader 与 PineScript 版本的信号与绩效，并微调参数满足文档中的全部测试示例。
    status: completed
isProject: false
---

### 目标

- **策略逻辑**: 按照文档与你补充的描述，实现基于 **MACD 柱状图三段顶背离 / 三段底背离** 的入场信号，并包含文中提到的特殊止损逻辑。
- **框架集成**: 在 Python 端基于 `BaseStrategy`/`ChainerTraderStrategy` 信号接口实现；在 PineScript 端基于 `chainer_trader.pine` 模板的 `getLongSignal` / `getShortSignal` 实现同构逻辑。
- **统一行为**: Backtrader 与 Pine 版本在同一历史数据/参数下，理论上给出一致的做多/做空信号与特殊止损行为（考虑到指标计算差异，允许极少量边缘差异）。

### 核心策略设计

- **MACD 设置**
  - 使用标准 MACD 参数 **(12, 26, 9)**，基于收盘价计算柱状图 `hist`。
  - 统一在 Backtrader 端用 `bt.indicators.MACDHisto`，Pine 端用 `ta.macd` 或等效内置实现，确保直方图含义一致（快线-慢线 的 EMA 差再平滑）。
- **“波段”定义（基于柱状图）**
  - 将 MACD 柱子按**符号连续**划分为一个个波段：
    - **红波段（底背离候选）**: `hist < 0` 连续区间；记录该段内 **最小值(最负)** 的绝对值 `|hist_min|` 以及该最小值所在 K 线索引。
    - **绿波段（顶背离候选）**: `hist > 0` 连续区间；记录该段内 **最大值** 以及所在 K 线索引。
  - 0 附近的极小柱（绝对值小于某个 `zero_eps`）可视为“空白”处理，避免噪声频繁分段。
- **三段底背离检测（做多信号）**
  - 在最近的历史中，寻找 **3 个依次出现的红波段 R1, R2, R3**，它们之间被“相反颜色”的波段隔开：
    - R1 — G12 — R2 — G23 — R3，其中 G12, G23 是绿波段或“接近相反方向的弱波段”。
    - 对“接近相反”的量化：
      - 取 R1, R2, R3 三段中最大的红柱绝对值 `H_ref`。
      - 对每个间隔波段 G，若其最大柱高 `G_max` 满足 `G_max <= opp_ratio * H_ref`，则视为“弱反向波段”可接受；否则认为结构不干净，不触发三段结构。
      - `opp_ratio` 作为**可调参数**，默认例如 `0.35`（后续你根据作者测试组微调）。
  - 在价格上：
    - 对应每个红波段，在该波段内寻找**最低价** `P1, P2, P3`（底背离）；
    - 要求 **P1 > P2 > P3**（价格依次创新低，可加一点 `price_eps` 容忍度）。
  - 在 MACD 柱上：
    - 对应 R1, R2, R3 的最负值为 `M1, M2, M3`（均为负数）；
    - 要求 **|M1| > |M2| > |M3|**（红柱绝对值依次变小，视觉上“峰”抬高），可加 `macd_eps` 容忍度。
  - 当上述条件全部满足，且结构完成于 R3 中的**最后一个红柱附近**（例如 R3 的最负点之后，价格出现反弹/柱子明显缩短），在靠近 R3 尾部那根 K 线上产生 **做多信号**。
- **三段顶背离检测（做空信号）**
  - 规则完全对称：
    - 使用 **绿波段 G1, G2, G3** 与中间红波段作为隔离；
    - 对应价格高点 **H1 < H2 < H3**（价格依次创新高）；
    - MACD 柱高度 **G1_max > G2_max > G3_max**（绿柱依次变矮）；
    - 同样采用 `opp_ratio`、`price_eps`、`macd_eps` 做容忍控制；
    - 在 G3 完成阶段给出**做空信号**。
- **特殊止损逻辑（基于 MACD 柱）**
  - 以底背离做多为例：
    - 入场时记录：当前柱状图值 `hist_entry`（应为负值但绝对值已经较前两段小）。
    - 之后若在持仓期间出现新的红柱，且其绝对值 **大于入场时的绝对值**：`|hist_now| > |hist_entry| + macd_stop_eps`，
    则认为 **底背离结构失效或进一步恶化**，立即发出 **强制止损信号**：
      - Backtrader 端：立刻触发 `exit_trade` 或直接平仓；
      - Pine 端：在同一根 K 线上发出“强制平仓”条件（不影响后续在同一大波段出现新三段结构再次入场）。
  - 顶背离做空逻辑镜像：若入场后出现更高的绿柱（`hist_now > hist_entry + macd_stop_eps`），则强制止损。

### Backtrader / ChainerTrader Python 实现方案

- **新策略类位置**
  - 在 `[src/trader/strategy](src/trader/strategy)` 下新建文件，命名类似 `MACDTripleDivergence.py`（英文命名，便于维护）。
  - 策略类例如 `MACDTripleDivergenceStrategy(BaseStrategy)`。
- **参数设计**
  - MACD 参数：`macd_fast=12, macd_slow=26, macd_signal=9`。
  - 结构参数：
    - `opp_ratio`（默认 0.35）：隔离波段最大柱高度占参考红柱高度的最大比例。
    - `zero_eps`：小于该绝对值的柱子视为 0，用于分段去噪。
    - `price_eps`：价格新高/新低比较时的最小差值阈值。
    - `macd_eps`：MACD 绝对值严格递减/递增时的容忍度。
    - `max_lookback_bars`：向后回溯查找波段的最大 K 线数限制。
  - Chainer 相关参数：沿用 `BaseStrategy` / `ChainerTraderStrategy` 的模式（`chainer_mode`, `chainer_auto_signal` 等），只在本策略中打开自动信号。（在文件注释中说明本策略主要通过 `get_long_signal` / `get_short_signal` 输出信号。）
- **内部数据结构与算法**
  - 在 `__init__` 中：
    - 初始化 `self.macd_hist = bt.indicators.MACDHisto(self.data, ...)`；
    - 维护一个**波段数组**结构，例如保存最近若干个完整波段：`[Segment]`，每个 Segment 包含：
      - `start_idx, end_idx, sign, max_val, min_val, max_idx, min_idx`；
    - 在 `next()` 或专门方法中，根据当前 `hist` 与前一根 `hist` 的符号，维护分段：
      - 符号改变（跨过 `zero_eps`）时关闭前一段并开启新段；
      - 更新当前段的极值与其索引。
  - 封装两个纯逻辑函数：
    - `detect_bottom_triple_divergence(segments, data)` → `bool`；
    - `detect_top_triple_divergence(segments, data)` → `bool`；
    - 这两个函数只依赖历史 `segments` 与 `close/high/low`，便于在 Pine 中 1:1 复刻。
  - 在策略中实现：
    - `get_long_signal()`：
      - 在当前 bar 前，拿最近若干个完整红/绿段调用 `detect_bottom_triple_divergence(...)`；
      - 返回 `True/False`；
    - `get_short_signal()`：对称调用 `detect_top_triple_divergence(...)`。
  - 特殊止损：
    - 使用 Chainer 的交易上下文（或直接通过 `self.position`）在 `next()` 中：
      - 如果存在持仓，并且是本策略开仓（可用 `self.position.size` 和方向判断），
      - 读取持仓建立时记录的 `hist_entry`（需要在开仓当根 bar 上缓存到策略属性中），
      - 若满足“更长柱子”条件，则主动调用 `exit_trade()` 或等效平仓，**不依赖 `get_short_signal()**`。

### PineScript 实现方案

- **新脚本位置与结构**
  - 在 `[src/pine_scripts/indicators](src/pine_scripts/indicators)` 新增一个脚本，例如 `macd_triple_divergence.pine`。
  - 参考现有 `[src/pine_scripts/indicators/chainer_trader.pine](src/pine_scripts/indicators/chainer_trader.pine)`：
    - 保留 Chainer 通用输入参数与状态管理；
    - 仅替换 `getLongSignal()` / `getShortSignal()` 的实现逻辑为“三段顶/底背离”。
- **信号实现对齐 Python 版**
  - 使用 `ta.macd` 获取 `macd`, `signal`, `hist`；
  - 在脚本内维护与 Python 端对应的**波段数组**：
    - Pine 中可用 `var` + 数组（`array`）保存最近 N 段；
    - 每根 bar 更新当前段信息，如符号变化则写入数组并开启新段；
  - 实现与 Python 版结构几乎相同的两个函数：
    - `detectBottomTripleDivergence()` → `bool`；
    - `detectTopTripleDivergence()` → `bool`；
  - `getLongSignal()` / `getShortSignal()` 直接返回上述函数结果，保证逻辑对齐。
- **特殊止损在 Pine 中的表现**
  - 若使用 **策略版**（`src/pine_scripts/strategies/chainer_trader.pine`），则：
    - 同样在开仓时缓存 `hist_entry` 与方向；
    - 在每根 bar 检查是否触发“柱子变得更极端”的条件，若触发：
      - 产生一个立即平仓操作（可通过库里的临时 exit API 或直接 `strategy.close`）。
  - 若使用 **指标版**，则：
    - 仅在图表上标记“提前止损信号”（例如画出特殊图标），由 Chainer 的逻辑在 Python 端对接；
    - 这部分可视你后续需要再扩展。

### 测试与验证

- **Python 端回测验证**
  - 使用已有的 BTC/ETH 1h 数据（`data/ETHUSDT-1h-202301-202401.csv` 等），在 `scripts/backtrader_strategy.json` 或新建任务配置中加入该策略；
  - 对比：
    - 多空信号是否与 TradingView 上的 Pine 版本大致一致；
    - 最大回撤 / 胜率 / 入场点是否与作者文中案例接近。
- **PineScript 端视觉验证**
  - 在 TradingView 上加载指标 + 策略版本，对照作者的截图/测试案例：
    - 检查三段底背离/顶背离标记位置；
    - 调整 `opp_ratio`、`zero_eps` 等参数，使所有样例都能被正确识别。
- **参数调优**
  - 将 `opp_ratio` 等关键参数以 `input` 形式暴露（Python 端通过配置，Pine 端通过 `input.float`）。
  - 你根据作者给出的多组日期案例逐一验证，微调参数后最终固化为默认值。

