## 1. Availability Metadata Model

- [x] 1.1 为 `(exchange, symbol, interval)` 定义 availability metadata 存储结构，包含 `earliest_known_open_time`
- [x] 1.2 在数据库层新增 availability metadata 读写接口
- [x] 1.3 约束 `earliest_known_open_time` 只能向更早更新，不能被更晚值覆盖

## 2. Backward Fill Workflow

- [x] 2.1 为历史补数抽象倒序分页流程，从 `requested_end` 向前获取批次
- [x] 2.2 为单批请求定义 `NON_EMPTY / EMPTY / ERROR` 三态结果
- [x] 2.3 确保只有 `EMPTY` 能结束当前回补，`ERROR` 必须走重试或保守退出
- [x] 2.4 在成功回补中记录本轮 `earliest_seen_open_time` 并回写 metadata

## 3. Dataset Resolver Integration

- [x] 3.1 让 `DatasetResolver` 读取 availability metadata，而不是直接信任数据库首根 K 线
- [x] 3.2 保持上市后真实中间缺口的检测与补数语义不变
- [x] 3.3 确保局部历史场景下，请求更早区间仍可继续扩展覆盖
- [x] 3.4 保持现有 CSV dataset cache 与 `dataset_ref` 复用逻辑兼容

## 4. Automated Tests

- [x] 4.1 先写失败测试：倒序分页在连续批次下能向前推进并更新 earliest metadata
- [x] 4.2 先写失败测试：`EMPTY` 与 `ERROR` 不会被混淆
- [x] 4.3 先写失败测试：已有局部历史时，请求更早区间不会被错误跳过
- [x] 4.4 先写失败测试：中间空窗不会把 metadata 回退成更晚
- [x] 4.5 补充 resolver 集成测试，验证 availability metadata 与缺口补数的接线正确

## 5. External Validation

- [x] 5.1 通过一次性验证脚本或受控 smoke check 确认 Binance `klines(endTime, limit)` 是否满足倒序分页假设
- [x] 5.2 若外部接口验证无法稳定自动化，明确记录限制并避免将其计入 CI 通过标准
