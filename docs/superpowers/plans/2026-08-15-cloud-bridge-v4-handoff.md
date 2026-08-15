# Handoff — Cloud Bridge v4 性能改造 Code Review

> **评审对象（按角色划分，截至本轮修复提交）：**
> - **生产实现范围：** `a91d6e1`（实现：7 files，+1338/−335）+ `603422a`（评审修复：2 files，+226/−22）。其后提交对 `.gs` 与测试**零改动**。
> - **Handoff/回滚交付修复范围（文档与运维脚本，零生产代码）：** `7f672f8`、`258078a`、本轮提交（回滚脚本入库 `tools/gmail/cloud/rollback_bridge_v3.mjs` + `release-manifest.txt` + 本文档）。
> - 另含已执行的线上部署（详见 §6）。
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
| `tools/gmail/cloud/rollback_bridge_v3.mjs` + `rollback_bridge_v3.gs` | 新增（本轮） | 云端回滚：哈希门禁的内置 v3 源（无 Git 依赖）+ scriptId 项目身份门禁 + 固定版本 clasp（300 s 超时）+ fail-fast（失败态 unknown，`--diagnose` 分诊）+ 探针成功门禁；随发行包交付 |
| `docs/superpowers/plans/2026-08-15-…speedup.md` | 新增 | 方案本体（历史记录，不需逐字审） |
| `docs/superpowers/plans/2026-08-15-…v4-handoff.md` | 新增（`603422a`） | 本文档：行为变更表、验证证据、回滚流程 |

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

部署操作账号与 Apps Script `scriptId` 属受控运维信息，不入公开文档：见本地 `tmp/clasp-bridge/.clasp.json`（未入库）及受控运维记录。部署 ID 与 `tools/gmail/gmail_edge_common.py` 的 `APP_SCRIPT_URL` 一致（运行时代码既有的公开标识，无新增披露）。历史提交中曾出现的账号/scriptId 是否需要进一步处置由安全策略决定；已推送历史不擅自改写。

**云端回滚（若评审否决）——fail-fast 单进程脚本，与调用 shell 无关：**

> ⚠️ 不可手敲链式命令：Windows PowerShell 5.1 的 `>` 重定向会把 `git show` 输出写成 UTF-16LE（实测首字节 `FF FE`、39,525 → 81,284 bytes），`&&` 在 PS 5.1 下不可解析，且 `HEAD^` 会随后续提交漂移。
>
> **语义是 fail-fast，不是原子事务，且失败后的远端状态是 unknown**：`clasp push` 与 `clasp deploy` 是两个独立远端变更，非零/超时退出可能发生在服务端已接受请求之后——**不能断言"push 失败 ⇒ 源仍为 v4"或"deploy 失败 ⇒ 线上仍为 v4"**。任何失败后先跑 `--diagnose`（隔离副本 `clasp pull` 比对 v3/v4 哈希 + `clasp deployments` + 现网探针）确定实际状态，再选择重跑或补偿。重复重跑安全：push 生成同一已验证 v3 内容的新版本，deploy 重新指向既有部署。deploy 成功后以现网探针（`bridge_version === 3`）作为**成功门禁**而非提示。

回滚脚本**已入库并随发行包交付**：`tools/gmail/cloud/rollback_bridge_v3.mjs` + 伴随的 v3 源 `tools/gmail/cloud/rollback_bridge_v3.gs`（均在 `release-manifest.txt`）。v3 源**内置于发行包、经哈希门禁**（首行 + SHA-256 `ceecde43…` + 39,525 字节三重校验），不依赖 Git 历史——在无 `.git` 的发行目录中源门禁照常通过（实测），后续在 clasp 工作目录前置条件处给出可执行的明确报错。

**运行前置条件（缺一即在对应门禁处以非零退出并零写入）：** Node.js；固定版本 `@google/clasp@3.3.0`（npx 在线或本地缓存；push/deploy 均有 300 s 超时并区分超时与退出码）；已登录的 `~/.clasprc.json`；clasp 工作目录 `tmp/clasp-bridge/`（需自行准备，不在发行包内）且其 `.clasp.json` 的 `scriptId` 必须与 `--script-id`（或 `GMAIL_BRIDGE_SCRIPT_ID`，来自受控运维记录）**严格相等**——不匹配立即退出、零写入，防止错误项目被覆盖；`--deployment-id`（或 `GMAIL_BRIDGE_DEPLOYMENT_ID`）取自 `APP_SCRIPT_URL`。`--dry-run` 只做源门禁 + 项目身份门禁、**不写任何文件**；`--diagnose` 在隔离副本中拉取比对，不触碰工作目录。

```bash
node tools/gmail/cloud/rollback_bridge_v3.mjs --dry-run \
  --script-id=<受控运维记录> --deployment-id=<APP_SCRIPT_URL 中的部署 ID>   # 1) 零副作用预检
node tools/gmail/cloud/rollback_bridge_v3.mjs --diagnose \
  --script-id=…                                                             # 失败后的状态分诊
node tools/gmail/cloud/rollback_bridge_v3.mjs \
  --script-id=… --deployment-id=…                                           # 2) push + deploy + 探针门禁
```

备选：通过 Apps Script API `deployments.update` 把部署直接指回不可变版本 @14（clasp CLI 不暴露该操作，需直接调 API），可完全避开 push/deploy 两段式中间态。

**仓库侧回滚——先完成云端回滚（脚本来自回滚前的树），再 revert 全部 v4 相关提交（新到旧），并复跑完整回归：**

```bash
# 1) 确认范围内只有本次变更的提交，无无关提交混入
git log --oneline 8fe39e4..HEAD
# 2) 范围 revert（2026-08-15 已在隔离 clone 验证：列表式与范围式均成功，
#    最终 tree 与 8fe39e4 完全一致）
git revert --no-commit 8fe39e4..HEAD
# 3) commit 前核对最终 tree 等于 v3（输出必须为空）
git diff --cached 8fe39e4 --stat
git commit -m "revert: cloud bridge v4 candidate per review"
# 4) 全量回归全绿才算回滚完成
python -m unittest discover tests
node --test tests/js/gmail_cloud_bridge.test.mjs
```

注意：范围 revert 会连同回滚脚本本身一起移除（它属于 v4 提交栈），因此云端回滚必须先行；如需保留脚本供事后审计，在 revert 前另存副本。

## 7. 已知限制 / 残留风险（有意不在本次解决）

- **元数据巨型线程仍不可收集**（`RESPONSE_TOO_LARGE`）：与 v3 相同的失败集合，元数据分块化列为后续方案（方案 §2 非目标）。
- **wire 模型是保守估计**（逐段累加，非整页精确序列化）：inner 6 MiB 与 wire 8 MiB 是两个**独立**上限（分别对应 `MAX_RESPONSE_BYTES` 与 broker `MAX_FRAME_BYTES`），**二者差值不是安全余量**；每轨真正的信封与近似误差余量是 `PAGE_ENVELOPE_RESERVE_BYTES` 的 4 KiB。跨层测试将模型固化为契约。
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
