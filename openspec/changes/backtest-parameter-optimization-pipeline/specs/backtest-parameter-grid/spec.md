## ADDED Requirements

### Requirement: 系统支持参数范围自动笛卡尔积展开

系统 SHALL 支持通过 `param_grid` 为单个策略声明多个参数候选值，并自动展开为全部参数组合。

#### Scenario: 两个参数自动展开为笛卡尔积
- **WHEN** `param_grid` 中参数 A 有 2 个候选值，参数 B 有 3 个候选值
- **THEN** 系统 SHALL 生成 6 个参数组合
- **AND** SHALL 为每个参数组合创建独立回测任务

#### Scenario: 单参数自动展开
- **WHEN** `param_grid` 仅包含一个参数且有多个候选值
- **THEN** 系统 SHALL 为该参数的每个候选值生成一个独立回测任务

### Requirement: 系统支持手工指定参数组合并优先于自动展开

系统 SHALL 支持通过 `param_combinations` 手工指定参数组合，并在存在时覆盖 `param_grid` 的自动笛卡尔积展开。

#### Scenario: 自定义组合覆盖默认展开
- **WHEN** 配置同时包含 `param_grid` 和 `param_combinations`
- **THEN** 系统 SHALL 仅使用 `param_combinations`
- **AND** SHALL 不执行 `param_grid` 的自动笛卡尔积展开

#### Scenario: 手工组合避免无意义参数组合
- **WHEN** 用户仅希望执行若干已知有效的参数组合
- **THEN** 系统 SHALL 允许用户仅声明这些组合
- **AND** SHALL 不要求用户显式列出无效组合的排除规则

### Requirement: 参数搜索配置仅适用于单策略任务条目

带有参数搜索配置的任务条目 SHALL 只绑定一个策略，以避免不同策略之间的参数命名空间冲突。

#### Scenario: 单任务条目声明多个策略且包含参数搜索
- **WHEN** 某任务条目同时包含多个策略声明和 `param_grid` 或 `param_combinations`
- **THEN** 系统 SHALL 将该配置视为无效
- **AND** SHALL 返回明确的配置错误信息

### Requirement: 参数组合成为回测身份的一部分

每个参数组合 SHALL 具有稳定参数标识，并成为任务标识、单次报告和聚合报告的一部分。

#### Scenario: 同策略同市场不同参数组合可区分
- **WHEN** 同一策略在同一币种和周期下以不同参数组合运行
- **THEN** 系统 SHALL 为每个组合生成不同的 `param_id`
- **AND** SHALL 在任务结果和报表中区分这些组合

### Requirement: 无参数搜索配置时保持现有行为不变

当任务未声明 `param_grid` 或 `param_combinations` 时，系统 SHALL 使用策略默认参数运行，行为与现有系统一致。

#### Scenario: 旧配置继续可用
- **WHEN** 用户提供现有格式的普通回测配置
- **THEN** 系统 SHALL 不要求新增任何参数搜索字段
- **AND** SHALL 按当前默认参数行为执行回测
