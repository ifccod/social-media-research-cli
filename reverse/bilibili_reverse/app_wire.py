"""哔哩哔哩 App 协议共用的最小 protobuf wire 基元。"""

from __future__ import annotations

from .errors import BilibiliResponseError


def _wire_fields(
    payload: bytes, maximum: int, label: str
) -> list[tuple[int, int, int, bytes]]:
    """读取一层 protobuf 字段，并限制不可信响应的字段数量。"""

    fields: list[tuple[int, int, int, bytes]] = []
    offset = 0
    while offset < len(payload):
        tag, offset = _read_varint(payload, offset)
        number = tag >> 3
        wire_type = tag & 7
        if number < 1 or number >= 1 << 29:
            raise BilibiliResponseError(f"protobuf {label} tag 非法")
        scalar = 0
        raw = b""
        if wire_type == 0:
            scalar, offset = _read_varint(payload, offset)
        elif wire_type == 1:
            end = offset + 8
            if end > len(payload):
                raise BilibiliResponseError(f"protobuf {label} fixed64 解析失败")
            scalar = int.from_bytes(payload[offset:end], "little")
            offset = end
        elif wire_type == 2:
            size, offset = _read_varint(payload, offset)
            end = offset + size
            if end > len(payload):
                raise BilibiliResponseError(f"protobuf {label} bytes 解析失败")
            raw = payload[offset:end]
            offset = end
        elif wire_type == 5:
            end = offset + 4
            if end > len(payload):
                raise BilibiliResponseError(f"protobuf {label} fixed32 解析失败")
            scalar = int.from_bytes(payload[offset:end], "little")
            offset = end
        else:
            raise BilibiliResponseError(f"protobuf {label} wire type={wire_type} 非法")
        fields.append((number, wire_type, scalar, raw))
        if len(fields) > maximum:
            raise BilibiliResponseError(f"{label}字段数量超过 {maximum}")
    return fields


def _read_varint(payload: bytes, offset: int) -> tuple[int, int]:
    """从指定偏移读取一个无符号 64 位 varint。"""

    value = 0
    for index in range(10):
        if offset >= len(payload):
            raise BilibiliResponseError("protobuf varint 解析失败")
        current = payload[offset]
        offset += 1
        if index == 9 and current > 1:
            raise BilibiliResponseError("protobuf varint 溢出")
        value |= (current & 0x7F) << (index * 7)
        if current < 0x80:
            return value, offset
    raise BilibiliResponseError("protobuf varint 溢出")


def _proto_varint(number: int, value: int) -> bytes:
    """编码一个 varint 字段。"""

    return _encode_varint(number << 3) + _encode_varint(value)


def _proto_bytes(number: int, value: bytes) -> bytes:
    """编码 string、bytes 或嵌套 message 字段。"""

    return _encode_varint((number << 3) | 2) + _encode_varint(len(value)) + value


def _encode_varint(value: int) -> bytes:
    """编码一个无符号 64 位 varint。"""

    if not 0 <= value < 1 << 64:
        raise ValueError("protobuf varint 必须在 uint64 范围内")
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)
