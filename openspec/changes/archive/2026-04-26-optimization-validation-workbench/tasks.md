## 1. Data Contract

- [x] 1.1 扩展逐笔交易 JSON 字段，补充数量、执行上下文和参数观察所需原始证据
- [x] 1.2 实现 `workbench.json` 生成逻辑，聚合 run 摘要、候选项、参数观察摘要和原始 report 链接
- [x] 1.3 为 `workbench.json` 和新增逐笔证据字段补充自动化测试

## 2. Parameter Observability

- [x] 2.1 实现关键 `Chainer` 参数的观察状态模型和证据摘要生成
- [x] 2.2 将参数观察结果接入候选项构建流程，并与现有 audit 结果对齐
- [x] 2.3 为参数观察模型补充针对确认、止损、止盈、保本和最小余额参数的测试

## 3. Dynamic Workbench Frontend

- [x] 3.1 新增独立的 workbench 前端静态资源，支持读取指定 run 的 `workbench.json`
- [x] 3.2 实现候选扫描视图、参数观察视图、紧凑交易明细视图和原始 report 深查入口
- [x] 3.3 为前端渲染契约和关键交互补充自动化验证

## 4. Delivery Path

- [x] 4.1 提供轻量本地 HTTP 入口或等价方式，确保 workbench 可通过 HTTP 动态读取 run 数据
- [x] 4.2 将最新基线 run 重生成并验证 workbench 页面可用
- [x] 4.3 运行完整回归测试、更新现有 PR，并整理验收汇总
