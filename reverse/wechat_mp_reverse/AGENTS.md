# 微信公众号平台记忆

## 适用范围

本文件约束微信公众号公开文章页面客户端；测试和 HTML/JSON 夹具位于 `test/wechat_mp/`。

## 当前研究记忆

- article、account、extensions 和 related 是不同页面/接口形状；文章正文、作者和媒体以页面公开数据为准。
- 页面内扩展配置是可选附加证据，不能替代文章 canonical identity。

## 已知坑与解决方式

- 扫码登录、验证码页、反爬页和真正的空文章必须分类，不要将拦截页面解析成空正文。
- 文章 URL 的 query 和 redirect 需要在官方主机范围内校验；媒体 URL 与文章 URL 分开处理。

## 验证与证据

- 页面样本放在 `test/wechat_mp/fixtures/`，新增解析字段先增加固定 HTML 测试。
- 修改后运行 `make test PYTHON=.venv/bin/python`。
