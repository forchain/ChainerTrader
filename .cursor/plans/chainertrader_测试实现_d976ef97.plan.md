---
name: ChainerTrader 测试实现
overview: 在 tests/trader/indicators/chainer_trader.py 中实现 ChainerTrader 框架的可视化测试，验证 MA Cross 信号、进出场确认、止损、保本等核心逻辑，输出丰富的图表用于对比验证 Pine Script 实现。
todos:
  - id: impl-test-strategy
    content: 实现 ChainerTraderTestStrategy，继承现有策略并记录所有信号状态
    status: completed
  - id: impl-observer
    content: 创建 ChainerTraderObserver 用于可视化信号标记（Entry/Exit/Confirm/Fail）
    status: completed
  - id: impl-data-export
    content: 实现数据加载、CSV 导出和图表生成逻辑
    status: completed
  - id: impl-main-test
    content: 实现 test_chainer_trader() 主测试函数，整合所有组件
    status: completed
---

# ChainerTrader 指标测试实现

## 目标

创建一个测试文件，用于**可视化验证** ChainerTrader 框架的核心逻辑，确保 Python 实现与 Pine Script 行为一致。不执行实际交易，但需要丰富的图表输出。

## 核心可视化内容（对应 Pine Script）

根据 [`src/pine_scripts/strategies/chainer_trader.pine`](src/pine_scripts/strategies/chainer_trader.pine) 中的 `plotshape` 和 `plot` 语句：| Pine Script | Python 可视化 ||-------------|---------------|| Fast/Slow SMA | 两条均线叠加在 K 线图上 || Entry Signal (E) | 绿色向上标记 || Exit Signal (X) | 红色向下标记 || Entry Confirm (flag) | 绿色旗帜标记 || Entry Fail (xcross) | 绿色叉号标记 || Exit Confirm (flag) | 红色旗帜标记 || Exit Fail (xcross) | 红色叉号标记 || Stop Loss 线 | 红色水平线（持仓期间） || Take Profit 线 | 青色水平线（持仓期间） |

## 实现结构

参考 [`tests/trader/indicators/test_super_trend.py`](tests/trader/indicators/test_super_trend.py) 的测试模式：

```javascript
tests/trader/indicators/chainer_trader.py
├── ChainerTraderTestStrategy      # 继承 BaseStrategy，记录所有信号用于可视化
├── ChainerTraderObserver          # 自定义 Observer，绘制信号标记
├── get_klines_from_db()           # 从 MongoDB 加载数据
├── extract_chainer_series()       # 提取指标数据用于导出
├── save_chainer_csv()             # 导出 CSV
└── test_chainer_trader()          # 主测试函数
```



## 关键实现点

1. **信号记录**：在策略的 `next()` 中记录所有信号状态到列表，供后续可视化
2. **Observer 可视化**：使用 backtrader 的 Observer 机制在图表上绘制标记
3. **止损/止盈线**：使用 `plot.style_linebr` 风格（仅持仓期间显示）
4. **数据源**：使用 MongoDB 中的 BTC-USDT 1h 数据（与其他测试一致）

## 文件依赖

- [`src/trader/strategy/base_strategy.py`](src/trader/strategy/base_strategy.py) - 基础策略框架