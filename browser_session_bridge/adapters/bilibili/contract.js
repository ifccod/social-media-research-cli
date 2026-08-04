const MID = /^[1-9][0-9]{0,19}$/;

export const BILIBILI_LOGIN_URL = "https://www.bilibili.com/";
export const BILIBILI_TAB_PATTERNS = [
  "https://www.bilibili.com/*",
  "https://space.bilibili.com/*"
];
export const BILIBILI_UP_STAT_PATH = "/bridge/v1/bilibili/up-stat";

export const BILIBILI_ERROR_CODES = new Set([
  "invalid_request",
  "runtime_unavailable",
  "request_failed",
  "timeout",
  "tab_unavailable",
  "invalid_response",
  "response_too_large",
  "not_logged_in",
  "verification_required",
  "rate_limited"
]);

export function validBilibiliEntries(path, entries) {
  return path === BILIBILI_UP_STAT_PATH &&
    Array.isArray(entries) &&
    entries.length === 1 &&
    Array.isArray(entries[0]) &&
    entries[0].length === 2 &&
    entries[0][0] === "mid" &&
    typeof entries[0][1] === "string" &&
    MID.test(entries[0][1]);
}

export function validBilibiliReferer(path, entries, value) {
  if (
    !validBilibiliEntries(path, entries) ||
    typeof value !== "string" ||
    value.length > 128
  ) {
    return false;
  }
  try {
    const parsed = new URL(value);
    return parsed.origin === "https://space.bilibili.com" &&
      parsed.pathname === `/${entries[0][1]}` &&
      parsed.search === "" &&
      parsed.hash === "" &&
      !parsed.username &&
      !parsed.password &&
      !parsed.port;
  } catch {
    return false;
  }
}

export function isBilibiliTabUrl(value) {
  try {
    const parsed = new URL(value);
    return (
      parsed.origin === "https://www.bilibili.com" ||
      parsed.origin === "https://space.bilibili.com"
    ) && !parsed.username && !parsed.password && !parsed.port;
  } catch {
    return false;
  }
}

export function sameBilibiliRequestContext(current, referer) {
  try {
    const currentURL = new URL(current);
    const refererURL = new URL(referer);
    return isBilibiliTabUrl(current) &&
      currentURL.origin === refererURL.origin &&
      currentURL.pathname === refererURL.pathname &&
      currentURL.search === refererURL.search;
  } catch {
    return false;
  }
}

export function validBilibiliRequest(message) {
  return Boolean(
    message &&
    validBilibiliReferer(message.path, message.entries, message.referer) &&
    (
      message.request_interval_ms === undefined ||
      (
        Number.isInteger(message.request_interval_ms) &&
        message.request_interval_ms >= 0 &&
        message.request_interval_ms <= 30000
      )
    )
  );
}
