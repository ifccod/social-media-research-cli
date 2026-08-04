from __future__ import annotations

import unittest

from reverse.twitter_reverse.errors import (
    TwitterError,
    TwitterInputError,
    TwitterResponseError,
    TwitterSignatureError,
)
from reverse.twitter_reverse.signer import MAX_TWEET_ID, TwitterSyndicationSigner, normalize_tweet_id


class TwitterSignerTest(unittest.TestCase):
    def test_error_types_share_the_public_base(self) -> None:
        self.assertTrue(issubclass(TwitterInputError, TwitterError))
        self.assertTrue(issubclass(TwitterResponseError, TwitterError))
        self.assertTrue(issubclass(TwitterSignatureError, TwitterError))

    def test_v8_base36_and_tokens_match_fixed_vectors(self) -> None:
        vectors = {
            "20": ("0.000000006dq1a2xwd93", "6dq1a2xwd93"),
            "123456789": ("0.0000ng9m4sqe3h", "ng9m4sqe3h"),
            "1000000000000000": ("3.53i5ab8p5f", "353i5ab8p5f"),
            "1460323737035677698": ("3jf.qq1vhqna", "3jfqq1vhqna"),
            "1628832338187636740": ("3y5.4libozsy", "3y54libozsy"),
            "1837264960789217459": ("4gb.xrs5o56v", "4gbxrs5o56v"),
            "2079150573920596294": ("51f.ue1jbd0h", "51fue1jbdh"),
            "2079384236730261989": ("51g.ktegoq0r", "51gktegoqr"),
            "18446744073709551615": ("18ps.5lqos4lc", "18ps5lqos4lc"),
        }

        for identifier, (base36, token) in vectors.items():
            with self.subTest(identifier=identifier):
                self.assertEqual(TwitterSyndicationSigner.base36(identifier), base36)
                self.assertEqual(TwitterSyndicationSigner.token(identifier), token)
                self.assertEqual(
                    TwitterSyndicationSigner.sign(identifier),
                    {"id": identifier, "token": token},
                )

    def test_snowflake_validation_is_strict(self) -> None:
        self.assertEqual(normalize_tweet_id(MAX_TWEET_ID), str(MAX_TWEET_ID))
        for value in (True, 0, -1, "", "0", "001", "12.3", "abc", MAX_TWEET_ID + 1):
            with self.subTest(value=value):
                with self.assertRaises(TwitterInputError):
                    normalize_tweet_id(value)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
