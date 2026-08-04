# Facebook Ads 平台记忆

## 适用范围

本文件约束 Meta Ads Library 匿名客户端；测试和 SSR/GraphQL 样本位于 `test/facebook_ads/`。

## 当前研究记忆

- Ads Library 的搜索建议、关键词搜索、Page 广告、详情和媒体下载是不同请求阶段；同一匿名会话内复用必要的 SSR 状态。
- 搜索结果以广告 ID、Page ID、稳定资料库 URL 和媒体元数据归一化，详情只对候选项补充地区触达、定向和付费主体。
- 普通商业广告没有通用的点赞、播放或精确曝光字段；页面排序和持续时间只能标记为代理证据。

## 已知坑与解决方式

- GraphQL 文档或 bundle 变化时先从当前页面发现文档，再重试一次；把文档漂移归类为稳定错误码。
- 媒体下载先校验官方 CDN 主机、响应类型和最大大小，使用临时文件并记录 SHA-256。
- 分页 cursor 必须按 opaque 值透传，不能按数字递增或拼接未知字段。

## 验证与证据

- 固定页面样本放在 `test/facebook_ads/testdata/`，新字段必须同时覆盖 SSR、GraphQL 和错误路径。
- 修改后运行 `make test PYTHON=.venv/bin/python`，不把账户令牌或会话 Cookie 写入 fixture。
