## ADDED Requirements

### Requirement: 信号生命周期结果可供通知流程消费

系统 SHALL 允许框架管理的信号生命周期结果被任务层或通知层消费，用于生成进场、出场、阻塞或取消等用户可见事件，而不要求具体策略覆写共享信号路由流程。

#### Scenario: entry context 创建后可生成通知事件
- **WHEN** 框架根据信号成功创建 entry context
- **THEN** 任务层或通知层 SHALL 能读取方向、信号上下文、trade id 和本地交易状态以生成进场通知事件

#### Scenario: exit request 触发后可生成通知事件
- **WHEN** 框架根据信号或本地交易引擎触发 exit request
- **THEN** 任务层或通知层 SHALL 能读取方向、信号上下文和退出原因以生成出场通知事件

#### Scenario: 通知消费不改变策略路由职责
- **WHEN** 系统启用手动实盘通知模式
- **THEN** 策略 SHALL 继续通过标准信号接口和框架 lifecycle 机制暴露行为
- **THEN** 策略 MUST NOT 为了发送通知而覆写共享 `_process_signals()` 路由流程
