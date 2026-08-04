from __future__ import annotations

import base64
import binascii
import hashlib
from urllib.parse import urlsplit

from .errors import XiguaResponseError

PLAY_URL_PASSPHRASE = "xigua.fe.web_mobile"

_SBOX = (
    0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
    0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
    0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
    0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
    0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
    0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
    0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
    0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
    0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
    0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
    0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
    0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
    0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
    0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
    0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
    0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16,
)
_INV_SBOX = tuple(_SBOX.index(value) for value in range(256))
_RCON = (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)


def _multiply(left: int, right: int) -> int:
    result = 0
    for _ in range(8):
        if right & 1:
            result ^= left
        high = left & 0x80
        left = (left << 1) & 0xFF
        if high:
            left ^= 0x1B
        right >>= 1
    return result


def _expand_aes256_key(key: bytes) -> list[bytes]:
    if len(key) != 32:
        raise ValueError("AES-256 requires a 32-byte key")
    words = [list(key[index : index + 4]) for index in range(0, 32, 4)]
    for index in range(8, 60):
        value = words[index - 1][:]
        if index % 8 == 0:
            value = value[1:] + value[:1]
            value = [_SBOX[item] for item in value]
            value[0] ^= _RCON[index // 8]
        elif index % 8 == 4:
            value = [_SBOX[item] for item in value]
        words.append([left ^ right for left, right in zip(words[index - 8], value)])
    return [bytes(sum(words[index : index + 4], [])) for index in range(0, 60, 4)]


def _add_round_key(state: list[list[int]], key: bytes) -> None:
    for column in range(4):
        for row in range(4):
            state[column][row] ^= key[column * 4 + row]


def _inverse_shift_rows(state: list[list[int]]) -> None:
    for row in range(1, 4):
        values = [state[column][row] for column in range(4)]
        values = values[-row:] + values[:-row]
        for column, value in enumerate(values):
            state[column][row] = value


def _inverse_mix_columns(state: list[list[int]]) -> None:
    for column in range(4):
        a, b, c, d = state[column]
        state[column] = [
            _multiply(a, 14) ^ _multiply(b, 11) ^ _multiply(c, 13) ^ _multiply(d, 9),
            _multiply(a, 9) ^ _multiply(b, 14) ^ _multiply(c, 11) ^ _multiply(d, 13),
            _multiply(a, 13) ^ _multiply(b, 9) ^ _multiply(c, 14) ^ _multiply(d, 11),
            _multiply(a, 11) ^ _multiply(b, 13) ^ _multiply(c, 9) ^ _multiply(d, 14),
        ]


def _decrypt_block(block: bytes, round_keys: list[bytes]) -> bytes:
    state = [list(block[index : index + 4]) for index in range(0, 16, 4)]
    _add_round_key(state, round_keys[14])
    for round_number in range(13, 0, -1):
        _inverse_shift_rows(state)
        for column in range(4):
            state[column] = [_INV_SBOX[value] for value in state[column]]
        _add_round_key(state, round_keys[round_number])
        _inverse_mix_columns(state)
    _inverse_shift_rows(state)
    for column in range(4):
        state[column] = [_INV_SBOX[value] for value in state[column]]
    _add_round_key(state, round_keys[0])
    return bytes(sum(state, []))


def _decrypt_aes256_cbc(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    if not ciphertext or len(ciphertext) % 16 or len(iv) != 16:
        raise XiguaResponseError("invalid AES-CBC ciphertext")
    keys = _expand_aes256_key(key)
    output = bytearray()
    previous = iv
    for index in range(0, len(ciphertext), 16):
        block = ciphertext[index : index + 16]
        clear = _decrypt_block(block, keys)
        output.extend(left ^ right for left, right in zip(clear, previous))
        previous = block
    padding = output[-1]
    if padding < 1 or padding > 16 or output[-padding:] != bytes([padding]) * padding:
        raise XiguaResponseError("invalid play URL padding")
    return bytes(output[:-padding])


def _evp_bytes_to_key(password: bytes, salt: bytes) -> tuple[bytes, bytes]:
    derived = bytearray()
    previous = b""
    while len(derived) < 48:
        previous = hashlib.md5(previous + password + salt).digest()
        derived.extend(previous)
    return bytes(derived[:32]), bytes(derived[32:48])


def decrypt_play_url(value: str, *, passphrase: str = PLAY_URL_PASSPHRASE) -> str:
    """解密 reverse(CryptoJS.AES.encrypt(url, passphrase).toString())。"""
    if not isinstance(value, str) or not value.strip():
        raise XiguaResponseError("missing encrypted play URL")
    if not isinstance(passphrase, str) or not passphrase:
        raise XiguaResponseError("missing play URL passphrase")
    try:
        raw = base64.b64decode(value.strip()[::-1], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise XiguaResponseError("invalid encrypted play URL encoding") from exc
    if len(raw) < 32 or raw[:8] != b"Salted__":
        raise XiguaResponseError("invalid CryptoJS OpenSSL envelope")
    key, iv = _evp_bytes_to_key(passphrase.encode("utf-8"), raw[8:16])
    try:
        clear = _decrypt_aes256_cbc(raw[16:], key, iv).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise XiguaResponseError("decrypted play URL is not UTF-8") from exc
    parsed = urlsplit(clear)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise XiguaResponseError("decrypted value is not a public HTTP URL")
    return clear
