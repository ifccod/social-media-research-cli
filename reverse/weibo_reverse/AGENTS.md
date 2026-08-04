# 微博平台记忆

## 适用范围

本文件约束微博移动网页 JSON 客户端；测试和夹具位于 `test/weibo/`。

## 当前研究记忆

- visitor/config、feed、trend、user、post、comments、replies 和 search 是不同移动网页接口。
- 访客初始化得到的 Cookie/身份只属于同一客户端会话；用户、帖子和评论响应要分别校验请求 ID。

## 已知坑与解决方式

- 访客页、登录墙、频控和普通 API 错误不能统一成空结果；记录状态和已保留的原始响应。
- `mid`、用户 ID 和 cursor 以字符串保留，评论/回复 cursor 必须前进，重复页立即停止。
- 页面来源的统计字段缺失时保留 null，不能把转发/点赞口径混为播放量。

## 验证与证据

- JSON/HTML 样本放在 `test/weibo/fixtures/`，覆盖 visitor、feed、post、评论和搜索。
- 修改后运行 `make test PYTHON=.venv/bin/python`。
