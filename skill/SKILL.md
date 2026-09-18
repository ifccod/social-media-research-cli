---
name: reverse
description: 本机运行的多平台公开数据 Python CLI，默认使用 Python HTTP 或 Node/V8 本地签名。
---

# reverse

<!-- 由 `python -m reverse describe --format skill` 生成。 -->

`reverse` 提供 26 个平台上下文和 284 条命令。
默认使用 Python HTTP 或 Node/V8 本地签名；浏览器桥只被动复用使用者已打开的页面。

## 使用方法

```bash
python -m reverse list
python -m reverse describe PLATFORM COMMAND --format markdown
python -m reverse PLATFORM COMMAND [options]
python -m reverse session start
python -m reverse session login PLATFORM
```

## 浏览器会话

`start`, `status`, `login`, `request`, `stop`

浏览器桥是待提纯能力的临时传输：扩展不打开、刷新、导航、聚焦或轮询等待页面。
交互式登录只由 Python CLI 打开一次白名单 URL，等待使用者手动登录；就绪后继续原请求，Cookie 不离开 Chrome。

使用 `python -m reverse describe session COMMAND --format markdown` 查看参数。

## 请求策略

- douyin、facebook_ads、snapchat_ads、tiktok、twitter 和 xiaohongshu 每个平台族同一时间只发送一个请求。
- 评论或分页读取先请求一小页，仅在需要时扩大范围。
- 列表翻页间隔 2-3 秒，回复翻页间隔 3-5 秒。
- 遇到 verification_required、rate_limited、forbidden、HTTP 429 或 HTTP 403 时停止当前批次。

## 调用层级

- 底层能力只读取一种数据或执行一个明确动作；探索任务优先由 Agent 动态组合这些命令。
- 扩词、相关性、商业意图不得写成 Python 关键词表或跨平台流水线。全仓库唯一领域工作流是 `twitter discover`：相关性只交给 Gemini（`--criteria`），Python 只做限流、去重、数值标签和有界扩散。
- 单一接口失败时保留其错误并继续可降级的研究步骤；生成、发布等动作必须先执行预检。

## 浏览器会话状态

- `tab_unavailable` 表示 Chrome 中没有匹配的业务标签页；交互式任务可调用 `session login` 打开一次白名单 URL。
- `not_logged_in` 表示匹配页面存在但登录态缺失；由使用者在该页面完成登录。
- `runtime_unavailable` 表示匹配页面已经存在，但仍在加载或目标接口上下文未就绪；不得解释为没有标签页。
- `advertiser_account_required` 表示现有 Ads Manager 页面还没有可复用的 `aadvid`；选择一个广告主账户即可，Keyword Planner 请求可复用任意已登录的 Ads Manager 账户页。
- Keyword Planner 命令出现 `tab_unavailable`、`runtime_unavailable` 或 `advertiser_account_required` 时，Agent 先调用 `session login tiktok_ads_manager`；该命令会打开 `https://ads.tiktok.com/i18n/search_ads_center/keyword-planner/creation`，不得把页面定位工作转交给使用者。已有带 `aadvid` 的 Ads Manager 标签页时直接复用，不要求停留在 Planner 路径。
- 只有上游明确返回账户无权访问或权限拒绝时才记录 Keyword Planner 权限缺失；仅有错误页面、缺少 `aadvid` 或请求上下文未就绪时，记录为页面或广告主账户上下文问题。
- `profile_required` 和 `verification_required` 分别表示业务资料和页面验证尚未完成。Agent 记录具体状态，不要求使用者导出 Cookie。

## Agent 研究流程

### 跨平台广告素材研究

1. 接受关键词、产品描述、商品链接或图片作为入口。链接先提取商品标题、品类、卖点、受众、场景、材质、价格、个性化字段和真实预览证据；图片先用 OCR/VLM 提取可见文字、主体、风格、构图、颜色和使用场景，再转成文本查询。Meta Ads Library 本身没有反向图片搜索输入，图片只能用于生成和筛选检索词。
2. 建立查询图而不是单一词表：至少区分精确商品、上位品类、受众、使用场景、节日/礼赠、问题/利益点、风格/材质、品牌/Page/落地域名。清除 SKU、尺寸、营销套话和无区分度停用词；保留原始词、清洗词、扩展来源、市场和语言，避免把 Agent 联想伪装成平台联想。
3. 匿名来源优先。Meta 先调用 `facebook_ads search-suggest` 找候选 Page，再分别用 `facebook_ads search-ads` 的 `KEYWORD_EXACT_PHRASE` 和 `KEYWORD_UNORDERED` 检查高价值查询；命中品牌、Page 或落地域名后用 `facebook_ads page-ads` 回收该广告主的近期素材，只对入围广告调用 `facebook_ads ad-details` 补充 EU/UK/BR 触达、定向和付费主体。Snapchat 不支持商品正文关键词搜索，只在已经解析出付费广告主名称后调用 `snapchat_ads search-ads`，对入围广告用 `snapchat_ads get-ad` 补齐真实曝光、分国家曝光、targeting 和动态商品。B2B 场景再使用 `linkedin ads` 与 `linkedin ad`；TikTok 按下述素材发现步骤读取自然内容、Creative Center 和 Top Ads。
4. 对查询图按市场、日期、媒体类型和投放平台做有证据的分支，不固定每个词抓取同样数量。每个适用入口必须记录 `attempted`、`skipped_not_applicable`、`unavailable_session`、`saturated` 或 `upstream_error`，以及查询、筛选、页数、原始数、去重数、入围数和停止原因；来源不可用不等于零结果。
5. 分层处理素材规模：先对全部候选完成主键去重、文案/落地域名/Page/日期/媒体元数据归一化和低成本相关性筛选；再对入围图片做 OCR/VLM，对入围视频抽取首帧、场景切换、字幕、口播、hook、CTA 和节奏。深度视频理解只覆盖能够改变候选集或创意模式的短名单，并在报告中同时列出总候选数、机器筛选数和深度分析数，不声称逐帧分析了未进入短名单的素材。
6. 严格分开指标口径。Meta 普通商业广告通常不公开点赞、播放量和精确曝光，只能使用服务端返回顺序、投放持续天数、`collation.count`、覆盖平台数和样本复用次数等代理证据；`ad-details` 在适用地区返回的是官方估算的唯一账户 reach，不是 impressions。Snapchat 的 `impressions_total` 与 `impressions_by_country` 是官方公开的实际曝光计数，可在本次已采集样本内排序，但它仍不提供 CTR、点赞和播放量。需要真实互动时，用同品牌、文案、商品或媒体指纹去 TikTok、Instagram、YouTube 等自然内容来源交叉验证。
7. 去重时保留所有 `source_hits`。每条证据至少保存采集时间、查询上下文、广告 ID、Page/广告主 ID、稳定资料库 URL、媒体类型、临时媒体 URL、落地页、日期和公开指标口径；Meta 和 Snapchat 入围素材分别使用 `facebook_ads download-media` 与 `snapchat_ads download-media` 在 CDN URL 有效期内落盘并记录 SHA-256，稳定来源页用于复核。先按内容哈希/感知哈希合并相同素材，再按 hook、镜头结构和卖点聚成可复刻创意模式。
8. 最终交付覆盖账本、清洗词与联想词、广告词拆解、候选榜、深度分析短名单、稳定数据源链接、复刻 brief 和 `reference_pack`。每个复刻变体必须指明借鉴的广告 ID/稳定 URL、保留的结构、替换的产品信息、首帧/尾帧/参考视频、运动提示和一致性检查，不能只给一段脱离参考素材的提示词。

### 关键词机会

1. 根据用户目标、市场和语言形成初始查询，但不把用户原词当作唯一词表。
2. 先调用 `tiktok search-suggest` 和 `tiktok trending-searchwords`；由 Agent 判断语言、商业意图和主题边界，形成候选词组。
3. 只对有解释价值的候选词调用 `tiktok search-general`，并按结果决定是否补充用户、音乐、图文或直播搜索；不要固定每类数量。
4. 根据证据缺口选择 Top Ads、Keyword Planner 或 TikTok One。账户型来源缺页或未就绪表示证据缺失，不表示市场需求为零。
5. 若自然内容、广告素材和关键词数据互相矛盾，调整查询或市场后再验证；新增结果不再改变结论时停止。
6. 输出候选词、保留与排除理由、来源证据、缺失阶段和下一步动作。除非用户给出评分标准，不生成固定机会分。

### TikTok 素材发现

1. 先建立来源覆盖账本。对每个入口记录 `attempted`、`skipped_not_applicable`、`unavailable_session`、`saturated` 或 `upstream_error`，并保留查询词、市场、筛选条件、页码、原始候选数、合格数和稳定来源页；缺页或会话错误不是零结果。
2. 先以 `search-suggest`、`trending-searchwords` 和 `search-general` 建立语义查询图。按商品、使用场景、受众、问题、礼赠场合、风格和相邻品类扩展；先小页验证，再只扩大能产生相关高表现候选的分支。`search-videos` 的 `--limit` 是总量而非单页上限：先读取 60-100 条；仍持续产生相关高播放高点赞候选时，继续按页扩大，直到无续页或满足停止条件，不能把 60 或 100 条误记为来源耗尽。
3. 对高价值自然候选继续按证据触发图谱扩展：只把 `search-users` 中 `profile_url_available=true` 且非空的 `profile_url` 传给 `videos`，`search-music` 后使用 `music-videos`，已知标签使用 `tag` 和 `tag-videos`；`search-photo` 只用于静态视觉或版式参考，不与视频播放/点赞排名混合。只在来源素材明确提供可用作者、音乐或标签证据时扩展，避免无关遍历。
4. 不依赖关键词的入口也要按适用性检查：对目标市场分别读取 `creative-trending-videos` 的 7/30 天 `views`、`engagement`、`completion` 预览；有 Creative Center 会话时按同一三种指标用 `creative-trending-videos-full` 继续分页。对值得保留的 ID 使用 `creative-trending-video-detail` 和 `video` 补齐稳定页、播放与点赞；读取 `creative-trending-hashtags`，有会话时用 `creative-trending-hashtags-full` 继续分页，并用 `creative-hashtag-detail` 验证其代表视频。匿名预览受限时记录 `continuation_restricted`，不把预览数量当成完整市场总量。
5. 对付费创意先读取 `creative-top-ads-filters` 与 `creative-top-ads-suggest`，再由 Agent 选择关键词或空关键词的市场/行业/目标分支，并分别检查 `impression`、`like`、`ctr` 排序和高赞 `like-range`。对入围素材读取 `creative-top-ads-detail`、相关推荐和 `creative-top-ads-keyframes`；必要时以 `one-creator-search --sort median_views|engagement` 找到相关创作者，先筛其带稳定 `url` 的 `recent_videos`，再回到公开 `video` 验证可迁移素材。
6. 自然视频先经过相关性门槛，再保留 `(plays, likes)` 的 Pareto 前沿：仅当两项都不低且至少一项更高时才支配另一条。对前沿候选按 `0.45 * percentile(log1p(plays)) + 0.45 * percentile(log1p(likes)) + 0.10 * percentile(log1p(shares + collects))` 排序；播放和点赞门槛应在每个相关候选集内取 `max(业务下限, P75)`，点赞率只作同量级的决胜项，不能让低播放素材因高比率进入主榜。为不同创意结构保留少量非支配的多样性候选。
7. 不跨口径合并指标：自然 `plays/likes`、Creative Center `video_views/engagement_rate` 和 Top Ads 的 `like`、CTR、上游 `impression` 排名分别标注。没有数值曝光时，`impression` 只能视为平台排序代理；只有经 ID 兼容性验证后才能把两个付费入口的观测合并。
8. 去重以自然 `video.id` 或稳定 TikTok URL、付费 `material_id` 为主键；保留所有 `source_hits`，不因重复命中而丢掉查询、榜单、页码和筛选上下文。稳定来源页与采集时间长期保存，带签名的 CDN 媒体 URL 仅用于当次下载。
9. 精确商品词和高价值标签只有在上游没有续页、出现限流/错误后才能标记为 `saturated`；宽泛词、作者和相邻标签可在连续两页几乎没有新增合格候选，或两次语义扩展都没有改变 Pareto 集时停止，并标记为有界采样而非穷尽。全部适用入口都有覆盖状态且新增证据不再改变候选或创意模式时结束本轮。

### TikTok 创意闭环

1. Agent 从已确认的关键词、自然内容、Top Ads 和达人证据中选择可解释的 hook、卖点与受众，不把原始结果整批写入 brief；每个选中素材都保留 `reference_evidence`，至少含稳定来源页、素材 ID、采集时间、媒体/封面地址、表现指标和借鉴的镜头结构。
2. 分析个性化商品时以真实页面控件、预览行为和配置证据交叉确认能力；单个插件标识、遗留脚本或布尔字段不足以推导在线预览缺失。
3. 生成商品素材前形成 `reference_pack`：至少包含产品正面身份图，并按场景补充环境图、结构尺寸图和真实个性化界面截图；不得只交付文本提示词。
4. 对需要保持商品结构、图案或定制文字的素材，同时给出 `start_frame`、`end_frame`、只描述运动的 `motion_prompt` 和一致性检查项。R2V 已恢复静态请求合同和参考限制；当前可用的 `creative-studio-prepare-r2v` 只校验已有 Studio `vid`，本机视频上传分片和真实生成提交仍未验证，不能把来源视频 URL 直接作为任务输入。T2V 用于不依赖身份锁定的概念验证。
5. 对选中的 Top Ads 素材，保留返回的 `creative_center_url`、`video.media_url`、`video.variants`、`landing_page` 和曲线高亮秒数；稳定来源页用于复核，带签名的媒体 URL 仅作当次下载，下载后记录本地路径和 SHA-256。
6. 生成前调用 `tiktok creative-studio-models` 判断输入模式。需要保持商品身份时，先分别调用 `tiktok creative-studio-upload-image` 上传 `start_frame` 和可选 `end_frame`，再把返回的 URL 交给 `tiktok creative-studio-prepare-i2v`；预检输出必须显示 `reference_count` 为 1 或 2，随后才调用 `tiktok creative-studio-generate-i2v`。需要核对 Seedance 2 R2V 会话时，使用现有 Studio `vid` 调用 `creative-studio-prepare-r2v`；该命令永远不会提交任务。只有不依赖参考图的概念验证才使用 `creative-studio-prepare` 和 `creative-studio-generate`。
7. 提交后保留 `task_id`；需要恢复时按情况调用任务、历史、详情和视频信息原语，不重新执行研究步骤。`creative-studio-video-info` 返回所有成品清晰度变体，默认 `video_url` 是像素面积最大的变体。
8. 结果不理想时由 Agent 判断应补充产品参考、首尾帧、关键词、广告结构还是达人证据，不重复执行整条固定流水线。

## 平台

### bilibili

Bilibili 匿名公开数据客户端

底层能力：`video`, `parts`, `playurl`, `subtitles`, `danmaku`, `user`, `user-videos`, `comments`, `replies`, `search`, `popular`, `hot-search`, `home-feed`, `app-popular`, `app-video-detail`, `app-comments`, `app-comment-replies`, `app-search-type`, `app-cinema-tab`, `app-bangumi-tab`, `relation-stats`, `favorite-folders`, `collection`, `live-room`, `live-areas`, `live-list`

### douyin

Douyin 匿名移动分享页与公开资料客户端

底层能力：`resolve`, `aweme`, `video`, `profile`, `author`, `batch-awemes`, `batch-profiles`, `stats`, `batch-stats`, `extract-aweme-ids`, `extract-sec-uids`, `user-posts`, `comments`, `comment-replies`, `search-videos`, `keyword-trend`, `hot`

### facebook_ads

Meta Ads Library 匿名 GraphQL 广告素材客户端

底层能力：`search-suggest`, `search-ads`, `page-ads`, `ad-details`, `download-media`

### instagram

Instagram 匿名公开数据客户端

底层能力：`profile`, `profile-page`, `posts`, `post`, `shortcode-to-id`, `id-to-shortcode`

### kuaishou

Kuaishou 匿名公开分享与 Web 热榜客户端

底层能力：`post`, `resolve`, `author`, `hot-list`

### lemon8

Lemon8 匿名公开页面客户端

底层能力：`post`, `profile`, `reference`, `parse-html`

### linkedin

LinkedIn 匿名公开页面 JSON-LD 与 SSR 客户端

底层能力：`post`, `resolve-post`, `article`, `person`, `author-articles`, `company`, `company-posts`, `company-people`, `company-affiliates`, `ad`, `ads`, `job`, `jobs`, `company-jobs`, `company-job-count`, `location-suggest`, `job-suggest`, `company-suggest`

### microsoft_ads

Microsoft Advertising 官方 Ad Library 匿名 OData API 客户端

底层能力：`search-advertisers`, `get-advertiser`, `search-ads`, `get-ad`

### netease_music

NetEase Cloud Music 匿名公开数据客户端

底层能力：`song`, `songs`, `playlist`, `playlist-tracks`, `album`, `artist`, `artist-albums`, `search`

### pinterest_ads

Pinterest Ads Repository、Lens 与公开 Pin 匿名素材客户端

底层能力：`visual-search`, `search-ads`, `get-ad`, `search-pins`, `pin`, `download-media`

### pipixia

PiPiXia 匿名公开 App JSON 客户端

底层能力：`post`, `comments`, `user`, `followers`, `following`, `hot`, `hashtag`, `short-url`, `resolve`, `reference`, `parse`

### reddit

Reddit 公开 JSON 匿名客户端

底层能力：`subreddit`, `batch-info`, `post`, `more-comments`, `user`, `user-trophies`, `user-posts`, `user-comments`, `subreddit-info`, `subreddit-rules`, `subreddit-settings`, `typeahead`, `search`

### snapchat_ads

Snapchat 官方 Ads Gallery 匿名 JSON API 客户端

底层能力：`search-ads`, `get-ad`, `sponsored-content`, `search-sponsored-content`, `download-media`

### telegram

Telegram 公开频道匿名客户端

底层能力：`channel`, `channels`, `posts`, `search`, `post`

### threads

Threads 公开 SSR 与嵌入页匿名客户端

底层能力：`profile`, `post`, `resolve`, `encode`, `decode`

### tiktok

TikTok 资料、视频、搜索、标签、音乐与评论查询客户端

底层能力：`videos`, `video`, `search-videos`, `search-general`, `search-users`, `search-music`, `search-live`, `search-photo`, `search-suggest`, `trending-searchwords`, `creative-trending-hashtags`, `creative-trending-hashtags-full`, `creative-hashtag-detail`, `creative-trending-videos`, `creative-trending-videos-full`, `creative-trending-video-detail`, `creative-top-ads-filters`, `creative-top-ads-suggest`, `creative-top-ads`, `creative-top-ads-performance`, `creative-top-ads-detail`, `creative-top-ads-keyframes`, `ads-keyword-ideas`, `ads-keyword-summary`, `creative-studio-credits`, `creative-studio-permissions`, `creative-studio-limits`, `creative-studio-status`, `creative-studio-models`, `creative-studio-prepare`, `creative-studio-prepare-i2v`, `creative-studio-prepare-r2v`, `creative-studio-ledger`, `creative-studio-history`, `creative-studio-task-detail`, `creative-studio-video-info`, `creative-studio-download`, `creative-studio-upload-image`, `creative-studio-generate`, `creative-studio-generate-i2v`, `creative-studio-task`, `one-creator-filters`, `one-creator-suggest`, `one-creator-search`, `tag`, `tag-videos`, `music`, `music-videos`, `comments`

### toutiao

今日头条公开 HTTP 匿名客户端

底层能力：`content`, `article`, `video`, `comments`, `search`, `hot`, `profile`, `user-id`, `user-info`, `reference`, `parse`

### twitter

X/Twitter Syndication、网页趋势与 Chrome 登录态用户图客户端

底层能力：`tweet`, `raw`, `token`, `trending`, `trend-locations`, `home-feed`, `search-posts`, `user`, `user-tweets`, `followers`, `following`, `follow`, `schedule-tweet`, `follow-batch`
领域工作流：`discover`

### wechat_channels

微信视频号公开分享匿名客户端

底层能力：`feed`, `export`

### wechat_mp

微信公众号文章匿名客户端

底层能力：`article`, `account`, `extensions`, `related`

### wechat_search

搜狗公开微信索引匿名 HTTP 客户端

底层能力：`articles`, `accounts`, `resolve`

### weibo

微博移动网页 JSON 匿名客户端

底层能力：`config`, `channel`, `trend`, `user`, `user-posts`, `post`, `comments`, `replies`, `search`, `hot`

### xiaohongshu

小红书公开页面与 Chrome 登录态数据客户端

底层能力：`note`, `resolve`, `profile`, `search-notes`, `search-users`, `search-suggest`, `search-filters`, `hot-list`, `user-posts`, `note-comments`, `note-related-searches`, `pgy-good-case-classes`, `pgy-good-notes`, `pgy-good-lives`, `pgy-top-bloggers`, `pgy-industries`

### xigua

西瓜视频移动端公开数据匿名客户端

底层能力：`video`, `video-raw`, `play`, `comments`, `user`, `user-posts`, `search`, `hot`, `reference`, `parse`

### youtube

YouTube 公开视频匿名客户端

底层能力：`video`, `oembed`, `captions`, `player`, `search`, `comments`, `channel-videos`, `search-suggest`, `trending`

### zhihu

知乎公开 JSON 匿名客户端

底层能力：`question`, `answer`, `article`, `pin`, `user`, `column`, `hot`, `hot-recommend`, `question-answers`, `user-answers`, `user-articles`, `user-followers`, `user-followees`, `user-pins`, `comments`, `comment-replies`, `pin-comments`, `search`

## 接口发现

仓库中的 Skill 是生成文件。使用以下命令查询当前代码契约的完整参数：

```bash
python -m reverse describe --format json
python -m reverse describe PLATFORM COMMAND --format markdown
```
