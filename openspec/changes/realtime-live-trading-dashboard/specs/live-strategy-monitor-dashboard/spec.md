## ADDED Requirements

### Requirement: Web 模式提供实盘策略监控面板
系统 SHALL 在 Web 模式下提供 live strategy monitor dashboard，用于查看当前运行中的实盘策略、市场流状态、最近一次策略执行状态、通知状态和图表诊断信息。

#### Scenario: 打开监控面板
- **WHEN** 用户在 Web 模式访问 live strategy monitor dashboard
- **THEN** 系统 SHALL 展示当前可监控的 live 策略列表
- **THEN** 系统 SHALL 展示每个策略的 symbol、interval、strategy name、execution mode、连接状态和最近一次执行时间

#### Scenario: 没有运行中的策略
- **WHEN** 用户打开监控面板且当前没有 live 策略运行
- **THEN** 系统 SHALL 展示空状态
- **THEN** 系统 SHALL 不渲染误导性的空白 K 线图

### Requirement: 监控面板使用可切换策略工作区
系统 SHALL 使用可切换的策略工作区展示多个 live 策略，避免将所有图表简单平铺在同一个页面。

#### Scenario: 切换策略标签
- **WHEN** 用户从 BTCUSDT 1m 策略切换到 ETHUSDT 1d 策略
- **THEN** 系统 SHALL 将主图表、策略状态、参数面板和诊断事件切换到 ETHUSDT 1d 策略
- **THEN** 系统 SHALL 保持其他策略继续在后台接收和处理实时更新

#### Scenario: 多策略状态摘要
- **WHEN** 多个 live 策略同时运行
- **THEN** 系统 SHALL 在策略列表或标签区域展示每个策略的摘要状态
- **THEN** 摘要状态 SHALL 至少区分运行中、断线重连中、最近产生信号和错误状态

### Requirement: 初始图表绘制最近 500 条 K 线
系统 SHALL 在用户选择某个 live 策略后，向图表提供该策略最近最多 500 条闭合 K 线作为初始 candlestick 数据集。

#### Scenario: 策略有超过 500 条历史 K 线
- **WHEN** 用户打开某个 live 策略图表，且数据库中该市场周期有超过 500 条闭合 K 线
- **THEN** 图表 SHALL 只加载最近 500 条闭合 K 线作为初始数据

#### Scenario: 策略少于 500 条历史 K 线
- **WHEN** 用户打开某个 live 策略图表，且数据库中该市场周期少于 500 条闭合 K 线
- **THEN** 图表 SHALL 加载所有可用闭合 K 线
- **THEN** 面板 SHALL 标明当前历史窗口不足 500 条

### Requirement: 实时绘制未闭合和已闭合 K 线
系统 SHALL 将服务器推送的每条 Kline update 实时绘制到图表上；未闭合 K 线 SHALL 更新当前 candle，已闭合 K 线 SHALL 完成当前 candle 并允许后续新 candle 追加。

#### Scenario: 未闭合 K 线更新当前 candle
- **WHEN** dashboard 收到 closed flag 为 false 的 Kline update
- **THEN** 图表 SHALL 用该 update 的 OHLCV 更新当前 candle
- **THEN** 图表 MUST NOT 标记该 candle 已完成

#### Scenario: 已闭合 K 线完成 candle
- **WHEN** dashboard 收到 closed flag 为 true 的 Kline update
- **THEN** 图表 SHALL 用该 update 的 OHLCV 绘制完成该 candle
- **THEN** 图表 SHALL 在后续新 open time 到来时追加下一根 candle

### Requirement: 图表展示策略信号和框架风险诊断
系统 SHALL 在图表和诊断面板中展示策略信号、框架参数和交易生命周期诊断，使用户能够快速核对 live runtime 是否按预期执行。

#### Scenario: 图表展示交易信号
- **WHEN** 策略执行结果包含进场、出场、阻塞或取消事件
- **THEN** dashboard SHALL 在对应 candle 上展示可区分的 signal marker
- **THEN** 诊断面板 SHALL 展示事件时间、方向、价格、原因和任务执行模式

#### Scenario: 图表展示止损和止盈参考
- **WHEN** 策略或 Chainer 框架为交易事件提供 stop-loss、take-profit 或 risk/reward reference
- **THEN** dashboard SHALL 在图表上展示对应价格线或区间
- **THEN** dashboard SHALL 标明这些线是本地策略风险参考而不是交易所已提交订单

#### Scenario: 图表展示保本止损移动
- **WHEN** Chainer 框架触发 breakeven stop movement
- **THEN** dashboard SHALL 在图表上展示止损位从旧价格移动到新价格的轨迹或事件标记
- **THEN** 诊断面板 SHALL 展示移动时间、旧止损价、新止损价和触发 step

#### Scenario: 图表展示 MACD 三背离诊断
- **WHEN** MACD triple divergence 策略输出 divergence legs 或 signal metadata
- **THEN** dashboard SHALL 在价格图或指标区域展示可核对的背离结构
- **THEN** 诊断面板 SHALL 展示对应 signal event id 和关键条件结果

### Requirement: 监控更新协议可被自动测试
系统 SHALL 定义稳定的 server-to-dashboard 更新协议，使自动测试能够验证初始快照、Kline update、strategy event、risk overlay 和 runtime status 的字段。

#### Scenario: 初始快照包含 chart-ready 数据
- **WHEN** dashboard 客户端订阅某个 live 策略
- **THEN** 服务器 SHALL 返回包含 strategy id、market、interval、latest candles、runtime status 和 enabled overlay types 的初始快照

#### Scenario: 实时事件包含诊断字段
- **WHEN** 服务器向 dashboard 推送实时更新
- **THEN** 每条更新 SHALL 包含 event type、strategy id、event time 和足够客户端幂等更新图表的 payload
