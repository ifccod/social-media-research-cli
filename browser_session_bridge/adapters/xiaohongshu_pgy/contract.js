import {
  isRecord,
  validOptionalRequestIntervalMs
} from "../../core/protocol.js";

export const XIAOHONGSHU_PGY_ORIGIN = "https://pgy.xiaohongshu.com";
export const XIAOHONGSHU_PGY_LOGIN_URL = `${XIAOHONGSHU_PGY_ORIGIN}/`;
export const XIAOHONGSHU_PGY_TAB_PATTERNS = [`${XIAOHONGSHU_PGY_ORIGIN}/*`];

export const XIAOHONGSHU_PGY_NOTE_DETAIL_PATH =
  "/bridge/v1/xiaohongshu-pgy/note-detail";
export const XIAOHONGSHU_PGY_BLOGGER_DETAIL_PATH =
  "/bridge/v1/xiaohongshu-pgy/blogger-detail";
export const XIAOHONGSHU_PGY_BLOGGER_NOTES_PATH =
  "/bridge/v1/xiaohongshu-pgy/blogger-notes";
export const XIAOHONGSHU_PGY_BLOGGER_NOTES_RATE_PATH =
  "/bridge/v1/xiaohongshu-pgy/blogger-notes-rate";
export const XIAOHONGSHU_PGY_BLOGGER_CORE_DATA_PATH =
  "/bridge/v1/xiaohongshu-pgy/blogger-core-data";
export const XIAOHONGSHU_PGY_BLOGGER_DATA_SUMMARY_PATH =
  "/bridge/v1/xiaohongshu-pgy/blogger-data-summary";
export const XIAOHONGSHU_PGY_BLOGGER_FANS_SUMMARY_PATH =
  "/bridge/v1/xiaohongshu-pgy/blogger-fans-summary";
export const XIAOHONGSHU_PGY_BLOGGER_FANS_PROFILE_PATH =
  "/bridge/v1/xiaohongshu-pgy/blogger-fans-profile";
export const XIAOHONGSHU_PGY_BLOGGER_FANS_HISTORY_PATH =
  "/bridge/v1/xiaohongshu-pgy/blogger-fans-history";
export const XIAOHONGSHU_PGY_BLOGGER_LIST_PATH =
  "/bridge/v1/xiaohongshu-pgy/blogger-list";
export const XIAOHONGSHU_PGY_GOOD_CASE_CLASSES_PATH =
  "/bridge/v1/xiaohongshu-pgy/good-case-classes";
export const XIAOHONGSHU_PGY_GOOD_NOTES_PATH =
  "/bridge/v1/xiaohongshu-pgy/good-notes";
export const XIAOHONGSHU_PGY_GOOD_LIVES_PATH =
  "/bridge/v1/xiaohongshu-pgy/good-lives";
export const XIAOHONGSHU_PGY_TOP_BLOGGERS_PATH =
  "/bridge/v1/xiaohongshu-pgy/top-bloggers";
export const XIAOHONGSHU_PGY_INDUSTRIES_PATH =
  "/bridge/v1/xiaohongshu-pgy/industries";

export const XIAOHONGSHU_PGY_ERROR_CODES = new Set([
  "forbidden",
  "invalid_request",
  "invalid_response",
  "not_logged_in",
  "rate_limited",
  "request_failed",
  "response_too_large",
  "runtime_unavailable",
  "tab_unavailable",
  "verification_required"
]);

const XHS_ID = /^[a-fA-F0-9]{24}$/;
const INTEGER = /^(?:0|[1-9][0-9]{0,3})$/;
const DIGITS = /^[0-9]{0,20}$/;
const FORBIDDEN_REQUEST_FIELDS = Object.freeze([
  "body",
  "headers",
  "params",
  "cookie",
  "cookies",
  "authorization",
  "xsec",
  "xsec_token",
  "xsec_source",
  "signature"
]);

const OPERATIONS = Object.freeze({
  [XIAOHONGSHU_PGY_NOTE_DETAIL_PATH]: {
    method: "GET",
    allowed: new Set(["note_id", "biz_code"]),
    required: new Set(["note_id"])
  },
  [XIAOHONGSHU_PGY_BLOGGER_DETAIL_PATH]: {
    method: "GET",
    allowed: new Set(["user_id"]),
    required: new Set(["user_id"])
  },
  [XIAOHONGSHU_PGY_BLOGGER_NOTES_PATH]: {
    method: "GET",
    allowed: new Set([
      "user_id", "page_number", "page_size", "note_type", "order_type",
      "advertise_switch"
    ]),
    required: new Set(["user_id"])
  },
  [XIAOHONGSHU_PGY_BLOGGER_NOTES_RATE_PATH]: {
    method: "GET",
    allowed: new Set([
      "user_id", "business", "note_type", "date_type", "advertise_switch"
    ]),
    required: new Set(["user_id"])
  },
  [XIAOHONGSHU_PGY_BLOGGER_CORE_DATA_PATH]: {
    method: "POST",
    allowed: new Set([
      "user_id", "business", "note_type", "date_type", "advertise_switch"
    ]),
    required: new Set(["user_id"])
  },
  [XIAOHONGSHU_PGY_BLOGGER_DATA_SUMMARY_PATH]: {
    method: "GET",
    allowed: new Set(["user_id", "business"]),
    required: new Set(["user_id"])
  },
  [XIAOHONGSHU_PGY_BLOGGER_FANS_SUMMARY_PATH]: {
    method: "GET",
    allowed: new Set(["user_id"]),
    required: new Set(["user_id"])
  },
  [XIAOHONGSHU_PGY_BLOGGER_FANS_PROFILE_PATH]: {
    method: "GET",
    allowed: new Set(["user_id"]),
    required: new Set(["user_id"])
  },
  [XIAOHONGSHU_PGY_BLOGGER_FANS_HISTORY_PATH]: {
    method: "GET",
    allowed: new Set(["user_id", "date_type", "increase_type"]),
    required: new Set(["user_id"])
  },
  [XIAOHONGSHU_PGY_BLOGGER_LIST_PATH]: {
    method: "POST",
    allowed: new Set([
      "brand_user_id", "page_num", "page_size", "fans_number_lower",
      "fans_number_upper"
    ]),
    required: new Set()
  },
  [XIAOHONGSHU_PGY_GOOD_CASE_CLASSES_PATH]: {
    method: "GET",
    allowed: new Set(),
    required: new Set()
  },
  [XIAOHONGSHU_PGY_GOOD_NOTES_PATH]: {
    method: "GET",
    allowed: new Set(["category"]),
    required: new Set(["category"])
  },
  [XIAOHONGSHU_PGY_GOOD_LIVES_PATH]: {
    method: "GET",
    allowed: new Set(["category"]),
    required: new Set(["category"])
  },
  [XIAOHONGSHU_PGY_TOP_BLOGGERS_PATH]: {
    method: "GET",
    allowed: new Set(["rank_type"]),
    required: new Set(["rank_type"])
  },
  [XIAOHONGSHU_PGY_INDUSTRIES_PATH]: {
    method: "GET",
    allowed: new Set(),
    required: new Set()
  }
});

function entryMap(value) {
  return new Map(Array.isArray(value) ? value : []);
}

function validParameterValue(name, value) {
  if (typeof value !== "string" || value.length > 1024 || /[\r\n\0]/.test(value)) {
    return false;
  }
  if (name === "note_id" || name === "user_id" || name === "brand_user_id") {
    return XHS_ID.test(value);
  }
  if (name === "fans_number_lower" || name === "fans_number_upper") {
    return DIGITS.test(value);
  }
  if (name === "biz_code") {
    return value.length <= 64 && /^[A-Za-z0-9_-]*$/.test(value);
  }
  if (name === "category") {
    return (
      value === value.trim() &&
      [...value].length >= 1 &&
      [...value].length <= 64
    );
  }
  return INTEGER.test(value);
}

export function validXiaohongshuPgyEntries(path, value) {
  const operation = OPERATIONS[path];
  if (!operation || !Array.isArray(value) || value.length > 16) {
    return false;
  }
  const seen = new Set();
  for (const entry of value) {
    if (
      !Array.isArray(entry) ||
      entry.length !== 2 ||
      typeof entry[0] !== "string" ||
      !operation.allowed.has(entry[0]) ||
      seen.has(entry[0]) ||
      !validParameterValue(entry[0], entry[1])
    ) {
      return false;
    }
    seen.add(entry[0]);
  }
  for (const name of operation.required) {
    if (!seen.has(name)) {
      return false;
    }
  }
  const values = entryMap(value);
  if (
    values.has("fans_number_lower") &&
    values.has("fans_number_upper") &&
    values.get("fans_number_lower") &&
    values.get("fans_number_upper") &&
    BigInt(values.get("fans_number_lower")) > BigInt(values.get("fans_number_upper"))
  ) {
    return false;
  }
  return true;
}

export function validXiaohongshuPgyReferer(value) {
  if (typeof value !== "string" || value.length > 4096) {
    return false;
  }
  try {
    const parsed = new URL(value);
    return (
      parsed.origin === XIAOHONGSHU_PGY_ORIGIN &&
      !parsed.username &&
      !parsed.password &&
      !parsed.port &&
      !parsed.hash
    );
  } catch {
    return false;
  }
}

export function isXiaohongshuPgyTabUrl(value) {
  return validXiaohongshuPgyReferer(value);
}

export function sameXiaohongshuPgyRequestContext(current, referer) {
  if (!validXiaohongshuPgyReferer(current) || !validXiaohongshuPgyReferer(referer)) {
    return false;
  }
  return new URL(current).origin === new URL(referer).origin;
}

export function validXiaohongshuPgyRequest(message) {
  if (
    !isRecord(message) ||
    FORBIDDEN_REQUEST_FIELDS.some((name) => Object.prototype.hasOwnProperty.call(message, name))
  ) {
    return false;
  }
  const operation = OPERATIONS[message.path];
  return Boolean(
    operation &&
    message.method === operation.method &&
    validOptionalRequestIntervalMs(message.request_interval_ms) &&
    validXiaohongshuPgyEntries(message.path, message.entries) &&
    validXiaohongshuPgyReferer(message.referer)
  );
}

export function xiaohongshuPgyMethod(path) {
  return OPERATIONS[path]?.method || "";
}
