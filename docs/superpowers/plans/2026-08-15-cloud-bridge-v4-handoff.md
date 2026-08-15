# Handoff — Cloud Bridge v4 性能改造 Code Review

> **评审对象：** main 分支提交 `a91d6e1`（7 files，+1338/−335），以及已执行的线上部署（详见 §6）。
> **背景文档：** [`2026-08-15-cloud-bridge-pagination-speedup.md`](2026-08-15-cloud-bridge-pagination-speedup.md) — 经 7 轮评审批准的实施方案（rev 7），§0 含全部 16 条评审意见的响应索引。**已定稿的设计决策请勿在本轮重复辩论，除非发现实现与方案不符。**
> **评审通过后：** 执行 Task 7（v1.9.4 发布 + 8 文件版本同步）。版本元数据 bump 故意不在本提交内。

---

## 1. 改了什么（一句话版）

Gmail 云桥（Apps Script）读线程接口从"每页 4 段、每页全量规范化所有消息"改为"每页最多 32 段、双轨字节预算、只解码当前页要发射的消息"，目的是把 case review 穷尽式收集的往返次数降一个数量级。**纯服务端变更**：broker / MCP server / SKILL.md / 安装器零改动。

## 2. 文件清单与评审入口

| 文件 | 变更 | 评审重点 |
|---|---|---|
| `tools/gmail/cloud/GmailMcpBridge.gs` | 核心 | 见 §3 |
| `tests/js/gmail_cloud_bridge_harness.mjs` | 新增 | 纯模块、无 `node:test` 依赖、无 stdout 写入（探针与主测试共用） |
| `tests/js/gmail_cloud_bridge.test.mjs` | 重写 | 既有断言的保持度；新增用例的覆盖质量 |
| `tests/js/gmail_cloud_bridge_wire_probe.mjs` | 新增 | 长度前缀帧协议的正确性；错误页也走真实 `doGet` |
| `tests/test_gmail_cloud_bridge_wire.py` | 新增 | 跨层契约：JS 预算模型 ↔ Python `encode_response` 膨胀公式 |
| `docs/GMAIL_CLOUD_BRIDGE.md` | 修改 | 行为陈述重写 + runbook 的 `Invoke-WebRequest -UseBasicParsing` 改法与逐页字节断言 |
| `docs/superpowers/plans/2026-08-15-…speedup.md` | 新增 | 方案本体（历史记录，不需逐字审） |

## 3. .gs 核心改动的正确性主张（请逐条核验）

1. **常量区**：`GMAIL_BRIDGE_VERSION` 3→4；`THREAD_PAGE_MAX_SEGMENTS` 4→32；新增 `THREAD_PAGE_INNER_BUDGET_BYTES`（6 MiB，与 `MAX_RESPONSE_BYTES` 同源）、`THREAD_PAGE_WIRE_BUDGET_BYTES`（8 MiB，与 broker `MAX_FRAME_BYTES` 同源）、`PAGE_ENVELOPE_RESERVE_BYTES`（4 KiB）。
2. **`readThreadPage_` / `readLazyThreadPage_`**：两阶段——阶段 1 只读 `id + internalDate` 做快照过滤与排序、manifest 只依赖 ID 序列（公式不变，同线程+快照的哈希与 v3 **字节一致**）；阶段 2 经 `resolveMessage` 回调只规范化当前页发射的消息。两条路径共用同一发射器，错误包装逐一对齐现状。
3. **`emitPageSegments_`**：next-fit 装箱，三重停页条件（段数 32 / inner / wire）；`segmentWireBytes_` 计算单段 `inner`（utf8 字节）与 `wire`（inner + 引号数 + 反斜杠数，建模 broker 外层 `json.dumps` 二次转义，每字符 +1）。**首段超任一预算抛 sanitized `RESPONSE_TOO_LARGE`**——这与 v3 的失败集合一致（v3 经 `assertResponseSize_` 或 broker 层拒绝同样的线程），只是判定提前到发射前。
4. **删除项**：`validateCursorPosition_`（chunk 边界检查移入发射器，错误码不变）、`emitSegments_` / `emitLazySegments_`（被统一发射器替代）、`validateLazyCursorPosition_`（并入 `decodePosition_`）、`compareMessages_`（排序统一走 `compareMessageStubs_`，键等价）。请确认无残留引用。

## 4. 有意的行为变更（不是 bug，但请确认可接受）

| 变更 | 理由 |
|---|---|
| 普通路径排序前移到 stub 校验之后、懒加载路径排序从裸排序（未知异常→`APP_ERROR`）统一为 `THREAD_SORT_FAILED` | 修复性统一，方案 §6.4 已明示 |
| 普通路径发射 try 增加 sanitized 透传 | 规范化移入发射器后，`INVALID_BODY_ENCODING` 等 sanitized 码必须透传而非包装成 `SEGMENT_EMISSION_FAILED` |
| 畸形 payload 的错误暴露时机后移到"轮到它的页" | 按需规范化的必然结果；门禁仍会阻塞（要求全量遍历），最终结果不变。**精确限定：快照之后（snapshot-ineligible）的畸形 payload 被完全跳过，不再像 v3 那样在收集期失败**——它们本就不属于本快照语料，合理但属行为变更，已有专门回归测试 |
| 普通路径改用 `validateMessageStub_` 做结构校验 | **条件语义，按路径分化**：`threadId` **存在且不匹配** → stub 阶段即抛 `INVALID_THREAD_RESPONSE`（旧普通路径只查存在性，不匹配也放行）；`threadId` **缺失** → stub 阶段放行（minimal 格式兼容）——普通路径随后在发射期由 `validateMessage_` 以 `INVALID_MESSAGE` 兜底，懒加载路径端到端成功（stub 不经 payload 校验，按页补取的完整消息自带 `threadId`）。三种情况均有测试 |
| v3 游标在重部署后失效为 `INVALID_CURSOR` | 版本内嵌校验使然 → 门禁阻塞 → 全新重试，设计内行为 |
| "每页至少一段"不变量被放弃 | 段元数据（headers/附件名）无长度上限，单段可超 8 MiB；首段超限抛 `RESPONSE_TOO_LARGE`（§3.3） |

## 5. 验证证据

**本地（提交前）：**
- `node --test tests/js/gmail_cloud_bridge.test.mjs`：**25/25**（含 32 段分页、消息内跨页恢复、引号密集 wire 装箱 + next-fit 精确重放、v3 通过域回归、错误映射三连、快照外畸形 payload 跳过、threadId 缺失/不匹配双路径、inner 轨锁定断言、懒加载 34 封选择性抓取）
- `python -m unittest discover tests`：**269/269**（含 5 个跨层帧回归：真实 `doGet` 输出 → 真实 `encode_response`，帧 ≤ 8 MiB、膨胀公式两侧吻合、v3 失败集证明）

**线上（部署后，同一 `snapshot_before`，案例 1-23744793322，39 封真实消息）：**

| 指标 | v3 基线 | v4 | 判定 |
|---|---|---|---|
| 游标读页 | 10 | 2 | 5.0×，达 ≥5× 阈值 |
| 收集耗时 | 56.5s | 12.5s | 4.5×（含每次 CLI 启动固定开销） |
| 消息摘要 | 39 个 | 39 个 | **逐字节一致** |
| manifest / 消息数 | — | — | 一致 |
| 逐页 inner / wire | — | 最大 199KB / 214KB | 远低于 6/8 MiB 双轨 |
| `RESPONSE_TOO_LARGE` / 门禁失败 | — | 0 | 通过 |

## 6. 部署状态与安全措施（评审前请知悉：线上已是 v4）

按批准方案的 Task 6 执行，顺序：**v3 基线先行** → 推送 v4 → 重部署。安全措施：
1. 推送前 `clasp pull` 比对：远端 `Code.js` 与仓库 v3 版本**逐字节一致**（防覆盖漂移）；
2. 推送后拉回核实远端为 v4（diff 相等 + `GMAIL_BRIDGE_VERSION = 4` 首行确认）；
3. `clasp deploy --deploymentId` 更新**既有部署**（`AKfycbwfqUG…`，@14→@15），URL 不变；
4. 部署后现网探针确认 `bridge_version: 4`。

部署用凭据：clasp（hmao@avaya.com，OAuth 经用户在 Edge 手工授权）。Apps Script 项目 scriptId：`1xnC5q_CjYUqu9Om5zRSCo1ApWacu5P5mPcTHdobH1zdkd0DtXBHX9YvS`，工作目录 `tmp/clasp-bridge/`（未入库）。

**回滚（若评审否决）——必须按以下字节安全流程，勿用 shell 重定向：**

> ⚠️ Windows PowerShell 5.1 的 `>` 重定向会把 `git show` 输出写成 UTF-16LE（实测首字节 `FF FE`、39,525 → 81,284 bytes），推上去会损坏脚本。且 `HEAD^` 在 Task 7 release commit 后会指向 v4，不可使用。回滚必须固定 v3 的完整 SHA。

v3 固定源：`8fe39e47a9ae2149a22ede22bf69fcf566a1a872`（v1.9.3 release commit）。

```bash
# 1) 二进制安全提取（Node execFileSync 直传 Buffer，无 shell 重定向），并自校验
node -e "
const { execFileSync } = require('child_process');
const { writeFileSync } = require('fs');
const buf = execFileSync('git', ['show', '8fe39e47a9ae2149a22ede22bf69fcf566a1a872:tools/gmail/cloud/GmailMcpBridge.gs'], { maxBuffer: 64 * 1024 * 1024 });
const text = buf.toString('utf8').replace(/\r\n/g, '\n');
if (!text.startsWith('var GMAIL_BRIDGE_VERSION = 3;')) throw new Error('pinned blob is not v3');
writeFileSync('tmp/clasp-bridge/Code.js', text);
console.log('bytes=' + Buffer.byteLength(text));
"
# 期望输出 bytes=39525；SHA-256 必须等于 ceecde437612bd3f99427907b7797c37df68b585715ea58c8489d02667bb2119
python -c "import hashlib;d=open('tmp/clasp-bridge/Code.js','rb').read().replace(b'\r\n',b'\n');h=hashlib.sha256(d).hexdigest();assert h=='ceecde437612bd3f99427907b7797c37df68b585715ea58c8489d02667bb2119' and len(d)==39525, h;print('ROLLBACK_SOURCE_VERIFIED')"
# 2) 推送并重部署（哈希核验通过后才执行）
cd tmp/clasp-bridge && npx --yes @google/clasp push
npx --yes @google/clasp deploy --deploymentId "AKfycbwfqUGLMBppaPEtdzAC74_TeT34shpYkIVv5FMY1JjhqPDH0MXEp-WdeTOp8zmCDL0F" --description "rollback to v3 (8fe39e4)"
# 3) 验证：现网探针 bridge_version 应回到 3
```

该提取流程已于 2026-08-15 实测：提取产物与此前 `clasp pull` 拉回的远端 v3 逐字节一致（同一 SHA-256）。备选：通过 Apps Script API `deployments.update` 把部署直接指回不可变版本 @14（clasp CLI 不暴露该操作，需直接调 API）。仓库侧 revert `a91d6e1`。

## 7. 已知限制 / 残留风险（有意不在本次解决）

- **元数据巨型线程仍不可收集**（`RESPONSE_TOO_LARGE`）：与 v3 相同的失败集合，元数据分块化列为后续方案（方案 §2 非目标）。
- **wire 模型是保守估计**（逐段累加 + 4 KiB 信封余量），非整页精确序列化；余量 2 MiB 覆盖近似误差。跨层测试将模型固化为契约。
- **每页仍全量重抓线程**（无状态设计、每页重算 manifest）：带宽随页数同比下降，但 O(N)/页 仍在；懒加载默认化是后续选项。
- runbook 的 PowerShell 逐页断言已写入文档，但本次线上验证走的是 Python 采集器（`tmp/task6_collect.py`，未入库），两者断言逻辑等价（inner/wire 公式相同）。

## 8. 本地复跑命令

```bash
node --test tests/js/gmail_cloud_bridge.test.mjs
python -m unittest tests.test_gmail_cloud_bridge tests.test_gmail_cloud_bridge_wire
python -m unittest discover tests
```

## 9. 评审通过后的 Task 7 清单（未执行，等结论）

1. 版本 bump 8 文件：`.codex-plugin/plugin.json`、`plugins/avaya-case-review/plugin.json`、`README.md`、`README.html`、`docs/RELEASE_NOTES.md`、`docs/RELEASE_NOTES.html`、`AGENTS.md`（版本历史）、`tests/test_case_review_contract.py`。
2. 按 `release-manifest.txt` 打 zip（不 git add）→ `gh release create v1.9.4` → 旧版本 superseded 横幅。
