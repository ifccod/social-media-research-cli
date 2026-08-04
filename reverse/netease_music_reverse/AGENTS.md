# 网易云音乐平台记忆

## 适用范围

本文件约束 NetEase Cloud Music 公开数据客户端；测试位于 `test/netease_music/`。

## 当前研究记忆

- song、playlist、album、artist 和 search 是不同数据形状，列表详情与批量详情需要分层归一化。
- 批量歌曲查询可能缺少部分条目；结果要保持请求顺序并显式记录缺失项。

## 已知坑与解决方式

- 播放列表的 track id 不等于完整歌曲对象，只有需要时再补详情，避免无界请求。
- API 错误、无效 JSON 和 HTTP 状态分别分类；瞬时失败使用统一重试边界，确定性错误不重复发送。
- 搜索类型和分页限制必须在网络请求前校验。

## 验证与证据

- 当前测试使用请求级 fixture/mocks，文件若后续增加应放在 `test/netease_music/`。
- 修改后运行 `make test PYTHON=.venv/bin/python`。
