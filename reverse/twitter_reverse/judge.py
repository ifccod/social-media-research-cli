from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import TwitterInputError, TwitterResponseError

_JUDGMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "matches_criteria",
        "need_tweets",
        "confidence",
        "summary",
        "reasons",
    ],
    "properties": {
        "matches_criteria": {
            "type": "boolean",
            "description": "true iff the account matches --criteria",
        },
        "need_tweets": {
            "type": "boolean",
            "description": "简介不足以判断时为 true",
        },
        "confidence": {"type": "number"},
        "summary": {"type": "string"},
        "reasons": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


def responses_url(base: str) -> str:
    """把调用方给的 Gemini 中转根路径收成 Responses 端点。"""
    value = base.strip().rstrip("/")
    if value.endswith("/responses"):
        return value
    if value.endswith("/v1"):
        return f"{value}/responses"
    return f"{value}/v1/responses"


def response_output_text(payload: Mapping[str, Any]) -> str:
    """取出 Responses JSON 里的模型文本，不把任意 message 当判定 JSON。"""
    text = payload.get("output_text")
    if isinstance(text, str) and text.strip():
        return text
    chunks: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, Mapping) and part.get("type") == "output_text":
                chunks.append(str(part.get("text") or ""))
    return "".join(chunks)


def judge_account(
    account: Mapping[str, Any],
    *,
    criteria: str,
    base_url: str,
    api_key: str,
    timeout: float,
    model: str = "gemini-3.8-flash",
) -> dict[str, Any]:
    """对单个脱敏账号调用一次 Gemini Responses，返回结构化判定。"""
    criteria_text = str(criteria or "").strip()
    base = str(base_url or "").strip()
    key = str(api_key or "").strip()
    if not base:
        raise TwitterInputError("缺少 Gemini base_url")
    if not key:
        raise TwitterInputError("缺少 Gemini api_key")
    if not criteria_text:
        raise TwitterInputError("缺少 criteria")

    body = json.dumps(
        _judgment_request(account, criteria=criteria_text, model=model),
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        responses_url(base),
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    return _parse_judgment(_read_responses(request, timeout))


def _judgment_request(
    account: Mapping[str, Any],
    *,
    criteria: str,
    model: str,
) -> dict[str, Any]:
    return {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": (
                    "你在为 X 冷启动筛选账号。"
                    "只根据给定简介和推文判断是否与下列主题相关："
                    f"{criteria}。"
                    "不要根据粉/关数给标签。"
                    "只输出一个 JSON 对象，不要 Markdown、不要解释。"
                    '字段必须是：{"matches_criteria":true,"need_tweets":false,"confidence":0.8,"summary":"...","reasons":["..."]}'
                ),
            },
            {"role": "user", "content": _account_prompt(account)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "twitter_follow_judgment",
                "strict": True,
                "schema": _JUDGMENT_SCHEMA,
            }
        },
        "reasoning": {"effort": "high"},
    }


def _account_prompt(account: Mapping[str, Any]) -> str:
    tweets = account.get("tweets")
    if not isinstance(tweets, list):
        tweets = []
    lines = [
        f"username: {_scalar(account.get('username'))}",
        f"name: {_scalar(account.get('name'))}",
        f"bio: {_scalar(account.get('description'))}",
        f"followers: {_scalar(account.get('followers'))}",
        f"following: {_scalar(account.get('following'))}",
        f"blue_verified: {_scalar(account.get('blue_verified'))}",
        "tweets:",
    ]
    for item in tweets:
        if not isinstance(item, Mapping):
            continue
        lines.append(f"- {_scalar(item.get('text'))}")
    return "\n".join(lines)


def _scalar(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return ""


def _read_responses(request: Request, timeout: float) -> bytes:
    try:
        return _urlopen_body(request, timeout)
    except HTTPError as exc:
        status = int(exc.code)
        exc.close()
        if status in {401, 403}:
            raise TwitterResponseError(
                "Gemini Responses 鉴权失败",
                code="gemini_unauthorized",
            ) from exc
        if status == 429:
            return _retry_after_rate_limit(request, timeout)
        raise TwitterResponseError(
            f"Gemini Responses 返回 HTTP {status}",
            code="llm_failed",
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise TwitterResponseError(
            "Gemini Responses 请求失败",
            code="llm_failed",
        ) from exc


def _retry_after_rate_limit(request: Request, timeout: float) -> bytes:
    # 429 只再 POST 一次同样 body；第二次无论 429 还是其它失败都记 gemini_rate_limited。
    try:
        return _urlopen_body(request, timeout)
    except HTTPError as exc:
        exc.close()
        raise TwitterResponseError(
            "Gemini Responses 请求频率受限",
            code="gemini_rate_limited",
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise TwitterResponseError(
            "Gemini Responses 请求频率受限",
            code="gemini_rate_limited",
        ) from exc


def _urlopen_body(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _parse_judgment(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
        if not isinstance(payload, Mapping):
            raise TypeError("Gemini payload is not an object")
        raw_text = response_output_text(payload)
        loaded = _loads_judgment_object(raw_text)
        judgment = _normalize_judgment(loaded)
        matches = _as_bool(judgment.get("matches_criteria"))
        if matches is None:
            raise KeyError(
                "matches_criteria，实际键: "
                + ",".join(str(key) for key in loaded.keys())
            )
        need_tweets = _as_bool(judgment.get("need_tweets"))
        if need_tweets is None:
            need_tweets = False
        return {
            "matches_criteria": matches,
            "need_tweets": need_tweets,
            "confidence": _as_number(judgment.get("confidence"), 0.5),
            "summary": _as_str(judgment.get("summary")),
            "reasons": _as_str_list(judgment.get("reasons")),
        }
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError, KeyError) as exc:
        raise TwitterResponseError(
            f"Gemini 判定结果无法解析: {exc}",
            code="llm_failed",
        ) from exc


def _loads_judgment_object(text: str) -> Mapping[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped[:4].lower() == "json":
            stripped = stripped[4:]
        stripped = stripped.strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(stripped[start : end + 1])
    if not isinstance(value, Mapping):
        raise TypeError("Gemini judgment is not an object")
    return value


def _first_present(payload: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload and payload[name] is not None:
            return payload[name]
    return None


def _normalize_judgment(payload: Mapping[str, Any]) -> dict[str, Any]:
    """中转常忽略 json_schema，把 relevant/reason 收成规范字段。"""
    matches = _first_present(
        payload,
        "matches_criteria",
        "relevant",
        "ai_related",
        "related",
        "match",
    )
    need_tweets = _first_present(
        payload, "need_tweets", "needTweets", "need_more"
    )
    confidence = _first_present(payload, "confidence", "score")
    summary = _first_present(payload, "summary", "reason", "explanation")
    reasons = _first_present(payload, "reasons")
    if reasons is None:
        reason = _first_present(payload, "reason")
        reasons = [str(reason)] if reason not in (None, "") else []
    return {
        "matches_criteria": matches,
        "need_tweets": False if need_tweets is None else need_tweets,
        "confidence": 0.5 if confidence is None else confidence,
        "summary": "" if summary is None else summary,
        "reasons": reasons,
    }


def _as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(int(value))
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "yes", "y", "1", "是", "相关"}:
            return True
        if text in {"false", "no", "n", "0", "否", "不相关"}:
            return False
    return None


def _as_number(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _as_str(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value in (None, ""):
        return []
    return [str(value)]
