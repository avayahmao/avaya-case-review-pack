# Cloud Bridge Pagination Speedup Implementation Plan (rev 7, approved with minor changes incorporated)

> **For agentic workers:** 按任务顺序逐项实施，使用 checkbox（`- [ ]`）跟踪进度。本方案只改云端 Apps Script 源、测试与文档；本地 Python 模块、MCP schema、安装器均不改。线上 Apps Script 重部署由用户手工完成并跑 runbook 验证，Agent 不得声称部署成功。

**目标：** 把 case review 的 Gmail 穷尽式收集耗时降一个数量级，方法是（1）将云桥每页段数上限从 4 提到 32、并新增端到端 wire 字节预算，（2）把"每页全量规范化所有消息"重构为"manifest 用元数据计算、正文只解码当前页要发射的消息"，消除 O(P×N) 重复劳动。

**架构约束：** 纯服务端变更，字节安全按**两层实际上限分别跟踪**：云端 `assertResponseSize_` 限定内层 JSON ≤ 6 MiB（`MAX_RESPONSE_BYTES`）；broker `encode_response` 限定整帧 ≤ 8 MiB（`MAX_FRAME_BYTES`，`tools/gmail/gmail_broker_protocol.py:13`）。Apps Script 响应体作为字符串嵌入 broker 帧后再经 `json.dumps` 二次编码（`:108-141` + `:256-282`），内层 JSON 中每个 `"` 与 `\` 各膨胀 +1 字节，引号/反斜杠密集正文最坏约 2× 膨胀。v3 的真实通过域是两个上限的**交集**（inner ≤ 6 MiB 且 wire ≤ 8 MiB）；发射预算必须复刻该交集而不是收紧 wire 到 6 MiB——否则 v3 可收集的线程（如单段 inner 3.20 MiB / wire 6.41 MiB）会被 v4 错误拒绝。**段元数据（headers、`attachment_names` 等）本身无长度上限，因此不存在"每页至少一段"的进度不变量**——首段超出任一实际上限按既有 sanitized 失败语义抛 `RESPONSE_TOO_LARGE`（§4.3）。SKILL.md 门禁契约全部保留。

**技术栈：** Google Apps Script V8 + Advanced Gmail Service（Gmail v1）、Node.js `node:test`（主测试 + 共享 harness + wire 探针）、Python `unittest`（既有包装 + 新增跨层帧驱动）。

---

## 0. 评审意见响应索引

### rev 1 → rev 2

| 意见 | 落实位置 |
|---|---|
| [P1] 32 段安全推导不成立（Cloud JSON 被 broker 二次编码） | §3、§4 重写为 wire-safe 字节预算 + 端到端回归测试；膨胀模型已用源码复核确认 |
| [P1] 伪代码缺少错误包装，异常可能退化为 APP_ERROR | §5.1/§5.3 补齐 try/catch；§7.1 新增错误映射测试 |
| [P1] 发布流程自相矛盾 + 版本元数据遗漏 | §9 重排为 候选提交 → 用户部署验证 → 发布；Task 7 列全 8 文件清单 |
| [P2] 测试硬编码 version 3、文档 "normalizes the full thread" 未重写 | §7.1 游标夹具版本无关化；§8 文档段落重写 |
| [P2] 性能公式应按总 segment 数建模 + 基线与验收阈值 | §5.5/§11 改用 S=Σ chunk_count；Task 6 增加基线与阈值 |

### rev 2 → rev 3

| 意见 | 落实位置 |
|---|---|
| [P1] 调用传入未定义的 `wireState`，resolver 错位 | §5.1 调用签名修正 |
| [P1] 首段可凭无上限元数据突破 8 MiB | §4.3 首段规则：超预算抛 sanitized `RESPONSE_TOO_LARGE`；删除"每页至少一段"承诺 |
| [P2] 排序错误码退化为 `MESSAGE_COLLECTION_FAILED` | §5.2 排序独立包装 `THREAD_SORT_FAILED`；懒加载路径统一（修复） |
| [P2] 帧测试未连接 JS 输出 | §7.2 改为 Node 产 doGet JSON 文本 → Python `encode_response` |
| [P2] 基线顺序不可行；`⌈S/32⌉+1` 未计入 wire | Task 6 重排为 v3 基线先行；阈值改双约束 |

### rev 3 → rev 4

| 意见 | 落实位置 |
|---|---|
| [P1] 6 MiB wire 预算收紧于 v3 真实通过域（单段 inner 3.20 MiB / wire 6.41 MiB 在 v3 两层均通过，rev 3 会拒绝），"与 v3 失败语义一致"不成立 | §4.2 改为**双预算分轨**：inner ≤ 6 MiB（`MAX_RESPONSE_BYTES` 同源）与 wire ≤ 8 MiB（`MAX_FRAME_BYTES` 同源）分别累计、分别判定；首段仅在超出任一**实际**上限时失败；§4.3 重写 v3 等价性论证（v3 经 `assertResponseSize_` 或 broker 层 `RESPONSE_TOO_LARGE` 失败的线程集合 = v4 首段/截断拒绝的集合） |
| [P2] `max(⌈S/32⌉,⌈W/C⌉+1)` 非上界（0.6C×100 顺序段实需 100 页，公式给 61）；且 runbook `Invoke-RestMethod` 不保留原始 JSON，W 不可采集 | §5.5/Task 6 放弃**预测页数公式**：夹具侧用发射器自身的 next-fit 精确重放；线上验收改为**逐页实测断言**（原始文本经 `Invoke-WebRequest` 采集，inner/wire 精确复算 ≤ 两上限）+ v3 基线页数对比；对抗语料改列安全性验证，不纳入 ≥5× 性能阈值（消除 4.17× 冲突） |
| [P2] 探针缺可复用基础设施（`loadBridge`/`rawMessage` 未导出，import 主测试会注册 node:test 并污染 stdout）；首段超限也应走真实 doGet 且错误 JSON 同样产生 broker 帧 | §7.2 重写：提取无 TAP 副作用的共享 harness 模块 `tests/js/gmail_cloud_bridge_harness.mjs`（主测试与探针共同 import）；探针驱动**真实 `doGet`**（mock `ContentService` 捕获输出文本），错误夹具的响应 JSON 同样送 `encode_response` 断言帧合法 |

### rev 4 → rev 5

| 意见 | 落实位置 |
|---|---|
| [P1] v3 通过域夹具不可实现：正文受 96 KiB 块上限约束，切不成 3.2 MiB 单段；且 38% 引号密度仅约 1.4× 膨胀，达不到 6.4/3.2 ≈ 2× | §7.1 夹具改用**无上限元数据**（巨型 `attachment_names`，字符几乎全为 `"`——`sanitizedAttachmentName_` 只剥离 NUL/CRLF，引号保留）构造单段，显式断言 `segments.length === 1` |
| [P2] runbook 修改未进入文档任务：Task 6 依赖原始 JSON，但 runbook 现用 `Invoke-RestMethod`，§8 却写"预期无需改" | §8 改为明确修改项：桥接助手改 `Invoke-WebRequest -UseBasicParsing`（PS 5.1 必带），同时保留 raw `.Content` 与 `ConvertFrom-Json` 解析对象；定义信封为 1 KiB 保守上界；Task 3/6 同步 |
| [P3] 收益表规范化次数不准确（单块消息不跨页，无重入） | §5.5/§11 改为 `N + 被页边界截断消息的重入次数`，上界 `N + P − 1`；各行数值修正 |

### rev 5 → rev 6

| 意见 | 落实位置 |
|---|---|
| [P1] 元数据夹具 raw/inner/wire 三层尺寸混淆：3.2 MiB 原始全引号元数据经 Apps Script `JSON.stringify`（inner）与 broker `json.dumps`（wire）两层转义后为 inner ≈ 6.4 MiB、wire ≈ 12.8 MiB；目标 inner 3.2 / wire 6.4 需**原始 ≈ 1.6 MiB**；且直接在原始 message 上填 `attachment_names` 会被 `normalizeMessage_` 按 payload 重建而忽略 | §7.1 夹具改为经 `payload.parts[].filename`（或 Content-Disposition）进入规范化管线；长度**按实际 `JSON.stringify(segment)` 结果动态调节**（初始长度 → 实测 → 比例缩放一次收敛），对序列化后的尺寸断言范围，不从密度反推 |
| [P2] 单块消息在字节预算截断页也会重入：发射器先 `resolveMessage()` 再发现首段放不下即收页，该消息下一页重新解析 | §5.5/§11 公式改为 `N + 页尾已解析但未完成发射的消息重入次数`（上界仍 N + P − 1）；"单块重入 0"限定为 32 段数量上限收页的情形 |

### rev 6 → rev 7（approve with minor changes，两项测试文档精化）

| 意见 | 落实位置 |
|---|---|
| [P2] 失败对照夹具"inner ≈ 4 / wire ≈ 8"可能落在 reserve 边界两侧，须先断言有效阈值再期待失败 | §7.1 对照夹具断言顺序：`innerAdd ≤ innerBudget` 且 `wireAdd > wireBudget` →（如需证明 v3 失败集合）真实 `encode_response` 帧 `> MAX_FRAME_BYTES` → 才断言 `RESPONSE_TOO_LARGE` |
| [P3] §7.1 运行命令遗漏新跨层模块 | 运行命令补 `tests.test_gmail_cloud_bridge_wire` 显式包含，或 `unittest discover tests` |

## 1. 背景与问题定位（2026-08-15 性能分析结论）

用户反馈 case review 执行慢。代码审查定位到三个相乘的放大器，本方案解决前两个：

1. **云端 O(P×N) 重复劳动（最大瓶颈）。** `readThreadPage_`（`GmailMcpBridge.gs:213-268`）被刻意设计为无状态：每一页游标请求都重新全量抓取线程（`fetchThreadForRead_`，`:271-290`），并对**全部**消息重跑 `normalizeMessage_`（`:502-560`：base64 解码、HTML→文本正则链、SHA-256、逐码点 UTF-8 切分）——包括此前页已返回的消息。P 页 × N 封邮件 = P×N 次规范化。
2. **每页只吐 4 段。** `THREAD_PAGE_MAX_SEGMENTS = 4`（`:6`），每次游标往返最多 4 个分块（每块上限 96 KB），而响应预算 `MAX_RESPONSE_BYTES = 6 MiB`（`:7`）——实际每页只用约 384 KB，比上限低一个数量级。总段数 S 的线程要 ⌈S/4⌉ 次往返，且每次往返都是一个 Agent 回合（工具延迟 + LLM 推理）。
3. 穷尽式收集工作流把上述成本按 页数 × 线程数 相乘（SKILL.md 契约，不改）。

次要因素（本次不动，留作后续）：每请求 health 探测双往返、每请求新开浏览器页面 + networkidle 等待、broker 全局串行锁、浏览器传输层本身。

## 2. 范围

**做：**
- `GmailMcpBridge.gs`：段数上限 4 → 32 + **双轨字节预算**（inner 6 MiB / wire 8 MiB，含首段超限规则）；`readThreadPage_` 两阶段按需规范化；`GMAIL_BRIDGE_VERSION` 3 → 4 并经测试导出。
- `tests/js/gmail_cloud_bridge.test.mjs`：分页/预算/错误映射/版本用例更新与新增，并改为引用共享 harness。
- 新增 `tests/js/gmail_cloud_bridge_harness.mjs`（共享 harness）、`tests/js/gmail_cloud_bridge_wire_probe.mjs`（探针）、`tests/test_gmail_cloud_bridge_wire.py`（跨层帧驱动）。
- `docs/GMAIL_CLOUD_BRIDGE.md`：分页与规范化行为描述重写。
- 候选提交 → 用户部署验证（v3 基线先行）→ v1.9.4 发布（含全部版本元数据同步）。

**不做（明示非目标）：**
- 不把懒加载路径设为所有线程默认（小线程 API 调用数会变多；`format:"minimal"` 是否含 `internalDate` 的既有依赖不在热路径上扩大）。
- 不改 broker / MCP server / SKILL.md / 安装器 / `.mcp.json`（两层上限常量不动，由云端预算分别适配）。
- 不引入 CacheService 或任何跨执行缓存（维持"每页重验"的正确性哲学）。
- **不做元数据分块重设计**（把 headers/附件名切成可分页子块）：segment 形状是 runbook PowerShell 验证与 SKILL 重组逻辑消费的线上契约，改动属更大范围的重设计；无上限元数据线程按 §4.3 既有失败语义阻塞，留作后续独立方案。
- 不动 `MAX_LIST_RESULTS`（列表页本就一页装满）。

## 3. 契约不变量（改动必须保全）

| 不变量 | 现状来源 | 改动后 |
|---|---|---|
| manifest = sha256(排序后 message_id 用 `\n` 连接) | `:247-255` / `:307-315`（两条路径重复实现） | 公式不变，提取为共享 helper；同线程+快照的 manifest 与 v3 字节一致 |
| 每页全量重抓线程、manifest 每页重算 | `fetchThreadForRead_` | 不变（仍每页 1 次 Gmail API 调用 + 超大线程 minimal 回退） |
| 每个发射分块带 `body_bytes` / `body_sha256`，客户端重组后校验 | `messageSegment_` | 不变 |
| 游标形状与校验（version/thread/snapshot/manifest/位置） | `encodeCursor_` / `decodeCursor_` / `validateCursorShape_` | 不变；chunk 边界检查位置移动（见 §6） |
| sanitized 错误码集合与既有映射（`THREAD_SORT_FAILED`、`MANIFEST_BUILD_FAILED`、`SEGMENT_EMISSION_FAILED`、`MESSAGE_COLLECTION_FAILED`、`RESPONSE_TOO_LARGE` 等） | `:236-267` / `:311-329` / `sanitizedErrorCodes_` | 不变；伪代码显式保留全部包装（§5）；懒加载路径排序从裸排序（→APP_ERROR）统一为 `THREAD_SORT_FAILED`，属修复 |
| **可收集线程集合 = v3 真实通过域（新增保证）** | v3：inner ≤ 6 MiB（`assertResponseSize_`）且 wire ≤ 8 MiB（broker `encode_response`，隐式） | 由双轨预算显式复刻：任一页超任一实际上限才失败（§4.2/§4.3）；v4 不收紧也不放宽 v3 的失败集合（4 KiB 信封余量除外，见 §4.3 注） |

## 4. 改动 1：段数上限 + 双轨字节预算（inner / wire 分别跟踪）

### 4.1 膨胀模型（为何必须按两层上限分别论证）

Apps Script 响应体（一段 JSON 文本）作为**字符串**传入 `BrokerResponse.success(request_id, body_text)`，随后 `encode_response` 对整个帧 `json.dumps`（`ensure_ascii=False`，`gmail_broker_protocol.py:262-268`）。外层编码只转义 `"`（→`\"`）与 `\`（→`\\`），各 +1 字节；内层 JSON 由 `JSON.stringify` 产生，不含裸控制字符（已转义为 `\n` 等，其中的反斜杠同样被二次转义）。因此：

```
inner = utf8Len(内层 JSON 文本)                 ← 云端 assertResponseSize_ 的对象，限 6 MiB
wire ≈ inner + count('"') + count('\\') + 信封  ← broker encode_response 的对象，限 8 MiB
```

两个反例界定了设计空间：
- **多段反例（v3 现状即坏）**：32 个 80 KiB、引号密集的单块正文 → inner 5.01 MiB（**通过**云端 6 MiB 检查）→ 帧 10.01 MiB（**超出** broker 8 MiB，现状 4 段上限下不可达，放宽段数后必须防）。
- **单段反例（rev 3 的错误收紧）**：单段 inner 3.20 MiB / wire 6.41 MiB → v3 两层均通过、可正常收集；rev 3 的"wire ≤ 6 MiB"预算会错误拒绝。**预算必须复刻 v3 的交集通过域，不能统一收紧到单层。**

### 4.2 设计：双轨预算

```javascript
var THREAD_PAGE_MAX_SEGMENTS = 32;                       // 数量上限
var THREAD_PAGE_INNER_BUDGET_BYTES = 6 * 1024 * 1024;    // 与 MAX_RESPONSE_BYTES 同源（云端层）
var THREAD_PAGE_WIRE_BUDGET_BYTES = 8 * 1024 * 1024;     // 与 broker MAX_FRAME_BYTES 同源（帧层）
var PAGE_ENVELOPE_RESERVE_BYTES = 4 * 1024;              // 双侧信封（segments 数组逗号、外层帧字段）与近似误差余量
```

- 发射器（§5.2）对每段**分别累计两个量**：`innerAdd = utf8ByteLength_(JSON.stringify(segment))`；`wireAdd = innerAdd + (piece.match(/["\\]/g) || []).length`。**段数达到 32，或下一段将使 inner 或 wire 任一超过其预算（扣除信封余量）时停止**，游标照常推进。
- 安全论证：inner 预算保证预算控制的页面永不触发 `assertResponseSize_`（6 MiB，严格大于判定）；wire 预算保证 `encode_response` 永不超 8 MiB。inner 稀疏时由 6 MiB 轨先停页，转义密集时由 8 MiB 轨先停页——单段反例（inner 3.20 / wire 6.41）两轨均通过，正常发射。
- 懒加载路径共用同一发射器，自动获得相同预算。
- 典型 Avaya 支持邮件正文 < 10 KB 且转义稀疏：30 封线程一页装完；引号密集的极端正文页数少于 32 段对应值，但远好于现状 4 段。

### 4.3 首段规则与 v3 等价性（放弃"每页至少一段"）

`messageSegment_` 携带的元数据——`from`/`to`/`cc`/`subject` 头与 `attachment_names`（含 RFC 2231 续段拼接结果）——**没有长度上限**，现有测试也覆盖超大附件名。巨型单段可达 inner 4.01 MiB / wire 8.01 MiB。规则：

- **首段（`segments.length === 0`）的 inner 或 wire 任一超其预算，直接抛 sanitized `RESPONSE_TOO_LARGE`**（该码已在 `sanitizedErrorCodes_` 集合中）。
- **v3 等价性**：v3 对此类线程同样失败——inner > 6 MiB 经 `assertResponseSize_` 拒绝；inner ≤ 6 MiB 但 wire > 8 MiB 经 broker `encode_response` 以 `RESPONSE_TOO_LARGE` 拒绝（错误同样作为 Gmail 工具失败阻塞门禁）。v4 把同一失败集合的判定从"整页序列化后 / broker 层"提前到"发射前 / 云端层"，**既不收紧也不放宽**。唯一偏差是 4 KiB 信封余量带来的极窄边界保守（inner/wiver 恰在预算±4 KiB 窗口内的线程），可接受。
- "每页至少一段"不成立的情况**仅此一类**（首段超实际上限）；首段在两轨预算内后，后续每页至少推进一段（后续段判定带 `segments.length > 0` 前置条件）。
- 元数据分块化见 §2 非目标，留作后续方案。

## 5. 改动 2：两阶段按需规范化

### 5.1 新结构（含完整错误包装，语义与现状逐一对齐）

`readThreadPage_` 重构为（普通路径）：

```javascript
function readThreadPage_(parameters) {
  var threadId = requireThreadId_(parameters.thread_id);
  var snapshotBefore = normalizeSnapshot_(parameters.snapshot_before);
  var snapshotMillis = snapshotCutoffMillis_(snapshotBefore);
  var thread = fetchThreadForRead_(threadId);          // 不变（全量抓取 + 超大线程 minimal 回退）
  validateThreadResponse_(thread);                     // 不变
  var sourceMessages = Array.isArray(thread.messages) ? thread.messages : [];
  if (thread.lazyMessageFetch === true) {
    return readLazyThreadPage_(parameters, threadId, snapshotBefore, snapshotMillis, sourceMessages);
  }
  // 阶段 1（每页都做，便宜）：只读 id + internalDate，不解码任何 payload
  // collectSnapshotEntries_ 内部：收集错误 → sanitized 透传 / MESSAGE_COLLECTION_FAILED；
  //                              排序错误 → THREAD_SORT_FAILED（独立包装，见 §5.2）
  var entries = collectSnapshotEntries_(sourceMessages, threadId, snapshotMillis, /* includeRaw */ true);
  var manifest;
  try {
    manifest = manifestFromEntries_(entries);
  } catch (error) {
    throw new Error("MANIFEST_BUILD_FAILED");                  // 与现状 :251-256 一致
  }
  // 游标解码 + 边界校验（decodeCursor_ 抛 sanitized INVALID_CURSOR，直接透传）
  var position = decodePosition_(parameters.cursor, threadId, snapshotBefore, manifest, entries.length);
  // 阶段 2（只做当前页）：仅对要发射的消息调 normalizeMessage_
  var emitted;
  try {
    emitted = emitPageSegments_(entries.length, position, function (index) {
      return normalizeMessage_(entries[index].raw, threadId);
    });
  } catch (error) {
    var emissionError = error && error.message ? String(error.message) : "";
    if (isSanitizedErrorCode_(emissionError)) throw error;     // INVALID_BODY_ENCODING / RESPONSE_TOO_LARGE 等透传
    throw new Error("SEGMENT_EMISSION_FAILED");                // 与现状 :262-267 一致
  }
  return buildThreadPageResult_(threadId, snapshotBefore, entries.length, manifest, emitted);
}
```

调用签名注意：`emitPageSegments_(entryCount, position, resolveMessage)` 三参，预算常量为模块级变量由发射器直接引用，**不传任何状态参数**（rev 2 的 `wireState` 为笔误性遗留，已删除）。

### 5.2 新增共享 helper

```javascript
// 阶段 1：快照过滤 + (internalDate, id) 排序；includeRaw 控制是否携带 payload 引用
function collectSnapshotEntries_(sourceMessages, threadId, snapshotMillis, includeRaw) {
  var entries = [];
  try {
    for (var index = 0; index < sourceMessages.length; index += 1) {
      var source = sourceMessages[index];
      validateMessageStub_(source, threadId);        // 现有函数：只查 id/threadId/internalDate，不碰 payload
      var internalMillis = Number(source.internalDate);
      if (internalMillis <= snapshotMillis) {
        var entry = { message_id: String(source.id), internal_millis: internalMillis };
        if (includeRaw) entry.raw = source;
        entries.push(entry);
      }
    }
  } catch (error) {
    var collectionError = error && error.message ? String(error.message) : "";
    if (isSanitizedErrorCode_(collectionError)) throw error;   // INVALID_THREAD_RESPONSE 等透传
    throw new Error("MESSAGE_COLLECTION_FAILED");              // 与现状 :236-240 语义一致
  }
  try {
    entries.sort(compareMessageStubs_);              // 现有函数，排序键与 compareMessages_ 等价
  } catch (error) {
    throw new Error("THREAD_SORT_FAILED");           // 与现状 :241-245 一致；懒加载路径同步统一
  }
  return entries;
}

// manifest 公式与现状字节一致
function manifestFromEntries_(entries) {
  var ids = [];
  for (var index = 0; index < entries.length; index += 1) ids.push(entries[index].message_id);
  return sha256Hex_(ids.join("\n"));
}

// 游标解码 + 边界检查（原 validateLazyCursorPosition_ 的推广；chunk 边界检查移入发射器）
function decodePosition_(cursor, threadId, snapshotBefore, manifest, messageCount) {
  var position = cursor
    ? decodeCursor_(cursor, threadId, snapshotBefore, manifest)
    : { message_index: 0, chunk_index: 0 };
  if (position.message_index > messageCount) throw new Error("INVALID_CURSOR");
  if (position.message_index === messageCount && position.chunk_index !== 0) throw new Error("INVALID_CURSOR");
  return position;
}

// 统一发射器：resolveMessage(index) 按需取规范化后的消息；双轨预算见 §4.2
function emitPageSegments_(entryCount, position, resolveMessage) {
  var segments = [];
  var messagesCompleted = position.message_index;
  var currentMessage = position.message_index;
  var currentChunk = position.chunk_index;
  var innerUsed = 0;
  var wireUsed = 0;
  var innerBudget = THREAD_PAGE_INNER_BUDGET_BYTES - PAGE_ENVELOPE_RESERVE_BYTES;
  var wireBudget = THREAD_PAGE_WIRE_BUDGET_BYTES - PAGE_ENVELOPE_RESERVE_BYTES;
  while (currentMessage < entryCount && segments.length < THREAD_PAGE_MAX_SEGMENTS) {
    var message = resolveMessage(currentMessage);
    var chunkCount = message.body_chunks.length;
    if (currentChunk >= chunkCount) throw new Error("INVALID_CURSOR");
    while (currentChunk < chunkCount && segments.length < THREAD_PAGE_MAX_SEGMENTS) {
      var segment = messageSegment_(message, currentChunk, chunkCount);
      var piece = JSON.stringify(segment);
      var innerAdd = utf8ByteLength_(piece);
      var wireAdd = innerAdd + (piece.match(/["\\]/g) || []).length;
      if (innerUsed + innerAdd > innerBudget || wireUsed + wireAdd > wireBudget) {
        if (segments.length === 0) throw new Error("RESPONSE_TOO_LARGE");  // 首段规则，§4.3
        return finishPage_(segments, messagesCompleted, currentMessage, currentChunk, entryCount);
      }
      segments.push(segment);
      innerUsed += innerAdd;
      wireUsed += wireAdd;
      currentChunk += 1;
    }
    if (currentChunk === chunkCount) {
      currentMessage += 1;
      currentChunk = 0;
      messagesCompleted += 1;
    }
  }
  return finishPage_(segments, messagesCompleted, currentMessage, currentChunk, entryCount);
}

function finishPage_(segments, messagesCompleted, currentMessage, currentChunk, entryCount) {
  return {
    segments: segments,
    messages_completed: messagesCompleted,
    message_index: currentMessage,
    chunk_index: currentChunk,
    complete: currentMessage === entryCount,
  };
}
```

### 5.3 懒加载路径对接（错误包装同样补齐）

`readLazyThreadPage_` 保留外壳，内部改用 `collectSnapshotEntries_(…, /* includeRaw */ false)`、`manifestFromEntries_`、`decodePosition_`、`emitPageSegments_`；manifest 构建保留 `MANIFEST_BUILD_FAILED` 包装（与现状 `:311-315` 一致），发射保留 sanitized 透传 / `SEGMENT_EMISSION_FAILED` 包装（与现状 `:322-329` 一致）。resolver 为：

```javascript
function (index) {
  var stub = entries[index];
  var source = fetchFullMessage_(stub.message_id);
  validateMessage_(source);
  if (source.id !== stub.message_id || source.threadId !== threadId ||
      Number(source.internalDate) !== stub.internal_millis) {
    throw new Error("THREAD_MANIFEST_CHANGED");       // 现有身份复验，保留
  }
  return normalizeMessage_(source, threadId);
}
```

### 5.4 删除项

- `validateCursorPosition_`（`:442-449`，需要全量 chunk 数，被 `decodePosition_` + 发射器守卫替代）。
- `emitSegments_`（`:459-482`）与 `emitLazySegments_`（`:366-399`）——被统一发射器替代。
- `validateLazyCursorPosition_`（`:351-356`）——并入 `decodePosition_`。
- 两条路径各自内联的 manifest 构建循环。

### 5.5 复杂度对比（按总段数 S = Σ chunk_count 建模）

| 路径 | 改动前 | 改动后 |
|---|---|---|
| 游标往返次数 | ⌈S/4⌉ | 由发射器 next-fit 决定：段数 ≤32 且 inner ≤6 MiB 且 wire ≤8 MiB 三约束下的装箱结果（顺序处理，非全局最优） |
| Gmail 全量线程抓取 | ⌈S/4⌉ 次 | 同上页数 |
| `normalizeMessage_` 调用 | ⌈S/4⌉ × N（每页规范化全部 N 封，O(P×N)） | N + 页尾已解析但未完成发射的消息重入次数（上界 N + P − 1）。重入来源有二：① 多块消息在页边界被截断，续页重入；② 字节预算截断的页面——发射器先 `resolveMessage(currentMessage)` 再发现该消息首段放不下即收页，该消息（含单块消息）下一页重新解析。仅由 32 段数量上限收页时不产生重入（外层循环先查段数再解析）；末页收尾不截断 |

单块消息（典型场景）S = N；96 KB 长正文使 S > N，收益同比例放大。**页数不做闭式预测**（段权和的装箱碎片使 `max(⌈S/32⌉, ⌈W/C⌉)` 类公式仅为下界，如 100 个各占 0.6C 的顺序段实需 100 页）；夹具侧预期页数用发射器自身算法**精确重放**取得，线上验收不预测、只实测（Task 6）。

## 6. 行为差异（明示，需测试覆盖）

1. **错误暴露时机后移。** 某封后面页的消息若有畸形 MIME / 解码失败，从"每一页都报"变为"轮到它的页才报"。最终仍阻塞评审（门禁要求全量遍历），契约结果不变。错误码映射不变：阶段 1 结构失败 sanitized 透传 / `MESSAGE_COLLECTION_FAILED`，排序失败 `THREAD_SORT_FAILED`；manifest 失败 `MANIFEST_BUILD_FAILED`；正文级失败 sanitized 透传 / `SEGMENT_EMISSION_FAILED`——与现状两条路径逐一对齐（§5.1/§5.3）。
2. **chunk 边界校验位置移动。** `chunk_index < 该消息 chunk 数` 从读页前置校验移到发射器内（懒加载路径现状即如此），错误码仍为 `INVALID_CURSOR`。
3. **双轨预算截断与首段超限（新增行为）。** 转义密集正文可能在未满 32 段时提前截断页面；游标推进与完备性判定不变。首段自身超出任一实际上限（inner > ~6 MiB 或 wire > ~8 MiB，如巨型 headers/附件名元数据）抛 sanitized `RESPONSE_TOO_LARGE`——失败集合与 v3 一致（§4.3），仅判定位置提前。
4. **懒加载路径排序错误码统一。** 现状懒路径排序无包装（未知异常 → `APP_ERROR`），改为 `THREAD_SORT_FAILED`，属修复而非回归。
5. **`GMAIL_BRIDGE_VERSION` 3 → 4**（`:1`）。游标内嵌版本校验（`validateCursorShape_`，`:200`）使重部署后的 v3 游标失效为 `INVALID_CURSOR` → 门禁阻塞 → 按既定路径以新 `snapshot_before` 全新重试。`bridge_version: 4` 出现在响应中供观测；已全仓确认无外部断言依赖 `bridge_version === 3`（测试夹具中的 `version: 3` 字面量属本次修改范围，见 §7.1）。

## 7. 测试改动

### 7.1 `tests/js/gmail_cloud_bridge.test.mjs`（含共享 harness 提取）

| 用例 | 改动 |
|---|---|
| **基础设施（rev 4 P2）** | 提取 `tests/js/gmail_cloud_bridge_harness.mjs`：纯模块，导出 `loadBridge`、mock Gmail/Utilities 工厂、`rawMessage` 等夹具构造器；**不 import `node:test`、不写 stdout**，主测试与 wire 探针共同引用。主测试改为 import harness（机械重构，断言不变） |
| `:508` "read_thread_page returns at most four segments…" | 重写为 32 段契约：thread-a（5 消息）改为单页 `segments.length === 5`、`messages_completed === 5`、`complete === true`、`next_cursor === null` |
| 新增：40 消息线程 | 夹具循环生成 40 条单块消息：第 1 页 32 段、`next_cursor` 非空；第 2 页 8 段、`complete === true`；两页 `manifest_sha256` 与 `message_count` 相同 |
| 新增：跨页截断的消息内恢复 | 30 条小消息 + 1 条约 2.5 × 96 KB 长正文（3 块）：总块数 33 > 32，第 1 页在长消息中间截断（`chunk_index > 0` 游标），第 2 页从块中间恢复，重组后哈希/字节校验通过 |
| 新增：双轨预算对抗页 | 夹具构造引号密集（正文全为 `"`）约 80 KiB 单块消息若干：断言每页 inner ≤ 6 MiB 且 wire ≤ 8 MiB（按 §4.1 公式复算）、段数可能 < 32、游标推进、跨页收尾后重组哈希通过——多段反例（inner 5.01 MiB / 帧 10.01 MiB）降为合法多页 |
| **新增：rev 4 P1 回归（v3 通过域保持）** | 用**无上限元数据**构造单段，且必须经规范化管线的真实入口：把巨型文件名写入 `payload.parts[].filename`（或 Content-Disposition filename 参数）——直接在原始 message 上填 `attachment_names` 会被 `normalizeMessage_` 忽略并按 payload 重建。文件名内容几乎全为 `"`（`sanitizedAttachmentName_` 只剥离 NUL/CRLF，引号保留）。**按序列化结果定尺寸，不从密度反推**：原始值经 Apps Script `JSON.stringify` 一次转义为 inner、经 broker 二次转义为 wire，故原始 ≈ 1.6 MiB 全引号文件名 → inner ≈ 3.2 MiB、wire ≈ 6.4 MiB（若原始给 3.2 MiB 会得到 inner ≈ 6.4 / wire ≈ 12.8）。夹具流程：构造初始长度 → 序列化实测 inner → 按 `目标/实测` 比例缩放一次收敛。断言：`segments.length === 1`；inner ∈ (3.0, 3.5) MiB；wire ∈ (6.0, 7.0) MiB——即 wire 超 6 MiB 但低于 8 MiB 轨，确保证明"介于两轨之间"的验证目标（v3 可收集，v4 不得因 wire > 6 MiB 拒绝）。**失败对照夹具先断言有效阈值，再期待失败**（避免 inner ≈ 4 / wire ≈ 8 落在 reserve ±4 KiB 边界两侧造成偶发）：同法调节尺寸后断言 `innerAdd ≤ innerBudget`（证明拒绝来自 wire 轨而非 inner 轨）且 `wireAdd > wireBudget`；如该夹具同时用于证明 v3 失败集合，则把其序列化文本经真实 `encode_response` 编码并断言帧 `> MAX_FRAME_BYTES`；此后才断言抛 `RESPONSE_TOO_LARGE` |
| 新增：首段超预算 | 夹具构造单条携带巨型元数据（超长 `attachment_names` / `to` 列表）的消息：断言 `readThreadPage` 抛 `RESPONSE_TOO_LARGE`（不是 `APP_ERROR`、不是静默截断） |
| 新增：预算模型单元测试 | 对抗字符串（混合 `"`、`\`、`\n` 转义序列、非 ASCII）断言 wire 估计 = utf8 长度 + 引号数 + 反斜杠数 |
| 新增：错误映射不退化为 APP_ERROR | 经 mock 注入：`Utilities.computeDigest` 抛未知异常 → 断言 `MANIFEST_BUILD_FAILED`；构造使 `normalizeMessage_` 抛非 sanitized 异常的 payload → 断言 `SEGMENT_EMISSION_FAILED`；临时替换 `Array.prototype.sort` 抛异常 → 断言 `THREAD_SORT_FAILED`（两条路径都要）；三者均不得是 `APP_ERROR` |
| 新增：next-fit 精确重放 | 对上述各多页夹具，用与发射器相同的算法对有序段权重重放，断言重放页数 == 实际页数（防发射器与验收模型漂移） |
| 改动：游标夹具版本无关化 | `:250` / `:259` 硬编码 `version: 3` → 改为引用 `GmailBridgeTestExports` 新增导出的 `bridgeVersion`（或 `encodeCursor` 产物），随版本 bump 自动一致 |
| `:590` 懒加载分页用例 | 按新段数与预算同步调整预期 |
| 保留不动 | manifest 跨页稳定、逐块哈希/字节校验、时间序 tie-break、超大线程 minimal 回退（`:711`）、96 KB 块上限（`:482`）、游标线程/快照/manifest 不匹配拒绝 |

运行方式：`node --test tests/js/gmail_cloud_bridge.test.mjs`；Python 侧 `python -m unittest tests.test_gmail_cloud_bridge tests.test_gmail_cloud_bridge_wire`（新跨层模块需显式包含），或 `python -m unittest discover tests` 全量发现。

### 7.2 真跨层帧回归（新增 `tests/js/gmail_cloud_bridge_harness.mjs` 复用 + `gmail_cloud_bridge_wire_probe.mjs` + `tests/test_gmail_cloud_bridge_wire.py`）

rev 3 的探针草案引用了主测试未导出的 `loadBridge`/`rawMessage`，且直接 import 主测试会注册 `node:test` 并污染长度前缀 stdout——不可行。改为：

1. **共享 harness**（§7.1 基础设施行）：`gmail_cloud_bridge_harness.mjs` 无 TAP 副作用，探针与主测试共同引用。
2. **Node 探针**（`gmail_cloud_bridge_wire_probe.mjs`）：按命令行指定夹具名，驱动**真实 `doGet({parameter:{action:"read_thread_page", …}})`**（mock `ContentService.createTextOutput` 捕获其输出的 JSON 文本——与线上传输形态一致），跟随游标至收尾，将每一页**响应 JSON 文本**以长度前缀帧写 stdout。**错误夹具同样走 `doGet`**：首段超限线程的 `{success:false, error:"RESPONSE_TOO_LARGE"}` 小型错误 JSON 也是一页输出。
3. **Python 驱动**（`test_gmail_cloud_bridge_wire.py`）：subprocess 运行探针，逐页取回 JSON 文本，对**每一页（含错误页）**执行 `BrokerResponse.success(request_id, text)` + `encode_response`，断言：
   - `len(frame) ≤ MAX_FRAME_BYTES`（8 MiB）——**JS 发射预算 ↔ Python 帧编码的端到端契约**；实际系统中错误响应同样产生 broker 帧，故错误页不得跳过；
   - 膨胀模型成立：`len(frame) == utf8Len(text) + count('"') + count('\\') + 信封`（信封 < 1 KiB 容差），JS 或 Python 任一侧模型漂移都会使断言失败；
   - 错误页额外断言 JSON 含 `"error":"RESPONSE_TOO_LARGE"` 且 `success === false`。
4. 该测试入常规 `unittest discover`；探针路径与夹具名在两文件间用常量对齐，避免漂移。

## 8. 文档改动

| 文件 | 改动 |
|---|---|
| `docs/GMAIL_CLOUD_BRIDGE.md:281-283` 及验证脚本 | **重写行为陈述**：由 "normalizes the full thread" 改为——每页仍全量重抓线程以重算 manifest，但只解码/规范化当前页发射的消息；超大线程回退 minimal manifest + 按页逐消息抓取；"four-segment maximum" 改为 32 段上限 + 双轨预算（inner 6 MiB / wire 8 MiB，含引号/反斜杠膨胀说明与首段 `RESPONSE_TOO_LARGE` 语义）。**修改 runbook 验证脚本（明确改动项，rev 4 误写为"预期无需改"）**：桥接调用由 `Invoke-RestMethod` 改为 `Invoke-WebRequest -UseBasicParsing`（PowerShell 5.1 必带 `-UseBasicParsing`），**同时保留**原始 `.Content` 文本与 `ConvertFrom-Json` 解析对象——游标循环用解析字段，字节断言用原始文本；写入信封计算定义：`wire = utf8Len(raw) + count('"') + count('\\') + 1 KiB`，其中信封为外层帧 id/version/ok 字段的保守上界，`utf8Len` 必须用 `[Text.Encoding]::UTF8.GetByteCount($raw)`（PS 字符串 `.Length` 按 UTF-16 码元计数，非 ASCII 下不等于字节数） |
| `AGENTS.md` §7 | 版本历史追加 v1.9.4 条目 |
| 历史方案文档（含 `docs/superpowers/plans/2026-08-04-exhaustive-context-collection.md:552`） | **不改**——历史记录 |

## 9. 实施任务清单

- [ ] **Task 1：云桥改动（`tools/gmail/cloud/GmailMcpBridge.gs`）**
  - [ ] `THREAD_PAGE_MAX_SEGMENTS` 4 → 32；新增 `THREAD_PAGE_INNER_BUDGET_BYTES` / `THREAD_PAGE_WIRE_BUDGET_BYTES` / `PAGE_ENVELOPE_RESERVE_BYTES`；`GMAIL_BRIDGE_VERSION` 3 → 4 并加入 `GmailBridgeTestExports` 导出
  - [ ] 新增 `collectSnapshotEntries_`（含 `THREAD_SORT_FAILED` 独立包装）/ `manifestFromEntries_` / `decodePosition_` / `emitPageSegments_`（三参签名、双轨累计、首段 `RESPONSE_TOO_LARGE` 规则）/ `finishPage_`
  - [ ] 重构 `readThreadPage_` 与 `readLazyThreadPage_` 使用共享 helper，**保留全部错误包装**（§5.1/§5.3）；删除 §5.4 列出的旧函数
- [ ] **Task 2：测试更新** — 按 §7.1 / §7.2 执行（含 harness、探针、Python 驱动三个新文件）
- [ ] **Task 3：文档更新** — 按 §8 执行；其中 runbook 验证脚本改为 `Invoke-WebRequest -UseBasicParsing` 双形态输出（raw `.Content` + `ConvertFrom-Json`）与信封定义是**明确修改项**
- [ ] **Task 4：本地验证**
  - [ ] `node --test tests/js/gmail_cloud_bridge.test.mjs` 全绿
  - [ ] `python -m unittest discover tests` 全量回归（含跨层帧回归；本地模块未改，防意外耦合）
- [ ] **Task 5：候选提交（不含 release）** — `git add` 改动文件、提交并推送 main；**不**打 zip、**不** `gh release`。提交信息：`perf(gmail-cloud): raise read-thread page capacity and normalize on demand`
- [ ] **Task 6：线上部署与验证（用户手工，Agent 不得代跑或声称成功；顺序不可颠倒）**
  - [ ] **(1) v3 基线先行**：在**当前现网部署**上，固定 `snapshot_before` 与案例号（如 1-23744793322）及参考线程集，记录：列表页数、游标页数、每页段数、收集总耗时、逐调用延迟、各消息哈希。采集用 `Invoke-WebRequest`（`.Content` 保留原始 JSON 文本；`Invoke-RestMethod` 会解析掉原文，无法复算 inner/wire）
  - [ ] **(2) 部署 v4**：按 `docs/GMAIL_CLOUD_BRIDGE.md` runbook：同 URL 编辑现有部署 → New version → 重部署
  - [ ] **(3) runbook 验证**：多消息线程游标耗尽 + manifest/哈希/计数检查
  - [ ] **(4) 安全复测（逐页实测，不预测页数）**：同一 `snapshot_before` 重跑，对**每一页原始响应文本**精确复算：`inner = utf8Len(text)`、`wire = inner + count('"') + count('\\') + 1 KiB 保守信封`（外层帧 id/version/ok 字段上界；`utf8Len` 用 `[Text.Encoding]::UTF8.GetByteCount`），断言每页 inner ≤ 6 MiB 且 wire ≤ 8 MiB；除病态元数据线程外零 `RESPONSE_TOO_LARGE`
  - [ ] **(5) 性能验收（仅典型语料）**：典型参考语料（正常 Avaya 支持邮件）实测页数较 v3 基线降幅 ≥ 5×；**对抗语料（引号密集等）定义为安全性验证对象，不适用 ≥5× 性能阈值**（其实际降幅受预算装箱影响，可能低于 5×）。哈希与计数校验和 v3 基线一致。基线数值记录在部署验证输出中，不入库
- [ ] **Task 7：发布 v1.9.4（仅在 Task 6 全部通过后）** — 按 AGENTS.md §7 流程打 zip、`gh release create`、`gh release edit` 旧版 superseded 横幅。版本元数据同步 v1.9.3 同款 8 文件：`.codex-plugin/plugin.json`、`plugins/avaya-case-review/plugin.json`、`README.md`、`README.html`、`docs/RELEASE_NOTES.md`、`docs/RELEASE_NOTES.html`、`AGENTS.md`（版本历史）、`tests/test_case_review_contract.py`（版本一致性断言）；不 git add zip

## 10. 部署顺序与回滚

- **顺序（与 §9 任务对应）：** Task 1–4 本地实现与验证 → Task 5 候选提交推送 → Task 6 **先采 v3 基线**、再部署 v4、runbook 验证与逐页安全复测 + 典型语料性能验收（云端先行，未通过则不发布）→ Task 7 发布 v1.9.4。本地模块无变更，无需重新跑 `install.bat`；SKILL 门禁在云端验证通过前不视为生效。
- **回滚：** 按 `docs/GMAIL_CLOUD_BRIDGE.md` 既有回滚节（`:298` 起）——把 Apps Script 重部署回 prior version 到同一 URL。版本 4 游标随之失效，正在进行的收集会以 `INVALID_CURSOR` 阻塞并全新重试，属设计内行为。若已发布 release，仓库侧 revert 提交 + 按需发补丁版本。

## 11. 预期收益与验收

| 场景 | 游标往返 + Agent 回合 | 云端 `normalizeMessage_` 调用 | 验收归属 |
|---|---|---|---|
| 30 封单块线程（S=30） | 8 → 1 | 240 → 30（典型小正文字节预算不触发、由数量上限收页，重入 0） | 性能（典型语料） |
| 100 封单块线程（S=100） | 25 → 4 | 2500 → 100（同上） | 性能（典型语料） |
| 30 封 × 3 块线程（S=90） | 23 → 3 | 690 → ≤ 32（N=30 + 至多 P−1=2 次页尾重入） | 性能（典型语料） |
| 100 段引号密集对抗正文 | 25 → 约 4–5（受 wire 轨装箱约束） | 2500 → ≈ 100 + ≤ 4 | **仅安全性**：逐页 inner/wire ≤ 上限，不适用 ≥5× 阈值 |

性能阈值仅对典型语料生效（≥5× 往返降幅）；对抗语料是双轨预算的安全性验证对象。每次往返省下的是"Agent 回合 + 浏览器导航 + Apps Script 执行"的整条固定成本（单次约 2–5 s），这是用户体感的主要来源。带宽（每页全量线程抓取）随页数同比下降；若后续需进一步压缩，再评估懒加载默认化（见 §2 非目标）。量化验收以 Task 6 的固定快照 v3 基线、逐页实测上限断言与典型语料阈值为准。
