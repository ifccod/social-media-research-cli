# TikTok 平台协作与调用记忆

## 适用范围

本文件约束 `reverse/tiktok_reverse/` 中的 TikTok 公开 Web、Creative Center、Top Ads、
Ads Manager Keyword Planner、TikTok One 和 Creative Studio 能力。Python 测试与 fixture
位于 `test/tiktok/`，浏览器页面合同测试位于 `browser_session_bridge/`。

本文件用于记录请求边界、参数语义、调用顺序和已验证的坑。各命令的名称、默认值、可选值
和帮助文本以 `reverse/tiktok_reverse/cli.py` 中的 `argparse` 声明为唯一事实来源。修改接口
后先更新 parser，再生成 `skill/SKILL.md`，不要在本文件维护第二份完整参数清单。

## 快速发现接口

```bash
# 查看 TikTok 命令目录
reverse list --platform tiktok

# 查看单条命令的当前参数
reverse describe tiktok COMMAND --format markdown

# 直接查看 argparse 帮助
reverse tiktok COMMAND --help
```

统一调用形式：

```text
reverse tiktok [平台通用参数] COMMAND [命令参数]
python -m reverse tiktok [平台通用参数] COMMAND [命令参数]
```

## 平台通用参数

| 参数 | 默认值 | 作用 | 使用要点 |
| --- | --- | --- | --- |
| `--timeout` | `20` | Python HTTP 请求超时秒数 | 主要作用于公开 HTTP 请求 |
| `--request-interval` | `3.0` | 同一 TikTok 客户端目标请求的最小启动间隔，范围 `0..10` 秒 | 浏览器桥会换算为 `request_interval_ms`；调试 fixture 时才使用 `0` |
| `--no-browser-login` | 关闭 | 商业页面会话缺失时直接返回会话错误 | 只影响 Chrome 会话命令；自动化和 CI 建议显式传入 |
| `--browser-login-timeout` | `300` | 交互式登录交接的最长等待秒数 | 只在终端交互式会话中生效 |
| `--output`, `-o` | `stdout` | 将命令 JSON 写入文件 | 这是平台参数，必须放在 `COMMAND` 前面 |

`creative-studio-download` 也有一个命令级 `--output`，该参数位于子命令后，表示视频文件路径：

```bash
# JSON 输出
reverse tiktok --output result.json video VIDEO_ID

# 视频文件输出
reverse tiktok creative-studio-download VID --output ./result.mp4
```

## 请求边界

TikTok 能力按访问方式分为七类。实现、会话状态和错误处理保持分离：

| 边界 | 代表命令 | 请求方式 | 会话要求 |
| --- | --- | --- | --- |
| 公开内容与搜索 | `video`、`videos`、`search-*`、`tag*`、`music*`、`comments` | Python HTTP；需要时通过本机 Node/V8 生成 `X-Dynosaur`、`X-Gnarly` | 匿名会话 |
| Creative Center 匿名预览 | `creative-trending-hashtags`、`creative-trending-videos`、`creative-trending-video-detail` | Python HTTP | 匿名会话；预览数量有边界 |
| Creative Center 完整页面 | `creative-trending-hashtags-full`、`creative-trending-videos-full`、`creative-hashtag-detail` | Chrome 被动会话桥 | 已打开的 Creative Center 匹配页面 |
| Top Ads | `creative-top-ads-*` | Chrome 被动会话桥 | 已打开的 Top Ads 匹配页面 |
| Ads Manager Keyword Planner | `ads-keyword-ideas`、`ads-keyword-summary` | Chrome 被动会话桥 | Ads Manager 登录态和广告主账户上下文 |
| TikTok One | `one-creator-*` | Chrome 被动会话桥 | TikTok One 登录态及业务资料 |
| Creative Studio | `creative-studio-*` | Chrome 被动会话桥 | Studio 登录态、资料、模型权限、积分和并发额度 |

Chrome 扩展只复用使用者已经打开的匹配标签页，在页面上下文内发起白名单请求。Cookie、
CSRF 和页面签名留在 Chrome。交互式 CLI 收到可恢复的会话错误后，可打开一次对应业务 URL，
等待使用者完成登录或账户选择，然后只重放原请求一次。

商业命令使用的会话平台名如下，平台名不可与 TikTok CLI 命令名混用：

| 请求边界 | 会话平台名 |
| --- | --- |
| Creative Center 完整页面 | `tiktok_creative` |
| Top Ads | `tiktok_creative_topads` |
| Ads Manager Keyword Planner | `tiktok_ads_manager` |
| TikTok One | `tiktok_one` |
| Creative Studio | `tiktok_creative_studio` |

```bash
reverse session start
reverse session status --platform tiktok_creative
reverse session login tiktok_creative
```

`session login` 只负责打开一次该平台的白名单业务页并等待手动登录；正常调用仍使用
`reverse tiktok COMMAND`，不要通过 `session request` 绕过平台客户端的参数校验和结果归一化。

## 公开 HTTP 请求过程

公开内容命令在一个 `TikTokClient` 内复用 HTTP Session、访客身份和请求节流状态。签名端点
按以下过程执行：

1. 先校验 URL、ID、关键词、分页和数量边界。
2. 按 `--request-interval` 等待下一个请求启动时间。
3. 初始化当前访客身份和 `msToken`。
4. 延迟加载 `TikTokSigner`，由 Node/V8 运行 `signature.js`。
5. 将 query、body、User-Agent、时间和指纹绑定到 `X-Dynosaur`、`X-Gnarly`。
6. 发出目标请求，校验响应身份、JSON 结构和游标推进，再归一化结果。

`search-suggest`、`trending-searchwords` 等公开入口按自身协议执行；未进入签名路径时保持
Node 运行时未初始化。连接错误和选定的瞬时 HTTP 状态按有界策略重试，确定性输入、身份、
响应结构和 WAF 错误直接分类返回。

### 签名算法边界

- `X-Dynosaur` 将 query、body、User-Agent、时间、计数器和指纹字段序列化，使用定制
  FNV-like 哈希、异或校验、ChaCha-like 流变换、动态密钥插入和自定义 Base64 字母表。
- `X-Gnarly` 对 query、body、User-Agent 分别做 MD5 字段摘要，再加入版本、时间、指纹和
  companion checksum，最后复用同类定制流变换封装。
- telemetry 先做 LZW 压缩，再使用独立 magic byte、Base64 字母表和同类流变换封装。
- 这里的 sigma、48 字节密钥形态、由密钥导出的轮数、密钥插入位置和字母表都属于 wire
  协议，不等同于标准 ChaCha20 参数。修改后必须通过 `test/tiktok/test_signature.py` 固定向量。

## 命令选择

### 1. 视频、资料、标签、音乐和评论

| 目标 | 命令 | 关键参数 |
| --- | --- | --- |
| 读取单条视频 | `video VIDEO_URL_OR_ID` | 接受视频 ID、标准 URL 或可验证的 TikTok 短链 |
| 读取作者公开视频 | `videos PROFILE_URL` | `--limit` 是总量上限；`--page-size` 是单次请求数量 |
| 读取视频评论 | `comments VIDEO_URL_OR_ID` | `--limit`、`--page-size`；回复使用 `--include-replies`、`--reply-limit`、`--reply-page-size` |
| 查询标签元数据 | `tag TAG_NAME` | 输入标签名称，结果中保存稳定 `tag_id` |
| 查询标签视频 | `tag-videos TAG_ID` | 输入标签 ID；支持 `--limit`、`--page-size` |
| 查询音乐元数据 | `music MUSIC_ID` | 输入音乐 ID |
| 查询音乐视频 | `music-videos MUSIC_ID` | 支持 `--limit`、`--page-size` |

示例：

```bash
reverse tiktok video 7460000000000000000
reverse tiktok videos 'https://www.tiktok.com/@creator' --limit 60 --page-size 16
reverse tiktok comments VIDEO_ID --limit 100 --page-size 20 \
  --include-replies --reply-limit 40 --reply-page-size 20
reverse tiktok tag 'smallbusiness'
reverse tiktok tag-videos TAG_ID --limit 60
reverse tiktok music-videos MUSIC_ID --limit 60
```

`tag` 的名称、`tag-videos` 的 ID、`music` 的 ID、视频 ID 和作者 `secUid` 是不同身份字段，
保存和传递时保持原类型与来源。

### 2. 搜索与趋势词

| 目标 | 命令 | 分页语义 |
| --- | --- | --- |
| 自动分页搜索视频 | `search-videos KEYWORD` | `--limit` 为总量；`--page-size` 为每次请求数量 |
| 获取一页混合搜索卡片 | `search-general KEYWORD` | 使用 `--offset` 和 `--search-id` 显式续页 |
| 搜索用户 | `search-users KEYWORD` | 使用 `--offset` 和 `--search-id`；命令按 `--limit` 有界收集 |
| 搜索音乐 | `search-music KEYWORD` | 使用 `--offset` 和 `--search-id` |
| 搜索直播 | `search-live KEYWORD` | 使用 `--offset` 和 `--search-id` |
| 搜索图文 | `search-photo KEYWORD` | 使用 `--offset` 和 `--search-id` |
| 获取联想词 | `search-suggest KEYWORD` | 使用 `--limit` 控制候选数 |
| 获取热门搜索词 | `trending-searchwords` | `--region`/`--country` 为两位地区代码，`--limit` 范围 `1..50` |

示例：

```bash
reverse tiktok search-suggest 'portable blender' --limit 20
reverse tiktok trending-searchwords --region US --limit 15
reverse tiktok search-videos 'portable blender' --limit 80 --page-size 20
reverse tiktok --output first-page.json search-general 'portable blender' --limit 12
reverse tiktok search-general 'portable blender' \
  --offset NEXT_CURSOR --search-id SEARCH_ID --limit 12
reverse tiktok search-users 'fitness creator' --limit 40
```

续页时同时保存返回的 `cursor`/`offset` 与 `search_id`。`search_id`、`rid`、视频列表 cursor、
评论 cursor 和 Creative Studio cursor 都是 opaque 值；不要自行递增、截断或跨命令复用。

### 3. Creative Center

匿名预览适合先判断国家、时间窗和指标是否有结果；需要完整分页或标签受众数据时，再进入
Chrome 页面边界。

| 目标 | 命令 | 关键参数 |
| --- | --- | --- |
| 热门标签匿名预览 | `creative-trending-hashtags` | `--country`、`--time-range`、`--industry-id`、`--page`、`--limit` |
| 热门标签完整分页 | `creative-trending-hashtags-full` | 参数与预览一致，需要 Creative Center 页面 |
| 标签受众与代表视频 | `creative-hashtag-detail HASHTAG_ID` | `--country`，`--time-range 7|30|90` |
| 热门视频匿名预览 | `creative-trending-videos` | `--metric views|engagement|completion`、国家、时间窗、内容标签 |
| 热门视频完整分页 | `creative-trending-videos-full` | 参数与预览一致，需要 Creative Center 页面 |
| 热门视频详情 | `creative-trending-video-detail ITEM_ID` | `--country`，`--time-range 7|30` |

示例：

```bash
reverse tiktok creative-trending-hashtags --country US --time-range 7 --limit 20
reverse tiktok creative-trending-videos \
  --country US --time-range 30 --metric engagement --limit 20
reverse tiktok creative-trending-videos-full \
  --country US --time-range 30 --metric completion --page 2 --limit 20
reverse tiktok creative-hashtag-detail HASHTAG_ID --country US --time-range 30
```

匿名响应中的 `continuation_restricted=true` 表示上游仍有更多结果，而匿名入口只提供当前
预览。它表示覆盖受限，不表示完整榜单已经耗尽。

### 4. Top Ads

先调用筛选目录和联想命令获取上游 ID，再构造搜索。Top Ads 的两个列表入口口径不同：

- `creative-top-ads` 使用 Creative Radar V2，排序为 `for_you`、`impression`、`ctr`、`like`。
- `creative-top-ads-performance` 使用 Top Ads Library 数值表现入口，排序为 `views`、`ctr`、
  `engagement`、`completion`。

关键参数：

- `--country` 和 `--language` 可重复传入，例如 `--country US --country GB`。
- `--industry-label-ids`、`--objectives`、`--pattern-label-ids` 接收逗号分隔 ID。
- `--metric` 在详情和关键帧命令中可重复传入。
- `material_id` 是 Top Ads 素材主键，与自然视频 `item_id` 分开保存。

示例：

```bash
reverse tiktok creative-top-ads-filters
reverse tiktok creative-top-ads-suggest 'portable blender' --country US
reverse tiktok creative-top-ads 'portable blender' \
  --country US --country GB --language en --time-range 30 --order ctr --limit 20
reverse tiktok creative-top-ads-performance 'portable blender' \
  --country US --time-range 30 --order views --limit 20
reverse tiktok creative-top-ads-detail MATERIAL_ID \
  --metric retain_ctr --metric play_retain_cnt
reverse tiktok creative-top-ads-keyframes MATERIAL_ID --metric retain_ctr
```

`impression` 排序、CTR 分位、逐秒留存、自然视频播放量和点赞量属于不同指标口径。报告中
保留来源命令、筛选参数、采集时间和稳定详情页，不把这些值合并为同一个表现分数。

### 5. Ads Manager Keyword Planner

`ads-keyword-ideas` 查询种子词的搜索量、CPC、趋势和竞争度；`ads-keyword-summary` 汇总已选
关键词包。两条命令都需要 Ads Manager 页面、登录态和广告主账户上下文。

```bash
reverse tiktok ads-keyword-ideas 'portable blender' 'smoothie maker' \
  --country US --language en --brand non_branded \
  --competition medium --competition high \
  --sort volume --order descending --limit 50

reverse tiktok ads-keyword-summary 'portable blender' 'smoothie maker' \
  --country US --match-type broad
```

种子词最多 10 个。`--competition` 可重复传入；国家必须来自 parser 的支持列表，当前语言
参数只接受 `en`。`advertiser_account_required` 表示页面已有登录态，但还需要选定广告主账户。

### 6. TikTok One 达人

推荐按 `one-creator-filters`、`one-creator-suggest`、`one-creator-search` 的顺序获取筛选值、
联想词和候选达人。`--country`、`--language` 可重复传入；粉丝、median views 和互动率使用
对应的 min/max 参数。

```bash
reverse tiktok one-creator-filters
reverse tiktok one-creator-suggest 'fitness' --limit 20
reverse tiktok one-creator-search 'fitness' \
  --country US --language en \
  --min-followers 10000 --max-followers 500000 \
  --min-median-views 20000 \
  --sort median_views --sort-direction descending --limit 24
```

达人列表中的 `recent_videos` 先筛选带稳定 URL 的条目，再用公开 `video` 命令核对自然内容
指标。TikTok One 的商业字段与公开视频统计分开记录。

### 7. Creative Studio

Creative Studio 将状态检查、预检、提交、轮询、恢复和下载拆成独立命令：

| 阶段 | 命令 | 标识符 |
| --- | --- | --- |
| 状态 | `creative-studio-status`、`creative-studio-credits`、`creative-studio-permissions`、`creative-studio-limits`、`creative-studio-models` | 无 |
| T2V 预检 | `creative-studio-prepare PROMPT` | 无；只返回预检结果 |
| I2V 资产 | `creative-studio-upload-image IMAGE_PATH` | 返回页面可用的图片 URL |
| I2V 预检 | `creative-studio-prepare-i2v PROMPT` | `--first-frame-url` 必填，`--last-frame-url` 可选 |
| R2V 预检 | `creative-studio-prepare-r2v PROMPT` | `--reference-vid` 可重复传入 1..3 个已有 Studio `vid` |
| 提交 | `creative-studio-generate`、`creative-studio-generate-i2v` | 返回 `task_id` |
| 任务查询 | `creative-studio-task TASK_ID` | 使用 `task_id`，支持 `--wait` |
| 历史恢复 | `creative-studio-history`、`creative-studio-task-detail DRAFT_ID` | 分别使用 offset 和 `draft_id` |
| 成品读取 | `creative-studio-video-info VID`、`creative-studio-download VID` | 使用成品 `vid` |
| 积分流水 | `creative-studio-ledger` | 使用 opaque `cursor` |

所有生成模式的 `--duration` 为 `4..15` 秒。`prepare*` 只校验输入、模型权限、积分和并发，
不提交生成任务。R2V 当前提供已有 Studio 视频的预检合同；提交命令以已验证的 T2V/I2V
合同为准。

T2V 示例：

```bash
reverse tiktok creative-studio-status
reverse tiktok creative-studio-models
reverse tiktok creative-studio-prepare \
  'A product close-up with a slow camera orbit' --duration 5
reverse tiktok creative-studio-generate \
  'A product close-up with a slow camera orbit' --duration 5 --wait
```

I2V 示例：

```bash
reverse tiktok creative-studio-upload-image ./first-frame.png
reverse tiktok creative-studio-prepare-i2v \
  'Slow push-in, preserve product shape and printed text' \
  --first-frame-url FIRST_FRAME_URL --duration 5
reverse tiktok creative-studio-generate-i2v \
  'Slow push-in, preserve product shape and printed text' \
  --first-frame-url FIRST_FRAME_URL --duration 5 --wait
```

恢复与下载：

```bash
reverse tiktok creative-studio-task TASK_ID --wait \
  --wait-timeout 900 --poll-interval 5
reverse tiktok creative-studio-history --offset 0 --limit 30
reverse tiktok creative-studio-task-detail DRAFT_ID
reverse tiktok creative-studio-video-info VID
reverse tiktok creative-studio-download VID --definition 720p --output ./video.mp4
```

`task_id`、`draft_id` 和 `vid` 分别表示提交任务、历史草稿和成品视频，禁止互换。等待逻辑
使用 `--wait-timeout` 和 `--poll-interval` 做有界轮询；中断后保存最后一次返回的任务状态，
后续从 `creative-studio-task` 或历史命令恢复。

## 参数与分页约定

1. `--limit` 在自动分页命令中表示本次总量上限；在带 `--page` 的页面命令中表示当前页数量。
2. `--page-size` 表示单次公开 API 请求数量，客户端会按接口上限收紧。
3. `--page` 从 1 开始；`--offset`、`cursor` 和 `search_id` 按响应原值续传。
4. `--country` 的形态按命令区分：Creative Center 多为单值，Top Ads/TikTok One 可重复，
   Keyword Planner 使用固定 choices。以单命令 `--help` 为准。
5. `action="append"` 参数通过重复 flag 传入；标明“逗号分隔”的参数在同一个值中传多个 ID。
6. 带签名的媒体 URL 有时效性；稳定详情页、内容 ID、采集时间和本机 SHA-256 一并保存。
7. `--output` 写 JSON 时放在子命令前；Studio 下载文件的 `--output` 放在子命令后。

## 浏览器会话状态

商业命令保留以下状态，不把会话缺口解释为零结果：

| 状态 | 含义 | 处理方式 |
| --- | --- | --- |
| `extension_disconnected` | 本机会话服务未连接扩展 | 启动会话服务并确认扩展连接 |
| `tab_unavailable` | Chrome 中缺少匹配业务页 | 交互式命令可进行一次登录交接 |
| `not_logged_in` | 页面存在，登录态缺失 | 在对应页面完成登录 |
| `runtime_unavailable` | 页面存在，但目标运行时仍未就绪 | 等页面稳定后重新发起一轮命令 |
| `advertiser_account_required` | Ads Manager 缺少已选广告主上下文 | 选择广告主账户并进入 Keyword Planner |
| `profile_required` | TikTok One/Studio 业务资料未完成 | 在业务页面完成资料流程 |
| `verification_required` | 页面要求验证 | 在当前页面完成验证 |
| `rate_limited` | 上游限流 | 停止当前批次，在下一轮继续 |

非交互运行时传入 `--no-browser-login`，让会话状态直接进入结构化错误。交互式登录只负责
打开白名单业务 URL 和等待使用者操作；扩展不点击页面、不填写表单、不提取 Cookie。

## 研究与实现注意事项

- Creative Center 匿名预览、完整页面、Top Ads、Keyword Planner、TikTok One 和 Studio
  是独立证据来源，分别记录 `attempted`、`unavailable_session`、`rate_limited`、
  `upstream_error` 或完成状态。
- 搜索列表、评论、标签视频和音乐视频必须验证游标前进、结果去重和请求身份；重复游标或
  ID 不归属请求对象时立即停止该分支。
- 自然内容的 `plays/likes`、Creative Center 的 views/engagement/completion、Top Ads 排序
  与逐秒曲线保持原始口径。
- 签名器延迟加载。签名、访客身份、浏览器 Cookie、Ads Manager 广告主上下文和 Studio
  任务状态分别管理。
- 首帧、尾帧和参考视频先通过对应 `prepare*` 校验。页面返回的上传 URL、已有 Studio `vid`
  和外部来源视频 URL 属于不同资产类型。
- 修改签名和协议时保留固定向量；修改页面合同先更新 fixture 和扩展合同测试，再更新 Python
  归一化层。

## 验证

```bash
# TikTok Python 测试
.venv/bin/python -m unittest discover -s test/tiktok -t . -v

# 全仓 Python、扩展和生成文档检查
make test PYTHON=.venv/bin/python

# 修改 argparse 后重新生成并检查 Skill
make docs PYTHON=.venv/bin/python
make docs-check PYTHON=.venv/bin/python
```
