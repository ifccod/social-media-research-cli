# Social Media Research CLI

> 一条命令，把 26 个平台的公开内容、社区讨论、广告素材与创意研究变成可组合、可复核的本机数据能力。

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Node.js 18+](https://img.shields.io/badge/Node.js-18%2B-339933?logo=node.js&logoColor=white)](https://nodejs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`reverse` 是一个面向本机运行的多平台公开数据 CLI。它把内容、作者、评论、热榜、搜索、
广告资料、关键词研究和创意生产拆成清晰的底层命令，统一输出结构化结果，让人和 Agent
都能直接调用、组合、保存和复核。

当前版本包含 26 个平台上下文和 284 条命令。每个平台拥有独立的协议、解析、签名、错误
分类和测试边界；完整参数以代码中的 `argparse` 声明为准，可通过 `reverse list` 和
`reverse describe` 实时发现。

## AIReiter：Claude Fable 5、Claude Opus 5、GPT 与多模态 AI API

[AIReiter（AI Reiter）](https://aireiter.com/) 是面向开发者的统一 AI API 平台。平台支持
[Claude Fable 5](https://aireiter.com/chat/claude-fable-5)、
[Claude Opus 5](https://aireiter.com/chat/claude-opus-5)、
[GPT 系列](https://aireiter.com/gpt-5.6)等先进模型，并通过一个 API、一套计费和一套开发
工作流提供文本、图像与视频生成能力。

**逆向与网络安全研究不设额外限制：** AIReiter 支持用户使用上述模型开展逆向工程、二进制
分析、协议分析、代码审计、漏洞研究、恶意样本分析、安全测试及其他网络安全研究，完整提供
模型能力与 API 访问。访问 [AIReiter 官网（aireiter.com）](https://aireiter.com/) 可查看
全部模型和 API 文档。

> **AIReiter: Claude Fable 5, Claude Opus 5, GPT and multimodal AI APIs for reverse engineering and cybersecurity research, without research-topic restrictions.**

## 核心密码学与协议算法

项目的核心价值之一，是把多个平台的签名、摘要、流加密和响应解密提纯为可测试的本地实现。
当前最重要的算法与协议按研究价值排序：

| 优先级 | 算法或实现 | 平台/模块 | 关键用途 |
| --- | --- | --- | --- |
| P0 | **自定义 ChaCha-like 流密码**：quarter round、可变轮数、定制密钥插入和 Base64 字母表 | TikTok `signature.js` | 生成 `X-Dynosaur`、`X-Gnarly`，支撑 Creative Center 和搜索请求签名 |
| P0 | **AES-256-CBC + PKCS#7 + OpenSSL `EVP_BytesToKey`/MD5** | Xigua `crypto.py` | 解密反转 Base64 和 `Salted__` 封装的 CryptoJS 播放地址 |
| P0 | **AES-CBC + PKCS#7** | Douyin `signing.py` | 解密 Trend Insight `x-encrypted: 2` 响应体 |
| P0 | **SM3 双重摘要 + RC4 + 定制置换/编码** | Douyin `a_bogus` | 生成 Web 请求签名，分别处理 query、body、User-Agent 和浏览器指纹 |
| P0 | **SM4-style 定制 32 轮分组变换 + MD5 输入摘要** | Zhihu `X-Zse-96` | 生成知乎签名头；保留固定 S-box、轮密钥、分组处理和结果编码 |
| P1 | **MD5 规范化签名 + WBI key mixing** | Bilibili App/Web | 生成 App `sign` 和 Web `w_rid`，覆盖移动接口与 WBI 播放接口 |
| P1 | **MD5 字段摘要 + 定制 FNV-like 哈希** | TikTok `X-Gnarly`/`X-Dynosaur` | 绑定 query、body、User-Agent、指纹和协议字段 |
| P1 | **SHA-256 + 常量时间比较** | 本机会话桥、广告媒体 | 会话令牌摘要校验，以及下载媒体的完整性哈希 |

其中 MD5、SM3、SHA-256 在这里主要承担上游协议兼容、字段绑定和完整性校验；它们不是新
安全系统的算法选型建议。TikTok、Douyin、Zhihu 的自定义签名实现均有固定向量或 fixture
覆盖，算法名称、输入边界和失败分类以代码与测试为准。

## 为什么值得 Star

- **覆盖广**：从 Bilibili、抖音、TikTok、小红书、YouTube、Reddit 到 Meta、LinkedIn、
  Snapchat 和 Pinterest 广告资料，一套 CLI 进入 26 个平台。
- **研究链路完整**：从关键词、用户、视频、音乐、标签、评论，到 Creative Center、Top Ads、
  TikTok One 和 Creative Studio，支持从发现证据到创意生产预检与任务恢复。
- **输出可用**：命令结果走 `stdout`，诊断走 `stderr`；支持 JSON、Markdown、`--output`
  文件和机器可读的接口目录，适合脚本、数据管道和 Agent。
- **本机优先**：核心运行时是 Python，协议计算优先使用 Python HTTP；只有必要时才调用本机
  Node.js/V8，浏览器扩展只作为尚未提纯协议的被动会话桥。
- **接口不漂移**：CLI 参数由 `argparse` 直接生成 `skill/SKILL.md`，测试、文档和实际命令
  共用一份接口事实来源。
- **可持续扩展**：每个平台都是独立限界上下文，新增平台或修复单个平台时不会把会话、字段
  和错误状态污染到其他平台。

如果你正在做内容研究、竞品观察、关键词发现、广告素材分析、创意拆解或个人数据工具，
这个项目值得一个 Star，也欢迎通过 Issue 和 Pull Request 带来新的平台证据与解析器。

## 能力总览

| 研究方向 | 当前能力 | 覆盖平台 |
| --- | --- | --- |
| 内容与作者 | 视频、帖子、文章、图文、个人资料、频道、作者作品、媒体解析 | Bilibili、Douyin、Instagram、Kuaishou、Lemon8、PiPiXia、Telegram、Threads、Toutiao、Twitter、Weibo、Xigua、YouTube、知乎、小红书、微信生态 |
| 搜索与发现 | 关键词搜索、联想词、热榜、趋势词、标签、音乐、频道、账号和相关内容 | TikTok、Bilibili、Douyin、Reddit、YouTube、Weibo、知乎、微信、网易云音乐等 |
| 社区讨论 | 评论、回复、More comments、帖子讨论、用户评论、频道文章 | Reddit、TikTok、Bilibili、Douyin、Weibo、YouTube、知乎、小红书等 |
| 广告资料 | 广告主、广告列表、详情、投放信息、受众/触达、赞助内容和媒体下载 | Meta/Facebook、LinkedIn、Microsoft Ads、Pinterest、Snapchat |
| TikTok 研究 | 自然内容、搜索建议、趋势搜索词、Creative Center、Top Ads、达人与关键词资料 | TikTok |
| TikTok 创意 | 模型、额度、权限、历史、任务详情、视频信息、参考图上传、T2V/I2V 预检与生成 | TikTok Creative Studio |
| 小红书商业资料 | PGY 行业、优质案例、优质笔记、优质直播、头部博主 | 小红书 |
| 本机会话 | 复用已有 Chrome 页面会话，在页面上下文发起白名单请求 | Reddit、TikTok、抖音、LinkedIn、Twitter、小红书等 |

## 快速开始

需要 Python 3.11 或更高版本。TikTok 本地签名、知乎挑战计算和浏览器扩展合同测试需要
Node.js 18 或更高版本。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

安装后可以使用 `reverse`，也可以使用 `python -m reverse`：

```bash
# 发现平台和命令
reverse list
reverse list --json
reverse describe reddit search --format markdown

# 内容与社区
reverse reddit search "python typing" --subreddit python --limit 10
reverse youtube search "python tutorial" --limit 10
reverse tiktok search-general "product research" --limit 10

# 广告资料
reverse facebook_ads search-ads "portable blender" --limit 10
reverse snapchat_ads search-ads "ADVERTISER_NAME" --limit 10

# 保存机器可读结果
reverse tiktok search-users "creator economy" --output creators.json
```

命令结果写入 `stdout`；进度和诊断信息写入 `stderr`。支持 `--output PATH` 的命令可以将
JSON 直接写入本机文件。平台和命令的完整参数使用以下命令查看：

```bash
reverse describe --format json
reverse describe PLATFORM COMMAND --format markdown
```

## 完整能力索引

下面列出当前 CLI 已暴露的底层能力。每个名称都是可以通过
`reverse PLATFORM COMMAND` 调用的命令；参数、必填项、返回结构和错误码以
`reverse describe` 及 [`skill/SKILL.md`](skill/SKILL.md) 为准。

<details open>
<summary><strong>内容、社区与公开资料</strong></summary>

### `bilibili`

视频、分 P、播放地址、字幕、弹幕、用户、评论、热门、直播和部分 App 公开数据。

`video` · `parts` · `playurl` · `subtitles` · `danmaku` · `user` · `user-videos` ·
`comments` · `replies` · `search` · `popular` · `hot-search` · `home-feed` ·
`app-popular` · `app-video-detail` · `app-comments` · `app-comment-replies` ·
`app-search-type` · `app-cinema-tab` · `app-bangumi-tab` · `relation-stats` ·
`favorite-folders` · `collection` · `live-room` · `live-areas` · `live-list`

### `douyin`

公开分享页、作品、资料、批量读取、评论、搜索、关键词趋势和热榜。

`resolve` · `aweme` · `video` · `profile` · `author` · `batch-awemes` ·
`batch-profiles` · `stats` · `batch-stats` · `extract-aweme-ids` ·
`extract-sec-uids` · `user-posts` · `comments` · `comment-replies` ·
`search-videos` · `keyword-trend` · `hot`

### `instagram`

公开资料页、帖子、短码与媒体 ID 转换。

`profile` · `profile-page` · `posts` · `post` · `shortcode-to-id` · `id-to-shortcode`

### `kuaishou`

公开分享内容、短链接解析、作者资料和 Web 热榜。

`post` · `resolve` · `author` · `hot-list`

### `lemon8`

公开帖子、资料、参考页和 HTML 解析。

`post` · `profile` · `reference` · `parse-html`

### `netease_music`

歌曲、歌单、专辑、歌手、歌手专辑和搜索。

`song` · `songs` · `playlist` · `playlist-tracks` · `album` · `artist` ·
`artist-albums` · `search`

### `pipixia`

帖子、评论、用户关系、热榜、话题、短链、参考页和内容解析。

`post` · `comments` · `user` · `followers` · `following` · `hot` · `hashtag` ·
`short-url` · `resolve` · `reference` · `parse`

### `reddit`

Subreddit、帖子、评论、用户、版规、设置、联想和全站/版内搜索。

`subreddit` · `batch-info` · `post` · `more-comments` · `user` · `user-trophies` ·
`user-posts` · `user-comments` · `subreddit-info` · `subreddit-rules` ·
`subreddit-settings` · `typeahead` · `search`

### `telegram`

公开频道、频道列表、帖子和搜索。

`channel` · `channels` · `posts` · `search` · `post`

### `threads`

公开资料、帖子、解析以及公开编码/解码能力。

`profile` · `post` · `resolve` · `encode` · `decode`

### `toutiao`

文章、视频、评论、搜索、热榜、用户资料、参考页和内容解析。

`content` · `article` · `video` · `comments` · `search` · `hot` · `profile` ·
`user-id` · `user-info` · `reference` · `parse`

### `twitter`

帖子、原始数据、Token、趋势地点、趋势、首页流、搜索和 Chrome 登录态用户图。

`tweet` · `raw` · `token` · `trending` · `trend-locations` · `home-feed` ·
`search-posts` · `user` · `user-tweets` · `followers` · `following` ·
`follow` · `schedule-tweet` · `follow-batch` · `discover`

### `wechat_channels`

视频号公开分享内容读取和导出。

`feed` · `export`

### `wechat_mp`

微信公众号文章、账号、扩展字段和相关文章。

`article` · `account` · `extensions` · `related`

### `wechat_search`

搜狗公开微信索引中的文章、账号和重定向解析。

`articles` · `accounts` · `resolve`

### `weibo`

配置、频道、趋势、用户、用户作品、帖子、评论、回复、搜索和热榜。

`config` · `channel` · `trend` · `user` · `user-posts` · `post` · `comments` ·
`replies` · `search` · `hot`

### `xigua`

视频、原始视频、播放地址、评论、用户、用户作品、搜索、热榜、参考页和解析。

`video` · `video-raw` · `play` · `comments` · `user` · `user-posts` · `search` ·
`hot` · `reference` · `parse`

### `youtube`

视频、oEmbed、字幕、播放器信息、搜索、评论、频道视频、联想和趋势。

`video` · `oembed` · `captions` · `player` · `search` · `comments` ·
`channel-videos` · `search-suggest` · `trending`

### `zhihu`

问题、回答、文章、想法、用户、专栏、热榜、搜索、用户内容、关注关系和评论。

`question` · `answer` · `article` · `pin` · `user` · `column` · `hot` ·
`hot-recommend` · `question-answers` · `user-answers` · `user-articles` ·
`user-followers` · `user-followees` · `user-pins` · `comments` ·
`comment-replies` · `pin-comments` · `search`

</details>

<details open>
<summary><strong>广告资料与商业素材</strong></summary>

### `facebook_ads`

Meta Ads Library 的建议词、广告搜索、Page 广告、详情和媒体下载。

`search-suggest` · `search-ads` · `page-ads` · `ad-details` · `download-media`

### `linkedin`

公开帖子、文章、人物、作者文章、公司资料、公司动态、员工与关联公司、广告、职位和
职位建议。

`post` · `resolve-post` · `article` · `person` · `author-articles` · `company` ·
`company-posts` · `company-people` · `company-affiliates` · `ad` · `ads` · `job` ·
`jobs` · `company-jobs` · `company-job-count` · `location-suggest` ·
`job-suggest` · `company-suggest`

### `microsoft_ads`

Microsoft Advertising Ad Library 的广告主、广告搜索和详情。

`search-advertisers` · `get-advertiser` · `search-ads` · `get-ad`

### `pinterest_ads`

Pinterest 广告、Lens 视觉搜索、公开 Pin 和媒体下载。

`visual-search` · `search-ads` · `get-ad` · `search-pins` · `pin` · `download-media`

### `snapchat_ads`

Snapchat Ads Gallery 的广告搜索、详情、赞助内容、赞助内容搜索和媒体下载。

`search-ads` · `get-ad` · `sponsored-content` · `search-sponsored-content` ·
`download-media`

</details>

<details open>
<summary><strong>TikTok 研究与创意生产</strong></summary>

### `tiktok`

TikTok 的能力覆盖自然内容发现、关键词、用户、音乐、标签、评论、Creative Center、
Top Ads、TikTok One 和 Creative Studio。

**自然内容与搜索**

`videos` · `video` · `search-videos` · `search-general` · `search-users` ·
`search-music` · `search-live` · `search-photo` · `search-suggest` ·
`trending-searchwords` · `tag` · `tag-videos` · `music` · `music-videos` · `comments`

**Creative Center 与 Top Ads**

`creative-trending-hashtags` · `creative-trending-hashtags-full` ·
`creative-hashtag-detail` · `creative-trending-videos` ·
`creative-trending-videos-full` · `creative-trending-video-detail` ·
`creative-top-ads-filters` · `creative-top-ads-suggest` · `creative-top-ads` ·
`creative-top-ads-performance` · `creative-top-ads-detail` ·
`creative-top-ads-keyframes`

**关键词与 TikTok One**

`ads-keyword-ideas` · `ads-keyword-summary` · `one-creator-filters` ·
`one-creator-suggest` · `one-creator-search`

**Creative Studio**

`creative-studio-credits` · `creative-studio-permissions` ·
`creative-studio-limits` · `creative-studio-status` · `creative-studio-models` ·
`creative-studio-prepare` · `creative-studio-prepare-i2v` ·
`creative-studio-prepare-r2v` · `creative-studio-ledger` · `creative-studio-history` ·
`creative-studio-task-detail` · `creative-studio-video-info` ·
`creative-studio-download` · `creative-studio-upload-image` ·
`creative-studio-generate` · `creative-studio-generate-i2v` · `creative-studio-task`

Creative Studio 的命令会区分模型、额度、权限、预检、任务状态和成品变体；需要保持商品
身份时，先上传首帧/尾帧并执行 I2V 预检，再提交生成任务。参考图、任务 ID、稳定来源和
下载后的 SHA-256 应作为研究证据保存。

### `xiaohongshu`

小红书公开笔记、资料、搜索、评论、热榜，以及已有页面中的 PGY 商业数据。

`note` · `resolve` · `profile` · `search-notes` · `search-users` · `search-suggest` ·
`search-filters` · `hot-list` · `user-posts` · `note-comments` ·
`note-related-searches` · `pgy-good-case-classes` · `pgy-good-notes` ·
`pgy-good-lives` · `pgy-top-bloggers` · `pgy-industries`

</details>

## 研究能力怎么组合

`reverse` 提供的是可组合的底层原语，而不是把每个平台封装成不可解释的黑盒工作流。
一个典型的研究任务可以按证据逐步推进：

1. 用搜索建议、趋势词、商品描述、场景和受众建立查询集合。
2. 用搜索、作者、音乐、标签和频道命令收集候选内容。
3. 用评论、帖子详情、广告详情和稳定来源页补齐证据。
4. 对候选内容做去重、相关性筛选和指标口径标注。
5. 对高价值素材提取媒体、关键帧、落地页、创意结构和可复核链接。
6. 在需要时进入 TikTok Creative Studio，执行模型、额度、权限和参考图预检，再提交或恢复任务。

扩词、商业意图判断、候选取舍、是否继续分页和最终报告组织属于 Agent 或上层脚本的决策；
底层命令只负责可验证的数据读取和明确动作，因此可以按项目需要重新组合。

## 接口发现与文档

各平台 `cli.py` 中的 `argparse` 声明是接口唯一事实来源。修改命令参数时只修改 parser
和实现，然后重新生成能力目录：

```bash
reverse list
reverse list --platform reddit
reverse describe --format json
reverse describe reddit search --format markdown

make docs
make docs-check
```

[`skill/SKILL.md`](skill/SKILL.md) 是生成文件，不手工维护平台参数列表。它同时提供平台
说明、命令摘要、参数帮助和 Agent 组合边界。

## 浏览器会话

Chrome 扩展是尚未提纯页面协议时使用的被动会话桥，不是网页自动化运行时。扩展只查询
使用者已经打开的匹配标签页，并在页面上下文中发起白名单请求；Cookie、页面签名和 CSRF
状态不会导出到 Python。

普通命令不会创建、刷新、导航、聚焦或轮询等待标签页。匹配页面缺失、未登录或页面运行时
未就绪时，会分别返回 `tab_unavailable`、`not_logged_in` 或 `runtime_unavailable`。
交互式 `session login` 可以显式打开一次白名单业务 URL，使用者完成登录后继续原请求，
扩展不会点击页面或填写表单。

### 安装扩展

1. 打开 `chrome://extensions`。
2. 开启“开发者模式”。
3. 选择“加载已解压的扩展程序”。
4. 选择仓库中的 `browser_session_bridge/`。

### 会话命令

```bash
make browser-start
reverse session status
reverse session status --platform reddit
reverse session login tiktok_creative_studio
reverse session request reddit /bridge/v1/reddit/home-feed \
  --param sort=BEST \
  --param limit=20 \
  --param after= \
  --referer https://www.reddit.com/ \
  --request-interval-ms 3000
reverse session stop
```

本机会话目录可以通过 `BROWSER_SESSION_HOME` 覆盖。目录只保存本机控制令牌、扩展实例
摘要、平台绑定、运行锁和诊断日志，不保存平台 Cookie。

## Reddit 请求策略

Reddit HTTP 使用 `curl_cffi.requests.Session`，统一复用会话和 Cookie jar，并先访问
`old.reddit.com` 建立会话。Session 使用 Chrome 指纹 `chrome146`、`trust_env=False` 和
`proxies={"all": ""}`；搜索和评论使用当前 JSON endpoint，并带 `raw_json=1`、JSON
Accept、语言、Referer 和 Chrome User-Agent。

代理只从 `REDDIT_OPPORTUNITY_PROXY` 或 CLI 的 `--proxy` 注入，不读取通用进程代理变量：

```bash
REDDIT_OPPORTUNITY_PROXY=PROXY_URL \
  reverse reddit search "python typing" --subreddit python --limit 10

reverse reddit --proxy PROXY_URL search "python typing" --limit 10
```

CLI 的 `--proxy` 优先于环境变量。代理 URL 不写入数据库、配置或日志，错误和原始抓取记录
会脱敏。bootstrap 403 不会跳过目标请求；目标 403 使用同一 Session 刷新 `old.reddit.com`
后重试一次。429 会记录 `Retry-After` 并停止当前批次，下一轮继续，不进行短间隔循环重试。

## 工程结构

```text
reverse/
  <platform>_reverse/       平台协议、签名、解析、错误分类和 CLI
  browser_session.py        本机会话服务
  catalog.py                从 argparse 生成接口读模型

test/
  <platform>/                按平台组织的 Python 测试和 fixture
  runtime/                   跨平台调度、会话和运行时合同测试

browser_session_bridge/     Chrome Manifest V3 被动会话桥
skill/SKILL.md               从代码生成的能力目录
```

每个平台上下文独立负责输入校验、HTTP/协议、签名、解析和错误分类。共享层只承载真实的
跨平台能力，不把平台字段或会话状态混在一起。

Python 单元测试统一放在根目录 `test/`，按平台分目录；`reverse/` 下不放测试源码或测试
夹具。新增测试时创建 `test/<platform>/`，跨平台测试放入 `test/runtime/`。

根目录 `AGENTS.md` 的规则递归作用于整个仓库；每个 `reverse/<platform>_reverse/AGENTS.md`
补充该平台的研究记忆、已知问题、解决方式和证据边界。平台记忆记录可复现事实，不把一次
样本或研究资产写成稳定接口。

App 研究资产位于 `reverse/*_app_reverse/`，包括版本绑定的 Hook 和协议证据；它们不自动
成为 CLI 接口，也不与浏览器 Cookie 或 Web 会话混用。

## 开发与测试

```bash
# Python、扩展和 Skill 一致性检查
make test PYTHON=.venv/bin/python

# 分开运行
make test-python PYTHON=.venv/bin/python
make test-extension
make docs-check
```

提交前建议同时检查：

```bash
git diff --check
reverse list --json > /tmp/reverse-catalog.json
```

## 边界说明

- 项目面向个人开源和本机运行，不依赖服务端、计费系统、数据库或远程 API 密钥。
- 平台公开接口、匿名入口和登录态页面都可能随上游变更；命令会保留错误分类，调用方应
  根据状态决定重试、降级或停止，而不是把失败当作零结果。
- 媒体 URL、临时签名和页面会话具有时效性；需要长期复核时，应在本机保存来源页、采集时间、
  返回元数据和媒体哈希。
- 账户型能力依赖已有页面会话、平台资料、广告主上下文或额度；缺少这些条件时，命令会
  返回明确状态，不把证据缺失包装成市场没有结果。

## 许可证

[MIT](LICENSE)

如果这个工具帮你少写了一套平台适配器，欢迎点一个 Star；更欢迎提交真实样本、回归 fixture
和平台变更记录，让下一次研究从更可靠的起点开始。
