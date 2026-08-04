from __future__ import annotations

import base64
import unittest

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from reverse.douyin_reverse import signing


class DouyinSigningTest(unittest.TestCase):
    def test_a_bogus_matches_fixed_vector(self) -> None:
        raw_query = (
            "device_platform=webapp&aid=6383&channel=channel_pc_web&count=18"
        )
        out = signing.a_bogus(
            {
                "raw_query": raw_query,
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "Chrome/131.0.0.0"
                ),
                "test_options": {
                    "start_time_ms": 1_700_000_000_123,
                    "end_time_ms": 1_700_000_000_127,
                    "random_values": [1234, 5678, 9012],
                    "browser_fingerprint": (
                        "1536|742|1536|864|0|0|0|0|1536|864|1536|864|"
                        "1536|742|24|24|Win32"
                    ),
                },
            }
        )
        self.assertEqual(
            out["a_bogus"],
            "E7mhBdu2krjihxWT56KLfY3q6Wp3Y2OI0SVkMD2f1dvJqL39HMTa9exoIBGvXFjjwG/"
            "-Ieujy4hbT3ohrQ2y0Hwf9W0L/25ksDSkKl5Q5xSSs1X9eghgJ04qmkt5SMx2RvB-"
            "rOXmqhZHKRbp09oHmhK4bIOwu3GMkj==",
        )
        self.assertEqual(out["query"], f"{raw_query}&a_bogus={out['a_bogus']}")

    def test_index_decrypt_matches_fixed_vector(self) -> None:
        self.assertEqual(
            signing.index_decrypt(
                {
                    "x_encrypted": "2",
                    "body": "PRLMa3x7laXGjz7PmvIm1g==",
                }
            ),
            {"plaintext": "{}"},
        )

    def test_index_hot_topics_fixture_decrypts(self) -> None:
        ciphertext = (
            "TXfxuwPPJeFi3poDXM46C5Y0BxajMNaZINoorMmptnE17jIwZo6BOQhbdpDJNhDa"
            "HIEc43teQtxKaN3K0XYicN9erQ2f53H5gh4n9fvstkYtcyju0sCuja7OzlLUMlDz"
            "M9CIr8JrRjDfLdar6f69JBV957zSDCLOUao8rcg5TNA="
        )
        self.assertEqual(
            signing.index_decrypt({"x_encrypted": "2", "body": ciphertext}),
            {
                "plaintext": (
                    "{\"hot_topics\":[{\"topic_name\":\"TARGET_TOPIC\","
                    "\"topic_id\":\"TARGET_TOPIC_ID\"}],\"BaseResp\":"
                    "{\"StatusMessage\":\"\",\"StatusCode\":0}}"
                ),
            },
        )

    def test_index_decrypt_rejects_wrong_version(self) -> None:
        for version in (None, "", "1", "3", 2):
            with self.subTest(version=version), self.assertRaises(ValueError):
                signing.index_decrypt(
                    {
                        "x_encrypted": version,
                        "body": "PRLMa3x7laXGjz7PmvIm1g==",
                    }
                )

    def test_index_decrypt_rejects_malformed_ciphertext(self) -> None:
        cases = {
            "non-base64": "!!!!",
            "non-canonical-base64": "PRLMa3x7laXGjz7PmvIm1h==",
            "not-a-full-block": base64.b64encode(b"short").decode("ascii"),
            "bad-padding": "PRLMa3x7laXGjz7PmvIm1w==",
        }
        for name, body in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                signing.index_decrypt({"x_encrypted": "2", "body": body})

    def test_index_decrypt_rejects_non_utf8_and_oversize_plaintext(self) -> None:
        def encrypt(plaintext: bytes) -> str:
            padder = padding.PKCS7(algorithms.AES.block_size).padder()
            padded = padder.update(plaintext) + padder.finalize()
            encryptor = Cipher(
                algorithms.AES(
                    bytes.fromhex("4a35db61325bef35e8513a1289c50bdc")
                ),
                modes.CBC(
                    bytes.fromhex("39e90c2e3821460f2f957fcf7a62dcf9")
                ),
            ).encryptor()
            return base64.b64encode(
                encryptor.update(padded) + encryptor.finalize()
            ).decode("ascii")

        with self.assertRaisesRegex(ValueError, "UTF-8"):
            signing.index_decrypt(
                {"x_encrypted": "2", "body": encrypt(b"\xff")}
            )

        original_limit = signing._INDEX_MAX_PLAINTEXT_BYTES
        try:
            signing._INDEX_MAX_PLAINTEXT_BYTES = 2
            with self.assertRaisesRegex(ValueError, "response size limit"):
                signing.index_decrypt(
                    {"x_encrypted": "2", "body": encrypt(b"abc")}
                )
        finally:
            signing._INDEX_MAX_PLAINTEXT_BYTES = original_limit


if __name__ == "__main__":
    unittest.main()
