from __future__ import annotations


DEFAULT_KOL_MIN_FOLLOWERS = 20000
DEFAULT_KOL_FOLLOWING_RATIO = 0.1
DEFAULT_MUTUAL_RATIO_MIN = 0.5
DEFAULT_MUTUAL_RATIO_MAX = 2.0
DEFAULT_MUTUAL_MIN_COUNT = 50
DEFAULT_EXPAND_MIN_FOLLOWERS = 50
DEFAULT_EXPAND_MAX_FOLLOWERS = 10000


def account_tag(
    followers: int | None,
    following: int | None,
    *,
    kol_min_followers: int,
    kol_following_ratio: float,
    mutual_ratio_min: float,
    mutual_ratio_max: float,
    mutual_min_count: int,
) -> str:
    """按粉丝/关注数打 kol、mutual_blue 或 none。"""

    if followers is None or following is None:
        return "none"
    if followers > kol_min_followers and following < followers * kol_following_ratio:
        return "kol"
    if (
        followers >= mutual_min_count
        and following >= mutual_min_count
        and mutual_ratio_min <= following / followers <= mutual_ratio_max
    ):
        return "mutual_blue"
    return "none"


def is_expand_hub(
    tag: str,
    followers: int | None,
    *,
    expand_min_followers: int,
    expand_max_followers: int,
) -> bool:
    """仅 mutual_blue 且粉丝落在闭区间时作为扩散枢纽。"""

    if tag != "mutual_blue" or followers is None:
        return False
    return expand_min_followers <= followers <= expand_max_followers
