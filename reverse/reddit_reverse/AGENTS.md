# Reddit 平台记忆

## 适用范围

本文件约束 Reddit 公开 JSON 客户端；测试和原始夹具位于 `test/reddit/`。

## 当前研究记忆

- HTTP 必须使用同一个 `curl_cffi.requests.Session`，配置 `impersonate="chrome146"`、`trust_env=False` 和 `proxies={"all": ""}`；首次请求先访问 `https://old.reddit.com/`。
- 全站搜索、subreddit 搜索、帖子评论和 `api/info` 使用各自的新 JSON 路径，JSON 请求带 `raw_json=1`、JSON Accept、语言、Referer 和 Chrome User-Agent。
- `--proxy` 优先于 `REDDIT_OPPORTUNITY_PROXY`，代理只通过请求参数显式注入；记录和异常只保留脱敏代理信息。

## 已知坑与解决方式

- bootstrap 403 不能阻止目标 JSON；目标 403 使用同一 Session 刷新 old.reddit.com 后只重试一次。
- bootstrap 和 JSON 的每次响应、状态码、正文都写入原始抓取记录；429 只记录 `Retry-After` 并停止当前批次，不做短间隔循环重试。
- 评论 `more`、listing cursor 和用户分页都要验证 ID 归属、游标前进和批次上限。

## 验证与证据

- `test/reddit/` 覆盖 Session 配置、路径/header、403/429、代理脱敏和原始响应保留；fixture 不包含真实代理凭据。
- 修改后运行 `make test PYTHON=.venv/bin/python`，生产代理通过 `REDDIT_OPPORTUNITY_PROXY` 或 CLI `--proxy` 注入。
