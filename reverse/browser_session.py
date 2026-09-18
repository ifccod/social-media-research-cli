"""兼容扩展 wire protocol v4 的本地浏览器会话桥。

浏览器负责 Cookie 与页面侧签名，本模块只负责回环传输、扩展注册、配置选择和
RPC 排序；不会创建、导航或等待平台标签页。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from collections.abc import Awaitable, Callable
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed, WebSocketException

from .browser_progress import stderr_progress


BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 18765
PROTOCOL_VERSION = 4
MAX_WIRE_BYTES = 7 * 1024 * 1024
CONTROL_PATH = "/control"
HELLO_TIMEOUT = 10
CONTROL_TIMEOUT = 90
CONTROL_REQUEST_TIMEOUT = 60
RPC_CANCELLATION_GRACE = 1.5
RPC_TRANSPORT_MARGIN = 3.5
LOGIN_RUNTIME_TIMEOUT = 20
READY_ROUTE_TTL = 600
# 同一 browser_instance_id 的新连接接管时，旧扩展据此停止自动重连。
INSTANCE_SUPERSEDED_CLOSE_CODE = 4009
INSTANCE_SUPERSEDED_CLOSE_REASON = "浏览器实例已由新连接接管"
PLATFORMS = frozenset(
    {
        "bilibili",
        "douyin",
        "douyin_index",
        "linkedin",
        "reddit",
        "tiktok_ads_manager",
        "tiktok_creative",
        "tiktok_creative_studio",
        "tiktok_creative_topads",
        "tiktok_one",
        "twitter_home",
        "twitter_search",
        "xiaohongshu",
        "xiaohongshu_app_v2",
        "xiaohongshu_pgy",
    }
)
FAMILIES = {
    "douyin_index": "douyin",
    "tiktok_ads_manager": "tiktok",
    "tiktok_creative": "tiktok",
    "tiktok_creative_studio": "tiktok",
    "tiktok_creative_topads": "tiktok",
    "tiktok_one": "tiktok",
    "twitter_home": "twitter",
    "twitter_search": "twitter",
    "xiaohongshu_app_v2": "xiaohongshu",
    "xiaohongshu_pgy": "xiaohongshu",
}
PLATFORM_LABELS = {
    "bilibili": "Bilibili",
    "douyin": "抖音",
    "douyin_index": "抖音指数",
    "linkedin": "LinkedIn",
    "reddit": "Reddit",
    "tiktok_ads_manager": "TikTok Ads Manager",
    "tiktok_creative": "TikTok Creative Center",
    "tiktok_creative_studio": "TikTok Creative Studio",
    "tiktok_creative_topads": "TikTok Top Ads",
    "tiktok_one": "TikTok One",
    "twitter_home": "X 推荐流",
    "twitter_search": "X 主动搜索",
    "xiaohongshu": "小红书",
    "xiaohongshu_app_v2": "小红书 App v2",
    "xiaohongshu_pgy": "小红书蒲公英",
}
PLATFORM_LOGIN_URLS = {
    "bilibili": "https://www.bilibili.com/",
    "douyin": "https://www.douyin.com/",
    "douyin_index": (
        "https://creator.douyin.com/creator-micro/creator-count/arithmetic-index"
    ),
    "linkedin": "https://www.linkedin.com/",
    "reddit": "https://www.reddit.com/",
    "tiktok_ads_manager": (
        "https://ads.tiktok.com/i18n/search_ads_center/keyword-planner/creation"
    ),
    "tiktok_creative": (
        "https://ads.tiktok.com/creative/creativeCenter/trends/hashtag"
        "?region=US&period=7"
    ),
    "tiktok_creative_studio": (
        "https://ads.tiktok.com/creative/creativestudio/create"
        "?from_creative=signup&region=row"
    ),
    "tiktok_creative_topads": (
        "https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en"
    ),
    "tiktok_one": (
        "https://ads.tiktok.com/creative/forpartners/creator/explore?region=row"
    ),
    "twitter_home": "https://x.com/home",
    "twitter_search": (
        "https://x.com/search?q=social%20research&src=typed_query&f=top"
    ),
    "xiaohongshu": "https://www.xiaohongshu.com/explore",
    "xiaohongshu_app_v2": "https://www.xiaohongshu.com/explore",
    "xiaohongshu_pgy": "https://pgy.xiaohongshu.com/",
}
INTERACTIVE_LOGIN_ERRORS = frozenset(
    {
        "advertiser_account_required",
        "extension_disconnected",
        "not_logged_in",
        "profile_required",
        "runtime_unavailable",
        "tab_unavailable",
        "verification_required",
    }
)
REFERER_HOSTS = {
    "bilibili": (".bilibili.com",),
    "douyin": (".douyin.com",),
    "douyin_index": (".douyin.com",),
    "linkedin": (".linkedin.com",),
    "reddit": (".reddit.com",),
    "tiktok_ads_manager": (".tiktok.com",),
    "tiktok_creative": (".tiktok.com",),
    "tiktok_creative_studio": (".tiktok.com",),
    "tiktok_creative_topads": (".tiktok.com",),
    "tiktok_one": (".tiktok.com",),
    "twitter_home": (".x.com", ".twitter.com"),
    "twitter_search": (".x.com", ".twitter.com"),
    "xiaohongshu": (".xiaohongshu.com",),
    "xiaohongshu_app_v2": (".xiaohongshu.com",),
    "xiaohongshu_pgy": (".xiaohongshu.com",),
}
EXTENSION_ID = re.compile(r"^[a-z0-9]{1,64}$")
BROWSER_INSTANCE_ID = re.compile(r"^[a-f0-9]{32}$")
REQUEST_ID = re.compile(r"^[a-f0-9]{32}$")
PARAMETER_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
ERROR_CODES = frozenset(
    {
        "extension_request_failed",
        "advertiser_account_required",
        "csrf_or_signature_expired",
        "forbidden",
        "invalid_request",
        "invalid_response",
        "keyword_invalid",
        "keyword_not_allowed",
        "no_douyin_tab",
        "not_logged_in",
        "profile_required",
        "rate_limited",
        "request_failed",
        "response_too_large",
        "runtime_unavailable",
        "tab_unavailable",
        "timeout",
        "transport_modules_changed",
        "verification_required",
    }
)

_LOCAL_LOCKS: dict[str, threading.Lock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()
ProgressSink = Callable[[dict[str, Any]], Awaitable[None]]
ProgressCallback = Callable[[dict[str, Any]], None]


class BrowserSessionError(RuntimeError):
    """边界明确的桥接或扩展错误。"""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def session_home() -> Path:
    configured = os.environ.get("BROWSER_SESSION_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "tiktok_reverse" / "browser-session"


def _family(platform: str) -> str:
    return FAMILIES.get(platform, platform)


def _rpc_timeout(platform: str, kind: str) -> float:
    if kind == "request":
        extension_timeout = 45 if platform == "xiaohongshu_pgy" else 35
    elif kind == "session" and platform == "xiaohongshu_pgy":
        extension_timeout = 20
    else:
        extension_timeout = 15
    return extension_timeout + RPC_CANCELLATION_GRACE + RPC_TRANSPORT_MARGIN


def _control_timeout(request: dict[str, Any]) -> float:
    return CONTROL_REQUEST_TIMEOUT if request.get("op") == "request" else CONTROL_TIMEOUT


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    info = path.lstat()
    owned = not hasattr(os, "getuid") or info.st_uid == os.getuid()
    if not stat.S_ISDIR(info.st_mode) or not owned:
        raise PermissionError(f"unsafe browser-session directory: {path}")
    os.chmod(path, 0o700)


def _set_private_file_mode(descriptor: int) -> None:
    info = os.fstat(descriptor)
    owned = not hasattr(os, "getuid") or info.st_uid == os.getuid()
    if not stat.S_ISREG(info.st_mode) or not owned:
        raise PermissionError("unsafe browser-session file")
    if hasattr(os, "fchmod"):
        os.fchmod(descriptor, 0o600)


def _open_private(path: Path, flags: int, *, create: bool = False) -> int:
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if create:
        flags |= os.O_CREAT
    descriptor = os.open(path, flags, 0o600)
    try:
        _set_private_file_mode(descriptor)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _read_private(path: Path, limit: int) -> str:
    descriptor = _open_private(path, os.O_RDONLY)
    with os.fdopen(descriptor, "r", encoding="utf-8") as source:
        return source.read(limit + 1)


def _write_private(path: Path, value: str) -> None:
    _ensure_private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        _set_private_file_mode(descriptor)
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            descriptor = -1
            target.write(value)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory = os.open(path.parent, directory_flags)
        try:
            with suppress(OSError):
                os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _lock_descriptor(descriptor: int) -> None:
    if os.name != "nt":
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return
    if os.fstat(descriptor).st_size == 0:
        os.write(descriptor, b"\0")
        os.fsync(descriptor)
    while True:
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            time.sleep(0.05)


def _unlock_descriptor(descriptor: int) -> None:
    if os.name != "nt":
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return
    os.lseek(descriptor, 0, os.SEEK_SET)
    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)


@contextmanager
def _exclusive_lock(path: Path):
    _ensure_private_directory(path.parent)
    key = str(path.resolve())
    with _LOCAL_LOCKS_GUARD:
        local_lock = _LOCAL_LOCKS.setdefault(key, threading.Lock())
    with local_lock:
        descriptor = _open_private(path, os.O_RDWR, create=True)
        try:
            _lock_descriptor(descriptor)
            yield
        finally:
            with suppress(OSError):
                _unlock_descriptor(descriptor)
            os.close(descriptor)


def _startup_lock_path() -> Path:
    return (
        Path.home()
        / ".local"
        / "share"
        / "tiktok_reverse"
        / "browser-session-locks"
        / f"fixed-port-{BRIDGE_PORT}.lock"
    )


def _control_token(home: Path) -> str:
    path = home / "control.token"
    try:
        _ensure_private_directory(home)
        with _exclusive_lock(home / ".control.lock"):
            try:
                value = _read_private(path, 256).strip()
            except FileNotFoundError:
                value = ""
            if 32 <= len(value) <= 256 and "\n" not in value and "\0" not in value:
                return value
            value = secrets.token_urlsafe(32)
            _write_private(path, value + "\n")
            return value
    except (OSError, UnicodeError) as exc:
        raise BrowserSessionError(
            "invalid_control_token",
            f"invalid browser-session control token: {exc}",
        ) from exc


def _empty_registry() -> dict[str, Any]:
    return {"schema_version": 2, "instances": {}, "platform_bindings": {}}


def _read_registry(home: Path) -> dict[str, Any]:
    path = home / "bridge.json"
    try:
        with _exclusive_lock(home / ".registry.lock"):
            source = _read_private(path, MAX_WIRE_BYTES)
    except FileNotFoundError:
        return _empty_registry()
    except (OSError, UnicodeError) as exc:
        raise BrowserSessionError("invalid_registry", f"invalid bridge registry: {exc}") from exc
    if len(source) > MAX_WIRE_BYTES:
        raise BrowserSessionError("invalid_registry", "bridge registry exceeds size limit")
    try:
        value = json.loads(source)
    except json.JSONDecodeError as exc:
        raise BrowserSessionError("invalid_registry", f"invalid bridge registry: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 2:
        return _empty_registry()
    instances = value.get("instances")
    bindings = value.get("platform_bindings")
    if not isinstance(instances, dict) or not isinstance(bindings, dict):
        raise BrowserSessionError("invalid_registry")
    for instance_id, registration in instances.items():
        if (
            not isinstance(instance_id, str)
            or not BROWSER_INSTANCE_ID.fullmatch(instance_id)
            or not isinstance(registration, dict)
            or not EXTENSION_ID.fullmatch(str(registration.get("extension_id", "")))
            or not re.fullmatch(r"[a-f0-9]{64}", str(registration.get("token_sha256", "")))
        ):
            raise BrowserSessionError("invalid_registry")
    for family, instance_id in bindings.items():
        if (
            family not in {_family(platform) for platform in PLATFORMS}
            or instance_id not in instances
        ):
            raise BrowserSessionError("invalid_registry")
    return value


def _write_registry(home: Path, registry: dict[str, Any]) -> None:
    with _exclusive_lock(home / ".registry.lock"):
        _write_private(
            home / "bridge.json",
            json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )


def _extension_id(origin: str | None) -> str | None:
    if not origin:
        return None
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "chrome-extension"
        or parsed.username
        or parsed.password
        or parsed.port
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    value = parsed.hostname or ""
    return value if EXTENSION_ID.fullmatch(value) else None


def _validate_platform(value: Any) -> str:
    if not isinstance(value, str) or value not in PLATFORMS:
        raise BrowserSessionError("invalid_request", "unsupported browser platform")
    return value


def _validate_platform_url(platform: str, value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise BrowserSessionError("invalid_request", "invalid browser login URL")
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").lower()
    allowed = REFERER_HOSTS[platform]
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.fragment
        or not any(
            hostname == suffix[1:] or hostname.endswith(suffix)
            for suffix in allowed
        )
    ):
        raise BrowserSessionError("invalid_request", "invalid browser login URL")
    return value


def _normalize_request(value: dict[str, Any]) -> dict[str, Any]:
    platform = _validate_platform(value.get("platform"))
    path = value.get("path")
    referer = value.get("referer", "")
    method = str(value.get("method", "GET")).upper()
    interval = value.get("request_interval_ms", 0)
    entries = value.get("entries", [])
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or path.startswith("//")
        or len(path) > 512
        or any(character in path for character in "\r\n\0")
        or method not in {"GET", "POST"}
        or not isinstance(interval, int)
        or not 0 <= interval <= 10_000
        or not isinstance(entries, list)
        or len(entries) > 32
    ):
        raise BrowserSessionError("invalid_request")
    normalized_entries: list[list[str]] = []
    for entry in entries:
        large_studio_image = (
            platform == "tiktok_creative_studio"
            and path == "/creative_bff_i18n/api/cue/upload/local-image"
            and isinstance(entry, list)
            and len(entry) == 2
            and entry[0] == "dataBase64"
            and isinstance(entry[1], str)
            and len(entry[1]) <= MAX_WIRE_BYTES
            and re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", entry[1])
            is not None
        )
        large_twitter_image = (
            platform == "twitter_home"
            and path == "/bridge/v1/twitter/upload-media"
            and isinstance(entry, list)
            and len(entry) == 2
            and entry[0] == "dataBase64"
            and isinstance(entry[1], str)
            and len(entry[1]) <= MAX_WIRE_BYTES
            and re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", entry[1])
            is not None
        )
        long_twitter_text = (
            platform == "twitter_home"
            and path == "/bridge/v1/twitter/create-scheduled-tweet"
            and isinstance(entry, list)
            and len(entry) == 2
            and entry[0] == "text"
            and isinstance(entry[1], str)
            and len(entry[1]) <= 25000
        )
        forbidden_controls = "\r\0" if long_twitter_text else "\r\n\0"
        if (
            not isinstance(entry, list)
            or len(entry) != 2
            or not isinstance(entry[0], str)
            or not PARAMETER_NAME.fullmatch(entry[0])
            or not isinstance(entry[1], str)
            or (
                len(entry[1]) > 4096
                and not large_studio_image
                and not large_twitter_image
                and not long_twitter_text
            )
            or any(character in entry[1] for character in forbidden_controls)
        ):
            raise BrowserSessionError("invalid_request")
        normalized_entries.append(entry)
    if not isinstance(referer, str) or len(referer) > 2048:
        raise BrowserSessionError("invalid_request")
    if referer:
        _validate_platform_url(platform, referer)
    result = {
        "platform": platform,
        "path": path,
        "entries": normalized_entries,
        "referer": referer,
        "request_interval_ms": interval,
    }
    if platform.startswith("xiaohongshu"):
        result["method"] = method
    elif method != "GET":
        raise BrowserSessionError(
            "invalid_request",
            "POST is supported only by Xiaohongshu browser scopes",
        )
    return result


def _wire_object(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise BrowserSessionError("invalid_request")
    message = json.loads(raw)
    if not isinstance(message, dict):
        raise BrowserSessionError("invalid_request")
    return message


@dataclass(eq=False)
class _Extension:
    websocket: ServerConnection
    extension_id: str
    instance_id: str = ""
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_seen: float = field(default_factory=time.monotonic)

    async def send(self, value: dict[str, Any]) -> None:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_WIRE_BYTES:
            raise BrowserSessionError("response_too_large")
        async with self.send_lock:
            await self.websocket.send(encoded)


class BridgeDaemon:
    """负责扩展注册和浏览器 RPC 排序的应用服务。"""

    def __init__(self, home: Path | None = None, port: int = BRIDGE_PORT) -> None:
        self.home = home or session_home()
        self.port = port
        self.control_token = _control_token(self.home)
        self.registry = _read_registry(self.home)
        self.connections: dict[str, _Extension] = {}
        self.pending: dict[str, tuple[_Extension, str, asyncio.Future[Any]]] = {}
        self.family_locks: dict[str, asyncio.Lock] = {}
        self.last_request_at: dict[tuple[str, str], float] = {}
        self.ready_routes: dict[str, tuple[str, float]] = {}
        self.connection_event = asyncio.Event()
        self.stop_event = asyncio.Event()
        self.server: Any = None

    async def start(self) -> int:
        self.server = await serve(
            self._handle_connection,
            BRIDGE_HOST,
            self.port,
            process_request=self._process_request,
            compression=None,
            max_size=MAX_WIRE_BYTES,
            ping_interval=20,
            ping_timeout=20,
        )
        sockets = self.server.sockets
        if not sockets:
            raise BrowserSessionError("bridge_start_failed")
        self.port = int(sockets[0].getsockname()[1])
        _write_private(self.home / "daemon.pid", f"{os.getpid()}\n")
        return self.port

    async def close(self) -> None:
        for extension in list(self.connections.values()):
            await extension.websocket.close(code=1001, reason="bridge shutdown")
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        try:
            (self.home / "daemon.pid").unlink()
        except FileNotFoundError:
            pass

    def _process_request(self, connection: ServerConnection, request: Any) -> Any:
        remote = connection.remote_address
        if not remote or remote[0] != BRIDGE_HOST:
            return connection.respond(403, "Forbidden\n")
        path = request.path.split("?", 1)[0]
        origin = request.headers.get("Origin")
        if path == CONTROL_PATH:
            return None if origin is None else connection.respond(403, "Forbidden\n")
        if path != "/" or _extension_id(origin) is None:
            return connection.respond(403, "Forbidden\n")
        return None

    async def _handle_connection(self, websocket: ServerConnection) -> None:
        if websocket.request.path.split("?", 1)[0] == CONTROL_PATH:
            await self._handle_control(websocket)
            return
        extension = _Extension(
            websocket=websocket,
            extension_id=_extension_id(websocket.request.headers.get("Origin")) or "",
        )
        try:
            first = _wire_object(
                await asyncio.wait_for(websocket.recv(), HELLO_TIMEOUT)
            )
            if first.get("type") != "hello":
                raise BrowserSessionError("invalid_request")
            await self._hello(extension, first)
            async for raw in websocket:
                message = _wire_object(raw)
                kind = message.get("type")
                if kind == "hello":
                    await self._hello(extension, message)
                elif kind == "response" and self._is_current(extension):
                    self._response(extension, message)
                else:
                    raise BrowserSessionError("invalid_request")
        except (
            ConnectionClosed,
            TimeoutError,
            json.JSONDecodeError,
            BrowserSessionError,
        ):
            pass
        finally:
            await self._disconnect(extension)

    async def _hello(self, extension: _Extension, message: dict[str, Any]) -> None:
        if message.get("protocol") != PROTOCOL_VERSION:
            await extension.send(
                {"type": "error", "code": "protocol_mismatch", "protocol": PROTOCOL_VERSION}
            )
            raise BrowserSessionError("protocol_mismatch")
        instance_id = message.get("browser_instance_id")
        if not isinstance(instance_id, str) or not BROWSER_INSTANCE_ID.fullmatch(instance_id):
            await extension.send({"type": "error", "code": "invalid_request"})
            raise BrowserSessionError("invalid_request")
        if extension.instance_id and extension.instance_id != instance_id:
            raise BrowserSessionError("invalid_request")
        extension.instance_id = instance_id
        extension.last_seen = time.monotonic()
        registration = self.registry["instances"].get(instance_id, {})
        token = message.get("token")
        authenticated = (
            isinstance(token, str)
            and registration.get("extension_id") == extension.extension_id
            and hmac.compare_digest(
                str(registration.get("token_sha256", "")),
                hashlib.sha256(token.encode()).hexdigest(),
            )
        )
        response: dict[str, Any] = {
            "type": "ready",
            "protocol": PROTOCOL_VERSION,
            "browser_instance_id": instance_id,
        }
        if not authenticated:
            token = secrets.token_urlsafe(32)
            self.registry["instances"][instance_id] = {
                "extension_id": extension.extension_id,
                "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            }
            _write_registry(self.home, self.registry)
            response["token"] = token
        await extension.send(response)
        previous = self.connections.get(instance_id)
        self.connections[instance_id] = extension
        self.connection_event.set()
        if previous is not None and previous is not extension:
            await previous.websocket.close(
                code=INSTANCE_SUPERSEDED_CLOSE_CODE,
                reason=INSTANCE_SUPERSEDED_CLOSE_REASON,
            )

    def _is_current(self, extension: _Extension) -> bool:
        return bool(
            extension.instance_id
            and self.connections.get(extension.instance_id) is extension
        )

    def _response(self, extension: _Extension, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
            return
        pending = self.pending.pop(request_id, None)
        if pending is None:
            return
        wanted_extension, platform, future = pending
        if future.done():
            return
        if wanted_extension is not extension or message.get("platform") != platform:
            future.set_exception(BrowserSessionError("invalid_response"))
            return
        if "payload" in message and message.get("error") is None:
            payload = message["payload"]
            if isinstance(payload, dict):
                future.set_result(payload)
            else:
                future.set_exception(BrowserSessionError("invalid_response"))
            return
        code = message.get("error")
        future.set_exception(
            BrowserSessionError(
                code
                if isinstance(code, str) and code in ERROR_CODES
                else "request_failed"
            )
        )

    async def _disconnect(self, extension: _Extension) -> None:
        if self._is_current(extension):
            self.connections.pop(extension.instance_id, None)
            if not self.connections:
                self.connection_event.clear()
        self.ready_routes = {
            platform: route
            for platform, route in self.ready_routes.items()
            if route[0] != extension.instance_id
        }
        for request_id, pending in list(self.pending.items()):
            if pending[0] is extension:
                self.pending.pop(request_id, None)
                if not pending[2].done():
                    pending[2].set_exception(BrowserSessionError("extension_disconnected"))

    def _take_pending(
        self,
        request_id: str,
        future: asyncio.Future[Any],
    ) -> bool:
        pending = self.pending.get(request_id)
        if pending is None or pending[2] is not future:
            return False
        self.pending.pop(request_id)
        return True

    async def _send_cancel(
        self,
        extension: _Extension,
        request_id: str,
        platform: str,
    ) -> None:
        try:
            await extension.send(
                {"type": "cancel", "id": request_id, "platform": platform}
            )
        except (ConnectionClosed, OSError, RuntimeError):
            pass

    async def _rpc(
        self,
        extension: _Extension,
        kind: str,
        platform: str,
        values: dict[str, Any] | None = None,
    ) -> Any:
        if not self._is_current(extension):
            raise BrowserSessionError("extension_disconnected")
        request_id = secrets.token_hex(16)
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = (extension, platform, future)
        message = {"type": kind, "id": request_id, "platform": platform}
        message.update(values or {})
        try:
            await extension.send(message)
            return await asyncio.wait_for(
                asyncio.shield(future),
                _rpc_timeout(platform, kind),
            )
        except TimeoutError as exc:
            if not self._take_pending(request_id, future):
                return await future
            future.cancel()
            await self._send_cancel(extension, request_id, platform)
            raise BrowserSessionError("timeout") from exc
        except asyncio.CancelledError:
            if self._take_pending(request_id, future):
                future.cancel()
                await self._send_cancel(extension, request_id, platform)
            raise
        finally:
            if self._take_pending(request_id, future) and not future.done():
                future.cancel()

    async def _select(
        self,
        platform: str,
        require_ready: bool,
        session_values: dict[str, Any] | None = None,
    ) -> _Extension:
        family = _family(platform)
        bound = self.registry["platform_bindings"].get(family)
        ordered = list(self.connections.values())
        if bound in self.connections:
            ordered.remove(self.connections[bound])
            ordered.insert(0, self.connections[bound])
        if not ordered:
            raise BrowserSessionError("extension_disconnected")
        if require_ready:
            # 带页面上下文的探测必须重新确认同一个 Chrome 实例中存在匹配标签页。
            # 否则 Top Ads 的 V2 页面会错误地掩盖 Library 页面缺失。
            if session_values is None:
                cached = self._cached_ready_route(platform)
                if cached is not None:
                    return cached
            snapshots = await asyncio.gather(
                *(
                    self._rpc(
                        extension,
                        "session",
                        platform,
                        session_values,
                    )
                    for extension in ordered
                ),
                return_exceptions=True,
            )
            for extension, snapshot in zip(ordered, snapshots, strict=True):
                if isinstance(snapshot, dict) and (
                    snapshot.get("request_ready") is True
                    or (
                        "request_ready" not in snapshot
                        and snapshot.get("logged_in") is True
                    )
                ):
                    self._bind_family(family, extension.instance_id)
                    self._remember_ready_route(platform, extension)
                    return extension
            error_codes = {
                snapshot.code
                for snapshot in snapshots
                if isinstance(snapshot, BrowserSessionError)
            }
            if any(
                isinstance(snapshot, dict)
                and snapshot.get("verification_required") is True
                for snapshot in snapshots
            ):
                error_codes.add("verification_required")
            if any(
                isinstance(snapshot, dict)
                and snapshot.get("profile_required") is True
                for snapshot in snapshots
            ):
                error_codes.add("profile_required")
            if any(
                isinstance(snapshot, dict)
                and snapshot.get("logged_in") is True
                and snapshot.get("request_ready") is False
                for snapshot in snapshots
            ):
                error_codes.add("runtime_unavailable")
            for code in (
                "verification_required",
                "profile_required",
                "advertiser_account_required",
                "runtime_unavailable",
            ):
                if code in error_codes:
                    raise BrowserSessionError(code)
            if snapshots and all(
                isinstance(snapshot, BrowserSessionError)
                and snapshot.code == "tab_unavailable"
                for snapshot in snapshots
            ):
                raise BrowserSessionError("tab_unavailable")
            raise BrowserSessionError("not_logged_in")
        extension = ordered[0]
        self._bind_family(family, extension.instance_id)
        return extension

    def _cached_ready_route(self, platform: str) -> _Extension | None:
        route = self.ready_routes.get(platform)
        if route is None:
            return None
        instance_id, expires_at = route
        extension = self.connections.get(instance_id)
        if extension is None or expires_at <= time.monotonic():
            self.ready_routes.pop(platform, None)
            return None
        return extension

    def _remember_ready_route(
        self,
        platform: str,
        extension: _Extension,
    ) -> None:
        self.ready_routes[platform] = (
            extension.instance_id,
            time.monotonic() + READY_ROUTE_TTL,
        )

    def _forget_ready_route(self, platform: str) -> None:
        self.ready_routes.pop(platform, None)

    def _bind_family(self, family: str, instance_id: str) -> None:
        if self.registry["platform_bindings"].get(family) == instance_id:
            return
        self.registry["platform_bindings"][family] = instance_id
        _write_registry(self.home, self.registry)

    async def _status(
        self,
        platform: str | None = None,
        *,
        url: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "running": True,
            "bridge_url": f"ws://{BRIDGE_HOST}:{self.port}",
            "protocol_version": PROTOCOL_VERSION,
            "connection_count": len(self.connections),
            "ready": bool(self.connections),
        }
        if platform:
            platform = _validate_platform(platform)
            target = _validate_platform_url(platform, url) if url else None
            session_values = {"referer": target} if target else None
            result["platform"] = platform
            if target:
                result["url"] = target
            cached = self._cached_ready_route(platform)
            result["request_route_cached"] = cached is not None
            if cached is not None:
                route = self.ready_routes[platform]
                result["request_route_ttl_ms"] = max(
                    0,
                    round((route[1] - time.monotonic()) * 1000),
                )
            try:
                extension = await self._select(platform, False)
                snapshot = await self._rpc(
                    extension,
                    "session",
                    platform,
                    session_values,
                )
                result["browser_instance_id"] = extension.instance_id
                result["session"] = snapshot
            except BrowserSessionError as exc:
                result["ready"] = False
                result["error"] = exc.code
        return result

    async def _pace(self, extension: _Extension, platform: str, interval_ms: int) -> None:
        key = (extension.instance_id, _family(platform))
        remaining = interval_ms / 1000 - (time.monotonic() - self.last_request_at.get(key, 0))
        if remaining > 0:
            await asyncio.sleep(remaining)
        self.last_request_at[key] = time.monotonic()

    @staticmethod
    async def _progress(
        sink: ProgressSink | None,
        stage: str,
        label: str,
        message: str,
        **details: Any,
    ) -> None:
        if sink is None:
            return
        await sink(
            {
                "event": "progress",
                "stage": stage,
                "label": label,
                "message": message,
                **details,
            }
        )

    async def _dispatch_control(
        self,
        request: dict[str, Any],
        progress: ProgressSink | None = None,
    ) -> Any:
        operation = request.get("op")
        if operation == "ping":
            return await self._status()
        if operation == "status":
            platform = request.get("platform")
            if platform is None:
                if request.get("url") is not None:
                    raise BrowserSessionError("invalid_request")
                return await self._status()
            platform = _validate_platform(platform)
            url = request.get("url")
            if url is not None:
                url = _validate_platform_url(platform, url)
            lock = self.family_locks.setdefault(_family(platform), asyncio.Lock())
            async with lock:
                if url is None:
                    return await self._status(platform)
                return await self._status(platform, url=url)
        if operation == "shutdown":
            return {"stopping": True}
        if operation != "request":
            raise BrowserSessionError("invalid_request")
        platform = _validate_platform(request.get("platform"))
        platform_label = PLATFORM_LABELS[platform]
        lock = self.family_locks.setdefault(_family(platform), asyncio.Lock())
        async with lock:
            normalized = _normalize_request(request)
            await self._progress(
                progress,
                "session",
                "会话",
                f"正在探测 {platform_label} 登录态",
                platform=platform,
            )
            session_values = (
                {"referer": normalized["referer"]}
                if normalized["referer"]
                else None
            )
            extension = await self._select(
                platform,
                True,
                session_values,
            )
            await self._progress(
                progress,
                "session",
                "会话",
                f"{platform_label} 会话可用，复用现有页面",
                platform=platform,
                ready=True,
            )
            await self._pace(extension, platform, normalized["request_interval_ms"])
            values = {key: value for key, value in normalized.items() if key != "platform"}
            await self._progress(
                progress,
                "request",
                "请求",
                f"正在读取 {platform_label} 数据",
                platform=platform,
            )
            try:
                result = await self._rpc(extension, "request", platform, values)
            except BrowserSessionError as exc:
                if exc.code in INTERACTIVE_LOGIN_ERRORS or exc.code in {
                    "advertiser_account_required",
                    "csrf_or_signature_expired",
                    "transport_modules_changed",
                }:
                    self._forget_ready_route(platform)
                raise
            self._remember_ready_route(platform, extension)
            await self._progress(
                progress,
                "complete",
                "完成",
                f"{platform_label} 数据读取完成",
                platform=platform,
            )
            return result

    async def _handle_control(self, websocket: ServerConnection) -> None:
        shutdown = False
        dispatch_task: asyncio.Task[Any] | None = None
        closed_task: asyncio.Task[Any] | None = None
        try:
            raw = await asyncio.wait_for(websocket.recv(), 5)
            if not isinstance(raw, str):
                raise BrowserSessionError("invalid_request")
            request = json.loads(raw)
            if (
                not isinstance(request, dict)
                or not hmac.compare_digest(str(request.pop("token", "")), self.control_token)
            ):
                raise BrowserSessionError("authentication_rejected")
            async def send_progress(event: dict[str, Any]) -> None:
                await websocket.send(
                    json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                )

            dispatch_task = asyncio.create_task(
                self._dispatch_control(request, send_progress)
            )
            closed_task = asyncio.create_task(websocket.wait_closed())
            done, _ = await asyncio.wait(
                (dispatch_task, closed_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if dispatch_task not in done:
                dispatch_task.cancel()
                await asyncio.gather(dispatch_task, return_exceptions=True)
                return
            result = dispatch_task.result()
            shutdown = request.get("op") == "shutdown"
            response = {"ok": True, "result": result}
        except (ConnectionClosed, TimeoutError, json.JSONDecodeError):
            return
        except BrowserSessionError as exc:
            response = {"ok": False, "error": exc.code, "message": str(exc)}
        finally:
            for task in (closed_task, dispatch_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (closed_task, dispatch_task) if task is not None),
                return_exceptions=True,
            )
        try:
            await websocket.send(
                json.dumps(response, ensure_ascii=False, separators=(",", ":"))
            )
        except ConnectionClosed:
            return
        if shutdown:
            self.stop_event.set()

    async def run(self) -> None:
        await self.start()
        loop = asyncio.get_running_loop()
        for name in ("SIGINT", "SIGTERM"):
            if hasattr(signal, name):
                try:
                    loop.add_signal_handler(getattr(signal, name), self.stop_event.set)
                except NotImplementedError:
                    pass
        try:
            await self.stop_event.wait()
        finally:
            await self.close()


async def call_daemon(
    request: dict[str, Any],
    timeout: float | None = None,
    progress: ProgressCallback | None = None,
) -> Any:
    token = _control_token(session_home())
    timeout = _control_timeout(request) if timeout is None else timeout
    try:
        async with connect(
            f"ws://{BRIDGE_HOST}:{BRIDGE_PORT}{CONTROL_PATH}",
            compression=None,
            max_size=MAX_WIRE_BYTES,
            open_timeout=1,
        ) as websocket:
            await websocket.send(
                json.dumps({"token": token, **request}, ensure_ascii=False, separators=(",", ":"))
            )
            async with asyncio.timeout(timeout):
                while True:
                    response = json.loads(await websocket.recv())
                    if (
                        isinstance(response, dict)
                        and response.get("event") == "progress"
                    ):
                        if progress is not None:
                            progress(response)
                        continue
                    break
    except TimeoutError as exc:
        raise BrowserSessionError("timeout") from exc
    except json.JSONDecodeError as exc:
        raise BrowserSessionError("invalid_response") from exc
    except (OSError, WebSocketException) as exc:
        raise BrowserSessionError("daemon_unavailable") from exc
    if not isinstance(response, dict) or response.get("ok") is not True:
        code = (
            response.get("error", "request_failed")
            if isinstance(response, dict)
            else "invalid_response"
        )
        message = response.get("message") if isinstance(response, dict) else None
        raise BrowserSessionError(str(code), message)
    return response.get("result")


def start_daemon() -> None:
    try:
        with _exclusive_lock(_startup_lock_path()):
            _start_daemon_locked()
    except BrowserSessionError:
        raise
    except OSError as exc:
        raise BrowserSessionError(
            "daemon_start_failed",
            f"browser-session daemon startup lock failed: {exc}",
        ) from exc


def _open_chrome_url(url: str) -> bool:
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["open", "-a", "Google Chrome", url],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return False
        return result.returncode == 0
    try:
        browser = webbrowser.get("chrome")
    except webbrowser.Error:
        return webbrowser.open(url, new=2, autoraise=True)
    return browser.open(url, new=2, autoraise=True)


def _login_progress(
    callback: ProgressCallback | None,
    message: str,
    *,
    platform: str,
    state: str,
    url: str,
) -> None:
    if callback is None:
        return
    callback(
        {
            "event": "progress",
            "stage": "login",
            "label": "登录",
            "message": message,
            "platform": platform,
            "state": state,
            "url": url,
        }
    )


def _browser_session_ready(status: Any) -> bool:
    if not isinstance(status, dict):
        return False
    session = status.get("session")
    if not isinstance(session, dict):
        return False
    if session.get("request_ready") is True:
        return True
    return "request_ready" not in session and session.get("logged_in") is True


def _browser_login_state(status: Any) -> tuple[str, str]:
    if not isinstance(status, dict):
        return "extension_disconnected", "正在等待 Chrome 扩展连接"
    session = status.get("session")
    if isinstance(session, dict):
        if session.get("verification_required") is True:
            return "verification_required", "请在浏览器中完成安全验证"
        if session.get("profile_required") is True:
            return "profile_required", "请在浏览器中完成业务资料设置"
        if session.get("logged_in") is not True:
            return "not_logged_in", "请在浏览器中完成登录"
        return (
            "runtime_unavailable",
            f"登录成功，正在确认接口上下文，最多等待 {LOGIN_RUNTIME_TIMEOUT} 秒",
        )
    code = str(status.get("error") or "extension_disconnected")
    messages = {
        "advertiser_account_required": (
            "请在 TikTok Ads Manager 选择广告主账户并进入 Keyword Planner"
        ),
        "extension_disconnected": "正在等待 Chrome 扩展连接",
        "tab_unavailable": "正在等待 Chrome 打开目标页面",
        "not_logged_in": "请在浏览器中完成登录",
        "profile_required": "请在浏览器中完成业务资料设置",
        "runtime_unavailable": "正在等待当前页面加载完成",
        "verification_required": "请在浏览器中完成安全验证",
    }
    return code, messages.get(code, "正在等待浏览器会话就绪")


def authorize_browser_session(
    platform: str,
    *,
    url: str | None = None,
    timeout: float = 300,
    poll_interval: float = 1,
    open_browser: bool = True,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """打开一次业务页面，等待使用者完成登录并返回脱敏会话摘要。"""

    platform = _validate_platform(platform)
    target_was_explicit = url is not None
    target = _validate_platform_url(
        platform,
        url or PLATFORM_LOGIN_URLS[platform],
    )
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not 1 <= timeout <= 3600
        or not isinstance(poll_interval, (int, float))
        or isinstance(poll_interval, bool)
        or not 0.2 <= poll_interval <= 10
    ):
        raise BrowserSessionError("invalid_request", "invalid browser login timeout")

    start_daemon()
    label = PLATFORM_LABELS[platform]
    try:
        status: Any = asyncio.run(
            call_daemon(
                {"op": "status", "platform": platform, "url": target},
                timeout=min(10.0, float(poll_interval) + 3.0),
            )
        )
    except BrowserSessionError as exc:
        status = {"ready": False, "error": exc.code}
    if _browser_session_ready(status) and not target_was_explicit:
        session = status["session"]
        _login_progress(
            progress,
            f"{label} 已有可用页面，直接复用",
            platform=platform,
            state="ready",
            url=target,
        )
        return {
            "platform": platform,
            "url": target,
            "ready": True,
            "session": session,
        }
    existing_page_state = (
        isinstance(status, dict)
        and (
            isinstance(status.get("session"), dict)
            or status.get("error") in {
                "advertiser_account_required",
                "not_logged_in",
                "profile_required",
                "runtime_unavailable",
                "verification_required",
            }
        )
    )
    should_open_target = open_browser and (
        not existing_page_state
        or platform == "tiktok_ads_manager"
        # 同一平台可能存在多个不能互换的业务页。调用方显式指定 URL
        # 时，不能把另一页的就绪快照误认为目标页已经可用。
        or target_was_explicit
    )
    if should_open_target:
        if not _open_chrome_url(target):
            raise BrowserSessionError(
                "browser_open_failed",
                f"failed to open Chrome for {label}",
            )
        _login_progress(
            progress,
            f"已打开 {label} 业务页面；页面提示时请手动登录",
            platform=platform,
            state="browser_opened",
            url=target,
        )
        if target_was_explicit:
            # 打开动作前的状态属于旧页面；等待下一次定向探测确认目标页。
            status = {"ready": False, "error": "tab_unavailable"}
    else:
        _login_progress(
            progress,
            f"正在等待现有 {label} 页面加载完成",
            platform=platform,
            state="browser_wait",
            url=target,
        )

    deadline = time.monotonic() + float(timeout)
    runtime_deadline: float | None = None
    previous_state = ""
    try:
        while True:
            if _browser_session_ready(status):
                session = status["session"]
                _login_progress(
                    progress,
                    f"{label} 登录态已就绪，继续执行原请求",
                    platform=platform,
                    state="ready",
                    url=target,
                )
                return {
                    "platform": platform,
                    "url": target,
                    "ready": True,
                    "session": session,
                }
            session = status.get("session") if isinstance(status, dict) else None
            ads_account_pending = (
                platform == "tiktok_ads_manager"
                and isinstance(session, dict)
                and session.get("logged_in") is True
                and session.get("request_ready") is False
                and session.get("fingerprint") == {}
            )
            if ads_account_pending:
                state = "advertiser_account_required"
                message = (
                    "请在新打开的 Keyword Planner 页面选择广告主账户"
                )
            else:
                state, message = _browser_login_state(status)
            if state != previous_state:
                previous_state = state
                _login_progress(
                    progress,
                    message,
                    platform=platform,
                    state=state,
                    url=target,
                )
            now = time.monotonic()
            if (
                isinstance(session, dict)
                and session.get("logged_in") is True
                and session.get("request_ready") is False
                and session.get("verification_required") is not True
                and session.get("profile_required") is not True
                and not ads_account_pending
            ):
                if runtime_deadline is None:
                    runtime_deadline = min(
                        deadline,
                        now + LOGIN_RUNTIME_TIMEOUT,
                    )
            else:
                runtime_deadline = None
            effective_deadline = (
                min(deadline, runtime_deadline)
                if runtime_deadline is not None
                else deadline
            )
            remaining = effective_deadline - now
            if remaining <= 0:
                if runtime_deadline is not None:
                    raise BrowserSessionError(
                        "runtime_unavailable",
                        (
                            f"{label} 已登录，但页面运行时在 "
                            f"{LOGIN_RUNTIME_TIMEOUT} 秒内未就绪"
                        ),
                    )
                raise BrowserSessionError(
                    "login_timeout",
                    f"{label} browser login timed out",
                )
            time.sleep(min(float(poll_interval), remaining))
            try:
                status = asyncio.run(
                    call_daemon(
                        {
                            "op": "status",
                            "platform": platform,
                            "url": target,
                        },
                        timeout=min(10.0, float(poll_interval) + 3.0),
                    )
                )
            except BrowserSessionError as exc:
                status = {"ready": False, "error": exc.code}
    except KeyboardInterrupt as exc:
        raise BrowserSessionError(
            "login_cancelled",
            f"{label} browser login cancelled",
        ) from exc


def _start_daemon_locked() -> None:
    try:
        asyncio.run(call_daemon({"op": "ping"}, timeout=1))
        return
    except BrowserSessionError as exc:
        if exc.code != "daemon_unavailable":
            raise
    home = session_home()
    _ensure_private_directory(home)
    log_descriptor = _open_private(
        home / "daemon.log",
        os.O_WRONLY | os.O_APPEND,
        create=True,
    )
    log = os.fdopen(log_descriptor, "ab")
    try:
        subprocess.Popen(
            [sys.executable, "-m", "reverse", "session", "_serve"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        log.close()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            asyncio.run(call_daemon({"op": "ping"}, timeout=1))
            return
        except BrowserSessionError as exc:
            if exc.code not in {"daemon_unavailable", "timeout"}:
                raise
            time.sleep(0.1)
    raise BrowserSessionError(
        "daemon_start_failed",
        f"browser-session daemon did not start; see {home / 'daemon.log'}",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m reverse session",
        description="管理本地 Chrome 扩展桥。",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("start", help="启动或复用本地桥接守护进程")
    status = commands.add_parser("status", help="显示守护进程或平台会话状态")
    status.add_argument("--platform", choices=sorted(PLATFORMS))
    status.add_argument("--url", help="按指定业务页面 URL 检查会话上下文")
    login = commands.add_parser(
        "login",
        help="打开平台页面，等待手动登录完成并返回会话状态",
    )
    login.add_argument("platform", choices=sorted(PLATFORMS))
    login.add_argument("--url", help="覆盖默认登录后的业务页面 URL")
    login.add_argument(
        "--timeout",
        type=float,
        default=300,
        help="等待登录完成的最长秒数（默认值: 300）",
    )
    login.add_argument(
        "--poll-interval",
        type=float,
        default=1,
        help="检查本地会话状态的间隔秒数（默认值: 1）",
    )
    request = commands.add_parser("request", help="通过已有 Chrome 页面转发一条白名单请求")
    request.add_argument("platform", choices=sorted(PLATFORMS))
    request.add_argument("path", help="适配器定义的请求路径")
    request.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="可重复传入的请求参数",
    )
    request.add_argument(
        "--referer",
        default="",
        help="作为请求上下文的平台页面 URL",
    )
    request.add_argument(
        "--method",
        choices=("GET", "POST"),
        default="GET",
        help="请求方法；POST 仅适用于小红书作用域（默认值: GET）",
    )
    request.add_argument(
        "--request-interval-ms",
        type=int,
        default=0,
        help="同平台族请求的最小间隔，单位为毫秒",
    )
    commands.add_parser("stop", help="停止本地桥接守护进程")
    return parser


def _entries(values: list[str]) -> list[list[str]]:
    result: list[list[str]] = []
    for value in values:
        name, separator, item = value.partition("=")
        if not separator:
            raise BrowserSessionError("invalid_request", f"invalid --param: {value}")
        result.append([name, item])
    return result


def main(argv: list[str] | None = None) -> int:
    if argv == ["_serve"]:
        asyncio.run(BridgeDaemon().run())
        return 0
    args = _parser().parse_args(argv)
    try:
        if args.command == "status":
            request = {"op": "status", "platform": args.platform}
            if args.url:
                request["url"] = args.url
            result = asyncio.run(call_daemon(request))
        elif args.command == "login":
            result = authorize_browser_session(
                args.platform,
                url=args.url,
                timeout=args.timeout,
                poll_interval=args.poll_interval,
                progress=stderr_progress(),
            )
        elif args.command == "stop":
            request = {"op": "shutdown"}
            result = asyncio.run(call_daemon(request))
        else:
            start_daemon()
            if args.command == "start":
                request = {"op": "ping"}
            else:
                request = {
                    "op": "request",
                    "platform": args.platform,
                    "path": args.path,
                    "entries": _entries(args.param),
                    "referer": args.referer,
                    "method": args.method,
                    "request_interval_ms": args.request_interval_ms,
                }
            result = asyncio.run(call_daemon(request))
    except BrowserSessionError as exc:
        print(f"browser-session: {exc}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0
