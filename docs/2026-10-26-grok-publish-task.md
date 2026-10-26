# 协议发布接口调研任务（Grok 执行）

## 背景

本项目已用浏览器会话桥（`browser_session_bridge/` 扩展 + `reverse/browser_session.py`）实现了多平台读取能力，以及 X 的少量写接口。当前运营痛点：每次发推/发笔记都要人工在网页上模拟操作，太费劲。本任务的目标是**调研**（不是直接上线功能）：摸清 X 与小红书「走协议发布」的可行路径，用现有被动桥做会话桥接，产出有证据的结论和下一步实现计划。

## 已知现状（先读代码核对，不要凭记忆）

- 必读：根 `AGENTS.md`、`reverse/twitter_reverse/AGENTS.md`、`reverse/xiaohongshu_reverse/AGENTS.md`、`README.md` 中桥与传输分级相关章节。
- X 现有写接口（均为 Chrome 登录态临时传输，只复用已有 `/home` 标签页在页面上下文发请求）：`schedule-tweet`（走原生 `CreateScheduledTweet`）、`follow` / `follow-batch`、`upload-media`（jpeg/png/webp，最多 4 张，单文件 ≤ 5,000,000 字节）。缺：立即发推、回复、点赞、转帖、删帖。
- X 已取证：`Following` / `Followers` / `UserTweets` 等 GraphQL POST 在 `/home` 页上下文可成功（body 需 `includePromotedContent` 等字段）；queryId 为动态发现、不硬编码。签名相关见 `reverse/twitter_reverse/signer.py` 与 `browser_session_bridge/test_twitter_contract.js`。
- 小红书现有能力全为只读（note / profile / 搜索 / 评论 / PGY，PGY 走桥）。**没有任何发布命令**。创作者平台发布链路从未取证。
- 桥的硬约束（根 AGENTS.md）：扩展只查询已有匹配标签页并在页面上下文发请求；不得创建、刷新、导航、聚焦或轮询等待标签页；Cookie 和页面签名留在 Chrome；缺页/未登录立即返回明确错误。

## 调研任务

### 阶段 0：现有桥工作方式梳理
通读 `reverse/browser_session.py`、`browser_session_bridge/service_worker_v2.js`、`reverse/twitter_reverse/client.py`、`reverse/xiaohongshu_reverse/client.py`，用一页篇幅说清：CLI ↔ 守护进程 ↔ 扩展 ↔ 页面上下文 fetch 的调用链、标签页匹配规则、串行/并行规则、`session login` 交接流程。写进报告第 0 节。

### 阶段 1：X 立即发推（CreateTweet）取证
1. 参照 `CreateScheduledTweet` 的既有实现与合同测试，定位 `CreateTweet` 的 queryId 动态发现路径（页面运行时/scripts/extra-fetch 哪条可行），记录发现方法与证据，不把 queryId 硬编码进长期缓存。
2. 梳理请求结构：variables（tweet_text、media.media_entities、reply.in_reply_to_tweet_id、semantic_annotation_ids 等以实际证据为准）、features 字段全集、成功响应结构（rest_id 位置）、主要错误码与触发条件。
3. 与 `CreateScheduledTweet` 做差异表：端点、variables、状态字段（scheduled vs 立即）、响应。
4. 媒体绑定：确认 `upload-media` 返回的 media_id 如何进入 CreateTweet；视频是否同链路（只记录，不扩展实现）。
5. 次级目标（同法取证，能做多少做多少）：`FavoriteTweet`（点赞）、`CreateRetweet`、`DeleteTweet`、回复（本质是带 in_reply_to 的 CreateTweet）。

### 阶段 2：X 落地路径分级
按仓库传输分级给结论，每级都要有证据：
- A 级：桥内页面上下文发送（与现有写接口同级，临时传输）——需要哪些请求级状态（bearer 来源、ct0、动态 queryId）、桥现有能力是否已覆盖。
- B 级：签名/状态提纯后 Python 直连——缺什么、提纯难点在哪（参照其他平台已有签名提纯先例）。
明确写出推荐路径和理由。

### 阶段 3：小红书发笔记链路取证
1. 创作者平台发布链路全程拆解（以代码与公开证据交叉确认，拿不准的标「待实测」）：图片上传（permit 申请 → 上传 → fileId）、发布提交接口（域名与路径，如 edith/creator 域）、请求体结构（图文笔记字段全集）、成功判定。
2. 签名与状态：`x-s` / `x-t` / `x-s-common` 等头/参数的生成位置（哪个页面 JS、是否可由桥在页面上下文直接调用页面 fetch 绕开自算签名）、a1/webId 等 cookie 依赖。
3. 桥覆盖问题：小红书账号会话目前在 Chrome **无痕窗口**的创作者平台标签页——确认扩展是否允许在无痕中运行、桥的标签匹配规则是否覆盖 `creator.xiaohongshu.com`、不覆盖时缺什么配置（只给结论和改法，不擅自改用户浏览器配置）。
4. 风控边界只记录不绕过：验证码/风险提示可能出现的环节、已知的发布频率限制。

### 阶段 4：原型设计（只设计，不真实发送）
- 给出命令设计稿：如 twitter `post`（含 `--text` / `--media` / `--reply-to`）、`like`、`repost`；xiaohongshu `publish-note`（含 `--title` / `--images` / `--content`）。参数风格与现有 `cli.py` 的 argparse 声明保持一致。
- 给出每条命令的合同测试样本结构（脱敏：只留字段名与结构，真实 Cookie/令牌值一律不落盘）。
- 给出真实发送验证方案（单独一节）：X 用 1 条测试帖验证的步骤与回滚（DeleteTweet）；小红书验证止步于「上传成功 + 发布请求构造完成」，不点最终发布（笔记有审核机制，避免产生垃圾笔记）——最终发布验证等使用者另行决定。
- **本任务内禁止执行任何真实发送**（不发帖、不发笔记、不点赞、不关注），只做取证、离线复现与设计。

## 约束（与根 AGENTS.md 一致，冲突时以根 AGENTS.md 为准）

- 不引入 Playwright、CDP、页面点击、页面导航作为运行时或取证手段；取证只走桥的既有被动方式与公开代码/文档证据。
- 不提取、不保存真实 Cookie/令牌到任何文件；证据样本全部脱敏。
- 工作树可能有未提交改动：不得 reset/checkout 覆盖；新增文件优先，改现有文件前先读懂。
- 若写原型代码：放对应平台目录，测试放 `test/<platform>/`，改完跑 `make test PYTHON=.venv/bin/python`；改接口声明跑 `make docs` 并过 `make docs-check`。文档与注释用中文。

## 产出

1. `docs/2026-10-26-publish-research.md`：按阶段 0–4 组织，结论先行——每平台一节含：接口链时序、关键请求结构（脱敏）、签名/状态来源表、可行性分级结论、未决问题清单、下一步实现计划（含粗略工作量）。
2. 结论摘要回写 `reverse/twitter_reverse/AGENTS.md` 与 `reverse/xiaohongshu_reverse/AGENTS.md` 的「当前研究记忆」（只写已取证结论，研究资产不得写成稳定接口）。
3. 完成时在会话输出一页摘要：两个平台各一句话结论 + 报告路径 + 未决问题数。
