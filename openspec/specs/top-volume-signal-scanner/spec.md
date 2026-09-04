# top-volume-signal-scanner Specification

## Purpose
TBD - created by archiving change top-volume-signal-scanner. Update Purpose after archive.
## Requirements
### Requirement: 系统能够选择 Binance 现货 USDT 交易对成交额前十的非稳定币标的

系统 SHALL 从 Binance 现货市场中筛选 `USDT` 交易对，排除稳定币基础资产后，按成交额排序选择前 10 个标的作为扫描范围。

#### Scenario: 稳定币交易对不进入扫描列表
- **WHEN** 榜单中包含 `USDCUSDT`、`BUSDUSDT`、`FDUSDUSDT` 等稳定币交易对
- **THEN** 这些交易对 SHALL 被排除，不计入最终 Top 10

#### Scenario: 只扫描 USDT 交易对
- **WHEN** Binance 现货榜单包含 `BTCUSDT`、`ETHBTC`、`BNBUSDC`
- **THEN** 只有 `BTCUSDT` 这类 `USDT` 交易对有资格进入候选集

#### Scenario: 最终候选集最多包含十个标的
- **WHEN** 候选交易对数量超过 10
- **THEN** 系统 SHALL 按成交额排序仅保留前 10 个标的

---

### Requirement: 系统在执行扫描前必须先补齐数据库中的所需 K 线

系统 SHALL 在运行策略前，先确保每个候选标的的 `1d` 最近 1 个月和 `1h` 最近 1 周 K 线数据在数据库中完整可用。

#### Scenario: 缺失数据时自动补齐
- **WHEN** 某个候选标的的 `1h` 最近 1 周数据在数据库中不完整
- **THEN** 系统 SHALL 先补齐缺失 K 线，再进入策略执行阶段

#### Scenario: 数据完整时跳过重复下载
- **WHEN** 某个候选标的的请求窗口已被数据库完整覆盖
- **THEN** 系统 SHALL 不重复下载该窗口数据

#### Scenario: 策略执行阶段只读数据库
- **WHEN** 扫描进入策略执行阶段
- **THEN** 系统 SHALL 从数据库读取窗口 K 线，而不是直接使用 API 返回的数据作为策略输入

---

### Requirement: 系统默认在两个固定窗口上执行策略

系统 SHALL 默认对每个候选标的执行两个时间窗口的扫描：`1d` 最近 1 个月，以及 `1h` 最近 1 周。

#### Scenario: 日线窗口固定为最近一个月
- **WHEN** 未传入自定义窗口参数
- **THEN** 日线扫描范围 SHALL 为最近 1 个月

#### Scenario: 小时线窗口固定为最近一周
- **WHEN** 未传入自定义窗口参数
- **THEN** 小时线扫描范围 SHALL 为最近 1 周

---

### Requirement: 系统默认使用 macd_triple_divergence 并允许策略可配置

系统 SHALL 支持通过参数指定策略名称；未指定时 SHALL 默认使用 `macd_triple_divergence`。

#### Scenario: 未指定策略参数时使用默认策略
- **WHEN** 用户运行扫描脚本且未传入策略参数
- **THEN** 系统 SHALL 使用 `macd_triple_divergence`

#### Scenario: 指定策略参数时使用目标策略
- **WHEN** 用户传入受支持的策略名称
- **THEN** 系统 SHALL 使用该策略执行扫描

---

### Requirement: 系统只输出 LONG 和 SHORT 入场信号

系统 SHALL 将“命中的信号”定义为策略产生的 `LONG` 或 `SHORT` 入场事件，并忽略平仓、止损、止盈等非入场事件。

#### Scenario: 入场信号被记录
- **WHEN** 某个候选标的在窗口内触发 `LONG` 或 `SHORT`
- **THEN** 系统 SHALL 记录一条信号，至少包含 `signal_time`、`symbol`、`interval`、`strategy`、`side`

#### Scenario: 非入场事件不输出
- **WHEN** 策略产生 `CLOSE`、`STOP`、`TP` 或其他非入场事件
- **THEN** 这些事件 SHALL 不出现在扫描结果中

---

### Requirement: 系统输出窗口内全部命中的入场信号并按时间全局排序

系统 SHALL 保留所有候选标的与周期在窗口内命中的全部入场信号，并按信号时间进行全局排序输出。

#### Scenario: 同一标的在窗口内多次命中时全部保留
- **WHEN** 同一 `symbol + interval` 在窗口内出现多次 `LONG` / `SHORT` 入场信号
- **THEN** 系统 SHALL 保留全部命中记录

#### Scenario: 汇总结果按时间排序
- **WHEN** 系统输出最终扫描结果
- **THEN** 所有信号 SHALL 按 `signal_time` 做全局排序

#### Scenario: 输出支持结构化结果
- **WHEN** 用户选择 JSON 输出
- **THEN** 系统 SHALL 生成可机器读取的结构化结果文件

