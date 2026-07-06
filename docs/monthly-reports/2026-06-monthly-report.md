# 2026-06 月报

**周期**: 2026-06-01 至 2026-06-30

**作者范围**: 全部作者

**数据来源**: `git-weekly-report` 技能脚本导出的 git 提交记录，并用 `origin/main` 主线提交交叉校验。

## 数据口径

- 主线已合入提交: 19 个，覆盖 PR #103 至 #125 期间的 live trading、任务恢复、资金预留、账户能力和订单管理工作。
- 全 refs 视图中有 66 个 6 月 author-date 提交条目，包含主线 squash commit 与分支级支撑提交。
- 本报告优先按 `origin/main` 已合入提交归纳成果；月底分支级提交单独标注，避免把尚未在 6 月主线化的工作混入主线成果。

## 已完成工作

### 主线合入成果

#### 新功能

- 调整 live MACD 任务周期到 1h，统一实盘任务执行节奏。(`b033c72`, #103)
- 新增 live task funds reservation，减少多任务或重复启动时的资金占用冲突。(`c2ef4a9`, #115)
- 为交易所订单打上结构化 `clientOrderId`，并在任务 start / stop 时执行 open orders 清理。(`f0f298b`, #124)
- 在账户页暴露 margin capacity，并强制用户级交易凭证路径，支持 borrowable / operable amount 展示。(`d2567cb`, #125)
- 增加 CCXT HTTP proxy 配置，补齐网络访问受限环境下的交易所连接配置入口。(`9258a81`, #106)

#### 缺陷修复

- 修复 workbench report asset paths，保证优化报告资源路径可访问。(`cc7456e`, #104)
- 恢复 running tasks / live tasks 的 restart recovery 路径，并避免重复恢复、嵌套 event loop、stale running task 等问题。(`d65d2ee`, #105; `7d66692`, #107)
- 处理 margin borrow block exceptions，并让 live fund precheck 支持 margin-aware 校验。(`b1bce24`, #108; `f475052`, #122)
- 在 shutdown 期间保留 live task state，增强 execution state persistence，并忽略 live task history 中的 warmup operations。(`82ea953`, #109; `a2e6427`, #112; `2f2f1cc`, #116)
- 分页展示 task operation records，减少长历史记录对任务页面可用性的影响。(`20efb9f`, #110)
- 修复 backtest dataset gaps，提高回测数据完整性。(`9cea635`, #113)
- 保持 polling scheduler 在 recovery failure 后继续运行。(`9e52d20`, #118)
- 保留 task config form submit 后的表单状态，减少配置失败后的重复输入成本。(`b2ccdfa`, #119)
- 暴露 task startup failures，避免启动失败只停留在服务端日志中。(`5311291`, #121)

#### 重构

- 移除 live short execution switch，收敛 live execution 配置面。(`1c0355c`, #120)

### 分支级支撑提交

- 月底形成了 leverage ratio config / live auto execution regression / leveraged entry notional cap 等提交，为后续杠杆风险控制主线化提供基础。(`9079495`, `53a6e1a`, `ae88f40`)
- 设计并实现 open orders page 的初步分支工作，包含错误模型、页面计划和功能提交。(`64484f1`, `dd51a88`, `c450145`, `785f279`)
- 收敛 shared Chainer sizing params 命名，降低策略参数与框架共享参数的冲突风险。(`0967e3e`)
- 账户能力分支补充了 margin capacity rejection 解释、exchange info 错误上下文、terminal error highlighting 和 legacy account info fields 兼容。(`963bdfc`, `76ee63f`, `4039800`, `45fd53d`)

## 进行中工作

- 6 月提交记录中未发现 `WIP`、`TODO`、`draft` 或 `partial` 等明确进行中标记。
- 从全 refs 视图看，open orders page、leverage ratio、prefixed sizing params 等月底分支工作在 6 月已有实质提交，但未全部以 6 月 author-date 主线提交呈现。

## 本月亮点

- Live task restart recovery 成为 6 月最核心的稳定性主题：任务恢复、状态持久化、shutdown 保留和失败可见性均有主线修复。
- 实盘资金与账户能力模型明显增强：资金预留、margin-aware precheck、borrowable / operable amount 展示共同降低了实盘启动前的资金判断盲区。
- 订单管理开始具备可追溯上下文：`clientOrderId` 标记和任务 start / stop open orders 清理为后续任务级订单治理打下基础。
- UI / 运维可用性持续改善：task operation pagination、startup failure surface、form state preservation 和 workbench asset path 修复降低了排障成本。

## 下月建议计划

- 把月底形成的 leverage ratio、open orders page、prefixed sizing params 工作继续推进到主线验收，并补齐对应的用户文档或验收记录。
- 针对 restart recovery、fund reservation、margin-aware precheck 和 order cleanup 建立组合回归矩阵，覆盖服务重启、任务恢复、账户余额不足、margin borrow blocked 和 open orders 残留场景。
- 将 `clientOrderId` 规则、订单清理边界、用户凭证使用路径写入运维手册，方便 live trading 问题排查时按任务和订单关联追踪。

## 风险与阻塞

- 提交记录中未出现明确阻塞项。
- 6 月变更集中在 live trading 关键路径，后续风险主要来自跨功能交互: restart recovery、资金预留、margin precheck 与订单清理需要一起验证，单点测试不足以证明完整实盘生命周期安全。
