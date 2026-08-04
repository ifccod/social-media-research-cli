# Kuaishou 平台记忆

## 适用范围

本文件约束 Kuaishou 公开分享页和 Web 热榜客户端；测试夹具位于 `test/kuaishou/`。

## 当前研究记忆

- 分享页 HTML 中的初始化状态是主要证据，热榜接口和分享页详情要分开归一化。
- 公开页面可能同时出现作品、作者和媒体的重复字段，应以稳定 ID 去重并保留 canonical URL。

## 已知坑与解决方式

- 缺失初始化 JSON、访问页和 malformed 页面不是空结果，必须返回可诊断的响应错误。
- 热榜条目和分享页条目的字段口径不同，不要把热榜排序当作播放或互动指标。

## 验证与证据

- HTML/JSON 样本放在 `test/kuaishou/fixtures/`；新增页面形状先增加固定 fixture。
- 修改后运行 `make test PYTHON=.venv/bin/python`。
