from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import AsyncMock, patch

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from reverse import browser_session
from reverse.browser_session import (
    BridgeDaemon,
    BrowserSessionError,
    INSTANCE_SUPERSEDED_CLOSE_CODE,
    INSTANCE_SUPERSEDED_CLOSE_REASON,
    PROTOCOL_VERSION,
    RPC_CANCELLATION_GRACE,
    RPC_TRANSPORT_MARGIN,
    _control_timeout,
    _control_token,
    _extension_id,
    _normalize_request,
    _read_registry,
    _rpc_timeout,
    _write_registry,
    authorize_browser_session,
)


INSTANCE_ID = "0" * 32
ORIGIN = "chrome-extension://abcdefghijklmnop"


def _close_details(connection: object) -> tuple[int | None, str | None]:
    source = connection if hasattr(connection, "close_code") else getattr(connection, "protocol")
    return getattr(source, "close_code"), getattr(source, "close_reason")


class BrowserSessionContractTest(unittest.TestCase):
    def test_macos_login_opens_chrome_without_applescript(self) -> None:
        completed = subprocess.CompletedProcess([], 0)
        with (
            patch.object(browser_session.sys, "platform", "darwin"),
            patch.object(
                browser_session.subprocess,
                "run",
                return_value=completed,
            ) as run,
            patch.object(browser_session.webbrowser, "get") as get_browser,
        ):
            opened = browser_session._open_chrome_url(
                "https://ads.tiktok.com/creative/creativestudio/create"
            )

        self.assertTrue(opened)
        run.assert_called_once_with(
            [
                "open",
                "-a",
                "Google Chrome",
                "https://ads.tiktok.com/creative/creativestudio/create",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        get_browser.assert_not_called()

    def test_origin_and_request_boundaries(self) -> None:
        self.assertEqual(_extension_id(f"{ORIGIN}/"), "abcdefghijklmnop")
        self.assertIsNone(_extension_id("https://abcdefghijklmnop/"))
        self.assertEqual(
            _normalize_request(
                {
                    "platform": "reddit",
                    "path": "/bridge/v1/reddit/home-feed",
                    "entries": [
                        ["sort", "BEST"],
                        ["limit", "20"],
                        ["after", ""],
                    ],
                    "referer": "https://www.reddit.com/",
                }
            )["entries"],
            [["sort", "BEST"], ["limit", "20"], ["after", ""]],
        )
        with self.assertRaises(BrowserSessionError):
            _normalize_request(
                {
                    "platform": "reddit",
                    "path": "https://example.com/",
                    "entries": [],
                }
            )

    def test_interactive_login_opens_once_and_waits_until_request_ready(self) -> None:
        statuses = [
            {"ready": False, "error": "extension_disconnected"},
            {
                "ready": True,
                "session": {"logged_in": True, "request_ready": False},
            },
            {
                "ready": True,
                "session": {"logged_in": True, "request_ready": True},
            },
        ]
        progress: list[dict[str, object]] = []
        with (
            patch.object(browser_session, "start_daemon") as start,
            patch.object(browser_session, "_open_chrome_url", return_value=True) as open_url,
            patch.object(
                browser_session,
                "call_daemon",
                new_callable=AsyncMock,
                side_effect=statuses,
            ) as status,
            patch.object(browser_session.time, "sleep") as sleep,
        ):
            result = authorize_browser_session(
                "tiktok_creative_studio",
                timeout=10,
                poll_interval=0.2,
                progress=progress.append,
            )

        self.assertTrue(result["ready"])
        self.assertTrue(result["session"]["request_ready"])
        start.assert_called_once_with()
        open_url.assert_called_once_with(
            "https://ads.tiktok.com/creative/creativestudio/create"
            "?from_creative=signup&region=row"
        )
        self.assertEqual(status.await_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(progress[-1]["state"], "ready")

    def test_interactive_login_can_wait_for_an_existing_loading_page(self) -> None:
        with (
            patch.object(browser_session, "start_daemon"),
            patch.object(browser_session, "_open_chrome_url") as open_url,
            patch.object(
                browser_session,
                "call_daemon",
                new_callable=AsyncMock,
                return_value={
                    "ready": True,
                    "session": {"logged_in": True, "request_ready": True},
                },
            ),
        ):
            result = authorize_browser_session(
                "tiktok_one",
                open_browser=False,
            )
        self.assertTrue(result["ready"])
        open_url.assert_not_called()

    def test_explicit_business_url_reopens_and_rechecks_a_distinct_context(
        self,
    ) -> None:
        library_url = "https://ads.tiktok.com/creative/inspiration/top-ads/library"
        statuses = [
            {
                "ready": True,
                "session": {"logged_in": False, "request_ready": True},
            },
            {
                "ready": True,
                "session": {"logged_in": False, "request_ready": True},
            },
        ]
        with (
            patch.object(browser_session, "start_daemon"),
            patch.object(
                browser_session,
                "_open_chrome_url",
                return_value=True,
            ) as open_url,
            patch.object(
                browser_session,
                "call_daemon",
                new_callable=AsyncMock,
                side_effect=statuses,
            ) as status,
            patch.object(browser_session.time, "sleep") as sleep,
        ):
            result = authorize_browser_session(
                "tiktok_creative_topads",
                url=library_url,
                timeout=10,
                poll_interval=0.2,
            )

        self.assertTrue(result["ready"])
        open_url.assert_called_once_with(library_url)
        self.assertEqual(status.await_count, 2)
        sleep.assert_called_once()

    def test_ads_manager_account_selection_opens_keyword_planner(self) -> None:
        progress: list[dict[str, object]] = []
        with (
            patch.object(browser_session, "start_daemon"),
            patch.object(browser_session, "_open_chrome_url") as open_url,
            patch.object(
                browser_session,
                "call_daemon",
                new_callable=AsyncMock,
                side_effect=[
                    {
                        "ready": False,
                        "error": "advertiser_account_required",
                    },
                    {
                        "ready": True,
                        "session": {
                            "logged_in": True,
                            "request_ready": True,
                        },
                    },
                ],
            ),
            patch.object(browser_session.time, "sleep"),
        ):
            result = authorize_browser_session(
                "tiktok_ads_manager",
                timeout=10,
                poll_interval=0.2,
                progress=progress.append,
            )

        self.assertTrue(result["ready"])
        open_url.assert_called_once_with(
            "https://ads.tiktok.com/i18n/search_ads_center/"
            "keyword-planner/creation"
        )
        self.assertIn(
            "advertiser_account_required",
            [str(item["state"]) for item in progress],
        )

    def test_interactive_login_reports_verification_until_it_clears(self) -> None:
        statuses = [
            {
                "ready": True,
                "session": {
                    "logged_in": True,
                    "request_ready": False,
                    "verification_required": True,
                },
            },
            {
                "ready": True,
                "session": {"logged_in": True, "request_ready": True},
            },
        ]
        progress: list[dict[str, object]] = []
        with (
            patch.object(browser_session, "start_daemon"),
            patch.object(browser_session, "_open_chrome_url", return_value=True),
            patch.object(
                browser_session,
                "call_daemon",
                new_callable=AsyncMock,
                side_effect=statuses,
            ),
            patch.object(browser_session.time, "sleep"),
        ):
            result = authorize_browser_session(
                "tiktok_creative",
                timeout=10,
                progress=progress.append,
            )

        self.assertTrue(result["ready"])
        self.assertIn(
            "verification_required",
            [str(item["state"]) for item in progress],
        )
        self.assertEqual(progress[-1]["state"], "ready")

    def test_ads_manager_account_page_opens_planner_and_waits_for_account(self) -> None:
        progress: list[dict[str, object]] = []
        statuses = [
            {
                "ready": True,
                "session": {
                    "fingerprint": {},
                    "logged_in": True,
                    "request_ready": False,
                    "verification_required": False,
                    "profile_required": False,
                },
            },
            {
                "ready": True,
                "session": {
                    "fingerprint": {"cookie_enabled": True},
                    "logged_in": True,
                    "request_ready": True,
                    "verification_required": False,
                    "profile_required": False,
                },
            },
        ]
        with (
            patch.object(browser_session, "start_daemon"),
            patch.object(
                browser_session,
                "_open_chrome_url",
                return_value=True,
            ) as open_url,
            patch.object(
                browser_session,
                "call_daemon",
                new_callable=AsyncMock,
                side_effect=statuses,
            ),
            patch.object(browser_session.time, "sleep") as sleep,
        ):
            result = authorize_browser_session(
                "tiktok_ads_manager",
                timeout=300,
                progress=progress.append,
            )

        self.assertTrue(result["ready"])
        open_url.assert_called_once_with(
            "https://ads.tiktok.com/i18n/search_ads_center/"
            "keyword-planner/creation"
        )
        self.assertIn(
            "advertiser_account_required",
            [str(item["state"]) for item in progress],
        )
        self.assertEqual(progress[-1]["state"], "ready")
        sleep.assert_called_once()

    def test_logged_in_runtime_wait_has_a_separate_short_deadline(self) -> None:
        status = {
            "ready": True,
            "session": {
                "fingerprint": {"cookie_enabled": True},
                "logged_in": True,
                "request_ready": False,
                "verification_required": False,
                "profile_required": False,
            },
        }
        with (
            patch.object(browser_session, "start_daemon"),
            patch.object(browser_session, "_open_chrome_url", return_value=True),
            patch.object(
                browser_session,
                "call_daemon",
                new_callable=AsyncMock,
                return_value=status,
            ),
            patch.object(browser_session, "LOGIN_RUNTIME_TIMEOUT", 0),
            patch.object(browser_session.time, "sleep"),
        ):
            with self.assertRaises(BrowserSessionError) as raised:
                authorize_browser_session(
                    "tiktok_one",
                    timeout=300,
                )

        self.assertEqual(raised.exception.code, "runtime_unavailable")
        self.assertIn("0 秒", str(raised.exception))

    def test_interactive_error_catalog_includes_verification(self) -> None:
        self.assertIn(
            "verification_required",
            browser_session.INTERACTIVE_LOGIN_ERRORS,
        )

    def test_request_normalization_for_commercial_platforms(self) -> None:
        with self.assertRaises(BrowserSessionError):
            _normalize_request(
                {
                    "platform": "reddit",
                    "path": "/api",
                    "entries": [],
                    "referer": "https://example.com/",
                }
            )
        with self.assertRaises(BrowserSessionError):
            _normalize_request(
                {
                    "platform": "reddit",
                    "path": "/bridge/v1/reddit/home-feed",
                    "entries": [],
                    "method": "POST",
                }
            )
        self.assertEqual(
            _normalize_request(
                {
                    "platform": "xiaohongshu",
                    "path": "/api/sns/web/v2/comment/page",
                    "entries": [],
                    "method": "POST",
                }
            )["method"],
            "POST",
        )
        self.assertEqual(
            _normalize_request(
                {
                    "platform": "tiktok_creative_studio",
                    "path": "/creative_bff_i18n/api/cue/generate-task/check",
                    "entries": [["taskId", "7667519430651838480"]],
                    "referer": (
                        "https://ads.tiktok.com/creative/creativestudio/create"
                        "?from_creative=signup&region=row"
                    ),
                }
            )["platform"],
            "tiktok_creative_studio",
        )
        self.assertEqual(
            _normalize_request(
                {
                    "platform": "tiktok_one",
                    "path": (
                        "/CreativeOne/MatchMaking/"
                        "QueryPartnerSearchSuggestWords"
                    ),
                    "entries": [["query", "coffee"]],
                    "referer": (
                        "https://ads.tiktok.com/creative/forpartners/"
                        "creator/explore?region=row"
                    ),
                }
            )["platform"],
            "tiktok_one",
        )
        self.assertEqual(
            _normalize_request(
                {
                    "platform": "tiktok_ads_manager",
                    "path": (
                        "/api/v4/i18n/search_ads/search_keyword/"
                        "mget_keyword_ideas/"
                    ),
                    "entries": [["keywords", '["wireless charger"]']],
                    "referer": (
                        "https://ads.tiktok.com/i18n/search_ads_center/"
                        "keyword-planner/creation"
                    ),
                }
            )["platform"],
            "tiktok_ads_manager",
        )
        large_image = "A" * 5000
        self.assertEqual(
            _normalize_request(
                {
                    "platform": "tiktok_creative_studio",
                    "path": (
                        "/creative_bff_i18n/api/cue/upload/local-image"
                    ),
                    "entries": [
                        ["name", "frame.png"],
                        ["mimeType", "image/png"],
                        ["dataBase64", large_image],
                    ],
                    "referer": (
                        "https://ads.tiktok.com/creative/"
                        "creativestudio/create"
                    ),
                }
            )["entries"][2][1],
            large_image,
        )
        with self.assertRaises(BrowserSessionError):
            _normalize_request(
                {
                    "platform": "tiktok_creative_studio",
                    "path": "/creative_bff_i18n/api/cue/generate-task/check",
                    "entries": [["taskId", large_image]],
                    "referer": (
                        "https://ads.tiktok.com/creative/"
                        "creativestudio/create"
                    ),
                }
            )

    def test_python_timeouts_cover_extension_cleanup(self) -> None:
        self.assertEqual(_rpc_timeout("reddit", "request"), 40)
        self.assertEqual(_rpc_timeout("reddit", "session"), 20)
        self.assertEqual(_rpc_timeout("xiaohongshu_pgy", "request"), 50)
        self.assertEqual(_rpc_timeout("xiaohongshu_pgy", "session"), 25)
        self.assertEqual(RPC_CANCELLATION_GRACE + RPC_TRANSPORT_MARGIN, 5)
        self.assertGreater(
            _control_timeout({"op": "request"}),
            _rpc_timeout("xiaohongshu_pgy", "request"),
        )
        self.assertGreater(
            _control_timeout({"op": "status"}),
            _control_timeout({"op": "request"}),
        )

    @unittest.skipIf(os.name == "nt", "POSIX permission bits required")
    def test_local_state_repairs_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "session"
            home.mkdir(mode=0o755)
            token_path = home / "control.token"
            token_path.write_text("x" * 43 + "\n", encoding="utf-8")
            token_path.chmod(0o644)

            self.assertEqual(_control_token(home), "x" * 43)
            self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(token_path.stat().st_mode), 0o600)

            registry = {
                "schema_version": 2,
                "instances": {},
                "platform_bindings": {},
            }
            _write_registry(home, registry)
            self.assertEqual(_read_registry(home), registry)
            self.assertEqual(
                stat.S_IMODE((home / "bridge.json").stat().st_mode),
                0o600,
            )

    def test_concurrent_token_initialization_returns_one_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "session"
            with ThreadPoolExecutor(max_workers=8) as pool:
                tokens = list(pool.map(lambda _: _control_token(home), range(32)))
            self.assertEqual(len(set(tokens)), 1)

    def test_concurrent_start_spawns_one_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            state = {"ready": False, "spawns": 0}
            state_lock = threading.Lock()

            async def fake_call_daemon(
                request: dict[str, object],
                timeout: float = 90,
            ) -> dict[str, bool]:
                del request, timeout
                with state_lock:
                    if state["ready"]:
                        return {"running": True}
                raise BrowserSessionError("daemon_unavailable")

            def fake_popen(*args: object, **kwargs: object) -> object:
                del args, kwargs
                with state_lock:
                    state["spawns"] += 1
                    state["ready"] = True
                return object()

            environment = {
                "HOME": str(home),
                "BROWSER_SESSION_HOME": str(home / "session"),
            }
            with (
                patch.dict(os.environ, environment),
                patch.object(browser_session, "call_daemon", fake_call_daemon),
                patch.object(browser_session.subprocess, "Popen", fake_popen),
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                futures = [pool.submit(browser_session.start_daemon) for _ in range(2)]
                for future in futures:
                    future.result(timeout=2)
            self.assertEqual(state["spawns"], 1)


class FakeExtension:
    def __init__(self, instance_id: str = INSTANCE_ID) -> None:
        self.instance_id = instance_id
        self.messages: list[dict[str, object]] = []
        self.sent = asyncio.Event()

    async def send(self, value: dict[str, object]) -> None:
        self.messages.append(value)
        self.sent.set()


class BrowserSessionRpcTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.daemon = BridgeDaemon(Path(self.temporary.name), 0)
        self.extension = FakeExtension()
        self.daemon.connections[INSTANCE_ID] = self.extension  # type: ignore[assignment]

    async def asyncTearDown(self) -> None:
        self.temporary.cleanup()

    async def test_task_cancellation_sends_cancel_and_clears_pending(self) -> None:
        task = asyncio.create_task(
            self.daemon._rpc(
                self.extension,  # type: ignore[arg-type]
                "request",
                "reddit",
                {},
            )
        )
        await asyncio.wait_for(self.extension.sent.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(
            [message["type"] for message in self.extension.messages],
            ["request", "cancel"],
        )
        self.assertFalse(self.daemon.pending)

    async def test_response_payload_must_be_an_object(self) -> None:
        task = asyncio.create_task(
            self.daemon._rpc(
                self.extension,  # type: ignore[arg-type]
                "session",
                "reddit",
            )
        )
        await asyncio.wait_for(self.extension.sent.wait(), 1)
        request = self.extension.messages[0]
        self.daemon._response(
            self.extension,  # type: ignore[arg-type]
            {
                "type": "response",
                "id": request["id"],
                "platform": "reddit",
                "payload": [],
            },
        )
        with self.assertRaises(BrowserSessionError) as raised:
            await task
        self.assertEqual(raised.exception.code, "invalid_response")

    async def test_timeout_race_returns_the_settled_response(self) -> None:
        async def racing_wait_for(
            awaitable: object,
            timeout: float,
        ) -> object:
            del awaitable, timeout
            request = self.extension.messages[0]
            self.daemon._response(
                self.extension,  # type: ignore[arg-type]
                {
                    "type": "response",
                    "id": request["id"],
                    "platform": "reddit",
                    "payload": {"ready": True},
                },
            )
            raise TimeoutError

        with patch.object(browser_session.asyncio, "wait_for", racing_wait_for):
            result = await self.daemon._rpc(
                self.extension,  # type: ignore[arg-type]
                "session",
                "reddit",
            )
        self.assertEqual(result, {"ready": True})
        self.assertEqual(
            [message["type"] for message in self.extension.messages],
            ["session"],
        )

    async def test_select_fails_immediately_without_an_extension_connection(self) -> None:
        self.daemon.connections.clear()
        with self.assertRaises(BrowserSessionError) as raised:
            await self.daemon._select("reddit", False)
        self.assertEqual(raised.exception.code, "extension_disconnected")

    async def test_ready_instances_are_probed_in_parallel(self) -> None:
        first = FakeExtension("1" * 32)
        second = FakeExtension("2" * 32)
        self.daemon.connections = {
            first.instance_id: first,  # type: ignore[dict-item]
            second.instance_id: second,  # type: ignore[dict-item]
        }
        started: set[str] = set()
        both_started = asyncio.Event()
        release = asyncio.Event()

        async def probe(
            extension: FakeExtension,
            kind: str,
            platform: str,
            values: dict[str, object] | None = None,
        ) -> dict[str, bool]:
            del kind, platform, values
            started.add(extension.instance_id)
            if len(started) == 2:
                both_started.set()
            await release.wait()
            return {"logged_in": extension is second}

        with (
            patch.object(self.daemon, "_rpc", side_effect=probe),
            patch.object(browser_session, "_write_registry"),
        ):
            selection = asyncio.create_task(self.daemon._select("reddit", True))
            await asyncio.wait_for(both_started.wait(), 1)
            release.set()
            self.assertIs(await selection, second)

    async def test_ready_route_skips_repeated_session_probe_until_expiry(
        self,
    ) -> None:
        async def probe(
            extension: FakeExtension,
            kind: str,
            platform: str,
            values: dict[str, object] | None = None,
        ) -> dict[str, bool]:
            del extension, platform, values
            self.assertEqual(kind, "session")
            return {"logged_in": True, "request_ready": True}

        with (
            patch.object(self.daemon, "_rpc", side_effect=probe) as rpc,
            patch.object(browser_session, "_write_registry"),
        ):
            first = await self.daemon._select("tiktok_one", True)
            cached = await self.daemon._select("tiktok_one", True)
            self.daemon.ready_routes["tiktok_one"] = (
                self.extension.instance_id,
                0,
            )
            expired = await self.daemon._select("tiktok_one", True)

        self.assertIs(first, self.extension)
        self.assertIs(cached, self.extension)
        self.assertIs(expired, self.extension)
        self.assertEqual(rpc.await_count, 2)

    async def test_select_preserves_advertiser_account_required(self) -> None:
        with patch.object(
            self.daemon,
            "_rpc",
            side_effect=BrowserSessionError("advertiser_account_required"),
        ):
            with self.assertRaises(BrowserSessionError) as raised:
                await self.daemon._select("tiktok_ads_manager", True)

        self.assertEqual(
            raised.exception.code,
            "advertiser_account_required",
        )

    async def test_select_preserves_tab_unavailable_when_all_tabs_are_missing(
        self,
    ) -> None:
        second = FakeExtension("2" * 32)
        self.daemon.connections[second.instance_id] = second  # type: ignore[assignment]

        async def probe(
            extension: FakeExtension,
            kind: str,
            platform: str,
            values: dict[str, object] | None = None,
        ) -> dict[str, bool]:
            del extension, kind, platform, values
            raise BrowserSessionError("tab_unavailable")

        with patch.object(self.daemon, "_rpc", side_effect=probe):
            with self.assertRaises(BrowserSessionError) as raised:
                await self.daemon._select("tiktok_ads_manager", True)
        self.assertEqual(raised.exception.code, "tab_unavailable")

    async def test_select_does_not_treat_logged_in_pending_runtime_as_ready(
        self,
    ) -> None:
        async def probe(
            extension: FakeExtension,
            kind: str,
            platform: str,
            values: dict[str, object] | None = None,
        ) -> dict[str, object]:
            del extension, kind, platform, values
            return {
                "logged_in": True,
                "request_ready": False,
                "verification_required": False,
            }

        with patch.object(self.daemon, "_rpc", side_effect=probe):
            with self.assertRaises(BrowserSessionError) as raised:
                await self.daemon._select("tiktok_ads_manager", True)
        self.assertEqual(raised.exception.code, "runtime_unavailable")

    async def test_select_preserves_verification_and_profile_states(self) -> None:
        for field, code in (
            ("verification_required", "verification_required"),
            ("profile_required", "profile_required"),
        ):
            with self.subTest(code=code):
                async def probe(
                    extension: FakeExtension,
                    kind: str,
                    platform: str,
                    values: dict[str, object] | None = None,
                ) -> dict[str, object]:
                    del extension, kind, platform, values
                    return {
                        "logged_in": field == "profile_required",
                        "request_ready": False,
                        field: True,
                    }

                with patch.object(self.daemon, "_rpc", side_effect=probe):
                    with self.assertRaises(BrowserSessionError) as raised:
                        await self.daemon._select("tiktok_creative_studio", True)
                self.assertEqual(raised.exception.code, code)

    async def test_request_fails_once_without_opening_or_polling_tabs(self) -> None:
        request = {
            "op": "request",
            "platform": "tiktok_one",
            "path": "/CreativeOne/MatchMaking/QueryPartnerSearchSuggestWords",
            "entries": [],
            "referer": (
                "https://ads.tiktok.com/creative/forpartners/"
                "creator/explore?region=row"
            ),
        }
        for code in ("tab_unavailable", "not_logged_in"):
            with self.subTest(code=code):
                with (
                    patch.object(
                        self.daemon,
                        "_select",
                        side_effect=BrowserSessionError(code),
                    ) as select_mock,
                    patch.object(self.daemon, "_rpc") as rpc_mock,
                ):
                    with self.assertRaises(BrowserSessionError) as raised:
                        await self.daemon._dispatch_control(request)
                self.assertEqual(raised.exception.code, code)
                select_mock.assert_awaited_once_with(
                    "tiktok_one",
                    True,
                    {"referer": request["referer"]},
                )
                rpc_mock.assert_not_awaited()

    async def test_session_error_invalidates_cached_request_route(self) -> None:
        request = {
            "op": "request",
            "platform": "tiktok_one",
            "path": "/CreativeOne/MatchMaking/QueryPartnerSearchSuggestWords",
            "entries": [["query", "coffee"]],
            "referer": (
                "https://ads.tiktok.com/creative/forpartners/"
                "creator/explore?region=row"
            ),
        }
        self.daemon._remember_ready_route(
            "tiktok_one",
            self.extension,  # type: ignore[arg-type]
        )
        with (
            patch.object(
                self.daemon,
                "_select",
                return_value=self.extension,
            ),
            patch.object(
                self.daemon,
                "_rpc",
                side_effect=BrowserSessionError("not_logged_in"),
            ),
        ):
            with self.assertRaises(BrowserSessionError) as raised:
                await self.daemon._dispatch_control(request)

        self.assertEqual(raised.exception.code, "not_logged_in")
        self.assertNotIn("tiktok_one", self.daemon.ready_routes)

    async def test_open_login_control_operation_is_not_exposed(self) -> None:
        with self.assertRaises(BrowserSessionError) as raised:
            await self.daemon._dispatch_control(
                {"op": "open_login", "platform": "reddit"}
            )
        self.assertEqual(raised.exception.code, "invalid_request")

    async def test_unchanged_family_binding_is_not_rewritten(self) -> None:
        with patch.object(browser_session, "_write_registry") as write_registry:
            self.assertIs(await self.daemon._select("reddit", False), self.extension)
            self.assertIs(await self.daemon._select("reddit", False), self.extension)
        write_registry.assert_called_once()

    async def test_same_family_requests_are_serial(self) -> None:
        started: list[str] = []
        first_started = asyncio.Event()
        release = asyncio.Event()

        async def select(
            platform: str,
            require_ready: bool,
            session_values: dict[str, object] | None = None,
        ) -> FakeExtension:
            del platform, require_ready, session_values
            return self.extension

        async def rpc(
            extension: FakeExtension,
            kind: str,
            platform: str,
            values: dict[str, object] | None = None,
        ) -> dict[str, str]:
            del extension, kind, values
            started.append(platform)
            if len(started) == 1:
                first_started.set()
                await release.wait()
            return {"platform": platform}

        first = {
            "op": "request",
            "platform": "tiktok_creative",
            "path": "/fixture",
            "entries": [],
            "referer": "https://ads.tiktok.com/",
        }
        second = {**first, "platform": "tiktok_creative_topads"}
        with (
            patch.object(self.daemon, "_select", side_effect=select),
            patch.object(self.daemon, "_rpc", side_effect=rpc),
        ):
            first_task = asyncio.create_task(self.daemon._dispatch_control(first))
            await asyncio.wait_for(first_started.wait(), 1)
            second_task = asyncio.create_task(self.daemon._dispatch_control(second))
            await asyncio.sleep(0.01)
            self.assertEqual(started, ["tiktok_creative"])
            release.set()
            await asyncio.gather(first_task, second_task)
        self.assertEqual(
            started,
            ["tiktok_creative", "tiktok_creative_topads"],
        )

    async def test_platform_status_uses_the_family_lock(self) -> None:
        lock = self.daemon.family_locks.setdefault("tiktok", asyncio.Lock())
        await lock.acquire()
        with patch.object(
            self.daemon,
            "_status",
            return_value={"ready": True},
        ) as status:
            task = asyncio.create_task(
                self.daemon._dispatch_control(
                    {"op": "status", "platform": "tiktok_creative"}
                )
            )
            await asyncio.sleep(0.01)
            status.assert_not_awaited()
            lock.release()
            self.assertEqual(await task, {"ready": True})
            status.assert_awaited_once_with("tiktok_creative")

    async def test_platform_status_probes_the_requested_page_context(self) -> None:
        url = "https://ads.tiktok.com/creative/inspiration/top-ads/library"
        with (
            patch.object(
                self.daemon,
                "_select",
                return_value=self.extension,
            ),
            patch.object(
                self.daemon,
                "_rpc",
                return_value={
                    "logged_in": True,
                    "request_ready": True,
                },
            ) as rpc,
        ):
            result = await self.daemon._dispatch_control(
                {
                    "op": "status",
                    "platform": "tiktok_creative_topads",
                    "url": url,
                }
            )

        self.assertEqual(result["url"], url)
        rpc.assert_awaited_once_with(
            self.extension,
            "session",
            "tiktok_creative_topads",
            {"referer": url},
        )

    async def test_contextual_session_probe_ignores_a_cached_other_page(self) -> None:
        first = self.extension
        second = FakeExtension("2" * 32)
        self.daemon.connections[second.instance_id] = second  # type: ignore[assignment]
        self.daemon.ready_routes["tiktok_creative_topads"] = (
            first.instance_id,
            time.monotonic() + 60,
        )
        url = "https://ads.tiktok.com/creative/inspiration/top-ads/library"
        calls: list[tuple[str, dict[str, object] | None]] = []

        async def probe(
            extension: FakeExtension,
            kind: str,
            platform: str,
            values: dict[str, object] | None = None,
        ) -> dict[str, bool]:
            self.assertEqual(kind, "session")
            self.assertEqual(platform, "tiktok_creative_topads")
            calls.append((extension.instance_id, values))
            if extension is first:
                raise BrowserSessionError("tab_unavailable")
            return {"logged_in": True, "request_ready": True}

        with (
            patch.object(self.daemon, "_rpc", side_effect=probe),
            patch.object(browser_session, "_write_registry"),
        ):
            selected = await self.daemon._select(
                "tiktok_creative_topads",
                True,
                {"referer": url},
            )

        self.assertIs(selected, second)
        self.assertEqual(
            calls,
            [
                (first.instance_id, {"referer": url}),
                (second.instance_id, {"referer": url}),
            ],
        )

    async def test_different_families_run_in_parallel(self) -> None:
        started: set[str] = set()
        both_started = asyncio.Event()
        release = asyncio.Event()

        async def select(
            platform: str,
            require_ready: bool,
            session_values: dict[str, object] | None = None,
        ) -> FakeExtension:
            del platform, require_ready, session_values
            return self.extension

        async def rpc(
            extension: FakeExtension,
            kind: str,
            platform: str,
            values: dict[str, object] | None = None,
        ) -> dict[str, str]:
            del extension, kind, values
            started.add(platform)
            if len(started) == 2:
                both_started.set()
            await release.wait()
            return {"platform": platform}

        reddit = {
            "op": "request",
            "platform": "reddit",
            "path": "/fixture",
            "entries": [],
            "referer": "https://www.reddit.com/",
        }
        bilibili = {
            **reddit,
            "platform": "bilibili",
            "referer": "https://www.bilibili.com/",
        }
        with (
            patch.object(self.daemon, "_select", side_effect=select),
            patch.object(self.daemon, "_rpc", side_effect=rpc),
        ):
            tasks = [
                asyncio.create_task(self.daemon._dispatch_control(reddit)),
                asyncio.create_task(self.daemon._dispatch_control(bilibili)),
            ]
            await asyncio.wait_for(both_started.wait(), 1)
            release.set()
            await asyncio.gather(*tasks)
        self.assertEqual(started, {"reddit", "bilibili"})


class BrowserSessionWireTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.daemon = BridgeDaemon(Path(self.temporary.name), 0)
        self.port = await self.daemon.start()
        self.extension = await self._connect()
        await self.extension.send(
            json.dumps(
                {
                    "type": "hello",
                    "protocol": PROTOCOL_VERSION,
                    "browser_instance_id": INSTANCE_ID,
                }
            )
        )
        self.ready = json.loads(await self.extension.recv())

    async def asyncTearDown(self) -> None:
        await self.extension.close()
        await self.daemon.close()
        self.temporary.cleanup()

    async def _connect(self):
        return await connect(
            f"ws://127.0.0.1:{self.port}",
            origin=ORIGIN,
            compression=None,
        )

    async def test_registration_token_is_reused(self) -> None:
        self.assertEqual(self.ready["type"], "ready")
        token = self.ready["token"]
        await self.extension.close()
        self.extension = await self._connect()
        await self.extension.send(
            json.dumps(
                {
                    "type": "hello",
                    "protocol": PROTOCOL_VERSION,
                    "browser_instance_id": INSTANCE_ID,
                    "token": token,
                }
            )
        )
        ready = json.loads(await self.extension.recv())
        self.assertNotIn("token", ready)

    async def test_duplicate_instance_closes_the_previous_connection_with_4009(
        self,
    ) -> None:
        previous = self.extension
        replacement = await self._connect()
        await replacement.send(
            json.dumps(
                {
                    "type": "hello",
                    "protocol": PROTOCOL_VERSION,
                    "browser_instance_id": INSTANCE_ID,
                    "token": self.ready["token"],
                }
            )
        )
        ready = json.loads(await replacement.recv())
        self.assertEqual(ready["type"], "ready")
        await asyncio.wait_for(previous.wait_closed(), 1)
        self.assertEqual(
            _close_details(previous),
            (
                INSTANCE_SUPERSEDED_CLOSE_CODE,
                INSTANCE_SUPERSEDED_CLOSE_REASON,
            ),
        )
        self.extension = replacement

    async def test_daemon_shutdown_keeps_the_standard_close_code(self) -> None:
        await self.daemon.close()
        await asyncio.wait_for(self.extension.wait_closed(), 1)
        self.assertEqual(
            _close_details(self.extension),
            (1001, "bridge shutdown"),
        )

    async def test_idle_connection_must_send_hello_before_deadline(self) -> None:
        with patch.object(browser_session, "HELLO_TIMEOUT", 0.01):
            idle = await self._connect()
            try:
                with self.assertRaises(ConnectionClosed):
                    await asyncio.wait_for(idle.recv(), 1)
            finally:
                await idle.close()

    async def test_control_disconnect_cancels_dispatch(self) -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def blocking_dispatch(
            request: dict[str, object],
            progress: object = None,
        ) -> object:
            del request, progress
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        with patch.object(self.daemon, "_dispatch_control", blocking_dispatch):
            control = await connect(
                f"ws://127.0.0.1:{self.port}/control",
                compression=None,
            )
            await control.send(
                json.dumps(
                    {
                        "token": self.daemon.control_token,
                        "op": "ping",
                    }
                )
            )
            await asyncio.wait_for(started.wait(), 1)
            await control.close()
            await asyncio.wait_for(cancelled.wait(), 1)

    async def test_control_progress_events_reach_the_client_callback(self) -> None:
        async def extension_worker() -> None:
            async for raw in self.extension:
                message = json.loads(raw)
                if message["type"] == "session":
                    payload = {
                        "logged_in": True,
                        "request_ready": True,
                        "fingerprint": {},
                    }
                else:
                    payload = {"items": []}
                await self.extension.send(
                    json.dumps(
                        {
                            "type": "response",
                            "id": message["id"],
                            "platform": message["platform"],
                            "payload": payload,
                        }
                    )
                )

        worker = asyncio.create_task(extension_worker())
        progress: list[dict[str, object]] = []
        try:
            with (
                patch.object(browser_session, "BRIDGE_PORT", self.port),
                patch.object(
                    browser_session,
                    "session_home",
                    return_value=Path(self.temporary.name),
                ),
            ):
                result = await browser_session.call_daemon(
                    {
                        "op": "request",
                        "platform": "reddit",
                        "path": "/bridge/v1/reddit/home-feed",
                        "entries": [],
                        "referer": "https://www.reddit.com/",
                    },
                    progress=progress.append,
                )
            self.assertEqual(result, {"items": []})
            self.assertEqual(
                [event["stage"] for event in progress],
                ["session", "session", "request", "complete"],
            )
            self.assertTrue(all(event["event"] == "progress" for event in progress))
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker

    async def test_session_and_request_round_trip(self) -> None:
        async def extension_worker() -> None:
            async for raw in self.extension:
                message = json.loads(raw)
                if message["type"] == "session":
                    payload = {
                        "logged_in": True,
                        "request_ready": True,
                        "fingerprint": {},
                    }
                elif message["type"] == "request":
                    payload = {"path": message["path"]}
                else:
                    payload = {"opened": True}
                await self.extension.send(
                    json.dumps(
                        {
                            "type": "response",
                            "id": message["id"],
                            "platform": message["platform"],
                            "payload": payload,
                        }
                    )
                )

        worker = asyncio.create_task(extension_worker())
        try:
            status = await self.daemon._dispatch_control(
                {"op": "status", "platform": "reddit"}
            )
            self.assertTrue(status["session"]["logged_in"])
            response = await self.daemon._dispatch_control(
                {
                    "op": "request",
                    "platform": "reddit",
                    "path": "/bridge/v1/reddit/home-feed",
                    "entries": [
                        ["sort", "BEST"],
                        ["limit", "20"],
                        ["after", ""],
                    ],
                    "referer": "https://www.reddit.com/",
                }
            )
            self.assertEqual(
                response, {"path": "/bridge/v1/reddit/home-feed"}
            )
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker


if __name__ == "__main__":
    unittest.main()
