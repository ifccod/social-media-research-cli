from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Mapping
from urllib.parse import urlencode, urlsplit

from .errors import BilibiliInputError, BilibiliSignatureError


QueryValue = str | int | float | bool

_WBI_FORBIDDEN_VALUE_CHARACTERS = "!'()*"
_WBI_KEY_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")
_WBI_MIXIN_KEY_ENC_TAB = (
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
)


def _unix_seconds(value: int | None, field: str) -> int:
    if value is None:
        return int(time.time())
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BilibiliInputError(f"{field} must be a non-negative integer")
    return value


def _stringify_params(params: Mapping[str, QueryValue]) -> dict[str, str]:
    if not isinstance(params, Mapping):
        raise BilibiliInputError("params must be a mapping")

    result: dict[str, str] = {}
    for key, value in params.items():
        if not isinstance(key, str) or not key:
            raise BilibiliInputError("parameter names must be non-empty strings")
        if value is None or not isinstance(value, (str, int, float, bool)):
            raise BilibiliInputError(
                f"parameter {key!r} must contain a scalar query value"
            )
        result[key] = str(value)
    return result


def _md5_hex(value: str) -> str:
    try:
        return hashlib.md5(value.encode("utf-8")).hexdigest()
    except (TypeError, UnicodeError, ValueError) as exc:
        raise BilibiliSignatureError("MD5 signature calculation failed") from exc


class BilibiliAppSigner:
    """生成 Bilibili Android API 使用的排序查询 MD5 签名。"""

    ANDROID_APP_KEY = "1d8b6e7d45233436"
    ANDROID_APP_SECRET = "560c52ccd288fed045859ed18bffd973"

    def __init__(
        self,
        app_key: str = ANDROID_APP_KEY,
        app_secret: str = ANDROID_APP_SECRET,
    ) -> None:
        if not isinstance(app_key, str) or not app_key:
            raise BilibiliInputError("app_key must be a non-empty string")
        if not isinstance(app_secret, str) or not app_secret:
            raise BilibiliInputError("app_secret must be a non-empty string")
        self.app_key = app_key
        self.app_secret = app_secret

    def sign(
        self,
        params: Mapping[str, QueryValue],
        *,
        timestamp: int | None = None,
    ) -> dict[str, str]:
        """返回补入 ``appkey``、``ts`` 和 ``sign`` 的参数副本。"""

        payload = _stringify_params(params)
        payload.pop("sign", None)
        payload["appkey"] = self.app_key
        payload["ts"] = str(_unix_seconds(timestamp, "timestamp"))

        canonical = dict(sorted(payload.items()))
        query = urlencode(canonical)
        canonical["sign"] = _md5_hex(query + self.app_secret)
        return canonical

    def sign_query(
        self,
        params: Mapping[str, QueryValue],
        *,
        timestamp: int | None = None,
    ) -> str:
        """返回追加 ``sign``、可直接传输的规范查询串。"""

        return urlencode(self.sign(params, timestamp=timestamp))


class BilibiliWbiSigner:
    """无需浏览器运行时，生成 Bilibili Web WBI ``w_rid`` 签名。"""

    MIXIN_KEY_ENC_TAB = _WBI_MIXIN_KEY_ENC_TAB

    def __init__(self, img_key: str | None = None, sub_key: str | None = None) -> None:
        self.img_key = self.extract_key(img_key, field="img_key") if img_key else None
        self.sub_key = self.extract_key(sub_key, field="sub_key") if sub_key else None

    @staticmethod
    def extract_key(value: str, *, field: str = "WBI key") -> str:
        """从裸 key 或图片 URL 中提取 32 字符 WBI key。"""

        if not isinstance(value, str) or not value.strip():
            raise BilibiliSignatureError(f"{field} is required")

        candidate = value.strip()
        try:
            path = urlsplit(candidate).path
        except ValueError as exc:
            raise BilibiliSignatureError(f"{field} contains a malformed URL") from exc
        basename = path.rsplit("/", 1)[-1]
        key = basename.rsplit(".", 1)[0] if "." in basename else basename
        if not _WBI_KEY_PATTERN.fullmatch(key):
            raise BilibiliSignatureError(
                f"{field} must be a 32-character hexadecimal key or WBI image URL"
            )
        return key.lower()

    @classmethod
    def derive_mixin_key(cls, img_key: str, sub_key: str) -> str:
        """应用 Bilibili 的 64 位排列并保留前 32 字节。"""

        raw_key = cls.extract_key(img_key, field="img_key") + cls.extract_key(
            sub_key, field="sub_key"
        )
        try:
            return "".join(raw_key[index] for index in cls.MIXIN_KEY_ENC_TAB)[:32]
        except (IndexError, TypeError) as exc:
            raise BilibiliSignatureError("WBI mixin key derivation failed") from exc

    def sign(
        self,
        params: Mapping[str, QueryValue],
        *,
        wts: int | None = None,
        img_key: str | None = None,
        sub_key: str | None = None,
    ) -> dict[str, str]:
        """返回补入规范 ``wts`` 和 ``w_rid`` 的参数副本。"""

        resolved_img_key = img_key if img_key is not None else self.img_key
        resolved_sub_key = sub_key if sub_key is not None else self.sub_key
        if resolved_img_key is None or resolved_sub_key is None:
            raise BilibiliSignatureError("both img_key and sub_key are required")
        mixin_key = self.derive_mixin_key(resolved_img_key, resolved_sub_key)

        payload = _stringify_params(params)
        payload.pop("w_rid", None)
        payload["wts"] = str(_unix_seconds(wts, "wts"))
        translation = str.maketrans("", "", _WBI_FORBIDDEN_VALUE_CHARACTERS)
        filtered = {key: value.translate(translation) for key, value in payload.items()}

        canonical = dict(sorted(filtered.items()))
        query = urlencode(canonical)
        canonical["w_rid"] = _md5_hex(query + mixin_key)
        return canonical

    def sign_query(
        self,
        params: Mapping[str, QueryValue],
        *,
        wts: int | None = None,
        img_key: str | None = None,
        sub_key: str | None = None,
    ) -> str:
        """返回追加 ``w_rid``、可直接传输的规范查询串。"""

        return urlencode(
            self.sign(params, wts=wts, img_key=img_key, sub_key=sub_key)
        )
