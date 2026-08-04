# 小红书平台记忆

## 适用范围

本文件约束小红书公开页面、搜索和 PGY 浏览器会话客户端；测试和夹具位于 `test/xiaohongshu/`。

## 当前研究记忆

- note、profile、搜索、评论和 PGY 数据是不同访问边界；公开页面用 Python HTTP，账户型 PGY 能力只复用已有浏览器页面。
- note/profile 的稳定 ID、canonical URL、媒体和正文要从页面真实状态交叉确认；搜索联想与结果分页独立处理。

## 已知坑与解决方式

- 页面缺失、登录态缺失、runtime 未就绪和权限/资料状态分开报告，不把页面错误当作市场无数据。
- 游标、note ID、user ID 和 PGY 分页值按原始类型保存并检查前进；媒体 URL 仅作当次下载输入。
- 浏览器桥不得创建、刷新、导航或轮询页面；缺页立即返回明确会话错误。

## 验证与证据

- 页面夹具放在 `test/xiaohongshu/fixtures/`，搜索、商业和内容洞察测试均放根目录测试包。
- 修改 CLI 参数后运行 `make docs PYTHON=.venv/bin/python`，再运行 `make test PYTHON=.venv/bin/python`。
