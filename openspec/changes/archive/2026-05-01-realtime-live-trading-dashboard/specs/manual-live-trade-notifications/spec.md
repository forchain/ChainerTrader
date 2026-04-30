## ADDED Requirements

### Requirement: 实时实盘通知仅由闭合 K 线策略执行触发
系统 SHALL 在 realtime live strategy runtime 中仅根据闭合 K 线触发的策略执行结果发送 manual live trade notification。未闭合 K 线更新 MAY 用于图表实时绘制，但 MUST NOT 触发邮件交易通知。

#### Scenario: 未闭合 K 线不发送信号邮件
- **WHEN** realtime live strategy runtime 收到未闭合 Kline update
- **THEN** 系统 SHALL 将该 update 推送给 dashboard
- **THEN** 系统 MUST NOT 因该未闭合 update 发送 manual live trade notification

#### Scenario: 闭合 K 线信号发送邮件
- **WHEN** realtime live strategy runtime 收到闭合 Kline update，并且闭合 K 线策略执行产生进场或出场操作
- **THEN** manual_notify 模式 SHALL 发送对应邮件通知
- **THEN** 邮件 SHALL 包含 signal price、signal time、direction、action 和本地策略建议说明

### Requirement: 实时实盘通知包含图表诊断引用
系统 SHALL 在 manual live trade notification 中包含可与 dashboard 图表核对的诊断引用，包括 strategy id、signal event id 或等价事件标识，以及可用的 stop-loss、take-profit、breakeven 和 divergence metadata。

#### Scenario: 信号含有风险参考
- **WHEN** realtime live strategy runtime 发送进场或出场通知，且策略或框架提供 stop-loss、take-profit 或 breakeven 信息
- **THEN** 邮件 SHALL 包含这些风险参考字段
- **THEN** 邮件 MUST NOT 声称这些风险参考已经作为交易所订单提交

#### Scenario: 信号含有 MACD 三背离事件标识
- **WHEN** MACD triple divergence 策略触发通知并提供 signal event id
- **THEN** 邮件 SHALL 包含该 signal event id 或等价诊断标识
- **THEN** 用户 SHALL 能通过 dashboard 使用该标识核对对应图表事件
