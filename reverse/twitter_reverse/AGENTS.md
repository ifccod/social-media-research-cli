# X/Twitter 平台记忆

## 适用范围

本文件约束 X/Twitter Syndication、网页趋势和搜索客户端；测试位于 `test/twitter/`。

## 当前研究记忆

- tweet、raw syndication、token、trending、home feed 和 search 是独立公开入口，先验证 tweet ID 与 canonical URL。
- CLI `user` / `user-tweets` / `followers` / `following` 是 Chrome 登录态临时传输，复用 `twitter_home`；非 `me` 的 `screen_name` 先 `user` 再带 `rest_id`。
- `discover` 是只读冷启动榜单：种子为自己的 following/followers，硬过滤蓝 V，Gemini 只吃 `--criteria`，JSONL resume，不 follow。`--pages` 控制种子翻页。榜单带 `followed_by_me`（当前登录号是否已关注）。`--csv` 写出 CSV（主页链接、是否关注、标签、粉/关、AI 摘要）。根目录 `.env` 的 `GEMINI_*` 由 CLI 自动读入，不覆盖已有环境变量。
- Syndication token 和签名输入属于请求级状态，不写入长期配置；趋势位置 ID 和帖子 ID 不同。

## 已知坑与解决方式

- 数字 tweet ID 需要限制范围并保持十进制字符串；无效 ID、外部 URL 和空 tweet 分别报错。
- 趋势/搜索响应的分页和列表字段不能互换；公开指标缺失时保留 null，不填零。
- 浏览器请求只复用已有匹配页面，缺页或 runtime 状态立即返回，不在客户端创建页面。
- 用户图 GraphQL 必须在 pathname=`/home` 的已有标签页发现。User* 不要先扫全部 webpack factory（home 通常未加载这些模块，扫完会超时）；先 scripts / extra-fetch。
- 2026-09-08 已登录 `https://x.com/home` 取证（queryId 动态发现，不硬编码进请求路径以外的缓存）：
  - `UserByScreenName` GET 成功；简介在 `profile_bio.description`
  - `UserByRestId` GET 成功（`screen_name=me` 读 twid）
  - `Following` / `Followers` / `UserTweets` **POST** 成功，body 需 `includePromotedContent`（推文为 true，关系列表为 false）；UserTweets 另需 `withVoice`/`withV2Timeline`/`withQuickPromoteEligibilityTweetFields`
  - 关系列表：`timeline.timeline.instructions` 里 `TimelineAddEntries`，用户 `entryId=user-*`，翻页 `cursor-bottom` / `cursor-top`
  - 用户时间线同样是 `TimelineAddEntries`，`entryId=tweet-*` plus pin 指令
  - GET 打列表会 `request_failed`；缺 `includePromotedContent` 时 POST 也会失败
- `discover` 不自动 follow / unfollow / 点赞；垂直口径只在 `--criteria` 给 Gemini，不要做成 Python 关键词黑名单。
- JSONL 终态只有 `skip` / `hit` / 最终 `judged`；`llm` 不是终态。`cursor.exhausted` 只表示上游没有下一页。`--max-candidates` / `--max-llm-calls` 按本轮计数；列表页、资料、推文和判定结果写入 `--state`，续跑不得重打。默认 `--gemini-concurrency 1`：队列里的主页先串行判定，Gemini 在飞时不翻下一页 X；命中只登记粉/关列表，不在判定时一次翻完。
- 扩散枢纽是 `mutual_blue` 且粉丝 50–10k；`kol` 进全量榜、不当种子。`today_suggested` 只放互关蓝 V。命中枢纽后下一页先翻对方 following/followers，不把自己的剩余种子页翻完。续跑读 jsonl：终态 skip/hit 不重判，`llm_failed` 会重试，列表从上次 cursor 接着翻。默认 `--max-llm-calls 40` 会在自己的关注前两页就停。限流/403/验证码停整批并闩 twitter 族，需重载扩展。

## 验证与证据

- 签名向量和浏览器合同分别在 `test/twitter/` 中覆盖；新增响应字段先固定样本。
- 修改后运行 `make test PYTHON=.venv/bin/python`。
