"""Douyin Web 本地签名与 Trend Insight 响应解密。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import random
import time
from functools import reduce
from operator import xor

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_SALT = b"cus"
_UA_KEY = b"\x00\x01\x0e"
_ALPHABET = "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"
_UA_ALPHABET = "ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe"

_INDEX_V2_KEY = bytes.fromhex("4a35db61325bef35e8513a1289c50bdc")
_INDEX_V2_IV = bytes.fromhex("39e90c2e3821460f2f957fcf7a62dcf9")
_INDEX_BLOCK_BYTES = algorithms.AES.block_size // 8
_INDEX_MAX_PLAINTEXT_BYTES = 8 << 20
_INDEX_MAX_CIPHERTEXT_BYTES = (
    (_INDEX_MAX_PLAINTEXT_BYTES // _INDEX_BLOCK_BYTES) + 1
) * _INDEX_BLOCK_BYTES
_INDEX_MAX_BASE64_BYTES = 4 * ((_INDEX_MAX_CIPHERTEXT_BYTES + 2) // 3)

_SORT_INDEX = (
    18, 20, 52, 26, 30, 34, 58, 38, 40, 53, 42, 21, 27, 54, 55, 31, 35,
    57, 39, 41, 43, 22, 28, 32, 60, 36, 23, 29, 33, 37, 44, 45, 59, 46,
    47, 48, 49, 50, 24, 25, 65, 66, 70, 71,
)
_CHECK_INDEX = (
    18, 20, 26, 30, 34, 38, 40, 42, 21, 27, 31, 35, 39, 41, 43, 22, 28,
    32, 36, 23, 29, 33, 37, 44, 45, 46, 47, 48, 49, 50, 24, 25, 52, 53,
    54, 55, 57, 58, 59, 60, 65, 66, 70, 71,
)

_PERMUTATION = (
    121, 243, 55, 234, 103, 36, 47, 228, 30, 231, 106, 6, 115, 95, 78,
    101, 250, 207, 198, 50, 139, 227, 220, 105, 97, 143, 34, 28, 194,
    215, 18, 100, 159, 160, 43, 8, 169, 217, 180, 120, 247, 45, 90, 11,
    27, 197, 46, 3, 84, 72, 5, 68, 62, 56, 221, 75, 144, 79, 73, 161,
    178, 81, 64, 187, 134, 117, 186, 118, 16, 241, 130, 71, 89, 147,
    122, 129, 65, 40, 88, 150, 110, 219, 199, 255, 181, 254, 48, 4,
    195, 248, 208, 32, 116, 167, 69, 201, 17, 124, 125, 104, 96, 83,
    80, 127, 236, 108, 154, 126, 204, 15, 20, 135, 112, 158, 13, 1,
    188, 164, 210, 237, 222, 98, 212, 77, 253, 42, 170, 202, 26, 22,
    29, 182, 251, 10, 173, 152, 58, 138, 54, 141, 185, 33, 157, 31,
    252, 132, 233, 235, 102, 196, 191, 223, 240, 148, 39, 123, 92, 82,
    128, 109, 57, 24, 38, 113, 209, 245, 2, 119, 153, 229, 189, 214,
    230, 174, 232, 63, 52, 205, 86, 140, 66, 175, 111, 171, 246, 133,
    238, 193, 99, 60, 74, 91, 225, 51, 76, 37, 145, 211, 166, 151,
    213, 206, 0, 200, 244, 176, 218, 44, 184, 172, 49, 216, 93, 168,
    53, 21, 183, 41, 67, 85, 224, 155, 226, 242, 87, 177, 146, 70,
    190, 12, 162, 19, 137, 114, 25, 165, 163, 192, 23, 59, 9, 94,
    179, 107, 35, 7, 142, 131, 239, 203, 149, 136, 61, 249, 14, 156,
)


def _sm3(data: bytes) -> bytes:
    try:
        return hashlib.new("sm3", data).digest()
    except ValueError as exc:  # pragma: no cover - 新版 OpenSSL 提供 SM3
        raise RuntimeError("Python/OpenSSL build does not expose SM3") from exc


def _double_sm3(value: str) -> bytes:
    return _sm3(_sm3(value.encode("utf-8") + _SALT))


def _rc4(key: bytes, plaintext: str) -> bytes:
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) % 256
        state[i], state[j] = state[j], state[i]

    i = j = 0
    result = []
    for char in plaintext:
        i = (i + 1) % 256
        j = (j + state[i]) % 256
        state[i], state[j] = state[j], state[i]
        key_byte = state[(state[i] + state[j]) % 256]
        result.append(ord(char) ^ key_byte)
    return bytes(result)


def _custom_b64(data: bytes | list[int], alphabet: str) -> str:
    result: list[str] = []
    for offset in range(0, len(data), 3):
        remaining = len(data) - offset
        n = data[offset] << 16
        if remaining > 1:
            n |= data[offset + 1] << 8
        if remaining > 2:
            n |= data[offset + 2]
        result.append(alphabet[(n & 0xFC0000) >> 18])
        result.append(alphabet[(n & 0x03F000) >> 12])
        if remaining > 1:
            result.append(alphabet[(n & 0x0FC0) >> 6])
        if remaining > 2:
            result.append(alphabet[n & 0x3F])
    result.append("=" * ((4 - len(result) % 4) % 4))
    return "".join(result)


def _transform(values: list[int]) -> list[int]:
    table = list(_PERMUTATION)
    output: list[int] = []
    index_b = table[1]
    initial_value = 0
    value_e = 0

    for index, value in enumerate(values):
        if index == 0:
            initial_value = table[index_b]
            sum_initial = index_b + initial_value
            table[1] = initial_value
            table[index_b] = index_b
        else:
            sum_initial = initial_value + value_e

        sum_initial %= len(table)
        output.append(value ^ table[sum_initial])

        value_e = table[(index + 2) % len(table)]
        sum_initial = (index_b + value_e) % len(table)
        initial_value = table[sum_initial]
        table[sum_initial], table[(index + 2) % len(table)] = (
            table[(index + 2) % len(table)],
            initial_value,
        )
        index_b = sum_initial
    return output


def _random_prefix(numbers: list[int] | tuple[int, ...] | None) -> list[int]:
    if numbers is None:
        numbers = [random.randrange(10_000) for _ in range(3)]
    if not isinstance(numbers, (list, tuple)) or len(numbers) != 3:
        raise ValueError("test_options.random_values must contain exactly 3 integers")

    result: list[int] = []
    for number in numbers:
        if (
            isinstance(number, bool)
            or not isinstance(number, int)
            or not 0 <= number < 10_000
        ):
            raise ValueError(
                "test_options.random_values entries must be integers in [0, 9999]"
            )
        low, high = number & 0xFF, number >> 8
        result.extend(
            (
                (low & 0xAA) | 1,
                (low & 0x55) | 2,
                (high & 0xAA) | 5,
                (high & 0x55) | 40,
            )
        )
    return result


def _fingerprint() -> str:
    inner_width = random.randint(1024, 1920)
    inner_height = random.randint(768, 1080)
    outer_width = inner_width + random.randint(24, 32)
    outer_height = inner_height + random.randint(75, 90)
    screen_y = random.choice((0, 30))
    size_width = random.randint(1024, 1920)
    size_height = random.randint(768, 1080)
    avail_width = random.randint(1280, 1920)
    avail_height = random.randint(800, 1080)
    return "|".join(
        str(value)
        for value in (
            inner_width,
            inner_height,
            outer_width,
            outer_height,
            0,
            screen_y,
            0,
            0,
            size_width,
            size_height,
            avail_width,
            avail_height,
            inner_width,
            inner_height,
            24,
            24,
            "Win32",
        )
    )


def _timestamp(options: dict, key: str, fallback: int | None = None) -> int:
    value = options.get(key)
    if value is None:
        value = options.get("timestamp_ms", fallback)
    if value is None:
        value = int(time.time() * 1000)
    if isinstance(value, bool):
        raise ValueError(f"test_options.{key} must be an integer")
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"test_options.{key} must be an integer") from exc
    if value < 0:
        raise ValueError(f"test_options.{key} must be non-negative")
    return value


def _generate(raw_query: str, user_agent: str, body: str, options: dict) -> str:
    fingerprint = options.get("browser_fingerprint")
    if fingerprint is None:
        fingerprint = _fingerprint()
    if not isinstance(fingerprint, str) or not fingerprint or not fingerprint.isascii():
        raise ValueError(
            "test_options.browser_fingerprint must be a non-empty ASCII string"
        )

    start_time = _timestamp(options, "start_time_ms")
    query_hash = _double_sm3(raw_query)
    body_hash = _double_sm3(body)
    ua_hash = _sm3(
        _custom_b64(_rc4(_UA_KEY, user_agent), _UA_ALPHABET).encode("ascii")
    )
    fixed_start = "start_time_ms" in options or "timestamp_ms" in options
    end_time = _timestamp(
        options, "end_time_ms", start_time if fixed_start else None
    )

    fields = {
        8: 3,
        18: 44,
        20: (start_time >> 24) & 0xFF,
        21: (start_time >> 16) & 0xFF,
        22: (start_time >> 8) & 0xFF,
        23: start_time & 0xFF,
        24: start_time >> 32,
        25: start_time >> 40,
        26: 0,
        27: 0,
        28: 0,
        29: 0,
        30: 0,
        31: 1,
        32: 0,
        33: 0,
        34: 0,
        35: 0,
        36: 0,
        37: 14,
        38: query_hash[21],
        39: query_hash[22],
        40: body_hash[21],
        41: body_hash[22],
        42: ua_hash[23],
        43: ua_hash[24],
        44: (end_time >> 24) & 0xFF,
        45: (end_time >> 16) & 0xFF,
        46: (end_time >> 8) & 0xFF,
        47: end_time & 0xFF,
        48: 3,
        49: end_time >> 32,
        50: end_time >> 40,
        51: 0,
        52: 0,
        53: 0,
        54: 0,
        55: 0,
        56: 6383,
        57: 6383 & 0xFF,
        58: (6383 >> 8) & 0xFF,
        59: 0,
        60: 0,
        64: len(fingerprint),
        65: len(fingerprint),
        66: 0,
        69: 0,
        70: 0,
        71: 0,
    }
    values = [fields.get(index, 0) for index in _SORT_INDEX]
    values.extend(fingerprint.encode("ascii"))
    values.append(reduce(xor, (fields.get(index, 0) for index in _CHECK_INDEX)))
    encoded = _random_prefix(options.get("random_values")) + _transform(values)
    return _custom_b64(encoded, _ALPHABET)


def a_bogus(payload: dict) -> dict:
    """返回 ``a_bogus`` 签名及签名后的查询串。"""

    raw_query = payload.get("raw_query")
    user_agent = payload.get("user_agent")
    body = payload.get("body", "")
    options = payload.get("test_options") or {}
    if not isinstance(raw_query, str) or not raw_query:
        raise ValueError("raw_query required")
    if not isinstance(user_agent, str) or not user_agent:
        raise ValueError("user_agent required")
    if not user_agent.isascii():
        raise ValueError("user_agent must be ASCII")
    if not isinstance(body, str):
        raise ValueError("body must be a string")
    if not isinstance(options, dict):
        raise ValueError("test_options must be an object")

    value = _generate(raw_query, user_agent, body, options)
    return {"a_bogus": value, "query": f"{raw_query}&a_bogus={value}"}


def index_decrypt(payload: dict) -> dict:
    """在本地解密 Trend Insight ``x-encrypted: 2`` 响应体。"""

    if payload.get("x_encrypted") != "2":
        raise ValueError("x_encrypted must be '2'")

    body = payload.get("body")
    if not isinstance(body, str) or not body:
        raise ValueError("body (base64 ciphertext) required")
    try:
        encoded = body.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("body must be ASCII base64") from exc
    if len(encoded) > _INDEX_MAX_BASE64_BYTES:
        raise ValueError("body exceeds encrypted response size limit")
    if len(encoded) % 4:
        raise ValueError("body must be canonical base64")
    try:
        ciphertext = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("body must be valid base64") from exc
    if base64.b64encode(ciphertext) != encoded:
        raise ValueError("body must be canonical base64")
    if not ciphertext or len(ciphertext) % _INDEX_BLOCK_BYTES:
        raise ValueError("ciphertext length must be a non-zero multiple of 16 bytes")
    if len(ciphertext) > _INDEX_MAX_CIPHERTEXT_BYTES:
        raise ValueError("ciphertext exceeds encrypted response size limit")

    decryptor = Cipher(
        algorithms.AES(_INDEX_V2_KEY),
        modes.CBC(_INDEX_V2_IV),
    ).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    try:
        plaintext_bytes = unpadder.update(padded) + unpadder.finalize()
    except ValueError as exc:
        raise ValueError("ciphertext has invalid PKCS#7 padding") from exc
    if len(plaintext_bytes) > _INDEX_MAX_PLAINTEXT_BYTES:
        raise ValueError("plaintext exceeds response size limit")
    try:
        plaintext = plaintext_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("decrypted plaintext must be valid UTF-8") from exc
    return {"plaintext": plaintext}
