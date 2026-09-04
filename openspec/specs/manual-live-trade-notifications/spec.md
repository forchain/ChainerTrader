# manual-live-trade-notifications Specification

## Purpose
TBD - created by archiving change manual-live-trade-email-notifications. Update Purpose after archive.
## Requirements
### Requirement: 手动实盘通知模式不执行交易所订单

系统 SHALL 支持一种手动实盘通知模式，在该模式下 live trader task 根据本地策略运行结果生成进场或出场建议，并通过通知渠道发送给用户，但 MUST NOT 调用交易所下单接口。

#### Scenario: 手动模式下出现买入信号
- **WHEN** live trader task 在手动实盘通知模式下产生买入或开多操作
- **THEN** 系统 SHALL 发送一条进场通知
- **THEN** 系统 MUST NOT 调用 exchange `new_order` 或等价下单接口

#### Scenario: 手动模式下出现卖出信号
- **WHEN** live trader task 在手动实盘通知模式下产生卖出、平多或出场操作
- **THEN** 系统 SHALL 发送一条出场通知
- **THEN** 系统 MUST NOT 调用 exchange `new_order` 或等价下单接口

### Requirement: 手动模式使用本地配置账户状态

手动实盘通知模式 SHALL 使用用户配置的初始资金、初始持仓和本地策略操作记录推进本地模拟账户状态。系统 MUST NOT 因真实交易所账户余额不足、余额未知或 margin SDK 不可用而阻止手动模式通知。

#### Scenario: 出场通知基于本地持仓
- **WHEN** 手动模式的本地模拟账户已有持仓，且策略触发出场操作
- **THEN** 系统 SHALL 基于本地持仓生成出场通知
- **THEN** 系统 MUST NOT 先查询真实交易所 base 资产余额来决定是否允许该通知

#### Scenario: 交易所余额不可用
- **WHEN** 手动模式产生进场或出场操作，且交易所账户余额 API 不可用
- **THEN** 系统 SHALL 仍可基于本地配置账户状态发送对应通知

### Requirement: 手动通知包含可执行操作信息

手动实盘通知邮件 SHALL 包含足够用户手动执行和核对的信息，至少包括市场、策略、模式、进场或出场动作、方向、建议金额或数量、信号价格、信号时间、本地模拟资金、本地模拟持仓，以及可用的触发原因。

#### Scenario: 进场通知内容完整
- **WHEN** 手动模式发送进场通知
- **THEN** 邮件 SHALL 标明市场、策略、`manual_notify` 模式、进场动作、买入或开多方向、建议金额或数量、信号价格和信号时间
- **THEN** 邮件 SHALL 标明该通知不是交易所成交确认

#### Scenario: 出场通知内容完整
- **WHEN** 手动模式发送出场通知
- **THEN** 邮件 SHALL 标明市场、策略、`manual_notify` 模式、出场动作、卖出或平仓方向、建议数量、信号价格、信号时间和出场原因
- **THEN** 邮件 SHALL 标明该通知不是交易所成交确认

### Requirement: 止损止盈以本地出场通知表达

手动实盘通知模式 SHALL 将止损价、止盈价和风险收益比作为策略参考信息或本地出场触发依据。系统 MUST NOT 要求用户根据邮件直接创建高级交易所订单，例如 OCO、bracket order、stop-limit 或 margin 专属订单。

#### Scenario: 进场通知附带风险参考
- **WHEN** 策略或框架为进场操作提供建议止损价、止盈价或风险收益比
- **THEN** 手动进场通知 SHALL 将这些字段作为风险参考展示
- **THEN** 邮件 MUST NOT 声称系统已经提交交易所止损或止盈订单

#### Scenario: 本地止损触发后发送出场通知
- **WHEN** 本地策略状态触发止损出场
- **THEN** 系统 SHALL 发送普通出场通知
- **THEN** 通知 SHALL 标明触发原因是止损

#### Scenario: 本地止盈触发后发送出场通知
- **WHEN** 本地策略状态触发止盈出场
- **THEN** 系统 SHALL 发送普通出场通知
- **THEN** 通知 SHALL 标明触发原因是止盈

### Requirement: 支持真实邮件端到端烟测

系统 SHALL 提供一个需要显式凭证和显式启用的端到端烟测路径，用极简策略在短周期行情输入下触发手动模式通知，并通过真实邮件服务发送通知。该烟测 MUST NOT 在缺少邮件凭证或未显式启用时运行。

#### Scenario: 极简策略触发真实邮件
- **WHEN** 用户提供有效邮件通知配置并显式启用端到端烟测
- **THEN** 系统 SHALL 使用极简策略和短周期 K 线输入触发一条手动进场或出场通知
- **THEN** 系统 SHALL 通过真实邮件服务发送该通知
- **THEN** 系统 MUST NOT 调用交易所下单接口

#### Scenario: 缺少邮件凭证时跳过真实邮件烟测
- **WHEN** 邮件发送凭证或收件配置不可用
- **THEN** 真实邮件端到端烟测 SHALL 被跳过或停止并报告缺少的前置条件
- **THEN** 系统 MUST NOT 使用占位符凭证尝试发送邮件

#### Scenario: 邮件收件验证可选
- **WHEN** 邮件提供方支持可用的收件箱 SDK 或 API 验证
- **THEN** 烟测 SHOULD 验证收件箱中存在本次测试邮件
- **WHEN** 收件箱验证不可用
- **THEN** 烟测 SHALL 输出足够的发送结果和邮件标识信息，允许用户手动验证收件

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
