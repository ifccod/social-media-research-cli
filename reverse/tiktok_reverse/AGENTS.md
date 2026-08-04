# TikTok 平台记忆

## 适用范围

本文件约束 TikTok 公开 Web、Creative Center、TikTok One 和 Creative Studio 原语；测试和夹具位于 `test/tiktok/`。

## 当前研究记忆

- 公开搜索、用户、音乐、标签、评论、Creative Center 和账户型 Studio 是不同访问边界，命令只返回各自可重复证据。
- 需要上游 JavaScript 时使用本机 Node/V8 签名；Creative Center/Studio 页面会话通过被动浏览器桥，不把 Cookie 导出到 Python。
- search cursor、continuation、material ID 和 task ID 都是不同 opaque 状态，按命令边界保存。

## 已知坑与解决方式

- 签名器延迟加载，未使用签名命令时不能初始化 Node；签名请求失败只按 transient/确定性分类重试。
- Creative Center 的匿名预览不是完整市场总量；页面、会话、账户、权限和额度错误要分开报告。
- I2V/R2V 先做图片或已有 Studio 视频预检，参考帧 URL 要显式进入任务；不能把来源视频 URL 当成已验证的上传合同。
- 搜索、评论和分页要验证游标前进、ID 归属和请求间隔；自然内容指标与 Top Ads 指标不得跨口径合并。

## 验证与证据

- 夹具放在 `test/tiktok/fixtures/`，Node/V8 合同测试和浏览器桥合同测试分别保持独立。
- 修改 CLI 参数后运行 `make docs PYTHON=.venv/bin/python`，随后运行 `make test PYTHON=.venv/bin/python`。
