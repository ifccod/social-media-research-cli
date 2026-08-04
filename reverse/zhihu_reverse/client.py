from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote, urlencode, urlsplit

from curl_cffi import requests

from .errors import ZhihuInputError, ZhihuResponseError, ZhihuSignatureError
from .signing import X_ZSE_93, ZhihuChallengeRunner, build_x_zse_96

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)

_WEB_BASE = "https://www.zhihu.com"
_APP_BASE = "https://api.zhihu.com"
_EXPLORE_URL = f"{_WEB_BASE}/explore"
_OWNED_WEB_HOSTS = frozenset({"zhihu.com", "www.zhihu.com"})
_ARTICLE_HOSTS = frozenset({"zhuanlan.zhihu.com"})
_STATIC_HOST = "static.zhihu.com"
_ID_RE = re.compile(r"^[1-9][0-9]{4,21}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,127}$")
_COLUMN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_CURSOR_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_CHALLENGE_SCRIPT_PATH_RE = re.compile(r"^/zse-ck/v4/[0-9a-fA-F]{8,128}\.js$")
_RETRYABLE_STATUS = frozenset({408, 425, 429})
_QUESTION_PATH_RE = re.compile(r"^/question/([1-9][0-9]{4,21})/?$")
_ANSWER_PATH_RE = re.compile(
    r"^/question/[1-9][0-9]{4,21}/answer/([1-9][0-9]{4,21})/?$"
)
_ARTICLE_PATH_RE = re.compile(r"^/p/([1-9][0-9]{4,21})/?$")
_PIN_PATH_RE = re.compile(r"^/pin/([1-9][0-9]{4,21})/?$")
_MEMBER_PATH_RE = re.compile(
    r"^/people/([A-Za-z0-9][A-Za-z0-9_-]{1,127})"
    r"(?:/(?:answers|posts|pins|following|followers))?/?$"
)
_COLUMN_PATH_RE = re.compile(r"^/column/([A-Za-z0-9][A-Za-z0-9_-]{0,79})/?$")
_ZHUANLAN_COLUMN_PATH_RE = re.compile(r"^/([A-Za-z0-9][A-Za-z0-9_-]{0,79})/?$")


class _ChallengeHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta_values: list[str] = []
        self.script_urls: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        lower = tag.lower()
        if lower == "meta" and values.get("id") == "zh-zse-ck":
            self.meta_values.append(values.get("content", ""))
        elif lower == "script" and values.get("src"):
            self.script_urls.append(values["src"])


def _is_retryable_status(status_code: int) -> bool:
    return status_code in _RETRYABLE_STATUS or 500 <= status_code <= 599


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _error_details(payload: Any) -> tuple[int | str | None, str]:
    root = _mapping(payload)
    error = _mapping(root.get("error"))
    code: int | str | None = error.get("code") or root.get("code")
    if isinstance(code, str) and code.isdecimal():
        code = int(code)
    message = str(
        error.get("message")
        or error.get("description")
        or root.get("message")
        or root.get("error_msg")
        or ""
    ).strip()
    return code, message


class ZhihuClient:
    """面向知乎公开 JSON 接口的匿名客户端。"""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        challenge_runner: ZhihuChallengeRunner | Callable[..., str] | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 20,
        retries: int = 2,
    ) -> None:
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(float(timeout))
            or timeout <= 0
        ):
            raise ZhihuInputError("timeout must be a positive finite number")
        if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
            raise ZhihuInputError("retries must be a non-negative integer")
        if (
            not isinstance(user_agent, str)
            or not user_agent.strip()
            or "\r" in user_agent
            or "\n" in user_agent
        ):
            raise ZhihuInputError("user_agent must be a non-empty single-line string")
        if challenge_runner is not None and not (
            callable(challenge_runner)
            or callable(getattr(challenge_runner, "run", None))
        ):
            raise ZhihuInputError("challenge_runner must be callable or expose run()")

        self.session = (
            session if session is not None else requests.Session(impersonate="chrome")
        )
        self.challenge_runner = (
            challenge_runner if challenge_runner is not None else ZhihuChallengeRunner()
        )
        self.user_agent = user_agent
        self.timeout = float(timeout)
        self.retries = retries
        self._visitor_ready = False
        self._challenge_ready = False
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
                "User-Agent": user_agent,
            }
        )

    @staticmethod
    def resolve_question_id(value: str | int) -> str:
        return ZhihuClient._resolve_numeric_reference(
            value, "question", _QUESTION_PATH_RE, _OWNED_WEB_HOSTS
        )

    @staticmethod
    def resolve_answer_id(value: str | int) -> str:
        return ZhihuClient._resolve_numeric_reference(
            value, "answer", _ANSWER_PATH_RE, _OWNED_WEB_HOSTS
        )

    @staticmethod
    def resolve_article_id(value: str | int) -> str:
        return ZhihuClient._resolve_numeric_reference(
            value, "article", _ARTICLE_PATH_RE, _ARTICLE_HOSTS
        )

    @staticmethod
    def resolve_pin_id(value: str | int) -> str:
        return ZhihuClient._resolve_numeric_reference(
            value, "pin", _PIN_PATH_RE, _OWNED_WEB_HOSTS
        )

    @staticmethod
    def resolve_comment_id(value: str | int) -> str:
        return ZhihuClient._decimal_id(value, "comment")

    @staticmethod
    def resolve_user_token(value: str) -> str:
        source = ZhihuClient._text_reference(value, "user token")
        if _TOKEN_RE.fullmatch(source):
            return source
        parsed = ZhihuClient._owned_url(source, _OWNED_WEB_HOSTS, "user")
        path = ZhihuClient._plain_path(parsed.path, "user")
        match = _MEMBER_PATH_RE.fullmatch(path)
        if not match:
            raise ZhihuInputError("reference is not a Zhihu public user URL or token")
        return match.group(1)

    @staticmethod
    def resolve_column_id(value: str) -> str:
        source = ZhihuClient._text_reference(value, "column id")
        if _COLUMN_RE.fullmatch(source):
            return source
        parsed = ZhihuClient._owned_url(
            source, _OWNED_WEB_HOSTS | _ARTICLE_HOSTS, "column"
        )
        path = ZhihuClient._plain_path(parsed.path, "column")
        host = (parsed.hostname or "").lower()
        matcher = _ZHUANLAN_COLUMN_PATH_RE if host in _ARTICLE_HOSTS else _COLUMN_PATH_RE
        match = matcher.fullmatch(path)
        if not match:
            raise ZhihuInputError("reference is not a Zhihu public column URL or id")
        return match.group(1)

    def initialize_session(
        self,
        api_path: str = "/api/v4/questions/37811449",
        *,
        referer: str = f"{_WEB_BASE}/explore",
        force: bool = False,
    ) -> None:
        """初始化 d_c0 访客并计算一个 __zse_ck 验证令牌。"""

        signed_path = self._validate_signed_path(api_path)
        page_url = self._validate_referer(referer)
        if self._challenge_ready and not force:
            return
        self._challenge_ready = False

        if not self._visitor_ready or not self._cookie("d_c0"):
            explore = self._send(
                _EXPLORE_URL,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                },
            )
            self._raise_for_response(explore, context="visitor bootstrap")
            if not self._cookie("d_c0"):
                raise ZhihuResponseError(
                    "Zhihu visitor bootstrap did not set d_c0",
                    status_code=explore.status_code,
                    url=str(explore.url or _EXPLORE_URL),
                )
            self._visitor_ready = True

        self._set_cookie("__zse_ck", "005_x-x")
        challenge_url = _WEB_BASE + signed_path
        challenge = self._send(
            challenge_url,
            headers=self._signed_headers(signed_path, referer=page_url),
        )
        try:
            meta, script_url = self.parse_challenge_html(challenge.text)
        except ZhihuResponseError:
            payload = self._json_response(
                challenge, context="challenge", allow_invalid=True
            )
            self._raise_for_response(
                challenge, payload=payload, context="challenge bootstrap"
            )
            raise
        script_response = self._send(
            script_url,
            headers={
                "Accept": "*/*",
                "Referer": page_url,
            },
        )
        self._raise_for_response(script_response, context="challenge script")
        self._validate_response_url(
            str(script_response.url or script_url),
            expected_host=_STATIC_HOST,
            expected_path=_CHALLENGE_SCRIPT_PATH_RE,
        )
        token = self._run_challenge(
            script_response.text,
            meta=meta,
            page_url=page_url,
        )
        if not isinstance(token, str) or not token.startswith("005_") or "-" not in token:
            raise ZhihuSignatureError("Zhihu challenge runner returned an invalid __zse_ck")
        self._set_cookie("__zse_ck", token)
        self._challenge_ready = True

    def get_question(self, value: str | int) -> dict[str, Any]:
        question_id = self.resolve_question_id(value)
        payload = self._signed_json_get(
            f"/api/v4/questions/{question_id}",
            referer=f"{_WEB_BASE}/question/{question_id}",
        )
        return self._detail(payload, question_id, "question")

    def get_answer(self, value: str | int) -> dict[str, Any]:
        answer_id = self.resolve_answer_id(value)
        payload = self._signed_json_get(
            f"/api/v4/answers/{answer_id}", referer=f"{_WEB_BASE}/answer/{answer_id}"
        )
        return self._detail(payload, answer_id, "answer")

    def get_article(self, value: str | int) -> dict[str, Any]:
        article_id = self.resolve_article_id(value)
        payload = self._signed_json_get(
            f"/api/v4/articles/{article_id}",
            referer=f"https://zhuanlan.zhihu.com/p/{article_id}",
        )
        return self._detail(payload, article_id, "article")

    def get_pin(self, value: str | int) -> dict[str, Any]:
        pin_id = self.resolve_pin_id(value)
        payload = self._signed_json_get(
            f"/api/v4/pins/{pin_id}", referer=f"{_WEB_BASE}/pin/{pin_id}"
        )
        return self._detail(payload, pin_id, "pin")

    def get_column_articles(
        self, value: str, *, limit: int = 10, offset: int = 0
    ) -> dict[str, Any]:
        column_id = self.resolve_column_id(value)
        size, start = self._window(limit, offset)
        return self._signed_json_get(
            f"/api/v4/columns/{column_id}/items",
            params=(("limit", size), ("offset", start)),
            referer=f"https://zhuanlan.zhihu.com/{column_id}",
        )

    def get_hot_list(self, *, limit: int = 50) -> dict[str, Any]:
        size, _ = self._window(limit, 0, maximum=100)
        path = self._query_path(
            "/topstory/hot-lists/total",
            (("limit", size), ("reverse_order", 0)),
            prefix="/topstory/",
        )
        response = self._send(_APP_BASE + path)
        payload = self._json_response(response, context="hot list", allow_invalid=True)
        self._raise_for_response(response, payload=payload, context="hot list")
        if payload is None:
            raise ZhihuResponseError(
                "Zhihu hot list response is not valid JSON",
                status_code=response.status_code,
                url=str(response.url or _APP_BASE + path),
            )
        return self._payload_mapping(payload, "hot list")

    def get_hot_recommend(
        self,
        *,
        offset: int = 0,
        page_number: int = 1,
        session_token: str = "",
    ) -> dict[str, Any]:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ZhihuInputError("offset must be a non-negative integer")
        if (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or not 1 <= page_number <= 100_000
        ):
            raise ZhihuInputError("page_number must be an integer from 1 through 100000")
        if (
            not isinstance(session_token, str)
            or len(session_token) > 200
            or (session_token and not _CURSOR_RE.fullmatch(session_token))
        ):
            raise ZhihuInputError("session_token must be an opaque URL-safe token")

        path = self._query_path(
            "/topstory/recommend",
            (
                ("action", "down"),
                ("ad_interval", -10),
                ("after_id", offset),
                ("page_number", page_number),
                ("session_token", session_token),
            ),
            prefix="/topstory/",
        )
        response = self._send(_APP_BASE + path)
        payload = self._json_response(
            response, context="hot recommend", allow_invalid=True
        )
        self._raise_for_response(response, payload=payload, context="hot recommend")
        if payload is None:
            raise ZhihuResponseError(
                "Zhihu hot recommend response is not valid JSON",
                status_code=response.status_code,
                url=str(response.url or _APP_BASE + path),
            )
        result = self._payload_mapping(payload, "hot recommend")
        if not isinstance(result.get("data"), list) or not isinstance(
            result.get("paging"), Mapping
        ):
            raise ZhihuResponseError(
                "Zhihu hot recommend response is missing data or paging",
                status_code=response.status_code,
                url=str(response.url or _APP_BASE + path),
                payload=result,
            )
        return result

    def get_question_answers(
        self,
        value: str | int,
        *,
        limit: int = 5,
        offset: int = 0,
        order: str = "default",
    ) -> dict[str, Any]:
        question_id = self.resolve_question_id(value)
        size, start = self._window(limit, offset)
        normalized_order = self._choice(
            order, {"default", "created", "updated"}, "order"
        )
        return self._signed_json_get(
            f"/api/v4/questions/{question_id}/answers",
            params=(
                ("limit", size),
                ("offset", start),
                ("platform", "desktop"),
                ("sort_by", normalized_order),
            ),
            referer=f"{_WEB_BASE}/question/{question_id}",
        )

    def get_user(self, value: str) -> dict[str, Any]:
        token = self.resolve_user_token(value)
        payload = self._signed_json_get(
            f"/api/v4/members/{token}", referer=f"{_WEB_BASE}/people/{token}"
        )
        result = self._payload_mapping(payload, "user")
        returned = str(result.get("url_token") or "")
        if not returned:
            raise ZhihuResponseError("Zhihu user response has no url_token", payload=result)
        if returned != token:
            raise ZhihuResponseError(
                f"Zhihu user response token mismatch: expected {token}, got {returned}",
                payload=result,
            )
        return result

    def get_user_answers(
        self, value: str, *, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        return self._user_listing(value, "answers", limit=limit, offset=offset)

    def get_user_followers(
        self, value: str, *, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        return self._user_listing(value, "followers", limit=limit, offset=offset)

    def get_user_followees(
        self, value: str, *, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        return self._user_listing(
            value,
            "followees",
            limit=limit,
            offset=offset,
            referer_resource="following",
        )

    def get_user_pins(
        self, value: str, *, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        return self._user_listing(value, "pins", limit=limit, offset=offset)

    def get_user_articles(
        self,
        value: str,
        *,
        limit: int = 20,
        offset: int = 0,
        sort: str = "created",
    ) -> dict[str, Any]:
        token = self.resolve_user_token(value)
        size, start = self._window(limit, offset)
        normalized_sort = self._choice(sort, {"created", "updated"}, "sort")
        return self._signed_json_get(
            f"/api/v4/members/{token}/articles",
            params=(
                ("limit", size),
                ("offset", start),
                ("sort_by", normalized_sort),
            ),
            referer=f"{_WEB_BASE}/people/{token}/posts",
        )

    def get_comments(
        self,
        answer: str | int,
        *,
        order_by: str = "score",
        limit: int = 20,
        offset: str | int = "",
    ) -> dict[str, Any]:
        answer_id = self.resolve_answer_id(answer)
        return self._comments(
            f"/api/v4/comment_v5/answers/{answer_id}/root_comment",
            referer=f"{_WEB_BASE}/answer/{answer_id}",
            order_by=order_by,
            limit=limit,
            offset=offset,
        )

    def get_comment_replies(
        self,
        comment: str | int,
        *,
        order_by: str = "score",
        limit: int = 20,
        offset: str | int = "",
    ) -> dict[str, Any]:
        comment_id = self.resolve_comment_id(comment)
        return self._comments(
            f"/api/v4/comment_v5/comment/{comment_id}/child_comment",
            referer=f"{_WEB_BASE}/",
            order_by=order_by,
            limit=limit,
            offset=offset,
        )

    def get_pin_comments(
        self,
        pin: str | int,
        *,
        order_by: str = "score",
        limit: int = 20,
        offset: str | int = "",
    ) -> dict[str, Any]:
        pin_id = self.resolve_pin_id(pin)
        return self._comments(
            f"/api/v4/comment_v5/pins/{pin_id}/root_comment",
            referer=f"{_WEB_BASE}/pin/{pin_id}",
            order_by=order_by,
            limit=limit,
            offset=offset,
        )

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        offset: int = 0,
        vertical: str = "",
        sort: str = "",
        time_interval: str = "",
    ) -> dict[str, Any]:
        keyword = self._keyword(query)
        size, start = self._window(limit, offset)
        normalized_vertical = self._choice(
            vertical, {"", "answer", "article", "zvideo"}, "vertical"
        )
        normalized_sort = self._choice(
            sort, {"", "upvoted_count", "created_time"}, "sort"
        )
        normalized_time = self._choice(
            time_interval,
            {
                "",
                "a_day",
                "a_week",
                "a_month",
                "three_months",
                "half_a_year",
                "a_year",
            },
            "time_interval",
        )
        filtered = bool(normalized_vertical or normalized_sort or normalized_time)
        params: list[tuple[str, Any]] = [
            ("t", "general"),
            ("q", keyword),
            ("correction", 1),
            ("offset", start),
            ("limit", size),
            ("lc_idx", start),
            ("show_all_topics", 0),
            ("search_source", "Filter" if filtered else "Normal"),
        ]
        if normalized_vertical:
            params.append(("vertical", normalized_vertical))
        if normalized_sort:
            params.append(("sort", normalized_sort))
        if normalized_time:
            params.append(("time_interval", normalized_time))
        if filtered:
            params.append(("vertical_info", "0,0,0,0,0,0,0,0,0,0,0,0"))
        return self._signed_json_get(
            "/api/v4/search_v3",
            params=params,
            referer=f"{_WEB_BASE}/search",
        )

    @classmethod
    def parse_challenge_html(cls, source: str) -> tuple[str, str]:
        if not isinstance(source, str) or not source.strip():
            raise ZhihuResponseError("Zhihu challenge response is empty")
        parser = _ChallengeHTMLParser()
        try:
            parser.feed(source)
            parser.close()
        except (ValueError, TypeError) as exc:
            raise ZhihuResponseError("Zhihu challenge HTML is malformed") from exc
        metas = [value.strip() for value in parser.meta_values if value.strip()]
        if len(metas) != 1 or len(metas[0]) > 2048 or any(
            ord(character) < 32 for character in metas[0]
        ):
            raise ZhihuResponseError("Zhihu challenge HTML has no unique zh-zse-ck meta")
        candidates: list[str] = []
        for value in parser.script_urls:
            try:
                candidates.append(cls._challenge_script_url(value))
            except ZhihuResponseError:
                continue
        candidates = list(dict.fromkeys(candidates))
        if len(candidates) != 1:
            raise ZhihuResponseError("Zhihu challenge HTML has no unique owned v4 script")
        return metas[0], candidates[0]

    def _user_listing(
        self,
        value: str,
        resource: str,
        *,
        limit: int,
        offset: int,
        referer_resource: str | None = None,
    ) -> dict[str, Any]:
        token = self.resolve_user_token(value)
        size, start = self._window(limit, offset)
        return self._signed_json_get(
            f"/api/v4/members/{token}/{resource}",
            params=(("limit", size), ("offset", start)),
            referer=f"{_WEB_BASE}/people/{token}/{referer_resource or resource}",
        )

    def _comments(
        self,
        path: str,
        *,
        referer: str,
        order_by: str,
        limit: int,
        offset: str | int,
    ) -> dict[str, Any]:
        normalized_order = self._choice(order_by, {"score", "ts"}, "order_by")
        size, _ = self._window(limit, 0)
        cursor = self._comment_cursor(offset)
        return self._signed_json_get(
            path,
            params=(("order_by", normalized_order), ("limit", size), ("offset", cursor)),
            referer=referer,
        )

    def _signed_json_get(
        self,
        path: str,
        *,
        params: Sequence[tuple[str, Any]] = (),
        referer: str,
    ) -> dict[str, Any]:
        signed_path = self._query_path(path, params)
        page_url = self._validate_referer(referer)
        self.initialize_session(signed_path, referer=page_url)
        refreshed = False
        while True:
            response = self._send(
                _WEB_BASE + signed_path,
                headers=self._signed_headers(signed_path, referer=page_url),
            )
            payload = self._json_response(response, context="API request", allow_invalid=True)
            code, _ = _error_details(payload)
            if code == 40362 and not refreshed:
                refreshed = True
                self.initialize_session(signed_path, referer=page_url, force=True)
                continue
            self._raise_for_response(response, payload=payload, context="API request")
            if payload is None:
                raise ZhihuResponseError(
                    "Zhihu API response is not valid JSON",
                    status_code=response.status_code,
                    url=str(response.url or _WEB_BASE + signed_path),
                )
            return self._payload_mapping(payload, "API")

    def _signed_headers(self, signed_path: str, *, referer: str) -> dict[str, str]:
        d_c0 = self._cookie("d_c0")
        if not d_c0:
            raise ZhihuSignatureError("d_c0 is required before signing a Zhihu request")
        return {
            "Accept": "application/json, text/plain, */*",
            "Referer": referer,
            "X-Api-Version": "3.0.91",
            "X-App-Za": "OS=Web",
            "X-Requested-With": "fetch",
            "X-Zse-93": X_ZSE_93,
            "X-Zse-96": build_x_zse_96(signed_path, d_c0),
        }

    def _send(self, url: str, *, headers: Mapping[str, str] | None = None) -> requests.Response:
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(
                    url,
                    headers=dict(headers or {}),
                    timeout=self.timeout,
                    allow_redirects=False,
                )
            except requests.exceptions.ConnectionError as exc:
                if attempt < self.retries:
                    time.sleep(0.25 * (2**attempt))
                    continue
                raise ZhihuResponseError(
                    f"Zhihu connection failed after {attempt + 1} attempt(s): {exc}",
                    url=url,
                    retryable=True,
                ) from exc
            except requests.exceptions.RequestException as exc:
                raise ZhihuResponseError(
                    f"Zhihu HTTP request failed: {exc}", url=url
                ) from exc
            if _is_retryable_status(response.status_code) and attempt < self.retries:
                time.sleep(0.25 * (2**attempt))
                continue
            return response
        raise AssertionError("unreachable request loop")

    def _raise_for_response(
        self,
        response: requests.Response,
        *,
        payload: Any = None,
        context: str,
    ) -> None:
        code, detail = _error_details(payload)
        status = int(response.status_code)
        if status < 400 and code is None:
            return
        url = str(response.url or "")
        if code in {40353, 40362}:
            label = "risk-control rejection" if code == 40353 else "expired visitor challenge"
            message = f"Zhihu {label} (code {code}, HTTP {status})"
        elif status == 401:
            message = "Zhihu anonymous request reached an authentication gate (HTTP 401)"
        else:
            suffix = f", code {code}" if code is not None else ""
            message = f"Zhihu {context} failed with HTTP {status}{suffix}"
        if detail:
            message += f": {detail[:300]}"
        raise ZhihuResponseError(
            message,
            status_code=status,
            error_code=code,
            payload=payload,
            url=url,
            retryable=_is_retryable_status(status),
        )

    @staticmethod
    def _json_response(
        response: requests.Response, *, context: str, allow_invalid: bool = False
    ) -> Any:
        try:
            return response.json()
        except (json.JSONDecodeError, TypeError, ValueError):
            if allow_invalid:
                return None
            raise ZhihuResponseError(
                f"Zhihu {context} response is not valid JSON",
                status_code=response.status_code,
                url=str(response.url or ""),
            )

    @staticmethod
    def _payload_mapping(payload: Any, context: str) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ZhihuResponseError(f"Zhihu {context} JSON root is not an object", payload=payload)
        return dict(payload)

    @classmethod
    def _detail(cls, payload: Any, expected_id: str, kind: str) -> dict[str, Any]:
        result = cls._payload_mapping(payload, kind)
        returned = str(result.get("id") or "")
        if not returned:
            raise ZhihuResponseError(f"Zhihu {kind} response has no id", payload=result)
        if returned != expected_id:
            raise ZhihuResponseError(
                f"Zhihu {kind} response ID mismatch: expected {expected_id}, got {returned}",
                payload=result,
            )
        return result

    def _run_challenge(self, source: str, *, meta: str, page_url: str) -> str:
        runner = self.challenge_runner
        function = getattr(runner, "run", None)
        if not callable(function):
            function = runner
        try:
            return function(
                source,
                meta=meta,
                page_url=page_url,
                user_agent=self.user_agent,
            )
        except ZhihuSignatureError:
            raise
        except Exception as exc:
            raise ZhihuSignatureError(f"Zhihu challenge runner failed: {exc}") from exc

    def _cookie(self, name: str) -> str:
        for domain in (".zhihu.com", "www.zhihu.com", "zhihu.com", None):
            try:
                value = (
                    self.session.cookies.get(name, domain=domain)
                    if domain is not None
                    else self.session.cookies.get(name)
                )
            except (KeyError, TypeError, ValueError, requests.exceptions.CookieConflict):
                continue
            if value:
                return str(value)
        return ""

    def _set_cookie(self, name: str, value: str) -> None:
        self.session.cookies.set(name, value, domain=".zhihu.com", path="/")

    @staticmethod
    def _query_path(
        path: str,
        params: Sequence[tuple[str, Any]],
        *,
        prefix: str = "/api/",
    ) -> str:
        if (
            not isinstance(path, str)
            or not path.startswith(prefix)
            or "?" in path
            or "#" in path
            or "\r" in path
            or "\n" in path
        ):
            raise ZhihuInputError("invalid Zhihu API path")
        query = urlencode(list(params), doseq=True)
        return f"{path}?{query}" if query else path

    @staticmethod
    def _validate_signed_path(path: str) -> str:
        parsed = urlsplit(path) if isinstance(path, str) else None
        if (
            not isinstance(path, str)
            or parsed is None
            or not parsed.path.startswith("/api/v4/")
            or "#" in path
            or "\r" in path
            or "\n" in path
            or "\\" in parsed.path
            or unquote(parsed.path) != parsed.path
            or any(part in {".", ".."} for part in parsed.path.split("/"))
            or parsed.scheme
            or parsed.netloc
        ):
            raise ZhihuInputError("invalid signed Zhihu API path")
        return path

    @classmethod
    def _challenge_script_url(cls, source: str) -> str:
        value = str(source or "").strip()
        if value.startswith("//"):
            value = "https:" + value
        elif value.startswith("/"):
            value = "https://static.zhihu.com" + value
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise ZhihuResponseError("Zhihu challenge script URL is malformed") from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname != _STATIC_HOST
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
            or parsed.query
            or parsed.fragment
            or not _CHALLENGE_SCRIPT_PATH_RE.fullmatch(parsed.path)
        ):
            raise ZhihuResponseError("Zhihu challenge script URL is outside the fixed v4 path")
        return f"https://{_STATIC_HOST}{parsed.path}"

    @staticmethod
    def _validate_response_url(
        source: str, *, expected_host: str, expected_path: re.Pattern[str]
    ) -> None:
        try:
            parsed = urlsplit(source)
            port = parsed.port
        except ValueError as exc:
            raise ZhihuResponseError("Zhihu response URL is malformed") from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname != expected_host
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
            or parsed.query
            or parsed.fragment
            or not expected_path.fullmatch(parsed.path)
        ):
            raise ZhihuResponseError("Zhihu response URL left the expected owned endpoint")

    @classmethod
    def _validate_referer(cls, source: str) -> str:
        parsed = cls._owned_url(
            cls._text_reference(source, "referer"),
            _OWNED_WEB_HOSTS | _ARTICLE_HOSTS,
            "referer",
        )
        return parsed.geturl()

    @staticmethod
    def _resolve_numeric_reference(
        value: str | int,
        kind: str,
        path_pattern: re.Pattern[str],
        hosts: frozenset[str],
    ) -> str:
        if isinstance(value, int) and not isinstance(value, bool):
            return ZhihuClient._decimal_id(value, kind)
        source = ZhihuClient._text_reference(value, f"{kind} id")
        if _ID_RE.fullmatch(source):
            return source
        parsed = ZhihuClient._owned_url(source, hosts, kind)
        path = ZhihuClient._plain_path(parsed.path, kind)
        match = path_pattern.fullmatch(path)
        if not match:
            raise ZhihuInputError(f"reference is not a Zhihu public {kind} URL or id")
        return match.group(1)

    @staticmethod
    def _decimal_id(value: str | int, kind: str) -> str:
        if isinstance(value, bool):
            raise ZhihuInputError(f"{kind} id must be a decimal identifier")
        source = str(value).strip() if isinstance(value, (str, int)) else ""
        if not _ID_RE.fullmatch(source):
            raise ZhihuInputError(f"{kind} id must be 5 to 22 digits without a leading zero")
        return source

    @staticmethod
    def _text_reference(value: Any, label: str) -> str:
        if not isinstance(value, str):
            raise ZhihuInputError(f"{label} must be a string")
        source = value.strip()
        if not source or len(source) > 2048 or any(ord(character) < 32 for character in source):
            raise ZhihuInputError(f"{label} is empty or contains control characters")
        return source

    @staticmethod
    def _owned_url(source: str, hosts: frozenset[str], kind: str):
        candidate = source
        if "://" not in candidate:
            candidate = "https://" + candidate
        try:
            parsed = urlsplit(candidate)
            port = parsed.port
        except ValueError as exc:
            raise ZhihuInputError(f"{kind} URL is malformed") from exc
        host = (parsed.hostname or "").lower()
        expected_port = 443 if parsed.scheme == "https" else 80
        if (
            parsed.scheme not in {"http", "https"}
            or host not in hosts
            or parsed.hostname != host
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, expected_port)
        ):
            raise ZhihuInputError(f"{kind} URL must use an owned Zhihu host and standard port")
        return parsed

    @staticmethod
    def _plain_path(path: str, kind: str) -> str:
        if unquote(path) != path:
            raise ZhihuInputError(f"{kind} URL path must not use percent-encoded route data")
        return path

    @staticmethod
    def _window(limit: int, offset: int, *, maximum: int = 100) -> tuple[int, int]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 1
            or limit > maximum
        ):
            raise ZhihuInputError(f"limit must be an integer from 1 through {maximum}")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ZhihuInputError("offset must be a non-negative integer")
        return limit, offset

    @staticmethod
    def _comment_cursor(value: str | int) -> str | int:
        if isinstance(value, bool):
            raise ZhihuInputError("comment offset must be a non-negative integer or cursor")
        if isinstance(value, int):
            if value < 0:
                raise ZhihuInputError("comment offset must be a non-negative integer or cursor")
            return value
        if isinstance(value, str) and (not value or _CURSOR_RE.fullmatch(value)):
            return value
        raise ZhihuInputError("comment offset must be a non-negative integer or cursor")

    @staticmethod
    def _choice(value: str, allowed: set[str], label: str) -> str:
        if not isinstance(value, str) or value not in allowed:
            raise ZhihuInputError(f"{label} must be one of: {', '.join(sorted(allowed))}")
        return value

    @staticmethod
    def _keyword(value: str) -> str:
        if not isinstance(value, str):
            raise ZhihuInputError("query must be a string")
        result = value.strip()
        if not result or len(result) > 500 or any(ord(character) < 32 for character in result):
            raise ZhihuInputError("query is empty, too long, or contains control characters")
        return result


__all__ = ["DEFAULT_USER_AGENT", "ZhihuClient"]
