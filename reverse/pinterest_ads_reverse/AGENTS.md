# Pinterest Ads 平台记忆

## 适用范围

本文件约束 Pinterest Ads Repository、Lens 和公开 Pin 客户端；测试预留在 `test/pinterest_ads/`。

## 当前研究记忆

- Ads Repository、visual search、自然 Pin 搜索和 Pin 详情是不同匿名入口；广告库主要提供适用市场的公开触达和受众字段。
- bookmark、search_identifier 等值是 opaque 分页状态，必须原样保存并随对应入口返回。

## 已知坑与解决方式

- 不要把广告主筛选当作商品正文全库搜索；无正文搜索证据时明确报告覆盖边界。
- Lens 上传先校验本机图片大小、裁剪范围和 MIME，再提交；CDN 下载校验官方主机、大小和文件完整性。
- 分页 cursor 不前进或重复时停止并保留已有条目，不能无限请求。

## 验证与证据

- 新增测试统一放入 `test/pinterest_ads/`，先固定 bookmark、详情和媒体样本，再扩展解析。
- 修改后运行 `make test PYTHON=.venv/bin/python`。
