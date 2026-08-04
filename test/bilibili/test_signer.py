from __future__ import annotations

import unittest

from reverse.bilibili_reverse.errors import (
    BilibiliError,
    BilibiliInputError,
    BilibiliResponseError,
    BilibiliSignatureError,
)
from reverse.bilibili_reverse.signer import BilibiliAppSigner, BilibiliWbiSigner


class BilibiliSignerTest(unittest.TestCase):
    IMG_KEY = "7cd084941338484aae1ad9425b84077c"
    SUB_KEY = "4932caff0ff746eab6f01bf08b70ac45"

    def test_error_types_share_the_public_base(self) -> None:
        self.assertTrue(issubclass(BilibiliInputError, BilibiliError))
        self.assertTrue(issubclass(BilibiliResponseError, BilibiliError))
        self.assertTrue(issubclass(BilibiliSignatureError, BilibiliError))

    def test_android_app_signature_matches_fixed_vector(self) -> None:
        params = {
            "aid": 2,
            "build": 6840300,
            "mobi_app": "android",
            "platform": "android",
        }

        signed = BilibiliAppSigner().sign(params, timestamp=1_700_000_000)

        self.assertEqual(params.get("ts"), None)
        self.assertEqual(signed["appkey"], "1d8b6e7d45233436")
        self.assertEqual(signed["ts"], "1700000000")
        self.assertEqual(signed["sign"], "49bdfeba2db4d63f9c17158c7c5e45dd")
        self.assertEqual(
            BilibiliAppSigner().sign_query(params, timestamp=1_700_000_000),
            "aid=2&appkey=1d8b6e7d45233436&build=6840300&"
            "mobi_app=android&platform=android&ts=1700000000&"
            "sign=49bdfeba2db4d63f9c17158c7c5e45dd",
        )

    def test_wbi_mixin_and_signature_match_fixed_vectors(self) -> None:
        signer = BilibiliWbiSigner(self.IMG_KEY, self.SUB_KEY)

        self.assertEqual(
            signer.derive_mixin_key(self.IMG_KEY, self.SUB_KEY),
            "ea1db124af3c7062474693fa704f4ff8",
        )
        self.assertEqual(
            signer.sign_query(
                {"foo": 114, "bar": 514, "zab": 1919810},
                wts=1_684_746_387,
            ),
            "bar=514&foo=114&wts=1684746387&zab=1919810&"
            "w_rid=a1d48f59663db6078c92dccb249618ba",
        )

    def test_wbi_filters_reserved_characters_and_accepts_image_urls(self) -> None:
        signer = BilibiliWbiSigner(
            f"https://i0.hdslb.com/bfs/wbi/{self.IMG_KEY}.png",
            f"https://i0.hdslb.com/bfs/wbi/{self.SUB_KEY}.png",
        )

        signed = signer.sign({"keyword": "a!b'c(d)*e", "page": 1}, wts=0)

        self.assertEqual(signed["keyword"], "abcde")
        self.assertEqual(signed["wts"], "0")
        self.assertEqual(signed["w_rid"], "602f381690ecf246d9f23a83317774b4")

    def test_invalid_input_and_missing_wbi_keys_are_layered(self) -> None:
        with self.assertRaises(BilibiliInputError):
            BilibiliAppSigner().sign({"aid": None}, timestamp=0)  # type: ignore[dict-item]
        with self.assertRaises(BilibiliInputError):
            BilibiliAppSigner().sign({}, timestamp=True)  # type: ignore[arg-type]
        with self.assertRaises(BilibiliSignatureError):
            BilibiliWbiSigner().sign({}, wts=0)
        with self.assertRaises(BilibiliSignatureError):
            BilibiliWbiSigner("not-a-key", self.SUB_KEY)


if __name__ == "__main__":
    unittest.main()
