## Why

现有优化报告已经能输出聚合排名、审计结果和交易明细，但还不能高效支持人工验证。用户无法从当前静态 HTML 中快速判断每个 `Chainer` 参数是否留下了可观察痕迹，也无法在界面微调时脱离重新生成整份 HTML 的低效工作流。

## What Changes

- 新增动态的 optimization validation workbench，前端从 JSON 产物读取数据并渲染交互界面，而不是将所有展示内容固化到单个 HTML 文件中
- 新增面向人工验证的 `workbench.json` 契约，聚合 run 摘要、候选项、参数观察结果、紧凑交易明细和原始 report 跳转入口
- 新增“参数观察”模型，按关键 `Chainer` 参数生成定性状态和证据摘要，帮助人工快速验证参数是否正在工作
- 重构优化报告展示结构，把“候选扫描”“参数验证”“深查入口”拆成独立视图，而不是继续扩展当前长表和抽屉
- 扩展逐笔交易 JSON 结构，补齐数量、执行上下文和参数观察所需字段
- 提供轻量本地服务入口，允许 workbench 通过 HTTP 动态读取 JSON 产物，避免纯前端改动也需要重新生成整份 HTML

## Capabilities

### New Capabilities
- `optimization-validation-workbench`: 提供动态的优化结果人工验证工作台，包括候选列表、参数观察视图、紧凑交易明细和原始报告深查入口
- `optimization-parameter-observability`: 为关键 `Chainer` 参数生成可供人工定性验证的观察状态、证据摘要和可疑信号

### Modified Capabilities
- `backtest-json-report`: 扩展回测与优化产物的 JSON 契约，输出 workbench 所需的逐笔交易字段、链接信息和参数观察原始证据

## Impact

- `src/trader/analyzers/backtest_report.py`
- `src/trader/task/optimization_report.py`
- `src/trader/task/optimization_audit.py`
- `src/trader/task/`
- `src/trader/rpc/static/`
- `scripts/`
- `reports/optimizations/<run_id>/`
- `tests/`
