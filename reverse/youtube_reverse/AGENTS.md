# YouTube 平台记忆

## 适用范围

本文件约束 YouTube 公开视频客户端；测试和页面/JSON 夹具位于 `test/youtube/`。

## 当前研究记忆

- watch page、oEmbed、player、captions、search、comments、channel videos 和 trending 是不同公开合同。
- 续页 continuation、视频 ID、频道 ID 和评论 thread ID 要按来源分别保存；播放器响应中的媒体字段不等于下载授权。

## 已知坑与解决方式

- 页面没有字幕、评论关闭、continuation 缺失和反爬页面必须区分；没有数据不能凭空补零。
- 视频/频道引用只允许官方 host 和已知路径，搜索结果要校验响应中的目标身份。
- watch HTML 与 JSON endpoint 可能字段漂移，先保存原始样本再调整解析器。

## 验证与证据

- 页面/JSON 样本放在 `test/youtube/fixtures/`，覆盖 watch、comments、continuation、channel 和 trending。
- 修改后运行 `make test PYTHON=.venv/bin/python`。
