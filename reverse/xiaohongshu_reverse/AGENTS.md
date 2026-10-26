# 小红书平台记忆

## 适用范围

本文件约束小红书公开页面、搜索和 PGY 浏览器会话客户端；测试和夹具位于 `test/xiaohongshu/`。

## 当前研究记忆

- note、profile、搜索、评论和 PGY 数据是不同访问边界；公开页面用 Python HTTP，账户型 PGY 能力只复用已有浏览器页面。
- note/profile 的稳定 ID、canonical URL、媒体和正文要从页面真实状态交叉确认；搜索联想与结果分页独立处理。
- `publish-note` 是 Chrome 创作者页临时传输，不是稳定直连接口。平台键 `xiaohongshu_creator`，需要已打开 `https://creator.xiaohongshu.com/publish/publish` 或已登录的 `https://creator.xiaohongshu.com/new/note-manager`（笔记管理页）。图文 `--images` 与视频 `--video` 必须二选一；视频单文件上限 64MB，按 4_194_304 字节切块走 `upload-video`（`begin`/`chunk`/`finish`），封面走 `upload-image`。无 `--cover` 时用本机 `ffmpeg -y -i VIDEO -vframes 1` 抽首帧，没有 ffmpeg 则报错要求 `--cover`。页面 webpack 优先 `webpackChunkugc`，也会扫其他 `webpackChunk*`；只有 `push` 已被运行时挂钩、能取出 `require.m` 才算 `request_ready`。登录态只认常量模块里的用户信息接口（LV.get，没有 LV 时同页 fetch）；标题「小红书创作服务平台」和「发布笔记」文案不算已登录，401 / 无登录信息是 `logged_in=false`。上传用 `UPLOADER_TOKEN_NEWV2`（`/api/media/v1/upload/creator/permit`，`scene=image|video`、`biz_name=spectrum`、`version=1`、`source=web`）向页面 LV 要 permit，再由页面 `fetch` PUT 到 `uploadAddr/spectrum/<fileId>`（不要用 LV.put，拦截器打到 COS 会 Network Error）。发布不要调用页面里依赖 `toSnakeCase` 的包装函数（笔记管理页上该依赖是空的），把蛇形正文交给同一个已签名客户端 `POST https://edith.xiaohongshu.com/web_api/sns/v2/note`。不要调用 Vue `getToken` / `imageUploader.upload`（失败会走 tokenInvalidHandler 清登录），不要用 edith 的 `UPLOADER_TOKEN`，不要把模块号当稳定接口。找不到 LV 是 `runtime_unavailable`。permit 与 PUT 在页面内有界超时，失败立刻返回。不要用 www 的 `webpackChunkxhs_pc_web` 代签创作者请求，也不要 Python 重算 `x-s` 或持有 permit token。2026-10-26 实发成功样本被页面客户端解成 `{id, score}`，笔记 ID 在顶层 `id`。细节在`docs/2026-10-26-publish-research.md`。
- `like` / `comment` / `view` / `home-feed` 是 www 登录态临时传输，不是 creator 发布页。平台键 `xiaohongshu`，需要已打开 `www.xiaohongshu.com` 探索或笔记页，与 `search-notes` 同一会话。页面 webpack 全局名是 `webpackChunkxhs_pc_web`，按路径边界找包装函数代签；`/api/sns/web/v1/feed` 不能误匹配 homefeed。找不到包装则 `runtime_unavailable`，不要 Python 重算 `x-s`。搜索结果把 `xsec_token` 留在非敏感字段 `note_gate`（来源 `note_from`），归一化后仍叫 `xsec_token`。点赞 `POST /api/sns/web/v1/note/like` 和浏览 `POST /api/sns/web/v1/feed` 的 body 必须带这个值，缺了返回 `xsec_required`，不要打成 `request_failed`。点赞 body 优先 `note_oid`，包装源码是 `note_id` 则跟源码。评论 `POST /api/sns/web/v1/comment/post`（`note_id`/`content`/`at_users:[]`，第一版只做主评）不要 xsec。推荐流走 homefeed。现有 `note` 是公开 HTML，不能当登录态浏览。不要 unlike / collect / 删评。

## 已知坑与解决方式

- 页面缺失、登录态缺失、runtime 未就绪和权限/资料状态分开报告，不把页面错误当作市场无数据。
- 游标、note ID、user ID 和 PGY 分页值按原始类型保存并检查前进；媒体 URL 仅作当次下载输入。
- 浏览器桥不得创建、刷新、导航或轮询页面；缺页立即返回明确会话错误。

## 验证与证据

- 页面夹具放在 `test/xiaohongshu/fixtures/`，搜索、商业和内容洞察测试均放根目录测试包。
- 修改 CLI 参数后运行 `make docs PYTHON=.venv/bin/python`，再运行 `make test PYTHON=.venv/bin/python`。
