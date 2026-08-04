# Microsoft Ads 平台记忆

## 适用范围

本文件约束 Microsoft Advertising Ad Library 匿名 OData 客户端；测试位于 `test/microsoft_ads/`。

## 当前研究记忆

- 广告主搜索、广告主详情、广告搜索和广告详情是官方 OData 资源，查询参数按资源分别建立。
- EEA 广告的日期、国家、曝光区间和定向字段由上游提供；结果中保留官方原始字段以便复核。

## 已知坑与解决方式

- `$skiptoken`、分页偏移和日期范围必须按官方值透传，不能假设结果按广告 ID 连续。
- OData 错误响应可能是 JSON 或文本；先保留响应正文，再归类为输入、上游或传输错误。
- `advertiser_id` 与广告 ID 是不同实体，详情请求前分别校验格式。

## 验证与证据

- 请求参数、分页和错误样本在 `test/microsoft_ads/test_client.py` 中固定覆盖。
- 修改后运行 `make test PYTHON=.venv/bin/python`，不要把代理或凭据写入输出。
