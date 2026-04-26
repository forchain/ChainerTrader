## Context

前一轮参数优化验证表明，历史数据准备的主要低效点不是样本执行，而是长区间补数时把上市前空窗当成有效覆盖工作：
- 在 `1d` 长窗口上，系统会反复对请求起点前后不存在的数据发起下载
- 用数据库首根 K 线推断“交易所最早可用时间”不严谨，因为数据库本身可能只保存了局部历史
- 交易所 SDK 和文档没有稳定暴露现成的 `listing_time` / `first_available_open_time` 字段，不能把方案建立在一个未经证实的字段上

因此本次 change 不依赖“交易所明确给出上市时间”这一前提，而是把最早可用时间视为一个系统运行时可学习、可持久化的 availability metadata。

## Goals / Non-Goals

**Goals:**
- 为 `(exchange, symbol, interval)` 引入持久化的 `earliest_known_open_time`
- 将历史补数改为从请求结束时间向前分页回补，并在成功回补中持续学习更早边界
- 保证 `earliest_known_open_time` 只会向更早更新，不会因为空响应或错误回退到更晚
- 区分 `EMPTY` 和 `ERROR`，避免把第三方接口失败误判成“已到最早可用时间”
- 保留上市后真实中间缺口的检测和补数能力
- 为核心状态机和边界更新逻辑提供自动化 TDD 覆盖

**Non-Goals:**
- 不依赖交易所专门提供 `listing_time` 或等价字段
- 不要求一次运行就精准求出绝对首根 K 线时间
- 不在本次 change 中解决所有中间缺口识别误差，只要求不把边界向更晚污染
- 不把外部网络调用作为 CI 中的强依赖测试

## Decisions

### 决策 1：引入“最早已知可用时间”元数据，而不是信任 DB 首根

**选择**：为 `(exchange, symbol, interval)` 维护 `earliest_known_open_time`，语义是“截至目前系统已知最早可以稳定获取到的数据时间”。

**备选方案**：
- 继续直接使用数据库首根 K 线
- 依赖交易所 `exchangeInfo` 或 SDK 暴露上市时间字段

**理由**：数据库首根只能代表“本地目前最早存到哪”，不能代表交易所最早可用时间；而现有文档和 SDK 模型没有证明存在稳定的上市时间字段。用系统自维护的 availability metadata 更稳，也更贴合后续多轮优化的运行模型。

### 决策 2：历史补数改为倒序分页，并顺手学习边界

**选择**：当需要扩展历史覆盖时，从 `requested_end` 向前分页拉取 K 线；每一批成功返回都会更新本轮 `earliest_seen_open_time`，在本轮结束后尝试把 metadata 向更早刷新。

**备选方案**：
- 继续从 `requested_start` 正向下载
- 额外设计一次性的“首根 K 线二分探测”

**理由**：倒序回补更符合实际需求，能优先拿到真实存在的数据并减少上市前空窗的无效请求。与额外 probe 相比，它把“学习边界”作为正常下载的副产品，不需要为 metadata 单独设计一套前置探测流程。

### 决策 3：空数据与请求失败必须区分为不同状态

**选择**：历史回补的单次请求结果分为三态：
- `NON_EMPTY`: 请求成功且返回 K 线
- `EMPTY`: 请求成功但无 K 线
- `ERROR`: 网络错误、超时、限流或其他失败

其中只有 `EMPTY` 才允许结束当前倒序回补；`ERROR` 不能被视为最早边界，需要走重试或保守退出。

**备选方案**：
- 将“空响应”和“请求失败”统一视为“获取不到”

**理由**：如果不区分 `EMPTY` 与 `ERROR`，第三方网络抖动会被误判成“已经没有更早数据”，从而污染 `earliest_known_open_time`，这是不可接受的。

### 决策 4：metadata 只允许向更早更新

**选择**：`earliest_known_open_time` 是单调递减边界：
- 若本轮回补拿到更早 K 线，则更新
- 若本轮只拿到更晚或同样早的时间，则不变
- 空响应、重试失败和中间缺口都不能把边界更新成更晚

**备选方案**：
- 每轮运行后都直接用本轮结果覆盖 metadata

**理由**：中间缺口或短暂 API 不稳定可能让某一轮过早停止。如果允许更晚覆盖更早，边界会被污染并导致后续重复下载。

### 决策 5：中间缺口暂不作为“绝对边界识别”的一部分

**选择**：当前版本只要求：
- 上市前空窗不再造成长期重复下载
- metadata 可以在多轮运行中逐步向更早修正

如果倒序分页恰好撞上中间缺口，本轮可以停止并保持当前 metadata，不需要在本次 change 中精确地区分“真实首边界”与“临时中间空窗”。

**备选方案**：
- 在第一版就精确检测所有中间缺口并继续跨缺口向前搜索

**理由**：这会显著放大状态复杂度和第三方请求量。当前更重要的是避免明显的上市前无效下载，并保持 metadata 不被错误回退。

### 决策 6：availability metadata 以数据库为权威存储，可选本地缓存为加速层

**选择**：权威状态保存在数据库；如需本地文件镜像，只作为加速副本，不作为真相来源。

**备选方案**：
- 只用本地文件缓存
- 把 metadata 混在 K 线表或 CSV cache 文件名里

**理由**：数据库更适合跨轮次、跨工作树复用状态；文件缓存容易丢失，不适合作为长期权威边界。

## Proposed Model

### Availability Metadata

最小字段集：
- `exchange`
- `symbol`
- `interval`
- `earliest_known_open_time`
- `updated_at`
- `source`

语义：
- `earliest_known_open_time` 不是“理论绝对首根”
- 它是“系统当前已知最早可用边界”
- 边界可以随着后续运行继续向更早修正

### Backward Fill State Machine

```text
current_end = requested_end
earliest_seen = None

loop:
  result = fetch_batch(end_time=current_end, limit=L)

  if result == ERROR:
    retry or abort conservatively

  if result == EMPTY:
    stop current backward fill

  if result == NON_EMPTY:
    write batch to DB
    earliest_seen = min(earliest_seen, batch.first_open_time)
    current_end = batch.first_open_time - interval_duration
    continue

after loop:
  if earliest_seen is earlier than metadata:
    persist metadata
```

## Risks / Trade-offs

- **倒序分页依赖交易所接口语义**：需要确认 `klines(endTime, limit)` 的返回稳定可用于向前翻页；这是外部接口验证项，不应伪装成稳定单元测试
- **中间缺口可能导致本轮提前停止**：metadata 可能暂时停在偏晚位置，但不会污染成更晚；后续运行仍可继续向前推进
- **第三方错误不能当作 empty**：实现上必须明确区分返回空数据和请求失败
- **数据库新增 metadata 存储层**：需要额外 schema 和读写路径，但能显著降低长区间重复下载

## Testing Strategy

### Automated TDD Coverage

默认以自动化测试为主，不要求人工参与。核心逻辑应先写失败测试，再实现：
- 倒序分页在连续批次下能持续向前推进
- `NON_EMPTY / EMPTY / ERROR` 三态行为正确
- `earliest_known_open_time` 只向更早更新，不向更晚回退
- 已有局部历史时，请求更早区间仍可继续向前扩展
- 中间空窗不会把 metadata 覆盖成更晚
- `DatasetResolver` 与 availability metadata 的集成行为正确

### External Interface Validation

需要单独验证 Binance `klines(endTime, limit)` 是否满足倒序翻页假设，但这属于第三方接口语义确认：
- 可以通过一次性脚本或受控 smoke check 验证
- 不作为稳定 CI 断言
- 如果环境网络、权限或第三方服务不可用，必须明确报告，而不是声称“自动化测试已覆盖”

### Manual Testing

默认不需要人工手测。
只有当第三方接口行为无法在当前环境可靠验证时，才需要额外说明该限制；这不应影响本地状态机和元数据逻辑的自动化 TDD 覆盖。

## Open Questions

- Binance `klines(endTime, limit)` 的真实返回语义是否完全稳定到足以作为倒序分页基础
- availability metadata 是否需要第一版就暴露管理命令或调试输出
- 本地文件镜像是否值得在第一版引入，还是先只做数据库权威存储
