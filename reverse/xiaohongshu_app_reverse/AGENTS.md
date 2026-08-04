# 小红书 App 研究记忆

## 适用范围

本目录保存小红书 App 版本绑定的 native Hook 资产；Python 单元测试位于 `test/xiaohongshu/`，本目录不是 Web 客户端。

## 当前研究记忆

- `frida_hooks/` 中的 shield、注册 native 和身份观测用于研究安装态协议，必须保留版本、ABI、调用栈和原始样本。
- App 身份、Web Cookie、页面签名和浏览器桥是互相独立的状态，不得合并成一个通用会话。

## 已知坑与解决方式

- 反调试或 shield 观测结果只说明某个样本的运行时行为，不能直接当成跨版本接口；先做重复安装态验证。
- 未完成协议提纯前只维护研究资产，不在 Web CLI 中伪造 App 响应或复用 Hook 生成的凭据。

## 验证与证据

- 更新探针时保留旧脚本和版本说明，完成真实安装态闭环后再放入独立 App 上下文。
- Web 能力运行 `make test PYTHON=.venv/bin/python`；它不替代 App 证据验证。
