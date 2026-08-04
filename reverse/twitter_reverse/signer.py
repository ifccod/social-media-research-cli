from __future__ import annotations

import math
import re

from .errors import TwitterInputError, TwitterSignatureError


MAX_TWEET_ID = (1 << 64) - 1

_TWEET_ID_RE = re.compile(r"^[1-9]\d{0,19}$")
_RADIX_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def normalize_tweet_id(value: str | int) -> str:
    """校验并规范化无符号 64 位 X snowflake 标识符。"""

    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise TwitterInputError("tweet ID must be a decimal string or integer")
    candidate = str(value).strip()
    if not _TWEET_ID_RE.fullmatch(candidate):
        raise TwitterInputError("tweet ID must be a positive decimal snowflake")
    if int(candidate) > MAX_TWEET_ID:
        raise TwitterInputError("tweet ID exceeds the unsigned 64-bit snowflake range")
    return candidate


def _double_to_radix(value: float, radix: int = 36) -> str:
    """移植 V8 的有限双精度进制转换，以匹配 Number.toString()。"""

    if not 2 <= radix <= 36:
        raise TwitterSignatureError("radix must be between 2 and 36")
    if not math.isfinite(value) or value == 0:
        raise TwitterSignatureError("token input must be a finite non-zero number")

    negative = value < 0
    if negative:
        value = -value

    integer = float(math.floor(value))
    fraction = value - integer
    delta = 0.5 * (math.nextafter(value, math.inf) - value)
    if delta <= 0:
        delta = math.nextafter(0.0, math.inf)

    fractional_digits: list[str] = []
    if fraction >= delta:
        fractional_digits.append(".")
        while True:
            fraction *= radix
            delta *= radix
            digit = int(fraction)
            fractional_digits.append(_RADIX_DIGITS[digit])
            fraction -= digit

            round_up = fraction > 0.5 or (fraction == 0.5 and bool(digit & 1))
            if round_up and fraction + delta > 1:
                while True:
                    previous = fractional_digits.pop()
                    if previous == ".":
                        integer += 1
                        break
                    previous_digit = _RADIX_DIGITS.index(previous)
                    if previous_digit + 1 < radix:
                        fractional_digits.append(_RADIX_DIGITS[previous_digit + 1])
                        break
                break
            if fraction < delta:
                break

    # X snowflake 不超过 uint64，缩放后的整数远小于 2**53，因此 Python
    # 整数除法与 V8 的双精度路径结果一致。
    integer_value = int(integer)
    integer_digits: list[str] = []
    while True:
        integer_value, remainder = divmod(integer_value, radix)
        integer_digits.append(_RADIX_DIGITS[remainder])
        if integer_value == 0:
            break

    result = "".join(reversed(integer_digits)) + "".join(fractional_digits)
    return f"-{result}" if negative else result


class TwitterSyndicationSigner:
    """生成 X tweet-result 接口接受的匿名令牌。"""

    @staticmethod
    def base36(tweet_id: str | int) -> str:
        identifier = normalize_tweet_id(tweet_id)
        try:
            value = (float(identifier) / 1e15) * math.pi
            return _double_to_radix(value, 36)
        except (OverflowError, ValueError) as exc:
            raise TwitterSignatureError("Syndication radix conversion failed") from exc

    @classmethod
    def token(cls, tweet_id: str | int) -> str:
        """复现 ``Number(id) / 1e15 * Math.PI`` 和 V8 ``toString(36)``。"""

        token = cls.base36(tweet_id).replace("0", "").replace(".", "")
        if not token:
            raise TwitterSignatureError("Syndication token calculation produced no data")
        return token

    @classmethod
    def sign(cls, tweet_id: str | int) -> dict[str, str]:
        identifier = normalize_tweet_id(tweet_id)
        return {"id": identifier, "token": cls.token(identifier)}


TwitterSigner = TwitterSyndicationSigner


__all__ = [
    "MAX_TWEET_ID",
    "TwitterSigner",
    "TwitterSyndicationSigner",
    "normalize_tweet_id",
]
