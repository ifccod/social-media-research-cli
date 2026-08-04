from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from reverse.bilibili_reverse.errors import BilibiliInputError, BilibiliResponseError
from reverse.bilibili_reverse.mobile_profile import (
    BUVID_ENV,
    DEVICE_ID_ENV,
    PROFILE_NAME,
    generate_mobile_profile,
    load_mobile_profile,
    MobileProfile,
    validate_mobile_profile,
)


class MobileProfileTests(unittest.TestCase):
    def test_generate_matches_android_identity_shape(self) -> None:
        chunks = iter((bytes(range(18)), bytes(range(32))))
        profile = generate_mobile_profile(
            now=datetime(2026, 7, 28, tzinfo=timezone.utc),
            random_bytes=lambda _: next(chunks),
        )

        validate_mobile_profile(profile)
        self.assertEqual(profile.buvid, "XX000102030405060708090A0B0C0D0E0F101")
        self.assertEqual(len(profile.device_id), 27)
        self.assertEqual(profile.created_at, "2026-07-28T00:00:00Z")
        with self.assertRaisesRegex(BilibiliInputError, "时区"):
            validate_mobile_profile(
                type(profile)(
                    version=profile.version,
                    buvid=profile.buvid,
                    device_id=profile.device_id,
                    created_at="2026-07-28T00:00:00",
                )
            )
        with self.assertRaisesRegex(BilibiliInputError, "Unix epoch"):
            validate_mobile_profile(
                MobileProfile(
                    version=profile.version,
                    buvid=profile.buvid,
                    device_id=profile.device_id,
                    created_at="1969-12-31T23:59:59Z",
                )
            )

    def test_load_creates_one_private_persistent_identity(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            first = load_mobile_profile(home=root, environ={})
            second = load_mobile_profile(home=root, environ={})
            path = Path(root) / f"{PROFILE_NAME}.json"

            self.assertEqual(first, second)
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(Path(root).stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["buvid"], first.buvid
            )

    def test_concurrent_loads_select_one_complete_identity(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with ThreadPoolExecutor(max_workers=8) as pool:
                profiles = list(
                    pool.map(
                        lambda _: load_mobile_profile(home=root, environ={}),
                        range(24),
                    )
                )

            self.assertEqual(len({profile.buvid for profile in profiles}), 1)
            self.assertEqual(len({profile.device_id for profile in profiles}), 1)

    def test_creation_works_when_fchmod_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with patch("reverse.bilibili_reverse.mobile_profile._FCHMOD", None):
                profile = load_mobile_profile(home=root, environ={})

            self.assertEqual(
                json.loads(
                    (Path(root) / f"{PROFILE_NAME}.json").read_text(encoding="utf-8")
                )["device_id"],
                profile.device_id,
            )

    def test_explicit_identity_requires_both_fields_and_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "profiles"
            with self.assertRaisesRegex(BilibiliInputError, "必须同时设置"):
                load_mobile_profile(home=root, environ={BUVID_ENV: "XX" + "A" * 35})
            self.assertFalse(root.exists())

            environment = {
                BUVID_ENV: "XX" + "A" * 35,
                DEVICE_ID_ENV: "B" * 27,
            }
            explicit = load_mobile_profile(
                home=root,
                environ=environment,
                now=lambda: datetime(2026, 7, 28, tzinfo=timezone.utc),
            )
            reloaded = load_mobile_profile(home=root, environ={})

            self.assertEqual(explicit, reloaded)
            self.assertEqual(explicit.created_at, "2026-07-28T00:00:00Z")

    def test_corrupt_identity_is_preserved_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / f"{PROFILE_NAME}.json"
            path.write_text("{bad", encoding="utf-8")
            path.chmod(0o600)

            with self.assertRaisesRegex(BilibiliResponseError, "已损坏"):
                load_mobile_profile(home=root, environ={})
            self.assertEqual(path.read_text(encoding="utf-8"), "{bad")

    def test_explicit_identity_repairs_corrupt_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / f"{PROFILE_NAME}.json"
            path.write_text("{bad", encoding="utf-8")
            path.chmod(0o600)

            profile = load_mobile_profile(
                home=root,
                environ={
                    BUVID_ENV: "XX" + "C" * 35,
                    DEVICE_ID_ENV: "D" * 27,
                },
            )

            self.assertEqual(profile.buvid, "XX" + "C" * 35)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["device_id"], "D" * 27
            )


if __name__ == "__main__":
    unittest.main()
