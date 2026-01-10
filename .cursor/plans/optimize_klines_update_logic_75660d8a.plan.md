---
name: 优化K线更新逻辑
overview: 优化 UpdateKlinesTask 的时间范围计算逻辑，支持检测和填补数据缺口，添加强制更新功能。
todos:
  - id: add-delete-method
    content: 在 kline.py 添加 delete_klines_in_range 方法
    status: completed
  - id: extend-config
    content: 在 task_config.py 添加 force_update 参数
    status: completed
  - id: refactor-task
    content: 重构 update_klines_task.py 的时间范围计算和下载逻辑
    status: completed
  - id: add-tests
    content: 添加各场景的单元测试
    status: completed
---

# 优化 K 线更新逻辑

## 核心修改

### 1. 新增数据库方法 - [`src/trader/database/kline.py`](src/trader/database/kline.py)

添加删除方法（现有的 `get_first_kline` 和 `get_latest_kline` 已满足查询需求）：

- `delete_klines_in_range(name, start_time, end_time)` - 删除指定时间范围内的记录

### 2. 扩展任务配置 - [`src/trader/task/task_config.py`](src/trader/task/task_config.py)

- 添加 `force_update: bool = False` 参数
- 解析配置时支持 `"force_update": true`

### 3. 重构更新逻辑 - [`src/trader/task/update_klines_task.py`](src/trader/task/update_klines_task.py)

```
1. 确定时间范围：
   - start_time: 未指定 -> 交易所最早可用
   - end_time: 未指定 -> 当前时间

2. 如果 force_update=true:
   - 删除 [start_time, end_time] 范围内所有记录
   - 直接下载 [start_time, end_time]，结束

3. 获取数据库边界：db_first, db_last

4. 根据边界关系确定下载范围：
   - 无记录: 下载 [start, end]
   - end < db_first: 下载 [start, end]
   - start < db_first ≤ end ≤ db_last: 下载 [start, db_first)
   - db_first ≤ start ≤ end ≤ db_last: 跳过
   - start ≤ db_last < end: 下载 (db_last, end]
   - start < db_first 且 db_last < end: 下载两段
```

## 配置示例

```json
{
  "task_type": "UPDATE_KLINES",
  "symbol": "BTC-USDT",
  "interval": "1h",
  "start_time": "2024-01-01 00:00:00",
  "end_time": "2024-06-01 00:00:00",
  "force_update": true
}
```

中间如有缺口，使用 `force_update: true` 重新下载整段数据。

