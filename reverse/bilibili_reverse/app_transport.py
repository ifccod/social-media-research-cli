from __future__ import annotations

import base64
import gzip
import io
import os
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote

from curl_cffi import requests

from .app_wire import _proto_bytes, _proto_varint
from .errors import BilibiliInputError, BilibiliResponseError
from .mobile_profile import (
    MobileProfile,
    _random_alphanumeric,
    validate_mobile_profile,
)

APP_BASE = "https://app.bilibili.com"
APP_USER_AGENT = (
    "Mozilla/5.0 BiliDroid/8.18.0 (bbcallen@gmail.com) "
    "os/android model/Pixel 8 mobi_app/android build/8180300 "
    "channel/master innerVer/8180310 osVer/14 network/2"
)
MAX_GRPC_MESSAGE_SIZE = 16 * 1024 * 1024
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def app_rest_headers(
    profile: MobileProfile,
    user_agent: str = APP_USER_AGENT,
) -> dict[str, str]:
    """返回匿名 Android REST 请求所需的稳定身份头。"""

    validate_mobile_profile(profile)
    normalized_user_agent = _user_agent(user_agent)
    return {
        "accept": "application/json",
        "buvid": profile.buvid,
        "device-id": profile.device_id,
        "user-agent": normalized_user_agent,
    }


def fetch_app_grpc(
    session: requests.Session,
    path: str,
    payload: bytes,
    *,
    profile: MobileProfile,
    user_agent: str = APP_USER_AGENT,
    timeout: float = 20,
    retries: int = 2,
) -> bytes:
    """发送一次 App gRPC unary 请求并返回裸 protobuf 消息。"""

    if not isinstance(path, str) or not path.startswith("/"):
        raise BilibiliInputError("App gRPC path 必须以 / 开头")
    frame = _encode_unary(payload)
    headers = _grpc_headers(profile, user_agent)
    retry_count = max(0, retries)
    last_error: Exception | None = None

    for attempt in range(retry_count + 1):
        try:
            response = session.post(
                f"{APP_BASE}{path}",
                data=frame,
                headers=headers,
                timeout=timeout,
                allow_redirects=False,
            )
        except requests.RequestsError as exc:
            last_error = exc
            if attempt >= retry_count:
                break
            time.sleep(0.35 * (2**attempt))
            continue

        status_code = int(response.status_code)
        if status_code in _RETRYABLE_STATUS:
            last_error = BilibiliResponseError(f"App gRPC HTTP {status_code}")
            if attempt < retry_count:
                time.sleep(0.35 * (2**attempt))
                continue
        return _decode_response(response)

    raise BilibiliResponseError(f"App gRPC 请求失败: {last_error}") from last_error


def _grpc_headers(
    profile: MobileProfile,
    user_agent: str = APP_USER_AGENT,
    random_bytes: Callable[[int], bytes] = os.urandom,
) -> dict[str, str]:
    validate_mobile_profile(profile)
    normalized_user_agent = _user_agent(user_agent)
    trace_raw = random_bytes(16)
    if len(trace_raw) != 16:
        raise BilibiliResponseError("生成 gRPC trace id 时随机源长度错误")
    trace = trace_raw.hex()
    session_id = _random_alphanumeric(8, random_bytes)
    created_at = _parse_created_at(profile.created_at)

    metadata = b"".join(
        (
            _proto_bytes(2, b"android"),
            _proto_bytes(3, b"android"),
            _proto_varint(4, 8180300),
            _proto_bytes(5, b"master"),
            _proto_bytes(6, profile.buvid.encode()),
            _proto_bytes(7, b"android"),
        )
    )
    device = b"".join(
        (
            _proto_varint(1, 1),
            _proto_varint(2, 8180300),
            _proto_bytes(3, profile.buvid.encode()),
            _proto_bytes(4, b"android"),
            _proto_bytes(5, b"android"),
            _proto_bytes(6, b"android"),
            _proto_bytes(7, b"master"),
            _proto_bytes(8, b"Google"),
            _proto_bytes(9, b"Pixel 8"),
            _proto_bytes(10, b"14"),
            _proto_bytes(13, b"8.18.0"),
            _proto_varint(15, _unix_milliseconds(created_at)),
        )
    )
    fawkes = b"".join(
        (
            _proto_bytes(1, b"android"),
            _proto_bytes(2, b"prod"),
            _proto_bytes(3, session_id.encode()),
        )
    )
    locale_ids = b"".join(
        (
            _proto_bytes(1, b"zh"),
            _proto_bytes(2, b"Hans"),
            _proto_bytes(3, b"CN"),
        )
    )
    locale = b"".join(
        (
            _proto_bytes(1, locale_ids),
            _proto_bytes(2, locale_ids),
            _proto_bytes(4, b"Asia/Shanghai"),
        )
    )

    def binary(value: bytes) -> str:
        return base64.b64encode(value).decode()

    return {
        "content-type": "application/grpc",
        "te": "trailers",
        "grpc-encoding": "gzip",
        "grpc-accept-encoding": "gzip,identity",
        "user-agent": (f"{normalized_user_agent} grpc-java-cronet/1.36.1"),
        "x-bili-gaia-vtoken": "",
        "x-bili-aurora-eid": "",
        "x-bili-mid": "0",
        "x-bili-aurora-zone": "",
        "x-bili-trace-id": f"{trace}:{trace[16:]}:0:0",
        "buvid": profile.buvid,
        "bili-http-engine": "cronet",
        "x-bili-fawkes-req-bin": binary(fawkes),
        "x-bili-metadata-bin": binary(metadata),
        "x-bili-device-bin": binary(device),
        "x-bili-network-bin": binary(_proto_varint(1, 1)),
        "x-bili-restriction-bin": "",
        "x-bili-locale-bin": binary(locale),
        "x-bili-exps-bin": "",
    }


def _encode_unary(payload: bytes) -> bytes:
    if not isinstance(payload, bytes):
        raise BilibiliInputError("gRPC 请求消息必须是 bytes")
    if len(payload) > MAX_GRPC_MESSAGE_SIZE:
        raise BilibiliInputError(f"gRPC 请求消息超过上限 {MAX_GRPC_MESSAGE_SIZE}")
    return b"\x00" + len(payload).to_bytes(4, "big") + payload


def _decode_response(response: Any) -> bytes:
    status_code = int(response.status_code)
    if status_code != 200:
        raise BilibiliResponseError(f"App gRPC HTTP {status_code}")

    content_type = _header(response, "content-type").strip().lower()
    if not content_type.startswith("application/grpc"):
        raise BilibiliResponseError(f"App gRPC Content-Type 非法: {content_type!r}")
    status_text = _header(response, "grpc-status", trailers_first=True).strip()
    if not status_text:
        raise BilibiliResponseError("App gRPC 响应缺 grpc-status")
    try:
        grpc_status = int(status_text)
    except ValueError as exc:
        raise BilibiliResponseError(
            f"App gRPC grpc-status 非法: {status_text!r}"
        ) from exc
    if grpc_status != 0:
        message = unquote(_header(response, "grpc-message", trailers_first=True))
        raise BilibiliResponseError(f"App gRPC status {grpc_status}: {message}")

    body = bytes(response.content)
    if not body:
        raise BilibiliResponseError("App gRPC status=0 但响应体为空")
    encoding = _header(
        response,
        "grpc-encoding",
        trailers_first=True,
    )
    return _decode_unary(body, encoding)


def _decode_unary(body: bytes, encoding: str) -> bytes:
    if len(body) < 5:
        raise BilibiliResponseError(f"gRPC 响应帧过短: {len(body)}")
    compressed = body[0]
    if compressed not in (0, 1):
        raise BilibiliResponseError(f"gRPC 非法压缩标记 {compressed}")
    size = int.from_bytes(body[1:5], "big")
    if size > MAX_GRPC_MESSAGE_SIZE:
        raise BilibiliResponseError(
            f"gRPC 响应消息 {size} 超过上限 {MAX_GRPC_MESSAGE_SIZE}"
        )
    if size != len(body) - 5:
        raise BilibiliResponseError(
            f"gRPC 响应帧长度不匹配: 声明 {size}，实际 {len(body) - 5}"
        )

    payload = body[5:]
    if compressed == 0:
        return payload
    if encoding.strip().lower() != "gzip":
        raise BilibiliResponseError(f"gRPC 响应使用压缩帧但 grpc-encoding={encoding!r}")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
            decoded = stream.read(MAX_GRPC_MESSAGE_SIZE + 1)
    except (OSError, EOFError) as exc:
        raise BilibiliResponseError(f"gRPC gzip 响应解压失败: {exc}") from exc
    if len(decoded) > MAX_GRPC_MESSAGE_SIZE:
        raise BilibiliResponseError(f"gRPC 解压响应超过上限 {MAX_GRPC_MESSAGE_SIZE}")
    return decoded


def _header(
    response: Any,
    name: str,
    *,
    trailers_first: bool = False,
) -> str:
    sources: list[Any] = []
    if trailers_first:
        sources.append(getattr(response, "trailers", None))
    sources.append(getattr(response, "headers", None))
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key, value in source.items():
            if str(key).lower() == name.lower() and value is not None:
                return str(value)
    return ""


def _parse_created_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BilibiliInputError("gRPC profile created_at 非法") from exc
    if parsed.tzinfo is None:
        raise BilibiliInputError("gRPC profile created_at 缺少时区")
    return parsed.astimezone(timezone.utc)


def _user_agent(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BilibiliInputError("App user_agent 不能为空")
    return value.strip()


def _unix_milliseconds(value: datetime) -> int:
    delta = value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000
