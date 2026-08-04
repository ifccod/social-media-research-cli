# 微信搜索平台记忆

## 适用范围

本文件约束搜狗公开微信索引客户端；测试和页面夹具位于 `test/wechat_search/`。

## 当前研究记忆

- articles、accounts 和 resolve 使用不同搜狗页面路径；结果是索引摘要，不等同公众号完整历史数据。
- canonical URL、公众号名称和文章标题是主要稳定字段，页面上的跟踪参数要清理。

## 已知坑与解决方式

- `antispider`、redirect、无结果和 malformed HTML 分别分类；遇到反爬页不要返回零条目。
- 搜索分页只能使用页面提供的链接或 token，不能猜页码；外部跳转必须拒绝。

## 验证与证据

- 固定页面样本放在 `test/wechat_search/fixtures/`，覆盖结果、账户、redirect 和反爬页面。
- 修改后运行 `make test PYTHON=.venv/bin/python`。
