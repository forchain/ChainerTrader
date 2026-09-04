## MODIFIED Requirements

### Requirement: 止损止盈以本地出场通知表达

手动实盘通知模式 SHALL 将止损价、止盈价和风险收益比作为策略参考信息或本地出场触发依据。系统 MUST NOT 要求用户根据邮件直接创建高级交易所订单，例如 OCO、bracket order、stop-limit 或 margin 专属订单。手动模式中的本地止损止盈通知 MUST NOT be reported as exchange-native protection and MUST NOT be reused as proof that an automatic live position is protected.

#### Scenario: 进场通知附带风险参考
- **WHEN** 策略或框架为进场操作提供建议止损价、止盈价或风险收益比
- **THEN** 手动进场通知 SHALL 将这些字段作为风险参考展示
- **THEN** 邮件 MUST NOT 声称系统已经提交交易所止损或止盈订单

#### Scenario: 本地止损触发后发送出场通知
- **WHEN** 本地策略状态触发止损出场
- **THEN** 系统 SHALL 发送普通出场通知
- **THEN** 通知 SHALL 标明触发原因是止损
- **THEN** 通知 MUST NOT 标明交易所原生止损单已经触发

#### Scenario: 本地止盈触发后发送出场通知
- **WHEN** 本地策略状态触发止盈出场
- **THEN** 系统 SHALL 发送普通出场通知
- **THEN** 通知 SHALL 标明触发原因是止盈
- **THEN** 通知 MUST NOT 标明交易所原生止盈单已经触发

### Requirement: Manual notify remains the no-order realtime safety baseline
When automatic live execution is available, `manual_notify` SHALL remain a recommendation-only mode. The system MUST NOT call exchange order placement APIs for `manual_notify` operations, even if the same task configuration format also supports `auto_trade`. The system MUST NOT route `manual_notify` operations through removed modes such as `paper_auto`.

#### Scenario: Manual notify receives a long signal after staged modes are added
- **WHEN** a realtime live task is configured with `live_execution_mode` set to `manual_notify` and the strategy emits a `BUY` or `LONG` operation
- **THEN** the system SHALL generate manual notification behavior according to the existing manual live notification requirements
- **THEN** the system MUST NOT simulate the operation through a removed live execution mode
- **THEN** the system MUST NOT place an exchange order

#### Scenario: Manual notify receives a short signal after staged modes are added
- **WHEN** a realtime live task is configured with `live_execution_mode` set to `manual_notify` and the strategy emits a `SHORT` operation
- **THEN** the system SHALL generate manual notification behavior according to the existing manual live notification requirements
- **THEN** the system MUST NOT route the operation through cross-margin short execution
- **THEN** the system MUST NOT place an exchange order
