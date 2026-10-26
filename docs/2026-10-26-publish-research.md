# 协议发布调研（X 与小红书）

调研日期：2026-10-26。本文件只记录取证和设计。任务期间没有发帖、没有发笔记、没有点赞、没有转帖、没有关注，也没有调用最终发布接口。

证据来源：

- 本仓库桥与写接口：`reverse/browser_session.py`、`browser_session_bridge/`、`reverse/twitter_reverse/`、`reverse/xiaohongshu_reverse/`。
- 公开协议实现：`d60/twikit`、`fa0311/TwitterInternalAPIDocument`、`ReaJason/xhs`、`cv-cat/Spider_XHS`。
- 匿名 `GET https://x.com/home` 只返回约 24KB 的外壳 HTML，不含 `client-web` GraphQL 模块，不能代替已登录 `/home` 的 queryId 发现。

未使用 Playwright、CDP、页面点击或页面导航。Cookie、令牌和 queryId 都不写入长期缓存；下文出现的 queryId 只说明不同公开快照不一致。

## 结论先行

### X

推荐 A 级：继续在已有 `https://x.com/home` 标签页的页面上下文里发 GraphQL，与 `schedule-tweet` / `follow` / `upload-media` 同级，并在命令说明里标成临时传输。

`CreateTweet` 与已经实现的 `CreateScheduledTweet` 是同一类请求：`POST /i/api/graphql/{queryId}/{operationName}`，Cookie 与 `x-client-transaction-id` 留在页面里。差异在 variables，不在传输。现有 `upload-media` 返回的 `media_id_string` 可以放进 `media.media_entities[].media_id`。回复是带 `reply.in_reply_to_tweet_id` 的 `CreateTweet`。`FavoriteTweet`、`CreateRetweet`、`DeleteTweet` 在公开客户端里是更短的 POST，当前页面运行时还不会按这个形状发送。

B 级不作为第一路径。Web GraphQL 的 transaction id 还没有提纯；`signer.py` 只覆盖 Syndication。直连还要把 `auth_token` / `ct0` 导出到 Python，这和桥的边界冲突。

粗略工作量：A 级 `post` / `like` / `repost` / 回滚用 `delete` 约 1–2 人日（发现顺序、mutation POST、合同测试、`make docs`）。真实发送不在这个工作量里，需使用者另行决定。

未决问题 7 条，见文末清单 X1–X7。

### 小红书

推荐仍是 A 级。2026-10-26 本机创作者页取证后，仓库已接 `xiaohongshu_creator` 临时传输（`publish-note`），调用页面 `webpackChunkugc` 包装，不导出 Cookie / token / `x-s`。本文件仍然没有实发样本。公开实现的提交点是 `POST https://edith.xiaohongshu.com/web_api/sns/v2/note`。上传走页面 `createUploader` / COS `uploadFile`，许可是 `creator/permit`。`x-s` / `x-t` / `x-s-common` 由创作者页拦截器生成。www 的 `webpackChunkxhs_pc_web` 不会代签。

扩展清单没有 `incognito` 字段。Chrome 在使用者手动允许无痕之前，不会把无痕标签页交给扩展。即便允许，匹配规则仍是 `https://www.xiaohongshu.com/*`，`creator.xiaohongshu.com` 既不在标签规则里，也不在 `host_permissions` 里。本次不改浏览器配置。

B 级有公开 Node 签名先例，但 2024 年前后的 `web/permit` 与 2026-07 的 `creator/permit`、以及后来补上的 `x-rap-param` 已经分叉。提纯要导出 Cookie 和页面指纹，不作为第一路径。

粗略工作量：新的创作者页平台上下文、标签匹配、页面内签名调用、上传与发布体构造、合同测试，约 3–5 人日。验证停在上传成功和发布请求构造完成，不点最终发布。

未决问题 7 条，见文末清单 R1–R7。两平台合计 14 条。

## 阶段 0：现有桥

调用链：

1. 平台 `cli.py` 把参数收成桥路径和字符串条目。X 的写路径登记在 `twitter_reverse/cli.py` 的 `_BROWSER_ROUTES`，平台名是 `twitter_home`，referer 固定 `https://x.com/home`。
2. `start_daemon()` 拉起本机守护进程。`call_daemon` 用本机控制令牌走 WebSocket，请求体是 `op=request`。守护进程不保存平台 Cookie。
3. `BridgeDaemon._dispatch_control` 按平台族取 `asyncio.Lock`。`twitter_home` 与 `twitter_search` 同属 `twitter`；`xiaohongshu`、`xiaohongshu_app_v2`、`xiaohongshu_pgy` 同属 `xiaohongshu`。不同族可以并行，同一族在守护进程里串行。
4. `_select` 按族做粘性实例选择，先对扩展发 `session`，确认已有标签页 `request_ready`。缺页、未登录、运行时未就绪直接返回对应错误码，不创建标签页。
5. 扩展 `service_worker_v2.js` 只暴露 `tabs.query` / `tabs.get` / `scripting.executeScript`。`TwitterSessionAdapter` 与小红书三个适配器各自再套 `SerialRequestPolicy`。X 的 home 与 search 共用一个策略对象，所以这两条浏览器请求也串行。写路径用 `runWithoutRiskLatch`，避免单次 429 把同族读请求闩死。
6. 适配器 `chrome.scripting.executeScript({ world: "MAIN" })` 把页面函数注入已有标签页。X 在页面里自己 `fetch`，凭据用 `credentials: "include"`。小红书 www 不自己拼 `x-s`，而是找到 webpack 导出的包装函数并调用它。

X 标签匹配：`contract.js` 要求规范化后的 pathname 是 `/home`。`https://x.com/*` 能被查到，但搜索页、个人页不能代替 home。

小红书 www 标签匹配：只查询 `https://www.xiaohongshu.com/*`。笔记、主页、搜索还要 pathname 与请求上下文一致。`creator.xiaohongshu.com` 不匹配。

`session login`：只有交互式命令在 `INTERACTIVE_LOGIN_ERRORS`（含 `tab_unavailable`、`not_logged_in`、`runtime_unavailable`、`verification_required`）时调用 `authorize_browser_session`。它用操作系统打开一次白名单 URL（macOS 为 `open -a "Google Chrome"`），然后有界轮询扩展返回的脱敏会话状态。扩展不点击、不填表、不读 Cookie。同一平台只重放原请求一次。非交互模式不会打开浏览器。

## 阶段 1：X `CreateTweet` 取证

### queryId 发现

发现函数是 `page_runtime.js` 的 `discoverOperation`。顺序：

1. `performance` 里已经出现过的 `/i/api/graphql/.../{operationName}`。
2. 已加载 webpack factory 的全文扫描。`UserByScreenName`、`UserByRestId`、`UserTweets`、`Followers`、`Following`、`CreateScheduledTweet` 跳过这一步。
3. 已加载的 `client-web` 脚本（`operationFromScripts`）。
4. preload / `webpackRequire.u` 指向、但页面还没执行的 chunk（`operationFromUnloadedChunks`，即 extra-fetch）。
5. 只有上面列出的操作才会在脚本失败后再扫 webpack。

`CreateTweet` 不在跳过名单里，所以会先扫 home 页的全部 factory。仓库记忆已经说明这条扫描会把超时吃掉，因为 home 通常没有这些模块。实现时应把 `CreateTweet`、`FavoriteTweet`、`CreateRetweet`、`DeleteTweet` 放进与 `CreateScheduledTweet` 相同的顺序：资源记录、脚本、extra-fetch，最后才扫 webpack。queryId 只留在页面内存 `Symbol` 里，404 时删掉该键。不要写入磁盘或常量。

公开快照已经证明 queryId 会变，不能当长期值：

| 操作 | twikit 快照路径中的 id | TwitterInternalAPIDocument 快照路径中的 id |
| --- | --- | --- |
| `CreateTweet` | `SiM_cAu83R0wnrpmKQQSEw` | `oTolA2WNu-LVMjbarDB2KA` |
| `CreateRetweet` | `ojPdsZsimiJrUGLR1sjUtA` | `mbRO74GrOvSfRcJnlMapnQ` |
| `DeleteTweet` | `VaenaVgh5q5ih7kvyVjgtg` | `nxpZCY2K-I6QoFHAHeojFQ` |
| `FavoriteTweet` | `lI07N6Otwv1PhnEgXILM7A` | 与左列相同 |
| `CreateScheduledTweet` | `LCVzRQGxOaGnOnYH01NQXg` | 与左列相同 |

相同的两行只说明那份文档生成时碰巧一致，不说明可以硬编码。本次没有在已登录 `/home` 上跑发现器，X1 仍待实测。

### 请求与响应

`CreateTweet` 公开客户端的 POST JSON：

```json
{
  "variables": {
    "tweet_text": "<text>",
    "dark_request": false,
    "media": {
      "media_entities": [
        {"media_id": "<media_id_string>", "tagged_users": []}
      ],
      "possibly_sensitive": false
    },
    "semantic_annotation_ids": [],
    "reply": {
      "in_reply_to_tweet_id": "<tweet_id>",
      "exclude_reply_user_ids": []
    }
  },
  "features": {"<featureSwitch>": true},
  "queryId": "<discovered>"
}
```

没有回复时不带 `reply`。没有媒体时 `media_entities` 为空数组。成功时公开客户端读 `data.create_tweet.tweet_results`，帖子 ID 在其中的 `rest_id`。本仓库 `extract_rest_id` 会在 `data` 里找第一个十进制 `rest_id`，不绑死字段名。长文另走 `CreateNoteTweet`，响应该读 `data.notetweet_create.tweet_results`。普通命令先按 `CreateTweet` 设计。

`features` 不能复用 home 时间线那份 `FEATURES` 常量。`fa0311` 文档给 `CreateTweet` 的开关表，和本仓库 2026-09-08 写死的 `FEATURES` 有差集：文档多 `rweb_sports_post_context_enabled`、`responsive_web_nested_quote_preview_enabled`；常量多 `rweb_video_screen_enabled`、`creator_subscriptions_tweet_preview_api_enabled`、`responsive_web_enhance_cards_enabled`。正确做法是沿用 `cacheFeaturesFromSource`：在 queryId 旁边的 `featureSwitches` 数组里取键。取不到就返回 `runtime_unavailable`，不要用过期全集顶上。

现有错误分类已经覆盖：HTTP 401 `not_logged_in`，403 `forbidden`，429 `rate_limited`，404 清 queryId 并返回 `runtime_unavailable`。GraphQL `errors` 里 code 88/161 或文案含 rate limit 为 `rate_limited`；326/226 或文案含 captcha/challenge 为 `verification_required`。公开库另外把 187 当成重复推文、324 当成无效媒体；当前分类器会把它们收成 `request_failed`，除非文案命中上面的关键字。

### 与 `CreateScheduledTweet` 的差异

| 项 | `CreateScheduledTweet`（已实现） | `CreateTweet`（未实现） |
| --- | --- | --- |
| 端点 | `POST /i/api/graphql/{queryId}/CreateScheduledTweet` | `POST /i/api/graphql/{queryId}/CreateTweet` |
| 正文 | `post_tweet_request.status` | `tweet_text` |
| 媒体 | `post_tweet_request.media_ids: string[]` | `media.media_entities[].media_id` |
| 时间 | `execute_at` 为 number，必须是未来时间 | 无 `execute_at`，发送即发布 |
| features | 代码里固定 `{}` | 必须来自该操作的 `featureSwitches`，空对象不够 |
| 发现顺序 | 脚本优先，webpack 最后 | 当前会先扫 webpack，需要改到与定时接口相同 |
| 响应 | 公开客户端读 `data.tweet.rest_id`；本仓库测试也接受 `scheduledtweet.rest_id` | 公开客户端读 `data.create_tweet.tweet_results` 内的 `rest_id` |

页面运行时里 `isMutation` 目前只认 `CreateScheduledTweet`。其他操作若没有被列成用户时间线，会发 GET。`CreateTweet` 必须进入 POST 分支。

### 媒体

`upload-media` 已经可用，且不发布推文：

1. 用页面 hostname `x.com` 加路径 `/i/media/upload.json` 计算 `x-client-transaction-id`。实际上传主机是 `https://upload.x.com`。
2. `INIT`：`total_bytes`、`media_type`、`media_category=tweet_image`。
3. `APPEND`：一段 `FormData`，`segment_index=0`。
4. `FINALIZE` 返回 `media_id_string`。

这个 id 原样进入定时接口的 `media_ids`，也应原样进入 `CreateTweet` 的 `media_entities[].media_id`。限制保持 jpeg/png/webp、最多 4 张、单文件原始字节不超过 5_000_000。

视频不是这条链路。公开客户端对视频使用另一档 `media_category`（实现里按类型区分，GIF 还必须显式使用 `tweet_gif`），按最多 8MB 分段 APPEND，并在 FINALIZE 后轮询处理状态，完成后仍把同一个 media id 放进 `media_entities`。本仓库没有 STATUS 轮询，也没有视频类别。本次只记录，不扩展实现。

### 次级写操作

公开客户端形状如下。三者都是 POST，且那份代码不附带 `features`。文档里这三项的 features 列也是空。当前 `graphqlRequest` 要求非空 features，因此即使得出 queryId 也不会按这个形状发送。

| 操作 | variables | 用途 |
| --- | --- | --- |
| `FavoriteTweet` | `{"tweet_id": "<id>"}` | 点赞 |
| `CreateRetweet` | `{"tweet_id": "<id>", "dark_request": false}` | 转帖 |
| `DeleteTweet` | `{"tweet_id": "<id>", "dark_request": false}` | 删除自己的帖，用作发推回滚 |

取消赞是 `UnfavoriteTweet`，取消转帖是 `DeleteRetweet`（variables 用 `source_tweet_id`）。本次不设计对应命令。成功响应的字段路径没有在本次阅读的公开函数里固定下来，实现时要先用脱敏夹具锁定，再决定读哪个 `rest_id`。

## 阶段 2：X 传输分级

### A 级：页面上下文，临时传输

请求级状态与现成来源：

| 状态 | 来源 | 桥是否已覆盖 |
| --- | --- | --- |
| Bearer | 已加载或 extra-fetch 的 `client-web` 脚本里的公开客户端 Bearer | 已覆盖，`bearerTokenFromScripts` |
| `ct0` | 页面 `document.cookie` 的 `x-csrf-token` | 已覆盖，不导出 |
| 登录 Cookie | `credentials: "include"` | 已覆盖，不导出 |
| `x-client-transaction-id` | webpack 里带 `rweb_client_transaction_id_enabled` 的模块，调用导出的 `kc(hostname, pathname, method)` | 已覆盖 |
| queryId | 动态发现，仅页面内存 | 机制已覆盖；`CreateTweet` 的扫描顺序还未按定时接口对齐 |
| features | `featureSwitches` 或现有常量表 | 定时接口用空对象；`CreateTweet` 不能用空对象，也不能盲目复用 home 的 `FEATURES` |
| 标签页 | 已有 pathname `/home` | 已覆盖 |

还要补的是白名单路径、POST 判定、variables 组装和合同测试，不是新的会话通道。

### B 级：提纯后 Python 直连

缺三块，而且第一块与仓库边界冲突：

- 会话 Cookie（至少 `auth_token` 与 `ct0`）必须离开浏览器。桥明确不导出 Cookie。
- `x-client-transaction-id` 依赖页面里的 ondemand / 动画键和 webpack 模块。本仓库的 `TwitterSyndicationSigner` 只生成 Syndication 的 base36 token，不能签 `/i/api/graphql`。
- queryId 与 `featureSwitches` 随前端发布变化。公开库把它们写死，所以两份快照已经对不上。

其他平台的提纯先例（页面脚本可在 Node/V8 里重复计算、且不需要把浏览器 Cookie 混进签名状态）不适用于这条 Web 写接口。B 级可以以后单独立项，不作为发推的实现路径。

## 阶段 3：小红书发笔记

### 接口链

以下由两套公开实现交叉得到，并已用 2026-10-26 本机创作者页只读取证闭合 R1/R3/R4/R6。更近的注释日期是 Spider_XHS 的 2026-07-25 与 2026-10-17。更早的 `ReaJason/xhs` 仍使用 `web/permit`。当前活路径是 `creator/permit`，不是 `web/permit`。本切片没有实发。

1. 页面：`https://creator.xiaohongshu.com/publish/publish`。站点根 `https://creator.xiaohongshu.com/` 是公开实现里发布 POST 的 Referer；许可请求才带发布页 URL。
2. 申请许可。较新实现：`GET https://creator.xiaohongshu.com/api/media/v1/upload/creator/permit`，查询参数 `biz_name=spectrum`、`scene=image|video`、`file_count=1`、`version=1`、`source=web`。较旧实现：`GET https://edith.xiaohongshu.com/api/media/v1/upload/web/permit`，参数同形。响应读取 `data.uploadTempPermits[0]` 的 `fileIds[0]`、`token`、`uploadAddr`、`expireTime`。
3. 上传。`PUT https://{uploadAddr}/spectrum/{fileId}`。`uploadAddr` 常见为 `ros-upload.xiaohongshu.com`，也可能落到 `xhscdn.com`。头里有 `x-cos-security-token` 和一条由 fileId、大小、过期时间算出的 `authorization` 签名。这个 PUT 不携带创作者登录 Cookie。视频响应头还有 `X-Ros-Video-Id`。
4. 发布。`POST https://edith.xiaohongshu.com/web_api/sns/v2/note`。图文 `common.type=normal`。成功判定在公开实现里是顶层 `success === true`，注释中的成功体含 `result: 0`。笔记 ID 所在字段本次没有在成功样本里钉死（R2）。

图文主体字段（脱敏，较新公开构造；地点未选时不带 `post_loc`，空对象会被 `-9059` 拒绝）：

```json
{
  "common": {
    "type": "normal",
    "title": "<title>",
    "note_id": "",
    "desc": "<content>",
    "source": "{\"type\":\"web\",\"ids\":\"\",\"extraInfo\":\"{\\\"subType\\\":\\\"official\\\",\\\"systemId\\\":\\\"web\\\"}\"}",
    "business_binds": "<json string: version, noteId, notePostTiming, noteCollectionBind>",
    "ats": [],
    "hash_tag": [],
    "privacy_info": {"op_type": 1, "type": 0, "user_ids": []},
    "goods_info": {},
    "biz_relations": [],
    "capa_trace_info": {"contextJson": "<json string>"}
  },
  "image_info": {
    "images": [
      {
        "file_id": "spectrum/<fileId>",
        "width": 0,
        "height": 0,
        "metadata": {"source": -1},
        "extra_info_json": "{\"mimeType\":\"image/jpeg\",\"image_metadata\":{\"bg_color\":\"\",\"origin_size\":0}}"
      }
    ]
  },
  "video_info": null
}
```

`privacy_info.type` 页面枚举已闭合（R6）：0 公开、1 仅自己、2 不给谁看、3 只给谁看、4 仅互关。默认 0。公开材料把 2 当「仅互关」已过时。话题、地点、定时发布和视频封面不进入第一版命令。

### 签名与状态

| 状态 | 生成位置 | 桥上的含义 |
| --- | --- | --- |
| `x-s` / `x-t` / `x-s-common` | 创作者页 JS。公开库用页面材料（含 `a1`、b1、MNS 序号）在本地脚本里算 | www 页的 webpack 包装函数只覆盖已登记的只读 path，不会给 `/web_api/sns/v2/note` 签名 |
| `a1` / `webId` | `.xiaohongshu.com` Cookie。现有运行时只用 `a1` 判断访客身份是否存在，不读取值 | 必须留在页面里 |
| 创作者宿主 Cookie | 公开库点名 `access-token-creator.xiaohongshu.com`、`galaxy_creator_session_id`、`customer-sso-sid` 等宿主 Cookie | `www.xiaohongshu.com` 页面里的 `fetch` 不会带上 creator 宿主专用 Cookie |
| `x-rap-param` | 较新公开实现在发布 POST 上另附，并写明 PC 首页那套短模板会被 `-9059` 拒绝 | 2026-10-26 创作者页 webpack / 拦截器 / as 脚本均无 `x-rap-param`。页面封装自带 `X-s` / `X-t` / `X-S-Common`。第一版不本地重算（R4 已闭合） |
| 上传 `authorization` | 对 fileId、大小和许可过期时间做签名，不是 `x-s` | 若走页面上传函数，可由页面生成；不要把 token 落盘 |

现有小红书页面运行时的做法是：注入 MAIN world，捕获 webpack 全局，按 path 或工厂标记找到包装函数，把参数交给它。包装函数内部完成签名。创作者页全局名是 `webpackChunkugc`（不是 www 的 `webpackChunkxhs_pc_web`）。发布包装按 factory 标记定位（`POST_NOTE` + `toSnakeCase` / `extractData:!1`），不要写死模块号。R3 已闭合。

本仓库 `xiaohongshu_reverse` 没有签名器。公开页走 Python HTTP 读 SSR；登录态搜索、评论和 PGY 走桥。发布没有命令。

### 桥与无痕

结论：

- 扩展默认不在无痕窗口运行。`manifest.json` 没有 `incognito` 键；使用者未在 `chrome://extensions` 里允许该扩展进入无痕时，`tabs.query` 看不到无痕标签页，结果是 `tab_unavailable`。
- 允许之后，Chrome 对未声明 `incognito` 的扩展使用 spanning：仍是当前这个会连接本机守护进程的 service worker。本次没有检查本机开关，也不去打开扩展管理页。
- 即使无痕可用，`XIAOHONGSHU_TAB_PATTERNS` 只有 `https://www.xiaohongshu.com/*`，`host_permissions` 也没有 `https://creator.xiaohongshu.com/*`。`creator.xiaohongshu.com` 上的标签页不会被选中，`executeScript` 也没有该主机权限。
- `edith.xiaohongshu.com` 现有权限只覆盖两条评论 path。页面上下文里的 `fetch` 用的是页面自己的网络栈，不靠扩展去请求 edith；缺的是创作者页主机权限，不是再加一条 edith 发布 path。

改法只写在这里，本次不改清单、不改用户浏览器：

1. 使用者自行勾选扩展的无痕权限。代码不能代做。
2. 新增独立平台键（建议 `xiaohongshu_creator`），族仍为 `xiaohongshu`，与 www / PGY 串行。
3. `host_permissions` 与标签规则增加 `https://creator.xiaohongshu.com/*`。匹配收紧到已有发布页，缺页立即 `tab_unavailable`。
4. 白名单登录 URL 使用 `https://creator.xiaohongshu.com/publish/publish`，只供显式 `session login`。
5. 页面运行时只调用该页已有的签名或上传函数。找不到函数就返回 `runtime_unavailable`。

### 风控（只记录）

- HTTP 461 / 471，响应头带验证类型与验证 id：公开库将其视为验证码，本桥应对应已有的 `verification_required`，然后停止。
- 业务 code `-1`：公开实现把它记成边缘拒绝。不在本设计里加自动重试去闯过它。
- 业务 `-9059`：参数错误，包括错误的 `post_loc`、过期的隐私枚举、错误的发布指纹模板。这是请求构造问题，不是可用重试解决的。
- 发布频率的数值阈值，本次公开材料和仓库里都没有可引用的稳定额度。不编造间隔。触发验证码或限流时停。

## 阶段 4：原型设计（不发送）

命令风格对齐现有 `argparse`：写操作的 help 写明「Chrome 登录态临时传输」，路径和字段名保持原值。本次不把这些声明写进 `cli.py`，因此也不跑 `make docs`。

### X

```text
post
  --text            必填，推文正文，允许换行
  --media           可重复，本地 jpeg/png/webp，最多 4 个，单文件不超过 5000000 字节
  --reply-to        可选，被回复帖的十进制 tweet id
like
  --tweet-id        必填
repost
  --tweet-id        必填
delete-tweet
  --tweet-id        必填，只作为 post 的回滚，help 里说明会删除帖子
```

`post` 的传输顺序与 `schedule-tweet` 相同：先对每张图调用现有 `upload-media`，再发 `CreateTweet`。`delete-tweet` 不作为日常运营命令宣传，合同测试用假 id。

合同测试只断言桥条目和归一化结果，全部使用假雪花 id：

```json
{
  "path": "/bridge/v1/twitter/create-tweet",
  "entries": {
    "text": "hello",
    "media_ids": "1000000000000000001",
    "reply_to": "1000000000000000002"
  },
  "page_body": {
    "variables": {
      "tweet_text": "hello",
      "dark_request": false,
      "media": {
        "media_entities": [
          {"media_id": "1000000000000000001", "tagged_users": []}
        ],
        "possibly_sensitive": false
      },
      "reply": {
        "in_reply_to_tweet_id": "1000000000000000002",
        "exclude_reply_user_ids": []
      }
    },
    "queryId": "<runtime>"
  },
  "upstream": {
    "data": {"create_tweet": {"tweet_results": {"result": {"rest_id": "1000000000000000003"}}}}
  }
}
```

`like` / `repost` / `delete-tweet` 的夹具同样只含 `tweet_id` 与操作名。features 用测试替身对象，不断言某一组生产开关为永久真值。queryId 用 `SCHED_QUERY_12` 这种测试桩，与现有 `CreateScheduledTweet` 合同测试一样。

### 小红书

```text
publish-note
  --title     必填
  --content   必填，笔记正文
  --images    可重复，本地图片路径
```

help 写明：Chrome 创作者页临时传输；无痕中的创作者标签页需要扩展已被允许进入无痕；本命令的第一阶段可以只做到上传许可和发布体构造。不提供「跳过确认直接公开展示」之外的隐藏开关。隐私默认按待确认的公开枚举设计，在 R6 闭合前不要把某个整数写死成稳定接口。

合同夹具：

```json
{
  "permit": {
    "scene": "image",
    "fileIds": ["<fileId>"],
    "uploadAddr": "ros-upload.example",
    "token": "<redacted>"
  },
  "upload": {
    "method": "PUT",
    "path": "/spectrum/<fileId>"
  },
  "publish": {
    "method": "POST",
    "url": "https://edith.xiaohongshu.com/web_api/sns/v2/note",
    "body": {
      "common": {"type": "normal", "title": "<title>", "desc": "<content>", "note_id": ""},
      "image_info": {"images": [{"file_id": "spectrum/<fileId>"}]},
      "video_info": null
    }
  }
}
```

夹具不得包含真实 `a1`、`x-s`、`x-s-common`、上传 token 或创作者 Cookie。

### 真实发送验证方案（本次不执行）

X，仅在使用者明确要求后做一次：

1. 确认已有登录的 `https://x.com/home`，扩展已连接。用一条无媒体、正文可识别的测试帖调用 `post`。
2. 断言返回的 `rest_id` 是十进制字符串。
3. 立刻用该 id 调用 `DeleteTweet` 路径删除。删除失败则把 id 和错误码交给使用者，不自动重试发送。
4. 点赞和转帖不纳入这第一次验证。

小红书：

1. 只在已打开的创作者发布页上申请一张图的上传许可并完成 PUT。
2. 在本地打印或单测里检查发布 JSON 的字段是否齐，不把该 JSON 发到 `/web_api/sns/v2/note`。
3. 笔记有审核，最终发布等使用者另行决定。验证码、`-1`、`-9059` 都停，不绕过。

## 未决问题

X：

- X1. 已登录 `/home` 上，`CreateTweet` 的 queryId 落在已加载脚本还是 extra-fetch chunk。当前代码会先扫 webpack。
- X2. `CreateTweet` 的 features 是否必须与该模块 `featureSwitches` 全集一致；home 常量与公开文档表已经不一致。
- X3. `FavoriteTweet` / `CreateRetweet` / `DeleteTweet` 省略 features 时服务端是否接受。
- X4. 超过普通长度的正文是否必须改走 `CreateNoteTweet`。
- X5. 视频与 GIF 的 `media_category`、分段和 STATUS 轮询没有在本桥实现。
- X6. GraphQL 187、324 目前会落到 `request_failed`。
- X7. 立即发推的额度数字没有取证，不能沿用 `follow-batch` 的关注额度。

小红书：

- R1. 已闭合：当前许可是 `GET https://creator.xiaohongshu.com/api/media/v1/upload/creator/permit`，图文 `scene=image`、`biz_name=spectrum`。不是 `web/permit`。
- R2. 发布成功响应里笔记 ID 的字段路径仍无实发样本。归一化在 `success===true` / `result===0` 下从 `id` / `note_id` / `noteId` / `data.*` 取第一个 24 位 hex；没有 id 也允许 `success=true` 且 `id=null`。
- R3. 已闭合：webpack 全局名 `webpackChunkugc`；发布包装可按 factory 标记调用，不要写死模块号。
- R4. 已闭合：本页不存在 `x-rap-param`；走页面 `LV.post` 拦截器自带的 `X-s` / `X-t` / `X-S-Common`。
- R5. 本机扩展是否已被允许进入无痕。本次不改这个配置。
- R6. 已闭合：`privacy_info.type` 为 0 公开 / 1 仅自己 / 2 不给谁看 / 3 只给谁看 / 4 仅互关，默认 0。
- R7. 验证码和发布频率的触发阈值没有量化。HTTP 461/471 → `verification_required`；业务 300013 → `rate_limited`。

## 下一步

1. X：把四个写操作的发现顺序改成与 `CreateScheduledTweet` 相同；`CreateTweet` 使用发现到的 features 并 POST。补 `test/twitter/` 与 `test_twitter_contract.js` 的脱敏夹具。约 1–2 人日。
2. 使用者决定后再做一条可删除的测试帖（验证方案第 1 节）。不要在实现 PR 里默认发送。
3. 小红书：`xiaohongshu_creator` / `publish-note` 已按创作者页临时传输落地（R1/R3/R4/R6 已闭合）。R2 仍无实发样本，不要把成功 ID 字段写成稳定接口。R5 无痕开关仍由使用者自行处理。
4. 两端都不要做 B 级 Cookie 导出。签名提纯只有在页面函数不可调用、并且可以不导出 Cookie 的前提下才重新评估。
