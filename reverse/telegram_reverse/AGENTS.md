# Telegram 平台记忆

## 适用范围

本文件约束 Telegram 公开频道页面客户端；测试和 HTML 夹具位于 `test/telegram/`。

## 当前研究记忆

- 公开频道、帖子、搜索和频道批量读取来自页面 HTML，不依赖 Bot API 或登录 Cookie。
- 页面中的帖子 ID、时间、正文、媒体预览和反应需要按页面顺序归一化；分页按 `before` 语义向旧内容推进。

## 已知坑与解决方式

- `t.me` 路径和频道名必须严格解析；单条帖子请求要从页面结果中选择精确 ID，不能只取首条。
- 没有 older link 不代表可以继续猜 cursor；返回截断标记和可用 cursor 即可。
- HTML 缺块、访问限制和 HTTP 错误分别分类，瞬时错误按统一边界重试。

## 验证与证据

- 页面样本放在 `test/telegram/fixtures/`；新增媒体类型时补页面结构和归一化测试。
- 修改后运行 `make test PYTHON=.venv/bin/python`。
