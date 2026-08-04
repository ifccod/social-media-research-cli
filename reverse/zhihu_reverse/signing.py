from __future__ import annotations

import hashlib
import json
import math
import secrets
import subprocess
from pathlib import Path
from typing import Any

from .errors import ZhihuSignatureError

X_ZSE_93 = "101_3_3.0"
_SALT = "6fpLRqJO8M/c3jnYxFkUVC4ZIG12SiH=5v0mXDazWBTsuw7QetbKdoPyAl+hN9rgE"
_FIX = [48, 53, 57, 48, 53, 51, 102, 55, 100, 49, 53, 101, 48, 49, 100, 55]
_ROUND_KEYS = [
    1170614578,
    1024848638,
    1413669199,
    -343334464,
    -766094290,
    -1373058082,
    -143119608,
    -297228157,
    1933479194,
    -971186181,
    -406453910,
    460404854,
    -547427574,
    -1891326262,
    -1679095901,
    2119585428,
    -2029270069,
    2035090028,
    -1521520070,
    -5587175,
    -77751101,
    -2094365853,
    -1243052806,
    1579901135,
    1321810770,
    456816404,
    -1391643889,
    -229302305,
    330002838,
    -788960546,
    363569021,
    -1947871109,
]
_SBOX = [
    20, 223, 245, 7, 248, 2, 194, 209, 87, 6, 227, 253, 240, 128, 222, 91,
    237, 9, 125, 157, 230, 93, 252, 205, 90, 79, 144, 199, 159, 197, 186, 167,
    39, 37, 156, 198, 38, 42, 43, 168, 217, 153, 15, 103, 80, 189, 71, 191,
    97, 84, 247, 95, 36, 69, 14, 35, 12, 171, 28, 114, 178, 148, 86, 182,
    32, 83, 158, 109, 22, 255, 94, 238, 151, 85, 77, 124, 254, 18, 4, 26,
    123, 176, 232, 193, 131, 172, 143, 142, 150, 30, 10, 146, 162, 62, 224, 218,
    196, 229, 1, 192, 213, 27, 110, 56, 231, 180, 138, 107, 242, 187, 54, 120,
    19, 44, 117, 228, 215, 203, 53, 239, 251, 127, 81, 11, 133, 96, 204, 132,
    41, 115, 73, 55, 249, 147, 102, 48, 122, 145, 106, 118, 74, 190, 29, 16,
    174, 5, 177, 129, 63, 113, 99, 31, 161, 76, 246, 34, 211, 13, 60, 68,
    207, 160, 65, 111, 82, 165, 67, 169, 225, 57, 112, 244, 155, 51, 236, 200,
    233, 58, 61, 47, 100, 137, 185, 64, 17, 70, 234, 163, 219, 108, 170, 166,
    59, 149, 52, 105, 24, 212, 78, 173, 45, 0, 116, 226, 119, 136, 206, 135,
    175, 195, 25, 92, 121, 208, 126, 139, 3, 75, 141, 21, 130, 98, 241, 40,
    154, 66, 184, 49, 181, 46, 243, 88, 101, 183, 8, 23, 72, 188, 104, 179,
    210, 134, 250, 201, 164, 89, 216, 202, 220, 50, 221, 152, 140, 33, 235, 214,
]


def _u32(value: int) -> int:
    return value & 0xFFFFFFFF


def _rotl(value: int, shift: int) -> int:
    value = _u32(value)
    return _u32((value << shift) | (value >> (32 - shift)))


def _word(block: list[int], offset: int) -> int:
    return _u32(
        ((block[offset] & 0xFF) << 24)
        | ((block[offset + 1] & 0xFF) << 16)
        | ((block[offset + 2] & 0xFF) << 8)
        | (block[offset + 3] & 0xFF)
    )


def _bytes(value: int) -> list[int]:
    value = _u32(value)
    return [value >> 24, (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF]


def _linear_transform(value: int) -> int:
    substituted = [_SBOX[part] for part in _bytes(value)]
    word = _word(substituted, 0)
    return _u32(word ^ _rotl(word, 2) ^ _rotl(word, 10) ^ _rotl(word, 18) ^ _rotl(word, 24))


def _round(block: list[int]) -> list[int]:
    if len(block) != 16:
        raise ZhihuSignatureError("Zhihu signature block must contain 16 bytes")
    state = [_word(block, offset) for offset in (0, 4, 8, 12)]
    for index, key in enumerate(_ROUND_KEYS):
        mixed = state[index + 1] ^ state[index + 2] ^ state[index + 3] ^ _u32(key)
        state.append(_u32(state[index] ^ _linear_transform(mixed)))
    result: list[int] = []
    for index in (35, 34, 33, 32):
        result.extend(_bytes(state[index]))
    return result


def _encrypt_blocks(source: list[int], key: list[int]) -> list[int]:
    result: list[int] = []
    current_key = key
    for offset in range(0, len(source), 16):
        block = source[offset : offset + 16]
        if len(block) != 16:
            raise ZhihuSignatureError("Zhihu signature payload is not block aligned")
        current_key = _round([value ^ current_key[index] for index, value in enumerate(block)])
        result.extend(current_key)
    return result


def _encode_chunk(value: int) -> str:
    return "".join(_SALT[(value >> shift) & 63] for shift in (0, 6, 12, 18))


def encrypt_md5(md5_hex: str, *, random_byte: int | None = None) -> str:
    """编码知乎 x-zse-96 v3 请求头使用的 32 字符 MD5 输入。"""

    value = str(md5_hex).lower()
    if len(value) != 32 or any(character not in "0123456789abcdef" for character in value):
        raise ZhihuSignatureError("Zhihu signature input must be a 32-character hexadecimal MD5")
    if random_byte is None:
        random_byte = secrets.randbelow(127)
    if isinstance(random_byte, bool) or not isinstance(random_byte, int) or not 0 <= random_byte <= 126:
        raise ZhihuSignatureError("random_byte must be an integer from 0 through 126")

    payload = [random_byte, 0, *(ord(character) for character in value), *([14] * 15)]
    front = [payload[index] ^ _FIX[index] ^ 42 for index in range(16)]
    first = _round(front)
    processed = first + _encrypt_blocks(payload[16:48], first)

    current = 0
    encoded: list[str] = []
    for index, item in enumerate(reversed(processed)):
        modifier = (58 >> (8 * (index % 4))) & 0xFF
        current |= (item ^ modifier) << (8 * (index % 3))
        if index % 3 == 2:
            encoded.append(_encode_chunk(current))
            current = 0
    return "".join(encoded)


def build_x_zse_96(api_path: str, d_c0: str, *, random_byte: int | None = None) -> str:
    if not isinstance(api_path, str) or not api_path.startswith("/api/"):
        raise ZhihuSignatureError("api_path must be an absolute Zhihu API path")
    if not isinstance(d_c0, str) or not d_c0:
        raise ZhihuSignatureError("d_c0 is required for Zhihu signing")
    digest = hashlib.md5(f"{X_ZSE_93}+{api_path}+{d_c0}".encode()).hexdigest()
    return "2.0_" + encrypt_md5(digest, random_byte=random_byte)


class ZhihuChallengeRunner:
    """在本地 Node.js/V8 进程中执行知乎访客 Cookie 验证。"""

    def __init__(self, *, node_binary: str = "node", timeout: float = 8.0) -> None:
        if (
            not isinstance(node_binary, str)
            or not node_binary.strip()
            or "\r" in node_binary
            or "\n" in node_binary
        ):
            raise ZhihuSignatureError("node_binary must be a non-empty single-line string")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(float(timeout))
            or timeout <= 0
        ):
            raise ZhihuSignatureError("challenge timeout must be a positive finite number")
        self.node_binary = node_binary
        self.timeout = float(timeout)
        self.script_path = Path(__file__).with_name("challenge_runner.mjs")

    def run(self, source: str, *, meta: str, page_url: str, user_agent: str) -> str:
        if not all(isinstance(value, str) and value for value in (source, meta, page_url, user_agent)):
            raise ZhihuSignatureError("Zhihu challenge source, meta, URL, and user-agent are required")
        payload = json.dumps(
            {"source": source, "meta": meta, "page_url": page_url, "user_agent": user_agent},
            ensure_ascii=False,
        )
        try:
            result = subprocess.run(
                [self.node_binary, str(self.script_path)],
                input=payload,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ZhihuSignatureError(f"Node.js/V8 challenge execution failed: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown V8 error").strip()
            raise ZhihuSignatureError(f"Node.js/V8 challenge execution failed: {detail[:500]}")
        try:
            decoded: Any = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ZhihuSignatureError("Node.js/V8 challenge returned malformed JSON") from exc
        token = decoded.get("token") if isinstance(decoded, dict) else None
        if not isinstance(token, str) or "-" not in token or not token.startswith("005_"):
            raise ZhihuSignatureError("Node.js/V8 challenge did not produce a complete __zse_ck")
        return token
