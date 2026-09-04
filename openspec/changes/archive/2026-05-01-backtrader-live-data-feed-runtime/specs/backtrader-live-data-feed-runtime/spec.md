## ADDED Requirements

### Requirement: 实盘使用持久 Backtrader 运行实例
系统 SHALL 为每个 realtime live trader task 创建一个持久运行的 Backtrader `Cerebro` 实例和策略实例，并通过 live data feed 推进策略执行。系统 MUST NOT 在每根闭合 K 线到达时重新创建 `Cerebro` 或重新对最新窗口执行完整策略回放。

#### Scenario: live task 启动持久策略实例
- **WHEN** realtime live trader task 启动
- **THEN** 系统 SHALL 创建一个 Backtrader `Cerebro` 实例
- **THEN** 系统 SHALL 将任务策略添加到该 `Cerebro`
- **THEN** 系统 SHALL 在任务生命周期内复用同一个策略实例处理后续闭合 K 线

#### Scenario: 闭合 K 线不触发窗口重跑
- **WHEN** realtime live trader task 已经运行且收到一根新的闭合 K 线
- **THEN** 系统 SHALL 将该 K 线交付给 Backtrader live data feed
- **THEN** 系统 MUST NOT 创建新的 `Node` 或新的 `Cerebro` 来重跑最新 500 根 K 线

### Requirement: 提供 Backtrader live K 线 Data Feed
系统 SHALL 提供一个 Backtrader-compatible live K-line data feed，用于向 Backtrader 按时间顺序交付闭合 K 线。该 feed SHALL 返回 `islive() == True`，并 SHALL 使用 Backtrader 的 live feed 语义支持无数据等待、状态通知和干净停止。

#### Scenario: feed 声明 live 模式
- **WHEN** Backtrader 检查 realtime K-line data feed
- **THEN** feed SHALL 返回 `islive() == True`
- **THEN** Backtrader SHALL 以非 preload、非 runonce 的方式逐 bar 推进策略

#### Scenario: feed 交付一根闭合 K 线
- **WHEN** feed 队列中存在一根闭合 K 线
- **THEN** feed `_load()` SHALL 将该 K 线的 datetime、open、high、low、close、volume 和 openinterest 写入 Backtrader lines
- **THEN** feed `_load()` SHALL 返回 `True`
- **THEN** Backtrader SHALL 推进策略一次

#### Scenario: feed 暂无新数据但仍运行
- **WHEN** feed 队列中暂时没有新 K 线且任务未停止
- **THEN** feed `_load()` SHALL 按 qcheck 等待新数据
- **THEN** feed `_load()` SHALL 返回 `None` 表示当前无 bar 但 feed 仍然存活

#### Scenario: feed 停止
- **WHEN** live task 请求停止
- **THEN** feed SHALL 唤醒等待中的 `_load()`
- **THEN** feed `_load()` SHALL 返回 `False`
- **THEN** 持久 `Cerebro` SHALL 退出运行循环

### Requirement: 启动补齐通过 warmup 走正常事件流程
系统 SHALL 在 realtime live task 启动时通过 REST 补齐最近闭合 K 线，并将这些 K 线按时间顺序送入同一个 live data feed 作为 warmup 数据。Warmup 阶段 SHALL 初始化策略指标和内部状态，并 SHALL 在产生策略操作时使用与 LIVE K 线相同的 dashboard event 和 manual notification 流程。

#### Scenario: warmup 输入历史 K 线
- **WHEN** realtime live task 启动并获取到启动补齐 K 线
- **THEN** 系统 SHALL 将补齐 K 线按 open time 升序送入 live data feed
- **THEN** 持久策略实例 SHALL 通过 Backtrader 正常处理这些 K 线
- **THEN** feed SHALL 在 warmup 阶段发布 DELAYED 或等价非 LIVE 状态

#### Scenario: warmup 产生策略操作
- **WHEN** warmup 阶段策略产生进场、出场、止损或止盈操作
- **THEN** 系统 SHALL 捕获这些新增操作
- **THEN** 系统 SHALL 发布 strategy execution、signal marker、risk overlay 和 notification 事件
- **THEN** manual_notify 模式 SHALL 根据这些 warmup 操作发送手动实盘通知

#### Scenario: warmup 完成后进入 LIVE
- **WHEN** 启动补齐 K 线已经全部交付给 Backtrader feed
- **THEN** feed SHALL 发布 LIVE 状态
- **THEN** 后续新闭合 K 线产生的允许通知事件 SHALL 被视为 live 增量事件

### Requirement: 每根闭合 K 线最多推进一次策略
系统 SHALL 对 realtime live feed 输入执行幂等控制，确保同一个 exchange、symbol、interval 和 open time 的闭合 K 线最多被交付给 Backtrader 策略一次。

#### Scenario: 首次收到闭合 K 线
- **WHEN** WebSocket 首次推送某个 open time 的闭合 K 线
- **THEN** 系统 SHALL 持久化该闭合 K 线
- **THEN** 系统 SHALL 将该闭合 K 线交付给 live data feed
- **THEN** 策略 SHALL 因该 K 线推进一次

#### Scenario: 重复收到同一闭合 K 线
- **WHEN** 系统已经交付某个 open time 的闭合 K 线，随后再次收到相同 exchange、symbol、interval 和 open time 的闭合 K 线
- **THEN** 系统 SHALL 忽略重复执行输入
- **THEN** 策略 MUST NOT 因重复 K 线再次推进

#### Scenario: 收到早于最新已交付闭合 K 线的数据
- **WHEN** live task 收到早于最新已交付 closed open time 的 K 线
- **THEN** 系统 SHALL 将其视为 stale 数据
- **THEN** 系统 MUST NOT 将其交付给 live data feed

### Requirement: 未闭合 K 线不进入 Backtrader 策略执行
系统 SHALL 将未闭合 K 线用于实时 dashboard 绘制，但 MUST NOT 将未闭合 K 线交付给 Backtrader live data feed 或持久化为最终闭合 K 线。

#### Scenario: 收到未闭合 K 线
- **WHEN** Binance WebSocket 推送 closed flag 为 false 的 Kline update
- **THEN** 系统 SHALL 发布 dashboard Kline update
- **THEN** 系统 MUST NOT 将该 update 交付给 Backtrader live data feed
- **THEN** 系统 MUST NOT 因该 update 推进策略 `next()`

### Requirement: 重连补齐通过同一 live feed 推进
系统 SHALL 在 WebSocket 断线重连后通过 REST bounded catch-up 获取缺失闭合 K 线，并将缺失 K 线按时间顺序送入同一个 Backtrader live data feed。系统 MUST NOT 使用窗口重跑替代 catch-up K 线交付。

#### Scenario: 断线期间缺失多根闭合 K 线
- **WHEN** WebSocket 重连后发现数据库最新闭合 K 线到当前最新闭合 K 线之间存在缺口
- **THEN** 系统 SHALL 通过 REST 获取最多 500 根缺失闭合 K 线
- **THEN** 系统 SHALL 按 open time 升序将缺失 K 线交付给 live data feed
- **THEN** 策略 SHALL 按 K 线顺序逐根推进

#### Scenario: catch-up 包含已交付 K 线
- **WHEN** REST catch-up 返回包含已交付 open time 的 K 线
- **THEN** 系统 SHALL 跳过已交付 K 线
- **THEN** 系统 SHALL 仅将未交付闭合 K 线送入 live data feed

### Requirement: live 策略事件增量输出
系统 SHALL 为持久 Backtrader live runtime 提供增量策略事件输出，使 manual notifications、dashboard signal markers、risk overlays 和诊断事件来自新产生的 live 策略事件，而不是来自完整窗口回放结果。

#### Scenario: live bar 产生新操作
- **WHEN** LIVE 状态下的新闭合 K 线推进策略并产生新的操作事件
- **THEN** 系统 SHALL 捕获该新增操作事件
- **THEN** 系统 SHALL 将该事件发布给 dashboard 事件构建器
- **THEN** manual_notify 模式 SHALL 根据该新增事件生成通知

#### Scenario: live bar 没有新操作
- **WHEN** LIVE 状态下的新闭合 K 线推进策略但没有产生新增操作事件
- **THEN** 系统 SHALL 记录本次策略推进状态
- **THEN** 系统 MUST NOT 根据已经发送过的操作重复发送通知或 signal marker

### Requirement: replay-on-window runtime 被替换
系统 SHALL 将 realtime live trader task 的默认执行路径迁移到 Backtrader live data feed runtime。旧 replay-on-window runtime MAY 在迁移期间作为内部 fallback 保留，但 MUST NOT 作为 realtime live task 的目标架构。

#### Scenario: realtime task 使用新 runtime
- **WHEN** task 配置 `live_data_mode` 为 `realtime`
- **THEN** 系统 SHALL 使用 Backtrader live data feed runtime 执行策略
- **THEN** 系统 MUST NOT 使用 replay-on-window runtime 作为默认路径

#### Scenario: fallback 被显式使用
- **WHEN** 开发者显式启用 legacy fallback 路径
- **THEN** 系统 SHALL 在日志或诊断状态中标明当前使用 legacy replay-on-window runtime
- **THEN** 系统 SHALL 保持 manual_notify 不执行交易所下单
