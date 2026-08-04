# Lemon8 平台记忆

## 适用范围

本文件约束 Lemon8 公开 HTML 客户端；测试夹具位于 `test/lemon8/`。

## 当前研究记忆

- 帖子和 profile 主要从公开页面的结构化状态、JSON-LD 和媒体链接中读取，HTML 解析与 URL reference 解析保持独立。
- 归一化结果只承诺页面实际出现的作者、标题、正文、媒体和时间字段。

## 已知坑与解决方式

- 页面脚本、内容正文和 JSON-LD 可能互相缺字段；按优先级合并并保留来源，不要把单一脚本字段视为完整资料。
- foreign host、伪造的帖子路径和缺少稳定 ID 的页面在请求前拒绝。

## 验证与证据

- 页面样本放在 `test/lemon8/fixtures/`；测试覆盖视频、图集、profile 和 malformed HTML。
- 修改后运行 `make test PYTHON=.venv/bin/python`。
