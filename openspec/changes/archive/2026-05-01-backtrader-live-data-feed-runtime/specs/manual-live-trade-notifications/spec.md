## ADDED Requirements

### Requirement: realtime 手动通知从 feed 增量事件发出
系统 SHALL 在 Backtrader live data feed runtime 中为同一个持久 feed 产生的增量策略事件发送手动实盘通知。系统 SHALL 在开发验证阶段让启动 warmup 操作和 LIVE 操作走同一通知流程。系统 MUST NOT 为完整窗口回放结果或已经发送过的历史操作发送 manual live trade notification。

#### Scenario: warmup 阶段产生进场操作
- **WHEN** Backtrader live data feed runtime 处于 warmup 或 DELAYED 状态，且策略处理历史补齐 K 线时产生进场操作
- **THEN** 系统 SHALL 保留该操作用于策略内部状态和诊断
- **THEN** 系统 SHALL 发送手动实盘进场通知
- **THEN** 系统 MUST NOT 调用交易所下单接口

#### Scenario: LIVE 阶段产生进场操作
- **WHEN** feed 已进入 LIVE 状态，且新闭合 K 线推进策略产生进场操作
- **THEN** 系统 SHALL 发送手动实盘进场通知
- **THEN** 系统 MUST NOT 调用交易所下单接口

#### Scenario: LIVE 阶段没有新增操作
- **WHEN** feed 已进入 LIVE 状态，且新闭合 K 线推进策略没有产生新增操作
- **THEN** 系统 MUST NOT 根据已经发送过的操作重复发送手动通知

#### Scenario: 重连 catch-up 产生操作
- **WHEN** WebSocket 重连后系统通过 catch-up K 线推进 live feed，且 catch-up K 线处于 LIVE 后的缺失区间
- **THEN** 系统 SHALL 按时间顺序处理这些新增策略事件
- **THEN** 系统 SHALL 对未发送过且符合通知策略的事件发送手动通知

### Requirement: 手动通知去重基于 live 事件身份
系统 SHALL 为 realtime 手动通知维护稳定事件身份，并基于该身份防止重复通知。事件身份 SHALL 至少包含 task id、symbol、interval、operation side、operation time 和可用的 signal event id。

#### Scenario: 同一 live 操作被重复观察
- **WHEN** 系统重复观察到同一个 live 操作事件
- **THEN** 系统 SHALL 识别其事件身份已经发送
- **THEN** 系统 MUST NOT 再次发送同一手动通知

#### Scenario: 不同 live 操作共享同一价格
- **WHEN** 两个 live 操作价格相同但 operation time 或 signal event id 不同
- **THEN** 系统 SHALL 将它们识别为不同事件
- **THEN** 系统 SHALL 分别按通知策略处理
