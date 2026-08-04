# Threads 平台记忆

## 适用范围

本文件约束 Threads 公开 SSR 和 embed 客户端；测试与页面夹具位于 `test/threads/`。

## 当前研究记忆

- profile、post、embed 和 reference 解析是不同入口；embed 页面通常包含比公开主页面更完整的文本和媒体信息。
- shortcode 与数值 ID 的编码转换是确定性工具，但结果仍要和页面 canonical 身份交叉校验。

## 已知坑与解决方式

- 页面存在嵌套可见帖子块时主帖子必须保持第一条，不能把引用内容当成目标帖子。
- profile/post 页面返回空 Open Graph、错误 canonical 或 shortcode 不匹配时要报错，不返回伪造成功。
- 公开页面的互动字段按页面实际口径保存，不把缺失值当作零。

## 验证与证据

- 页面样本放在 `test/threads/fixtures/`，转换函数使用固定向量测试。
- 修改后运行 `make test PYTHON=.venv/bin/python`。
