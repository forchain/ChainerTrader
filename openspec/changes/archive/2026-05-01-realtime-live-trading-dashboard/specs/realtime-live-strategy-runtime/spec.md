## ADDED Requirements

### Requirement: 实盘启动时补齐最近缺失 K 线
系统 SHALL 在开启 realtime live strategy runtime 时，根据任务的 exchange、symbol 和 interval 查询数据库最新闭合 K 线，并通过交易所 REST Kline API 补齐数据库最新记录到当前时间之间缺失的闭合 K 线，单次启动补齐数量 MUST NOT 超过 500 条。

#### Scenario: 数据库没有历史记录
- **WHEN** realtime live strategy runtime 启动，且数据库没有该 exchange、symbol 和 interval 的 K 线记录
- **THEN** 系统 SHALL 从交易所获取最新的 500 条 K 线数据
- **THEN** 系统 SHALL 将获取到的闭合 K 线写入数据库

#### Scenario: 数据库缺失 100 条 K 线
- **WHEN** realtime live strategy runtime 启动，且数据库最新记录到当前时间之间缺失 100 条闭合 K 线
- **THEN** 系统 SHALL 从交易所获取这 100 条缺失 K 线
- **THEN** 系统 SHALL 将获取到的闭合 K 线写入数据库

#### Scenario: 数据库缺失超过 500 条 K 线
- **WHEN** realtime live strategy runtime 启动，且数据库最新记录到当前时间之间缺失超过 500 条闭合 K 线
- **THEN** 系统 SHALL 仅获取最近 500 条 K 线用于本次 live 启动
- **THEN** 系统 SHALL 在 runtime 诊断状态中标明启动补齐被 500 条上限截断

### Requirement: 启动补齐后立即执行一次策略
系统 SHALL 在启动补齐完成并持久化后，使用该任务最新的最多 500 条闭合 K 线执行一次策略，用于检查启动前是否已经存在可通知的交易信号。

#### Scenario: 启动补齐后存在进场信号
- **WHEN** runtime 启动补齐完成后执行策略，且策略在最新闭合 K 线窗口产生进场操作
- **THEN** 系统 SHALL 按任务执行模式处理该操作
- **THEN** manual_notify 模式 SHALL 发送对应通知事件

#### Scenario: 启动补齐后没有交易信号
- **WHEN** runtime 启动补齐完成后执行策略，且策略没有产生进场或出场操作
- **THEN** 系统 SHALL 记录本次启动执行结果
- **THEN** 系统 SHALL 继续进入 WebSocket 实时监听状态

### Requirement: 通过 Binance Kline WebSocket 接收实时数据
系统 SHALL 使用 Binance Spot Kline WebSocket stream 接收任务 symbol 和 interval 的实时 K 线更新，并将交易所 payload 规范化为包含 open time、close time、OHLCV、event time 和 closed flag 的本地 Kline update。

#### Scenario: 收到未闭合 K 线更新
- **WHEN** Binance WebSocket 推送的 Kline payload 中 closed flag 为 false
- **THEN** 系统 SHALL 发布该 Kline update 给实时监控消费者
- **THEN** 系统 MUST NOT 执行策略
- **THEN** 系统 MUST NOT 将该未闭合 K 线作为最终闭合记录写入 K 线数据库

#### Scenario: 收到已闭合 K 线更新
- **WHEN** Binance WebSocket 推送的 Kline payload 中 closed flag 为 true
- **THEN** 系统 SHALL 将该闭合 K 线写入数据库
- **THEN** 系统 SHALL 使用最新的闭合 K 线窗口执行一次策略
- **THEN** 系统 SHALL 发布策略执行结果和 Kline update 给实时监控消费者

### Requirement: 多个实盘策略共享市场数据流
系统 SHALL 支持多个 live strategy runtime 同时运行，并对相同 exchange、symbol 和 interval 的任务共享同一个市场 WebSocket 数据流。

#### Scenario: 两个策略订阅相同市场周期
- **WHEN** BTCUSDT 1m 的两个 live 策略同时启动
- **THEN** 系统 SHALL 建立或复用同一个 BTCUSDT 1m WebSocket 订阅
- **THEN** 两个策略 runtime SHALL 分别接收该市场数据流的 Kline update

#### Scenario: 两个策略订阅不同市场周期
- **WHEN** BTCUSDT 1m 和 ETHUSDT 1d 的 live 策略同时启动
- **THEN** 系统 SHALL 为不同 exchange、symbol 和 interval 组合维护独立市场流状态
- **THEN** 两个策略 runtime SHALL 独立执行各自策略生命周期

### Requirement: WebSocket 断线后补齐缺失闭合 K 线
系统 SHALL 在 Binance WebSocket 断线重连后，根据数据库最新闭合 K 线和当前时间执行一次 bounded catch-up，并在恢复实时监听前补齐最多 500 条缺失闭合 K 线。

#### Scenario: 断线期间缺失闭合 K 线
- **WHEN** WebSocket 断线后重新连接，且断线期间已经产生闭合 K 线
- **THEN** 系统 SHALL 通过 REST 获取缺失闭合 K 线
- **THEN** 系统 SHALL 按时间顺序持久化并执行这些闭合 K 线对应的策略检查

#### Scenario: 重连时没有缺失闭合 K 线
- **WHEN** WebSocket 断线后重新连接，且数据库最新闭合 K 线仍然连续
- **THEN** 系统 SHALL 不执行额外 REST 补齐
- **THEN** 系统 SHALL 继续消费 WebSocket 推送

### Requirement: 提供 BTCUSDT 1 分钟 MACD 三背离示范策略任务
系统 SHALL 提供一个端到端 BTCUSDT 1 分钟 MACD triple divergence live demo task，用于在 manual_notify 模式下高频手动验证实时行情、策略触发、图表诊断和邮件通知路径。

#### Scenario: 运行示范任务
- **WHEN** 用户启动 BTCUSDT 1m MACD triple divergence demo live task
- **THEN** 系统 SHALL 使用 realtime live strategy runtime 获取并更新 BTCUSDT 1m K 线
- **THEN** 系统 SHALL 使用 MACD triple divergence 策略检查信号
- **THEN** 系统 SHALL 在 signal 产生时通过 manual_notify 路径发送邮件通知

#### Scenario: 示范任务不执行交易所下单
- **WHEN** BTCUSDT 1m demo task 在 manual_notify 模式产生交易操作
- **THEN** 系统 MUST NOT 调用交易所下单接口
- **THEN** 系统 SHALL 在通知和 dashboard 中标明该事件是本地策略建议
