# Bilibili 平台记忆

## 适用范围

本文件约束 `reverse/bilibili_reverse/` 的运行时代码；对应单元测试和夹具位于 `test/bilibili/`。

## 当前研究记忆

- Web 请求和 App 请求是两条独立边界。Web 侧使用 WBI 参数，App 侧使用固定的移动身份、REST 和 gRPC/protobuf 传输。
- App 搜索、热门、视频详情、评论和回复已经提炼为 Python 原语；未知 protobuf 字段要保留在原始载荷中，不要凭字段名猜业务含义。
- WBI key、移动身份和播放地址签名属于不同上下文，不能共用 Cookie、请求头或身份文件。

## 已知坑与解决方式

- 游标可能是大整数或 opaque 字符串，始终按字符串或受边界保护的整数处理，并验证游标前进。
- gRPC frame、gzip trailer、响应体和分页 token 都有大小边界；先验证边界，再解析字段。
- App 身份文件必须是本机私有文件；损坏身份要报告并可修复，不能静默生成另一份身份。

## 验证与证据

- 固定样本放在 `test/bilibili/testdata/`，新增协议字段先补 fixture 和解析边界测试。
- 修改此上下文后运行 `make test PYTHON=.venv/bin/python`；不要把测试重新放回生产包。
