# Snapchat Ads 平台记忆

## 适用范围

本文件约束 Snapchat 官方 Ads Gallery 匿名客户端；测试位于 `test/snapchat_ads/`。

## 当前研究记忆

- 搜索广告、广告详情、赞助内容和创作者搜索是不同官方入口；广告库主要覆盖 EEA 及官方公开时间窗。
- `impressions_total`、分国家曝光和 targeting 是上游公开指标，不能补推 CTR、点赞或播放量。

## 已知坑与解决方式

- cursor 和 next link 是 opaque 状态，必须确认仍在官方 endpoint 后再继续；重复或跨主机链接立即停止。
- 动态商品列表必须有 `product_limit`，不能因为广告包含多个商品而无限展开。
- CDN 下载先校验主机、大小、内容类型和临时文件完整性，再写入最终路径。

## 验证与证据

- 分页、真实曝光、动态商品和媒体下载测试位于 `test/snapchat_ads/test_client.py`。
- 修改后运行 `make test PYTHON=.venv/bin/python`。
