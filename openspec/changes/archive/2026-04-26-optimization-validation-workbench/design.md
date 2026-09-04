## Context

当前优化结果已经具备 `aggregate/audit/clusters/local_best/shortlist` 等机器可读产物，但人工验证入口仍然停留在单个静态 `rankings/index.html`。现有页面同时承担“候选扫描”“参数验证”“逐笔交易浏览”三种职责，导致交互和布局不断退化，而且每次界面微调都需要重新生成整份 HTML。

新设计将把优化报告拆成两层：Python 负责生成结构化 JSON，动态前端 workbench 负责读取 JSON 并提供适合人工验证的界面。目标不是替代审计层，而是在审计层之上提供一个围绕 `Chainer` 参数可观察性设计的验证工作台。

## Goals / Non-Goals

**Goals:**
- 为每个 optimization run 生成单一入口的 `workbench.json`，供动态前端消费
- 为关键 `Chainer` 参数生成人工可读的“参数观察”状态和证据摘要
- 提供围绕“候选扫描 -> 参数验证 -> 深查原始报告”的页面结构
- 将 workbench 与 run 数据解耦，使纯前端改动不需要重跑优化
- 保留原有审计产物，并让 workbench 复用其结果而不是重复推导

**Non-Goals:**
- 不替代原始 `runs/*.json` 作为最细粒度证据源
- 不在 V1 实现复杂图表、TradingView 联动或跨 run 对比
- 不在 V1 重写已有 RPC 系统，只提供能稳定打开本地 run 数据的轻量入口

## Decisions

### 决策 1：新增 `workbench.json` 作为前端专用聚合契约

**选择**：每个 optimization run 生成一个 `reports/optimizations/<run_id>/workbench.json`，包含 run 摘要、候选项、参数观察摘要、紧凑交易明细和原始报告链接。

**备选方案**：
- 前端自行拼接 `aggregate.json`、`audit.json`、`clusters.json`、`runs/*.json`
- 继续将所有信息固化到静态 HTML

**理由**：单一契约能显著降低前端复杂度，也避免界面层对现有内部 JSON 结构形成硬耦合。现有审计 JSON 仍保留给脚本和 Agent 使用，`workbench.json` 只服务人工验证界面。

### 决策 2：参数观察模型独立于机器审计状态

**选择**：每个关键参数在 workbench 中输出人工验证状态：`has_evidence`、`not_triggered`、`no_evidence`、`suspicious`，并附带证据摘要和简要统计。

**备选方案**：
- 直接暴露机器审计状态 `effective/no_opportunity/...`
- 不单独建模参数观察，只让用户阅读逐笔交易

**理由**：机器审计状态适合脚本和阻断逻辑，不适合人工快速浏览。参数观察模型面向“定性验证”，强调“这个参数有没有留下可见痕迹”，更接近用户的实际核验任务。

### 决策 3：详情视图按验证任务组织，而不是按 JSON 字段组织

**选择**：候选详情固定分为 `参数观察`、`交易明细`、`审计上下文` 三个视图。交易明细采用 5 列紧凑语义布局：方向、时间、价格、风控、退场。

**备选方案**：
- 继续在抽屉里扩展长表和字段列
- 将所有字段平铺成多列，由自动列宽算法决定布局

**理由**：人工验证关注的是参数是否工作，而不是字段是否完整。按验证任务组织界面，能显著减少横向滚动和反复回跳。

### 决策 4：动态 workbench 通过 HTTP 读取 run 数据

**选择**：提供轻量本地服务入口，让前端通过 HTTP 读取 `reports/optimizations/<run_id>/workbench.json` 和原始 `runs/*.json`。

**备选方案**：
- 继续双击打开 `file://` HTML
- 在 HTML 中内联全部 JSON 内容

**理由**：浏览器对 `file://` 场景下的动态读取限制较多，不适合作为长期方案。HTTP 方案更稳定，也能让前端资源与 run 数据彻底解耦。

### 决策 5：逐笔交易 JSON 补充数量与执行证据字段

**选择**：在现有 `BacktestReportAnalyzer` 输出基础上补充数量、仓位成本、执行关联字段和 parameter-observability 所需原始证据。

**备选方案**：
- 前端自行从 PnL 和价格反推数量
- 仅在 workbench.json 中补充衍生字段，不改原始 `runs/*.json`

**理由**：数量、信号时间、止损变化等信息本身就是最细粒度的证据，应该存在于原始 run 报告中，而不是只存在于衍生视图。

## Risks / Trade-offs

- **前端资产与 run 数据路径耦合** → 通过 `workbench.json` 和统一静态服务前缀隔离路径细节
- **参数观察规则过多，前端逻辑复杂** → 参数观察在 Python 端计算，前端只渲染结果
- **workbench.json 体积膨胀** → 只放人工验证需要的摘要与紧凑交易数据，原始明细仍保留在 `runs/*.json`
- **旧静态排名页与新 workbench 并存造成混乱** → 保留旧页作为兼容入口，但将 workbench 设为默认人工验证入口

## Migration Plan

1. 为新 change 增加 `workbench.json`、参数观察模型和动态前端规格
2. 在现有优化产物生成流程中追加 `workbench.json` 输出，不移除旧产物
3. 增加静态前端资源和本地 HTTP 入口，能够读取指定 run 的 workbench 数据
4. 将最新基线 run 重生成为 workbench 数据并验证交互
5. 保留旧 `rankings/index.html` 作为兼容视图，待用户确认后再决定是否降级或移除

## Open Questions

- V1 是否需要在 workbench 中直接展示 shortlist，还是先聚焦候选扫描与参数验证
- 原始 report 的打开方式是直接 JSON 链接即可，还是需要额外提供目录级浏览入口
- 是否需要在 V1 中支持跨 run 对比，还是留到后续 change
