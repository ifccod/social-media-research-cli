# LinkedIn 平台记忆

## 适用范围

本文件约束 LinkedIn 公开页面和 Ad Library 客户端；测试与 HTML/JSON 夹具位于 `test/linkedin/`。

## 当前研究记忆

- person、company、post、article、job 和 ad library 是独立页面合同；优先从 canonical、JSON-LD 和 SSR 状态获取稳定身份。
- 同一页面可能混合结构化字段、嵌入对象和 Open Graph 兜底；结果要标记来源和是否为有限 fallback。

## 已知坑与解决方式

- slug、数字 ID、URN 和短链接必须逐一校验归属，不能用字符串包含判断对象类型。
- 登录墙、访问限制、空 SSR 和外部重定向分别报错；transient 网络错误只按客户端统一策略重试。
- 广告库、职位和社交内容的分页参数不可互换，cursor 只透传上游值。

## 验证与证据

- 所有页面样本放在 `test/linkedin/fixtures/`；广告解析新增字段时同步覆盖列表和详情。
- 修改后运行 `make test PYTHON=.venv/bin/python`。
