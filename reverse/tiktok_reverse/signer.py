from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import execjs

from .errors import TikTokSignatureError


class TikTokSigner:
    """通过 PyExecJS 和 Node/V8 运行独立实现的签名逻辑。"""

    def __init__(self, source_path: str | Path | None = None) -> None:
        self.source_path = Path(source_path or Path(__file__).with_name("signature.js"))
        try:
            runtime = execjs.get("Node")
            self._context = runtime.compile(self.source_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise TikTokSignatureError(
                "Node.js and PyExecJS are required to compile signature.js"
            ) from exc
        self._lock = threading.Lock()

    def sign(
        self,
        raw_query: str,
        *,
        user_agent: str,
        ms_token: str,
        body: str = "",
        counters: dict[str, int] | None = None,
        **test_options: Any,
    ) -> dict[str, str]:
        options: dict[str, Any] = {
            "userAgent": user_agent,
            "msToken": ms_token,
            "body": body,
            "counters": counters
            or {"txr": 24, "tfr": 0, "ixr": 28, "ifr": 0, "dynosaurIxr": 4},
            **test_options,
        }
        try:
            with self._lock:
                result = self._context.call("signQuery", raw_query, options)
        except Exception as exc:
            raise TikTokSignatureError(f"signature generation failed: {exc}") from exc
        if not isinstance(result, dict) or not isinstance(result.get("query"), str):
            raise TikTokSignatureError("signature.js returned an invalid result")
        return result

    def call(self, function: str, *args: Any) -> Any:
        """调用本地向量测试使用的确定性辅助函数。"""
        try:
            with self._lock:
                return self._context.call(function, *args)
        except Exception as exc:
            raise TikTokSignatureError(f"signature helper {function} failed: {exc}") from exc

    def encode_telemetry(self, payload: Mapping[str, Any]) -> str:
        raw_json = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        result = self.call("encodeTelemetry", raw_json)
        if not isinstance(result, str) or not result:
            raise TikTokSignatureError("signature.js returned invalid telemetry data")
        return result
