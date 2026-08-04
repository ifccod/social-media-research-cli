# 知乎平台记忆

## 适用范围

本文件约束知乎公开 JSON、搜索和动态挑战客户端；测试和夹具位于 `test/zhihu/`。

## 当前研究记忆

- question、answer、article、pin、user、comments 和 search 的响应合同独立；公开 API 需要按对象 ID 校验归属。
- 动态访客挑战使用仓库内 Node/V8 runner；脚本只计算本地挑战结果，不把页面自动化作为运行时。

## 已知坑与解决方式

- challenge、登录墙、40362 业务错误、HTTP 403 和空列表要分类保存；挑战脚本缺失或字段漂移不能静默降级为成功。
- `paging.next`、comment cursor 和对象 ID 只按官方 opaque 值透传，重复链接立即停止。
- 公开热榜与普通内容字段口径不同，缺失统计保持 null。

## 验证与证据

- JSON/HTML/JS 样本放在 `test/zhihu/fixtures/`，固定向量覆盖挑战和各类分页。
- 修改 CLI 或 runner 后运行 `make docs PYTHON=.venv/bin/python` 与 `make test PYTHON=.venv/bin/python`。
