## Why

ChainerTrader 当前的历史回测能力主要围绕“币种 × 周期 × 策略”展开，尚不支持将策略参数作为正式搜索维度，因此无法系统性寻找跨币种、跨周期更稳健的参数组合。与此同时，历史数据获取与自动补数能力仍然分散在具体任务实现中，尚未形成统一的数据准备机制，容易在未来不同回测场景中重复实现“查库、补数、缓存”的逻辑。

本次变更的目标是建立一套端到端、机制化的历史回测优化管线：用户只需声明币种、周期、时间区间、策略和参数空间，框架自动准备所需数据、展开回测矩阵、执行批量回测、生成单次与聚合报表，并通过自动化测试保证整个闭环可持续演进。

## What Changes

- 新增统一的历史回测数据准备机制，在回测前自动检查数据库覆盖情况、识别区间缺口、缺失时自动从交易所补数并写回数据库
- 新增内部透明缓存机制，作为数据库数据的本地物化层，供同批回测任务共享
- 新增参数搜索配置能力，支持 `param_grid` 自动笛卡尔积和 `param_combinations` 手工组合优先级
- 扩展回测任务展开逻辑，使参数组合成为正式任务维度和结果标识
- 增强单次回测 JSON 报告，记录参数、运行标识和数据集引用
- 新增聚合优化报表，按 `(strategy, params)` 聚合跨币种、跨周期结果
- 新增排名视图，至少包含综合榜和超额收益榜
- 新增自动化测试，覆盖数据准备、参数展开、参数透传、聚合排名和报表契约

## Capabilities

### New Capabilities
- `backtest-data-preparation`: 统一准备历史回测所需数据，负责数据库覆盖检查、自动补数和内部透明缓存复用
- `backtest-parameter-grid`: 支持参数范围自动笛卡尔积、手工组合优先级和参数化回测任务展开
- `backtest-optimization-report`: 生成带运行标识的单次样本报告、聚合优化报告和目录化运行产物
- `backtest-ranking-score`: 为参数优化结果提供综合榜和超额收益榜，并定义可版本化的评分视图

### Modified Capabilities
- `backtest-json-report`: 单次回测 JSON 报告增加参数上下文、运行标识和数据集引用

## Impact

- `src/trader/task/task_config.py`
- `src/trader/task/backtrader_task.py`
- `src/trader/task/update_klines_task.py`
- `src/trader/strategy/node.py`
- `src/trader/analyzers/backtest_report.py`
- `src/trader/statistics/statistics.py`
- `tests/`
- `scripts/`
