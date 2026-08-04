# 西瓜视频平台记忆

## 适用范围

本文件约束西瓜视频公开移动数据客户端；测试和夹具位于 `test/xigua/`。

## 当前研究记忆

- video detail、play URL、comments、user、search 和 hot 是不同接口；引用解析先确认视频或用户身份。
- 播放地址、视频 metadata 和页面 HTML 的证据等级不同，归一化时保留来源及媒体类型。

## 已知坑与解决方式

- 加密/编码的播放字段只在完整响应结构和固定向量下解析； malformed payload、外部 URL 和缺失字段必须分类。
- 用户/评论分页 cursor 不前进时停止；数字 ID 以字符串处理，不能丢失精度。
- 搜索和热榜排序是上游顺序或样本排序，不等于统一播放指标。

## 验证与证据

- JSON/HTML 夹具放在 `test/xigua/fixtures/`，覆盖播放、评论、用户和搜索。
- 修改后运行 `make test PYTHON=.venv/bin/python`。
