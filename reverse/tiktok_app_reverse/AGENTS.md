# TikTok App 研究记忆

## 适用范围

本目录保存 TikTok App 版本绑定的 Hook 和移动协议证据；Python 单元测试位于 `test/tiktok/`，本目录不是 Web CLI。

## 当前研究记忆

- `frida_hooks/` 只记录安装态 native 调用、移动身份和请求链，必须绑定 App 版本、ABI 和样本来源。
- Web 签名、Chrome 会话和 App 身份是三个边界，不能因为字段名称相似而合并。

## 已知坑与解决方式

- 单个版本的 native trace 不能直接视为稳定协议；先保留原始 trace，再通过重复安装态样本验证。
- 不要把 Hook 脚本当作运行时接口或从中导出用户 Cookie；研究资产与公开 Web 客户端分开维护。

## 验证与证据

- 更新探针时保留版本说明和旧证据，真实安装态验证完成后再迁入独立 App 实现。
- 运行 `make test PYTHON=.venv/bin/python` 验证 Web 客户端，不以 Web fixture 替代 App 证据。
