# ChainerTrader 指标和策略模板实现计划

## 目标

1. 将现有的指标版本 `src/pine_scripts/indicators/chainer_trader.pine` 改造成模板结构
2. 创建策略版本 `src/pine_scripts/strategies/chainer_trader.pine`，实现止损与确认的区分
3. 两个版本都设计为可扩展模板，只需替换信号生成函数即可

## 关键设计决策

### 1. 止损 vs 确认的区别

- **止损**：使用 `strategy.exit()` 的 `stop` 参数，TradingView 实时监控价格，一旦触及立即执行
- **确认**：在 `barstate.isconfirmed` 时检查 `close` 价格，判断是否满足确认条件

### 2. 模板结构

- **信号生成函数化**：将进场/出场信号生成独立为函数，方便替换
- **清晰的代码分区**：使用注释标记各个功能模块
- **通用框架复用**：止损、确认、保本、风险回报比等逻辑作为通用框架

## 实现步骤

### 第一部分：指标模板改造

### 步骤 1: 改造指标文件结构

改造 `src/pine_scripts/indicators/chainer_trader.pine`：

- 将信号生成逻辑提取为独立函数 `getEntrySignal()` 和 `getExitSignal()`
- 使用清晰的注释分区标记各个功能模块
- 保持指标的可视化功能（plotshape、label等）

### 步骤 2: 指标信号函数化

在指标版本中：

- 创建 `getEntrySignal() => bool` 函数，封装MA Cross进场信号逻辑
- 创建 `getExitSignal() => bool` 函数，封装MA Cross出场信号逻辑
- 保留自定义时间信号作为备选（通过参数控制）

### 步骤 3: 指标确认逻辑优化

- 确保确认逻辑在 `barstate.isconfirmed` 时执行（使用close价格）
- 止损检查保持实时（使用low/high价格）
- 保持现有的绘图和标签功能

### 第二部分：策略模板创建

### 步骤 4: 创建策略文件

在 `src/pine_scripts/strategies/` 目录下创建 `chainer_trader.pine`

### 步骤 5: 基础结构设置

- 使用 `strategy()` 声明（而非 `indicator()`）
- 导入 ChainerTraderLib 库
- 设置策略参数（仓位大小、手续费等）

### 步骤 6: 策略信号生成函数化

创建以下函数模板：

```pine
// 信号生成函数（新策略只需替换这部分）
getEntrySignal() => bool
getExitSignal() => bool
```

当前实现使用 MA Cross 作为示例，新策略只需替换这两个函数。

### 步骤 7: 交易状态管理

- 使用 `strategy.position_size` 判断持仓状态
- 管理 `pendingEntry` 和 `pendingExit` 状态
- 跟踪 `entryKeyBarIndex` 和 `exitKeyBarIndex`

### 步骤 8: 进场逻辑实现

- **进场信号触发**：调用 `getEntrySignal()`，记录关键K线索引
- **止损计算**：使用 `ChainerTraderLib.stopPrice()` 计算初始止损价
- **是否需要确认**：
- 如果不需要确认：立即执行 `strategy.entry()`，设置 `strategy.exit()` 的 `stop`
- 如果需要确认：设置 `pendingEntry = true`，等待确认

### 步骤 9: 进场确认逻辑（bar_close时）

- 在 `barstate.isconfirmed` 时检查确认状态
- 使用 `ChainerTraderLib.entryConfirm()` 检查 `close` 价格
- 确认成功：执行 `strategy.entry()`，设置止损
- 确认失败：清空交易状态

### 步骤 10: 出场逻辑实现

- **出场信号触发**：调用 `getExitSignal()`，记录关键K线索引
- **是否需要确认**：
- 如果不需要确认：立即执行 `strategy.close()`
- 如果需要确认：设置 `pendingExit = true`，等待确认

### 步骤 11: 出场确认逻辑（bar_close时）

- 在 `barstate.isconfirmed` 时检查确认状态
- 使用 `ChainerTraderLib.exitConfirm()` 检查 `close` 价格
- 确认成功：执行 `strategy.close()`
- 确认失败：清空出场状态

### 步骤 12: 止损和止盈管理

- **止损**：使用 `strategy.exit()` 的 `stop` 参数，TradingView 自动实时监控
- **止盈**：如果设置了风险回报比，使用 `strategy.exit()` 的 `limit` 参数
- **保本**：在 `barstate.isconfirmed` 时检查保本条件，动态更新 `strategy.exit()` 的 `stop` 参数

### 步骤 13: 保本逻辑实现

- 在 `barstate.isconfirmed` 时检查保本条件
- 使用 `ChainerTraderLib.breakevenPrice()` 计算新的保本价
- 如果达到保本条件，更新 `strategy.exit()` 的 `stop` 参数

### 步骤 14: 绘图和调试

- 绘制进场/出场信号标记
- 绘制止损/止盈线（仅在持仓时）
- 实现调试日志功能

## 文件结构

### 指标模板结构

```javascript
src/pine_scripts/indicators/chainer_trader.pine
├── 指标声明和导入
├── 参数设置（Chainer参数 + 信号参数）
├── 信号生成函数（模板部分，可替换）
│   ├── getEntrySignal() => bool
│   └── getExitSignal() => bool
├── 交易状态变量（var）
├── 进场逻辑
│   ├── 信号触发
│   ├── 止损计算
│   └── 立即进场或等待确认
├── 进场确认（bar_close时）
├── 出场逻辑
├── 出场确认（bar_close时）
├── 止损/保本管理（实时检查low/high）
├── 绘图（plotshape、label等）
└── 调试日志
```



### 策略模板结构

```javascript
src/pine_scripts/strategies/chainer_trader.pine
├── 策略声明和导入
├── 参数设置（Chainer参数 + 信号参数）
├── 信号生成函数（模板部分，可替换）
│   ├── getEntrySignal() => bool
│   └── getExitSignal() => bool
├── 交易状态变量
├── 进场逻辑
│   ├── 信号触发
│   ├── 止损计算
│   └── 立即进场或等待确认
├── 进场确认（bar_close时）
├── 出场逻辑
│   ├── 信号触发
│   └── 立即出场或等待确认
├── 出场确认（bar_close时）
├── 止损/止盈/保本管理
│   ├── 初始止损/止盈设置
│   └── 保本更新（bar_close时）
├── 绘图
└── 调试日志
```



## 关键代码模式

### 止损设置（实时监控）

```pine
if hasTrade and not na(stopPrice)
    strategy.exit("Exit", "Entry", stop=stopPrice, limit=takeProfitPrice)
```



### 确认检查（bar_close时）

```pine
if barstate.isconfirmed and pendingEntry
    confirmStatus = ChainerTraderLib.entryConfirm(dir, entryKeyBarIndex)
    if confirmStatus == 1
        // 确认成功，执行进场
    else if confirmStatus == -1
        // 确认失败，清空状态
```



### 保本更新（bar_close时）

```pine
if barstate.isconfirmed and hasTrade and enableBreakeven
    newBreakevenStop = ChainerTraderLib.breakevenPrice(dir, entryPrice, initialStop)
    if not na(newBreakevenStop) and newBreakevenStop > stopPrice  // LONG
        stopPrice := newBreakevenStop
        // 更新 strategy.exit() 的 stop 参数
```



## 扩展性设计

1. **信号函数独立**：新策略只需实现 `getEntrySignal()` 和 `getExitSignal()`
2. **参数分组**：Chainer参数和信号参数分开，便于管理
3. **注释清晰**：每个模块都有清晰的注释说明
4. **状态管理统一**：所有策略共享相同的状态管理逻辑

## 指标与策略版本的区别

### 指标版本特点

- 使用 `indicator()` 声明，不执行实际交易
- 使用 `var` 变量模拟交易状态
- 止损检查：实时检查 `low/high` 是否触及止损价
- 确认检查：在 `barstate.isconfirmed` 时检查 `close` 价格
- 可视化：使用 `plotshape`、`label` 等绘图函数

### 策略版本特点

- 使用 `strategy()` 声明，可执行实际交易
- 使用 `strategy.position_size` 判断持仓状态
- 止损管理：使用 `strategy.exit()` 的 `stop` 参数，TradingView自动实时监控
- 确认检查：在 `barstate.isconfirmed` 时检查 `close` 价格
- 可视化：使用 `plotshape`、`plot` 等绘图函数

## 注意事项

1. **barstate.isconfirmed**：确保确认逻辑只在K线完成时执行