from __future__ import annotations

import unittest

from reverse.twitter_reverse.labels import (
    DEFAULT_EXPAND_MAX_FOLLOWERS,
    DEFAULT_EXPAND_MIN_FOLLOWERS,
    DEFAULT_KOL_FOLLOWING_RATIO,
    DEFAULT_KOL_MIN_FOLLOWERS,
    DEFAULT_MUTUAL_MIN_COUNT,
    DEFAULT_MUTUAL_RATIO_MAX,
    DEFAULT_MUTUAL_RATIO_MIN,
    account_tag,
    is_expand_hub,
)


_DEFAULT_TAG = {
    "kol_min_followers": DEFAULT_KOL_MIN_FOLLOWERS,
    "kol_following_ratio": DEFAULT_KOL_FOLLOWING_RATIO,
    "mutual_ratio_min": DEFAULT_MUTUAL_RATIO_MIN,
    "mutual_ratio_max": DEFAULT_MUTUAL_RATIO_MAX,
    "mutual_min_count": DEFAULT_MUTUAL_MIN_COUNT,
}
_DEFAULT_HUB = {
    "expand_min_followers": DEFAULT_EXPAND_MIN_FOLLOWERS,
    "expand_max_followers": DEFAULT_EXPAND_MAX_FOLLOWERS,
}


class TwitterLabelsTest(unittest.TestCase):
    def test_account_tag_missing_counts_are_none(self) -> None:
        cases = (
            (None, None),
            (None, 500),
            (500, None),
            (None, 0),
            (0, None),
        )
        for followers, following in cases:
            with self.subTest(followers=followers, following=following):
                self.assertEqual(
                    account_tag(followers, following, **_DEFAULT_TAG),
                    "none",
                )

    def test_account_tag_default_thresholds(self) -> None:
        cases = (
            (19999, 2000, "none"),
            (20000, 1, "none"),
            (20001, 2000, "kol"),
            (20001, 2001, "none"),
            (500, 500, "mutual_blue"),
            (50, 50, "mutual_blue"),
            (49, 49, "none"),
            (88000, 410, "kol"),
            (21000, 18000, "mutual_blue"),
        )
        for followers, following, expected in cases:
            with self.subTest(followers=followers, following=following):
                self.assertEqual(
                    account_tag(followers, following, **_DEFAULT_TAG),
                    expected,
                )

    def test_is_expand_hub_default_range(self) -> None:
        cases = (
            ("mutual_blue", 3000, True),
            ("mutual_blue", 50, True),
            ("mutual_blue", 49, False),
            ("mutual_blue", 10000, True),
            ("mutual_blue", 10001, False),
            ("kol", 88000, False),
            ("kol", 3000, False),
            ("none", 3000, False),
            ("mutual_blue", None, False),
        )
        for tag, followers, expected in cases:
            with self.subTest(tag=tag, followers=followers):
                self.assertEqual(
                    is_expand_hub(tag, followers, **_DEFAULT_HUB),
                    expected,
                )

    def test_custom_thresholds_change_behavior(self) -> None:
        self.assertEqual(account_tag(11, 0, **_DEFAULT_TAG), "none")
        self.assertEqual(
            account_tag(
                11,
                0,
                kol_min_followers=10,
                kol_following_ratio=DEFAULT_KOL_FOLLOWING_RATIO,
                mutual_ratio_min=DEFAULT_MUTUAL_RATIO_MIN,
                mutual_ratio_max=DEFAULT_MUTUAL_RATIO_MAX,
                mutual_min_count=DEFAULT_MUTUAL_MIN_COUNT,
            ),
            "kol",
        )
        self.assertEqual(account_tag(50, 50, **_DEFAULT_TAG), "mutual_blue")
        self.assertEqual(
            account_tag(
                49,
                49,
                kol_min_followers=DEFAULT_KOL_MIN_FOLLOWERS,
                kol_following_ratio=DEFAULT_KOL_FOLLOWING_RATIO,
                mutual_ratio_min=DEFAULT_MUTUAL_RATIO_MIN,
                mutual_ratio_max=DEFAULT_MUTUAL_RATIO_MAX,
                mutual_min_count=49,
            ),
            "mutual_blue",
        )
        self.assertTrue(is_expand_hub("mutual_blue", 50, **_DEFAULT_HUB))
        self.assertFalse(
            is_expand_hub(
                "mutual_blue",
                50,
                expand_min_followers=100,
                expand_max_followers=DEFAULT_EXPAND_MAX_FOLLOWERS,
            )
        )

    def test_thresholds_are_keyword_only(self) -> None:
        with self.assertRaises(TypeError):
            account_tag(20001, 2000, 20000, 0.1, 0.5, 2.0, 100)  # type: ignore[misc]
        with self.assertRaises(TypeError):
            is_expand_hub("mutual_blue", 3000, 1000, 10000)  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
