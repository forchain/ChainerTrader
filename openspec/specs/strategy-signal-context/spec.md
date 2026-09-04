# strategy-signal-context Specification

## Purpose
TBD - created by archiving change macd-triple-divergence-decoupling. Update Purpose after archive.
## Requirements
### Requirement: 策略通过统一接口向框架提供入场上下文

系统 SHALL 允许策略在触发 `LONG` / `SHORT` 信号时向框架提供标准化入场上下文，至少包括 `suggested_stop_price` 和 `signal_metadata`。

#### Scenario: 策略为本次信号提供建议止损价
- **WHEN** 策略产生一个 `LONG` 或 `SHORT` triggered signal
- **THEN** 框架可以读取该信号对应的 `suggested_stop_price` 用于初始化交易止损

#### Scenario: 策略为本次信号提供附加元数据
- **WHEN** 策略产生一个 triggered signal
- **THEN** 框架可以读取 `signal_metadata` 作为结构化上下文，而不需要策略覆写交易流程

---

### Requirement: 策略私有退出规则可以与框架通用止损机制并存

系统 SHALL 允许策略在持仓后根据私有规则直接触发退出，同时保留框架通用 stoploss / take profit / breakeven 机制的可选叠加能力。

#### Scenario: 关闭框架通用止损时仅保留策略私有退出
- **WHEN** 框架通用 stoploss / take profit / breakeven 均关闭
- **THEN** 持仓退出只由策略私有退出规则和必要的最小交易流程控制

#### Scenario: 开启框架通用止损时与策略私有退出共存
- **WHEN** 框架通用 stoploss / take profit / breakeven 开启
- **THEN** 它们 SHALL 与策略私有退出规则同时生效

#### Scenario: 策略私有退出被触发
- **WHEN** 策略内部动态退出条件满足
- **THEN** 策略可以调用框架退出入口完成平仓，并由框架统一处理后续状态收口

---

### Requirement: 三背离策略不依赖文档专属交易执行开关

`macd_triple_divergence` SHALL 通过 `get_long_signal()` / `get_short_signal()` 输出信号，不再依赖 `doc_trade_logic` 这种文档专属交易执行开关。

#### Scenario: 三背离多头信号通过标准入口暴露
- **WHEN** 策略检测到底背离
- **THEN** `get_long_signal()` 返回 `True`

#### Scenario: 三背离空头信号通过标准入口暴露
- **WHEN** 策略检测到顶背离
- **THEN** `get_short_signal()` 返回 `True`

---

### Requirement: 文档样例数据不内嵌在策略运行时代码中

`macd_triple_divergence` SHALL 不在运行时代码中内嵌特定标的、特定周期的文档样例元数据；这些案例 SHALL 迁移到测试或验证资产中。

#### Scenario: 策略运行时不依赖 BTC 日线样例
- **WHEN** 策略在任意标的、任意周期上运行
- **THEN** 策略逻辑不依赖硬编码的 BTC 日线 `DOCUMENTED_CASES_META`

#### Scenario: 文档样例仍可被验证
- **WHEN** 执行对应测试或案例验证
- **THEN** BTC 日线文档样例仍可被读取并用于校验三背离信号行为

