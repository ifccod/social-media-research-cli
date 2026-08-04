# X/Twitter 平台记忆

## 适用范围

本文件约束 X/Twitter Syndication、网页趋势和搜索客户端；测试位于 `test/twitter/`。

## 当前研究记忆

- tweet、raw syndication、token、trending、home feed 和 search 是独立公开入口，先验证 tweet ID 与 canonical URL。
- Syndication token 和签名输入属于请求级状态，不写入长期配置；趋势位置 ID 和帖子 ID 不同。

## 已知坑与解决方式

- 数字 tweet ID 需要限制范围并保持十进制字符串；无效 ID、外部 URL 和空 tweet 分别报错。
- 趋势/搜索响应的分页和列表字段不能互换；公开指标缺失时保留 null，不填零。
- 浏览器请求只复用已有匹配页面，缺页或 runtime 状态立即返回，不在客户端创建页面。

## 验证与证据

- 签名向量和浏览器合同分别在 `test/twitter/` 中覆盖；新增响应字段先固定样本。
- 修改后运行 `make test PYTHON=.venv/bin/python`。
