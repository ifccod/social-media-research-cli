# Instagram 平台记忆

## 适用范围

本文件约束 Instagram 公开页面客户端；测试和页面样本位于 `test/instagram/`。

## 当前研究记忆

- profile、post、embed 和 shortcode/id 转换各自有不同公开页面形状，解析时优先使用 canonical URL 和页面内稳定 ID。
- 匿名请求只保留公开资料、媒体和分页字段；页面附带的内部状态不能直接当作长期 API 合同。

## 已知坑与解决方式

- 账号不存在、登录墙、空页面和真实网络错误要分别分类；不能把登录墙解析成空账号。
- shortcode 与数字 media ID 转换要限制字符集和长度，并验证转换结果能回到同一条目。
- 媒体字段可能只有图片或视频之一，归一化时保持媒体类型和原始顺序。

## 验证与证据

- HTML/JSON 样本放在 `test/instagram/fixtures/`，先更新样本再修改解析器。
- 修改后运行 `make test PYTHON=.venv/bin/python`，测试不得访问真实 Instagram。
