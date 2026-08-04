from __future__ import annotations

import hashlib
import unittest

from reverse.tiktok_reverse.signer import TikTokSigner


class TikTokSignatureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.signer = TikTokSigner()

    @staticmethod
    def _options() -> dict[str, object]:
        return {
            "userAgent": "UA/FIXTURE",
            "body": '{"fixture":true}',
            "timestampMs": 1700000000123,
            "microseconds": 1700000000123456,
            "microsecondDelta": 321,
            "dynosaurRandomLow16": 0x1234,
            "gnarlyRandomLow16": 0x4567,
            "gnarlyRandom32": 0x89ABCDEF,
            "fingerprintValue": 2363850128,
            "counters": {
                "txr": 24,
                "tfr": 0,
                "ixr": 28,
                "ifr": 0,
                "dynosaurIxr": 4,
            },
            "dynosaurKeyHex": "".join(f"{value:02x}" for value in range(48)),
            "gnarlyKeyHex": "".join(f"{47 - value:02x}" for value in range(48)),
        }

    @staticmethod
    def _gnarly_fields(plain_hex: str) -> dict[int, bytes]:
        raw = bytes.fromhex(plain_hex)
        count = raw[0]
        fields: dict[int, bytes] = {}
        offset = 1
        while offset < len(raw):
            field = raw[offset]
            length = int.from_bytes(raw[offset + 1 : offset + 3], "big")
            offset += 3
            fields[field] = raw[offset : offset + length]
            offset += length
        if len(fields) != count or offset != len(raw):
            raise AssertionError("invalid Gnarly fixture encoding")
        return fields

    def test_hash_number_and_checksum_wire_vectors(self) -> None:
        hashes = {
            "": "811c9dc4",
            "hello": "7cb6b374",
            "aid=1988&count=20": "2443f87f",
            "\u4e2d\u6587": "62f0eab0",
        }
        for value, expected in hashes.items():
            with self.subTest(kind="hash", value=value):
                self.assertEqual(self.signer.call("hashHex", value), expected)

        numbers = {
            0: "dbdedfe00001",
            42: "ebd7dfe00002",
            255: "e3c3c7e00003",
            4294967295: "ebd7f73ff7d7cfc7c783000a",
        }
        for value, expected in numbers.items():
            with self.subTest(kind="number", value=value):
                self.assertEqual(self.signer.call("encodeNumberHex", value), expected)

        checksums = {
            0: "5cdedfe00001",
            42: "545adfe00002",
            255: "58544ee00003",
        }
        for value, expected in checksums.items():
            with self.subTest(kind="checksum", value=value):
                self.assertEqual(self.signer.call("encodeChecksumHex", value), expected)

    def test_gnarly_companion_and_header_fields_match_fixed_vector(self) -> None:
        plain_hex = self.signer.call(
            "gnarlyPlainHex",
            "aid=1988&count=20&msToken=fixture-token",
            self._options(),
        )
        fields = self._gnarly_fields(plain_hex)

        self.assertEqual(int.from_bytes(fields[16], "big"), 0x1B4C10ED)
        self.assertEqual(int.from_bytes(fields[0], "big"), 0x6330373E)

    def test_empty_query_report_signature_matches_fixed_vector(self) -> None:
        options = self._options()
        options["body"] = '{"magic":538969122}'
        result = self.signer.sign(
            "",
            user_agent=str(options.pop("userAgent")),
            ms_token="initial-token",
            body=str(options.pop("body")),
            **options,
        )

        self.assertTrue(result["query"].startswith("X-Dynosaur="))
        self.assertIn("&msToken=initial-token&X-Bogus=1&X-Gnarly=", result["query"])
        self.assertEqual(result["baseQueryHash"], "811c9dc4")
        self.assertEqual(result["gnarlyQueryMd5"], "c3584d878b0632759c9758c2d4743317")
        self.assertEqual(
            hashlib.sha256(result["query"].encode()).hexdigest(),
            "0fdd54e44bca848989817ee190a45cf6087940179b405641de6957112f16566b",
        )

    def test_telemetry_small_vector_matches_lzw_cipher_wire_format(self) -> None:
        key_hex = "".join(f"{value:02x}" for value in range(48))

        encoded = self.signer.call("encodeTelemetry", "{}", key_hex)

        self.assertEqual(
            encoded,
            "3Q32DDgdDjfhkEWKdfYBpDy/pJDvgi86hvR14kL54JjUZiSEKwKNsd6osnETQ7uuBwVFhf==",
        )


if __name__ == "__main__":
    unittest.main()
