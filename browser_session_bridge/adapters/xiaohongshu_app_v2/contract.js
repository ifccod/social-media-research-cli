import {
  isRecord,
  validOptionalRequestIntervalMs
} from "../../core/protocol.js";

export const XIAOHONGSHU_APP_V2_ORIGIN = "https://www.xiaohongshu.com";
export const XIAOHONGSHU_APP_V2_LOGIN_URL =
  `${XIAOHONGSHU_APP_V2_ORIGIN}/explore`;
export const XIAOHONGSHU_APP_V2_TAB_PATTERNS = [
  `${XIAOHONGSHU_APP_V2_ORIGIN}/*`
];

export const XIAOHONGSHU_APP_V2_SEARCH_IMAGES_PATH =
  "/bridge/v1/xiaohongshu-app-v2/search-images";
export const XIAOHONGSHU_APP_V2_SEARCH_PRODUCTS_PATH =
  "/bridge/v1/xiaohongshu-app-v2/search-products";
export const XIAOHONGSHU_APP_V2_SEARCH_GROUPS_PATH =
  "/bridge/v1/xiaohongshu-app-v2/search-groups";
export const XIAOHONGSHU_APP_V2_PRODUCT_DETAIL_PATH =
  "/bridge/v1/xiaohongshu-app-v2/product-detail";
export const XIAOHONGSHU_APP_V2_PRODUCT_REVIEW_OVERVIEW_PATH =
  "/bridge/v1/xiaohongshu-app-v2/product-review-overview";
export const XIAOHONGSHU_APP_V2_PRODUCT_REVIEWS_PATH =
  "/bridge/v1/xiaohongshu-app-v2/product-reviews";
export const XIAOHONGSHU_APP_V2_PRODUCT_RECOMMENDATIONS_PATH =
  "/bridge/v1/xiaohongshu-app-v2/product-recommendations";
export const XIAOHONGSHU_APP_V2_TOPIC_INFO_PATH =
  "/bridge/v1/xiaohongshu-app-v2/topic-info";
export const XIAOHONGSHU_APP_V2_TOPIC_FEED_PATH =
  "/bridge/v1/xiaohongshu-app-v2/topic-feed";
export const XIAOHONGSHU_APP_V2_CREATOR_INSPIRATION_PATH =
  "/bridge/v1/xiaohongshu-app-v2/creator-inspiration";
export const XIAOHONGSHU_APP_V2_CREATOR_HOT_INSPIRATION_PATH =
  "/bridge/v1/xiaohongshu-app-v2/creator-hot-inspiration";

export const XIAOHONGSHU_APP_V2_ERROR_CODES = new Set([
  "forbidden",
  "invalid_request",
  "invalid_response",
  "not_logged_in",
  "rate_limited",
  "request_failed",
  "response_too_large",
  "runtime_unavailable",
  "tab_unavailable",
  "timeout",
  "verification_required"
]);

const XHS_ID = /^[a-fA-F0-9]{24}$/;
const PARAMETER_NAME = /^[A-Za-z][A-Za-z0-9_]{0,79}$/;
const OPAQUE = /^[A-Za-z0-9_.:-]{0,256}$/;
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

function operation(context, allowed, required = [], method = "GET") {
  return Object.freeze({
    method,
    context,
    allowed: new Set(allowed),
    required: new Set(required)
  });
}

const OPERATIONS = Object.freeze({
  [XIAOHONGSHU_APP_V2_SEARCH_IMAGES_PATH]: operation(
    "search",
    [
      "keyword",
      "page",
      "search_id",
      "search_session_id",
      "word_request_id",
      "source"
    ],
    ["keyword"],
    "POST"
  ),
  [XIAOHONGSHU_APP_V2_SEARCH_PRODUCTS_PATH]: operation(
    "search",
    ["keyword", "page", "search_id", "source"],
    ["keyword"]
  ),
  [XIAOHONGSHU_APP_V2_SEARCH_GROUPS_PATH]: operation(
    "chat",
    ["keyword", "page_no", "search_id", "source", "is_recommend"],
    ["keyword"]
  ),
  [XIAOHONGSHU_APP_V2_PRODUCT_DETAIL_PATH]: operation(
    "explore",
    ["sku_id", "source", "pre_page"],
    ["sku_id"]
  ),
  [XIAOHONGSHU_APP_V2_PRODUCT_REVIEW_OVERVIEW_PATH]: operation(
    "explore",
    ["sku_id", "tab"],
    ["sku_id"]
  ),
  [XIAOHONGSHU_APP_V2_PRODUCT_REVIEWS_PATH]: operation(
    "explore",
    ["sku_id", "page", "sort_strategy_type", "share_pics_only", "from_page"],
    ["sku_id"]
  ),
  [XIAOHONGSHU_APP_V2_PRODUCT_RECOMMENDATIONS_PATH]: operation(
    "explore",
    ["sku_id", "cursor_score", "region"],
    ["sku_id"]
  ),
  [XIAOHONGSHU_APP_V2_TOPIC_INFO_PATH]: operation(
    "search",
    ["page_id", "source", "note_id"],
    ["page_id"]
  ),
  [XIAOHONGSHU_APP_V2_TOPIC_FEED_PATH]: operation(
    "search",
    [
      "page_id",
      "sort",
      "cursor_score",
      "last_note_id",
      "last_note_ct",
      "session_id",
      "first_load_time",
      "source"
    ],
    ["page_id"]
  ),
  [XIAOHONGSHU_APP_V2_CREATOR_INSPIRATION_PATH]: operation(
    "explore",
    ["cursor", "tab", "source"]
  ),
  [XIAOHONGSHU_APP_V2_CREATOR_HOT_INSPIRATION_PATH]: operation(
    "explore",
    ["cursor"]
  )
});

function decimalInRange(value, minimum, maximum) {
  return /^(?:0|[1-9][0-9]*)$/.test(value) &&
    Number(value) >= minimum &&
    Number(value) <= maximum;
}

function validSource(path, value) {
  const expected = {
    [XIAOHONGSHU_APP_V2_SEARCH_IMAGES_PATH]: "explore_feed",
    [XIAOHONGSHU_APP_V2_SEARCH_PRODUCTS_PATH]: "explore_feed",
    [XIAOHONGSHU_APP_V2_SEARCH_GROUPS_PATH]: "unifiedSearchGroup",
    [XIAOHONGSHU_APP_V2_PRODUCT_DETAIL_PATH]: "mall_search",
    [XIAOHONGSHU_APP_V2_TOPIC_INFO_PATH]: "normal",
    [XIAOHONGSHU_APP_V2_TOPIC_FEED_PATH]: "normal",
    [XIAOHONGSHU_APP_V2_CREATOR_INSPIRATION_PATH]: "creator_center"
  }[path];
  return expected !== undefined && value === expected;
}

function validParameterValue(path, name, value) {
  if (
    typeof value !== "string" ||
    value.length > 1024 ||
    /[\r\n\0]/.test(value)
  ) {
    return false;
  }
  if (
    name === "sku_id" ||
    name === "page_id" ||
    name === "note_id" ||
    name === "last_note_id"
  ) {
    return value === "" ? name === "note_id" || name === "last_note_id" : XHS_ID.test(value);
  }
  if (name === "keyword") {
    return value.trim().length > 0 && value.length <= 256;
  }
  if (name === "page") {
    const minimum = path === XIAOHONGSHU_APP_V2_PRODUCT_REVIEWS_PATH ? 0 : 1;
    return decimalInRange(value, minimum, 10000);
  }
  if (name === "page_no") {
    return decimalInRange(value, 0, 10000);
  }
  if (name === "is_recommend" || name === "share_pics_only") {
    return value === "0" || value === "1";
  }
  if (name === "sort_strategy_type") {
    return value === "0" || value === "1";
  }
  if (name === "tab") {
    return decimalInRange(value, 0, 20);
  }
  if (name === "source") {
    return validSource(path, value);
  }
  if (name === "pre_page") {
    return value === "mall_search";
  }
  if (name === "from_page") {
    return value === "score_page";
  }
  if (name === "region") {
    return /^[A-Z]{2}$/.test(value);
  }
  if (name === "sort") {
    return value === "trend" || value === "time";
  }
  if (name === "last_note_ct" || name === "first_load_time") {
    return DIGITS.test(value);
  }
  if (
    name === "search_id" ||
    name === "search_session_id" ||
    name === "word_request_id" ||
    name === "cursor_score" ||
    name === "session_id" ||
    name === "cursor"
  ) {
    return OPAQUE.test(value);
  }
  return false;
}

export function getXiaohongshuAppV2Operation(path) {
  return typeof path === "string" && Object.prototype.hasOwnProperty.call(OPERATIONS, path)
    ? OPERATIONS[path]
    : null;
}

export function validXiaohongshuAppV2Entries(path, entries) {
  const descriptor = getXiaohongshuAppV2Operation(path);
  if (!descriptor || !Array.isArray(entries) || entries.length > 16) {
    return false;
  }
  const names = new Set();
  for (const entry of entries) {
    if (
      !Array.isArray(entry) ||
      entry.length !== 2 ||
      typeof entry[0] !== "string" ||
      !PARAMETER_NAME.test(entry[0]) ||
      !descriptor.allowed.has(entry[0]) ||
      names.has(entry[0]) ||
      !validParameterValue(path, entry[0], entry[1])
    ) {
      return false;
    }
    names.add(entry[0]);
  }
  for (const name of descriptor.required) {
    if (!names.has(name)) {
      return false;
    }
  }
  return true;
}

function contextPath(context, pathname) {
  if (context === "search") {
    return /^\/search_result\/?$/.test(pathname);
  }
  if (context === "chat") {
    return /^\/chat\/?$/.test(pathname);
  }
  return context === "explore" && /^\/(?:explore)?\/?$/.test(pathname);
}

export function validXiaohongshuAppV2Referer(path, entries, value) {
  const descriptor = getXiaohongshuAppV2Operation(path);
  if (
    !descriptor ||
    !validXiaohongshuAppV2Entries(path, entries) ||
    typeof value !== "string" ||
    value.length > 4096
  ) {
    return false;
  }
  try {
    const parsed = new URL(value);
    return (
      parsed.origin === XIAOHONGSHU_APP_V2_ORIGIN &&
      !parsed.username &&
      !parsed.password &&
      !parsed.port &&
      !parsed.hash &&
      !parsed.search &&
      contextPath(descriptor.context, parsed.pathname)
    );
  } catch {
    return false;
  }
}

export function isXiaohongshuAppV2TabUrl(value) {
  try {
    const parsed = new URL(value);
    return (
      parsed.origin === XIAOHONGSHU_APP_V2_ORIGIN &&
      !parsed.username &&
      !parsed.password &&
      !parsed.port
    );
  } catch {
    return false;
  }
}

export function sameXiaohongshuAppV2RequestContext(current, referer) {
  if (!isXiaohongshuAppV2TabUrl(current) || !isXiaohongshuAppV2TabUrl(referer)) {
    return false;
  }
  const currentURL = new URL(current);
  const refererURL = new URL(referer);
  return currentURL.pathname.replace(/\/$/, "").toLowerCase() ===
    refererURL.pathname.replace(/\/$/, "").toLowerCase();
}

export function validXiaohongshuAppV2Request(message) {
  if (
    !isRecord(message) ||
    FORBIDDEN_REQUEST_FIELDS.some((name) =>
      Object.prototype.hasOwnProperty.call(message, name)
    )
  ) {
    return false;
  }
  const descriptor = getXiaohongshuAppV2Operation(message.path);
  return Boolean(
    descriptor &&
    message.method === descriptor.method &&
    validOptionalRequestIntervalMs(message.request_interval_ms) &&
    validXiaohongshuAppV2Referer(message.path, message.entries, message.referer)
  );
}

export function xiaohongshuAppV2Method(path) {
  return getXiaohongshuAppV2Operation(path)?.method || "";
}
