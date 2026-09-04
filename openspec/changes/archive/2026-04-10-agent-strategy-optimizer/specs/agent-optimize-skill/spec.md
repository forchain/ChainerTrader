## ADDED Requirements

### Requirement: Skill 定义完整的 Agent 纵向优化工作流

`strategy-optimize` skill SHALL 定义一套完整、可被任意 Agent（包括低成本模型）执行的策略纵向优化工作流，包括前置检查、问题识别框架、One Change Rule、迭代循环和停止条件。

#### Scenario: Skill 被 Agent 调用时执行前置检查
- **WHEN** Agent 调用 strategy-optimize skill
- **THEN** Agent SHALL 首先验证：JSON 报告系统可用、训练/验证数据集就位、已记录 baseline 指标

#### Scenario: Skill 定义问题识别优先级
- **WHEN** Agent 读取 JSON 报告后进行问题识别
- **THEN** Agent SHALL 按以下优先级顺序识别最高优先级问题：(1) Sharpe < 0，(2) 总交易数 < 10，(3) 最大回撤 > 20%，(4) Profit Factor < 1.0，(5) 验证集衰减 > 30%

#### Scenario: Skill 强制执行 One Change Rule
- **WHEN** Agent 决定进行代码改动
- **THEN** Agent SHALL 每次迭代只改动一处（一个函数、一个参数、或一段逻辑），改动前记录 `git diff`

#### Scenario: Skill 定义改动接受/回滚机制
- **WHEN** Agent 完成一次迭代并比较指标
- **THEN** 若主指标（Sharpe + Profit Factor）改善则保留改动；否则执行 `git checkout` 回滚并记录失败假设

#### Scenario: Skill 定义停止条件
- **WHEN** 满足以下任一条件
- **THEN** Agent SHALL 停止优化循环并报告结果：(a) 达到目标指标（Sharpe > 1.0 且 Profit Factor > 1.5 且 MaxDD < 20%），(b) 连续 5 次迭代无改善，(c) 已完成 20 次迭代

---

### Requirement: Skill 包含防过拟合校验步骤

Skill SHALL 规定每 5 次训练集迭代后，Agent MUST 在验证集上运行一次回测，检查验证集 Sharpe 是否 ≥ 训练集 Sharpe × 0.7。

#### Scenario: 验证集通过防过拟合校验
- **WHEN** Agent 在验证集运行回测且 val_sharpe ≥ train_sharpe × 0.7
- **THEN** Agent 可继续优化循环

#### Scenario: 验证集未通过防过拟合校验
- **WHEN** Agent 在验证集运行回测且 val_sharpe < train_sharpe × 0.7
- **THEN** Agent SHALL 停止优化，报告过拟合风险，建议回滚到上一个验证集通过的版本

---

### Requirement: Skill 对 Token 消耗优化

Skill SHALL 明确规定 Agent 只读取 JSON 报告文件（< 5KB）进行分析，禁止读取原始日志文件；每轮迭代的 Token 消耗目标 < 5000 tokens。

#### Scenario: Agent 分析时只读 JSON 报告
- **WHEN** Agent 执行分析步骤
- **THEN** Agent SHALL 读取 `reports/` 下最新的 JSON 文件，不得读取日志文件或原始 CSV 数据

#### Scenario: 单轮迭代流程紧凑
- **WHEN** Agent 执行一次完整迭代（读报告 → 分析 → 改动 → 运行 → 比较）
- **THEN** 所读取的文件总大小 < 20KB（JSON 报告 + 改动的代码片段）
