# 皮皮虾平台记忆

## 适用范围

本文件约束 PiPiXia 公开 App JSON 客户端；测试和夹具位于 `test/pipixia/`。

## 当前研究记忆

- 帖子、评论、用户、热榜和 hashtag 使用不同 App JSON 路径；短分享链接先解析为稳定帖子引用。
- offset、count 和 cursor 可能是十进制字符串或大整数，归一化时保持精度和原始顺序。

## 已知坑与解决方式

- 账号、帖子和短链接都要校验官方主机、路径和响应身份；lookalike URL、凭据和外部跳转在请求前拒绝。
- 评论回复与顶层评论的用户、游标和嵌套结构不可混用；缺失数据要给出逐项错误。
- App 请求身份与浏览器会话分离，不能把移动 headers 挪到 Web 客户端。

## 验证与证据

- JSON/HTML 夹具放在 `test/pipixia/fixtures/`，覆盖媒体、作者、评论和分页边界。
- 修改后运行 `make test PYTHON=.venv/bin/python`。
