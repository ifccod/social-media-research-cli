from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import BilibiliInputError, BilibiliResponseError

PROFILE_NAME = "bilibili-android-anonymous-v1"
PROFILE_VERSION = 1
PROFILE_HOME_ENV = "REVERSE_MOBILE_PROFILE_HOME"
BUVID_ENV = "REVERSE_BILIBILI_MOBILE_BUVID"
DEVICE_ID_ENV = "REVERSE_BILIBILI_MOBILE_DEVICE_ID"

_ALPHANUMERIC = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
_FCHMOD = getattr(os, "fchmod", None)


class _CorruptProfileError(BilibiliResponseError):
    """普通 profile 文件存在，但其 JSON 或字段已经损坏。"""


@dataclass(frozen=True, slots=True)
class MobileProfile:
    """Bilibili Android 匿名客户端在本机持久化的稳定身份。"""

    version: int
    buvid: str
    device_id: str
    created_at: str


def load_mobile_profile(
    *,
    home: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
    now: Callable[[], datetime] | None = None,
    random_bytes: Callable[[int], bytes] = os.urandom,
) -> MobileProfile:
    """读取稳定身份；首次调用时以私有权限原子创建。"""

    environment = os.environ if environ is None else environ
    clock = now or (lambda: datetime.now(timezone.utc))
    path = mobile_profile_path(home=home, environ=environment)

    buvid = environment.get(BUVID_ENV, "").strip()
    device_id = environment.get(DEVICE_ID_ENV, "").strip()
    if bool(buvid) != bool(device_id):
        raise BilibiliInputError(f"{BUVID_ENV} 与 {DEVICE_ID_ENV} 必须同时设置")

    explicit: MobileProfile | None = None
    if buvid:
        explicit = MobileProfile(
            version=PROFILE_VERSION,
            buvid=buvid,
            device_id=device_id,
            created_at=_format_time(clock()),
        )
        validate_mobile_profile(explicit)

    _prepare_home(path.parent)
    if explicit is not None:
        try:
            existing = _load_if_present(path)
        except _CorruptProfileError:
            existing = None
        if existing and existing.buvid == buvid and existing.device_id == device_id:
            return existing
        _replace(path, explicit)
        return explicit

    existing = _load_if_present(path)
    if existing:
        return existing

    candidate = generate_mobile_profile(now=clock(), random_bytes=random_bytes)
    temp = _write_temp(path.parent, candidate)
    try:
        try:
            os.link(temp, path)
        except FileExistsError:
            winner = _load_if_present(path)
            if winner is None:
                raise BilibiliResponseError("移动身份并发创建后未找到结果")
            return winner
        except OSError as exc:
            raise BilibiliResponseError(f"原子创建移动身份失败: {exc}") from exc
        try:
            path.chmod(0o600)
        except OSError as exc:
            raise BilibiliResponseError(f"设置移动身份权限失败: {exc}") from exc
        _sync_directory(path.parent)
        return candidate
    finally:
        _remove_temp(temp)


def mobile_profile_path(
    *,
    home: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """返回移动身份文件的绝对路径。"""

    environment = os.environ if environ is None else environ
    configured = str(home or environment.get(PROFILE_HOME_ENV, "")).strip()
    root = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local/share/tiktok_reverse/mobile-profiles"
    )
    return root.absolute() / f"{PROFILE_NAME}.json"


def generate_mobile_profile(
    *,
    now: datetime | None = None,
    random_bytes: Callable[[int], bytes] = os.urandom,
) -> MobileProfile:
    """生成符合公开 Android 客户端字段形状的匿名身份。"""

    raw = random_bytes(18)
    if len(raw) != 18:
        raise BilibiliResponseError("生成 Buvid 时随机源返回长度错误")
    profile = MobileProfile(
        version=PROFILE_VERSION,
        buvid="XX" + raw.hex().upper()[:35],
        device_id=_random_alphanumeric(27, random_bytes),
        created_at=_format_time(now or datetime.now(timezone.utc)),
    )
    validate_mobile_profile(profile)
    return profile


def validate_mobile_profile(profile: MobileProfile) -> None:
    """校验持久化字段，避免损坏身份进入 App 请求。"""

    if type(profile.version) is not int or profile.version != PROFILE_VERSION:
        raise BilibiliInputError(f"profile version 必须为 {PROFILE_VERSION}")
    if (
        not isinstance(profile.buvid, str)
        or len(profile.buvid) != 37
        or not profile.buvid.startswith("XX")
        or any(character not in "0123456789ABCDEF" for character in profile.buvid[2:])
    ):
        raise BilibiliInputError("Buvid 必须为 XX 加 35 位大写十六进制")
    if (
        not isinstance(profile.device_id, str)
        or len(profile.device_id) != 27
        or any(character not in _ALPHANUMERIC for character in profile.device_id)
    ):
        raise BilibiliInputError("Device-ID 必须为 27 位 ASCII 字母数字")
    if not isinstance(profile.created_at, str):
        raise BilibiliInputError("created_at 必须为 RFC3339 时间")
    try:
        created_at = datetime.fromisoformat(profile.created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BilibiliInputError("created_at 必须为 RFC3339 时间") from exc
    if created_at.tzinfo is None:
        raise BilibiliInputError("created_at 必须包含 RFC3339 时区")
    if created_at.astimezone(timezone.utc) < datetime(1970, 1, 1, tzinfo=timezone.utc):
        raise BilibiliInputError("created_at 不得早于 Unix epoch")


def _load_if_present(path: Path) -> MobileProfile | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise BilibiliResponseError(f"检查移动身份失败: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise BilibiliResponseError("移动身份文件类型非法")
    try:
        if stat.S_IMODE(info.st_mode) != 0o600:
            path.chmod(0o600)
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise _CorruptProfileError("移动身份文件已损坏: 不是 UTF-8") from exc
    except OSError as exc:
        raise BilibiliResponseError(f"读取移动身份失败: {exc}") from exc
    try:
        value: Any = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("根节点不是对象")
        profile = MobileProfile(
            version=value["version"],
            buvid=value["buvid"],
            device_id=value["device_id"],
            created_at=value["created_at"],
        )
        validate_mobile_profile(profile)
        return profile
    except (
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        BilibiliInputError,
    ) as exc:
        raise _CorruptProfileError(f"移动身份文件已损坏: {exc}") from exc


def _prepare_home(root: Path) -> None:
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = root.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise BilibiliResponseError("移动身份目录类型非法")
        root.chmod(0o700)
    except OSError as exc:
        raise BilibiliResponseError(f"准备移动身份目录失败: {exc}") from exc


def _replace(path: Path, profile: MobileProfile) -> None:
    temp = _write_temp(path.parent, profile)
    try:
        try:
            os.replace(temp, path)
            path.chmod(0o600)
        except OSError as exc:
            raise BilibiliResponseError(f"替换移动身份失败: {exc}") from exc
        _sync_directory(path.parent)
    finally:
        _remove_temp(temp)


def _write_temp(root: Path, profile: MobileProfile) -> str:
    payload = json.dumps(asdict(profile), ensure_ascii=False, indent=2) + "\n"
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{PROFILE_NAME}.",
            suffix=".tmp",
            dir=root,
        )
    except OSError as exc:
        raise BilibiliResponseError(f"创建临时移动身份失败: {exc}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            if _FCHMOD is not None:
                _FCHMOD(output.fileno(), 0o600)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        return name
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        _remove_temp(name)
        raise BilibiliResponseError(f"写入移动身份失败: {exc}") from exc


def _remove_temp(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _sync_directory(root: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(root, os.O_RDONLY)
    except OSError as exc:
        raise BilibiliResponseError(f"同步移动身份目录失败: {exc}") from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise BilibiliResponseError(f"同步移动身份目录失败: {exc}") from exc
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _random_alphanumeric(
    length: int,
    random_bytes: Callable[[int], bytes],
) -> str:
    output: list[str] = []
    while len(output) < length:
        chunk = random_bytes(32)
        if not chunk:
            raise BilibiliResponseError("生成字母数字标识时随机源未返回数据")
        for value in chunk:
            if value < 248:
                output.append(_ALPHANUMERIC[value % len(_ALPHANUMERIC)])
                if len(output) == length:
                    break
    return "".join(output)


def _format_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
