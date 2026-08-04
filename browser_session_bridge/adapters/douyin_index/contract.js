const DATE = /^[0-9]{8}$/;
const PARAMETER_NAME = /^[A-Za-z][A-Za-z0-9_]{0,79}$/;

export const DOUYIN_INDEX_ORIGIN = "https://creator.douyin.com";
export const DOUYIN_INDEX_LOGIN_URL =
  `${DOUYIN_INDEX_ORIGIN}/creator-micro/creator-count/arithmetic-index`;
export const DOUYIN_INDEX_TAB_PATTERNS = [`${DOUYIN_INDEX_ORIGIN}/*`];
export const DOUYIN_INDEX_KEYWORD_TREND_PATH =
  "/api/v2/index/get_multi_keyword_hot_trend";
export const DOUYIN_INDEX_ERROR_CODES = new Set([
  "invalid_request",
  "runtime_unavailable",
  "transport_modules_changed",
  "request_failed",
  "timeout",
  "tab_unavailable",
  "invalid_response",
  "response_too_large",
  "verification_required",
  "not_logged_in",
  "rate_limited"
]);

const REQUIRED_PARAMETERS = new Set([
  "keyword_list",
  "start_date",
  "end_date",
  "app_name"
]);
const ALLOWED_PARAMETERS = new Set([...REQUIRED_PARAMETERS, "region"]);

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasControlCharacters(value) {
  return /[\r\n\0]/.test(value);
}

function validCalendarDate(value) {
  if (!DATE.test(value)) {
    return false;
  }
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
  );
}

function parseStringList(value, maximumItems, maximumLength, allowEmpty = false) {
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch {
    return null;
  }
  if (
    !Array.isArray(parsed) ||
    parsed.length > maximumItems ||
    (!allowEmpty && parsed.length === 0)
  ) {
    return null;
  }
  const seen = new Set();
  for (const item of parsed) {
    if (
      typeof item !== "string" ||
      item !== item.trim() ||
      item.length === 0 ||
      [...item].length > maximumLength ||
      hasControlCharacters(item) ||
      seen.has(item)
    ) {
      return null;
    }
    seen.add(item);
  }
  return parsed;
}

export function validDouyinIndexReferer(value) {
  if (typeof value !== "string" || value.length > 4096) {
    return false;
  }
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    return false;
  }
  return (
    parsed.origin === DOUYIN_INDEX_ORIGIN &&
    parsed.pathname ===
      "/creator-micro/creator-count/arithmetic-index" &&
    !parsed.username &&
    !parsed.password &&
    !parsed.search &&
    !parsed.hash &&
    (!parsed.port || parsed.port === "443")
  );
}

export function isDouyinIndexTabUrl(value) {
  try {
    const parsed = new URL(value);
    return (
      parsed.origin === DOUYIN_INDEX_ORIGIN &&
      parsed.pathname.startsWith(
        "/creator-micro/creator-count/arithmetic-index"
      ) &&
      !parsed.username &&
      !parsed.password &&
      (!parsed.port || parsed.port === "443")
    );
  } catch {
    return false;
  }
}

export function sameDouyinIndexRequestContext(current, referer) {
  return isDouyinIndexTabUrl(current) && validDouyinIndexReferer(referer);
}

export function validDouyinIndexEntries(value) {
  if (!Array.isArray(value) || value.length < 4 || value.length > 5) {
    return false;
  }
  const values = new Map();
  for (const entry of value) {
    if (
      !Array.isArray(entry) ||
      entry.length !== 2 ||
      typeof entry[0] !== "string" ||
      typeof entry[1] !== "string" ||
      !PARAMETER_NAME.test(entry[0]) ||
      !ALLOWED_PARAMETERS.has(entry[0]) ||
      values.has(entry[0]) ||
      entry[1].length > 4096 ||
      hasControlCharacters(entry[1])
    ) {
      return false;
    }
    values.set(entry[0], entry[1]);
  }
  for (const name of REQUIRED_PARAMETERS) {
    if (!values.has(name)) {
      return false;
    }
  }
  if (
    !parseStringList(values.get("keyword_list"), 5, 50) ||
    (values.has("region") &&
      !parseStringList(values.get("region"), 34, 32, true)) ||
    !validCalendarDate(values.get("start_date")) ||
    !validCalendarDate(values.get("end_date")) ||
    values.get("start_date") > values.get("end_date") ||
    !["aweme", "toutiao"].includes(values.get("app_name"))
  ) {
    return false;
  }
  const start = Date.UTC(
    Number(values.get("start_date").slice(0, 4)),
    Number(values.get("start_date").slice(4, 6)) - 1,
    Number(values.get("start_date").slice(6, 8))
  );
  const end = Date.UTC(
    Number(values.get("end_date").slice(0, 4)),
    Number(values.get("end_date").slice(4, 6)) - 1,
    Number(values.get("end_date").slice(6, 8))
  );
  return end - start <= 366 * 24 * 60 * 60 * 1000;
}

export function validDouyinIndexRequest(message) {
  return Boolean(
    isRecord(message) &&
    Object.keys(message).every((name) =>
      ["path", "entries", "referer", "request_interval_ms"].includes(name)
    ) &&
    message.path === DOUYIN_INDEX_KEYWORD_TREND_PATH &&
    validDouyinIndexEntries(message.entries) &&
    validDouyinIndexReferer(message.referer) &&
    (
      message.request_interval_ms === undefined ||
      (
        Number.isInteger(message.request_interval_ms) &&
        message.request_interval_ms >= 0 &&
        message.request_interval_ms <= 10000
      )
    )
  );
}
