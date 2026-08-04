import { validOptionalRequestIntervalMs } from "../../core/protocol.js";

const PARAMETER_NAME = /^[A-Za-z][A-Za-z0-9_]{0,79}$/;
const XHS_ID = /^[a-fA-F0-9]{24}$/;
const SEARCH_ID = /^[A-Za-z0-9_-]{8,128}$/;
const CATEGORY = /^[A-Za-z][A-Za-z0-9_.-]{0,79}$/;
const XSEC_TOKEN = /^[A-Za-z0-9_-]+={0,2}$/;
const XSEC_SOURCE = /^[A-Za-z0-9_-]+$/;

export const XIAOHONGSHU_ORIGIN = "https://www.xiaohongshu.com";
export const XIAOHONGSHU_API_ORIGIN = "https://edith.xiaohongshu.com";
export const XIAOHONGSHU_LOGIN_URL = `${XIAOHONGSHU_ORIGIN}/explore`;
export const XIAOHONGSHU_TAB_PATTERNS = [`${XIAOHONGSHU_ORIGIN}/*`];

export const XIAOHONGSHU_USER_POSTED_PATH = "/api/sns/web/v1/user_posted";
export const XIAOHONGSHU_SEARCH_NOTES_PATH = "/api/sns/web/v2/search/notes";
export const XIAOHONGSHU_FEED_PATH = "/api/sns/web/v1/feed";
export const XIAOHONGSHU_HOMEFEED_PATH = "/api/sns/web/v1/homefeed";
export const XIAOHONGSHU_HOMEFEED_CATEGORY_PATH = "/api/sns/web/v1/homefeed/category";
export const XIAOHONGSHU_SEARCH_HOTLIST_PATH =
  "/api/sns/web/v1/search/trending/query";
export const XIAOHONGSHU_SEARCH_RECOMMEND_PATH = "/api/sns/web/v1/search/recommend";
export const XIAOHONGSHU_SEARCH_FILTER_PATH = "/api/sns/web/v1/search/filter";
export const XIAOHONGSHU_SEARCH_USERS_PATH = "/api/sns/web/v1/search/usersearch";
export const XIAOHONGSHU_USER_INFO_PATH = "/api/sns/web/v1/user/otherinfo";
export const XIAOHONGSHU_COLLECTED_NOTES_PATH = "/api/sns/web/v2/note/collect/page";
export const XIAOHONGSHU_COMMENT_PATH = "/api/sns/web/v2/comment/page";
export const XIAOHONGSHU_SUB_COMMENT_PATH = "/api/sns/web/v2/comment/sub/page";
export const XIAOHONGSHU_WIDGETS_PATH = "/api/sns/web/v2/widgets";

export const XIAOHONGSHU_ERROR_CODES = new Set([
  "invalid_request",
  "runtime_unavailable",
  "request_failed",
  "timeout",
  "tab_unavailable",
  "invalid_response",
  "response_too_large",
  "not_logged_in",
  "forbidden",
  "verification_required",
  "rate_limited"
]);

function operation(method, context, allowed, required = []) {
  return Object.freeze({
    method,
    context,
    allowed: new Set(allowed),
    required: new Set(required)
  });
}

const OPERATIONS = Object.freeze({
  [XIAOHONGSHU_USER_POSTED_PATH]: operation(
    "GET", "profile", ["user_id", "cursor", "num", "image_formats"], ["user_id"]
  ),
  [XIAOHONGSHU_SEARCH_NOTES_PATH]: operation(
    "POST",
    "search",
    ["keyword", "page", "page_size", "search_id", "sort", "note_type"],
    ["keyword", "page", "page_size", "search_id"]
  ),
  [XIAOHONGSHU_FEED_PATH]: operation(
    "POST", "note", ["note_id", "image_formats"], ["note_id"]
  ),
  [XIAOHONGSHU_HOMEFEED_PATH]: operation(
    "POST", "explore", ["cursor_score", "num", "category", "need_filter_image"]
  ),
  [XIAOHONGSHU_HOMEFEED_CATEGORY_PATH]: operation("GET", "explore", []),
  [XIAOHONGSHU_SEARCH_HOTLIST_PATH]: operation("GET", "search", []),
  [XIAOHONGSHU_SEARCH_RECOMMEND_PATH]: operation("GET", "search", ["keyword"]),
  [XIAOHONGSHU_SEARCH_FILTER_PATH]: operation(
    "GET", "search", ["keyword", "search_id"], ["keyword", "search_id"]
  ),
  [XIAOHONGSHU_SEARCH_USERS_PATH]: operation(
    "POST",
    "search",
    ["keyword", "page", "page_size", "search_id"],
    ["keyword", "page", "page_size", "search_id"]
  ),
  [XIAOHONGSHU_USER_INFO_PATH]: operation(
    "GET", "profile", ["user_id", "image_formats"], ["user_id"]
  ),
  [XIAOHONGSHU_COLLECTED_NOTES_PATH]: operation(
    "GET", "profile", ["user_id", "cursor", "num", "image_formats"], ["user_id"]
  ),
  [XIAOHONGSHU_COMMENT_PATH]: operation(
    "GET",
    "note",
    ["note_id", "cursor", "top_comment_id", "image_formats"],
    ["note_id"]
  ),
  [XIAOHONGSHU_SUB_COMMENT_PATH]: operation(
    "GET",
    "note",
    ["note_id", "root_comment_id", "num", "cursor", "top_comment_id", "image_formats"],
    ["note_id", "root_comment_id"]
  ),
  [XIAOHONGSHU_WIDGETS_PATH]: operation(
    "POST", "note", ["note_id"], ["note_id"]
  )
});

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

function entryMap(value) {
  return new Map(value.map(([name, parameter]) => [name, parameter]));
}

function xsecQuery(value, allowXsec) {
  const names = [...value.searchParams.keys()];
  if (names.length === 0) {
    return { token: "", source: "", sourcePresent: false };
  }
  if (!allowXsec || names.length > 2 || new Set(names).size !== names.length) {
    return null;
  }
  for (const name of names) {
    if (name !== "xsec_token" && name !== "xsec_source") {
      return null;
    }
  }
  const tokens = value.searchParams.getAll("xsec_token");
  const sources = value.searchParams.getAll("xsec_source");
  const validToken = tokens.length === 1 &&
    tokens[0].length > 0 &&
    tokens[0].length <= 512 &&
    tokens[0] === tokens[0].trim() &&
    XSEC_TOKEN.test(tokens[0]);
  if (
    tokens.length > 1 ||
    sources.length > 1 ||
    (tokens.length === 1 && !validToken) ||
    (sources.length === 1 && (
      sources[0].length === 0
        ? !validToken
        : sources[0].length > 64 ||
          sources[0] !== sources[0].trim() ||
          !XSEC_SOURCE.test(sources[0])
    ))
  ) {
    return null;
  }
  return {
    token: tokens[0] || "",
    source: sources[0] || "",
    sourcePresent: sources.length === 1
  };
}

function pathAllowsXsec(pathname) {
  return /^\/(?:explore|discovery\/item)\/[a-fA-F0-9]{24}\/?$/.test(pathname) ||
    /^\/user\/profile\/[a-fA-F0-9]{24}\/?$/.test(pathname);
}

function decimalInRange(value, minimum, maximum) {
  return /^(?:0|[1-9]\d*)$/.test(value) &&
    Number(value) >= minimum &&
    Number(value) <= maximum;
}

function validParameterValue(path, name, value) {
  if (name === "note_id" || name === "root_comment_id" || name === "user_id") {
    return XHS_ID.test(value);
  }
  if (name === "num") {
    return decimalInRange(value, 1, path === XIAOHONGSHU_HOMEFEED_PATH ? 40 : 100);
  }
  if (name === "page") {
    return decimalInRange(value, 1, 10000);
  }
  if (name === "page_size") {
    const maximum = path === XIAOHONGSHU_SEARCH_NOTES_PATH ? 20 : 50;
    return decimalInRange(value, 1, maximum);
  }
  if (name === "search_id") {
    return SEARCH_ID.test(value);
  }
  if (name === "image_formats") {
    return value === "jpg,webp,avif";
  }
  if (name === "top_comment_id") {
    return value === "";
  }
  if (name === "sort") {
    return new Set([
      "general",
      "popularity_descending",
      "time_descending",
      "comment_descending",
      "collect_descending"
    ]).has(value);
  }
  if (name === "note_type") {
    return value === "0" || value === "1" || value === "2";
  }
  if (name === "need_filter_image") {
    return value === "true" || value === "false";
  }
  if (name === "category") {
    return CATEGORY.test(value);
  }
  if (name === "keyword") {
    return (
      (path === XIAOHONGSHU_SEARCH_RECOMMEND_PATH || value.trim().length > 0) &&
      value.length <= 256
    );
  }
  return true;
}

export function getXiaohongshuOperation(path) {
  return typeof path === "string" && Object.prototype.hasOwnProperty.call(OPERATIONS, path)
    ? OPERATIONS[path]
    : null;
}

export function validXiaohongshuEntries(path, value) {
  const descriptor = getXiaohongshuOperation(path);
  if (!descriptor || !Array.isArray(value) || value.length > 16) {
    return false;
  }
  const names = new Set();
  for (const entry of value) {
    if (!Array.isArray(entry) || entry.length !== 2) {
      return false;
    }
    const [name, parameter] = entry;
    if (
      typeof name !== "string" ||
      typeof parameter !== "string" ||
      !PARAMETER_NAME.test(name) ||
      !descriptor.allowed.has(name) ||
      names.has(name) ||
      parameter.length > 4096 ||
      /[\r\n\0]/.test(parameter) ||
      !validParameterValue(path, name, parameter)
    ) {
      return false;
    }
    names.add(name);
  }
  for (const name of descriptor.required) {
    if (!names.has(name)) {
      return false;
    }
  }
  return true;
}

export function validXiaohongshuReferer(path, entries, value) {
  const descriptor = getXiaohongshuOperation(path);
  if (
    !descriptor ||
    !validXiaohongshuEntries(path, entries) ||
    typeof value !== "string" ||
    value.length > 4096
  ) {
    return false;
  }
  let referer;
  try {
    referer = new URL(value);
  } catch {
    return false;
  }
  if (
    referer.origin !== XIAOHONGSHU_ORIGIN ||
    referer.username ||
    referer.password ||
    referer.port ||
    referer.hash
  ) {
    return false;
  }
  if (!xsecQuery(
    referer,
    descriptor.context === "note" || descriptor.context === "profile"
  )) {
    return false;
  }
  const values = entryMap(entries);
  if (descriptor.context === "note") {
    const match = /^\/(?:explore|discovery\/item)\/([a-fA-F0-9]{24})\/?$/.exec(
      referer.pathname
    );
    const noteID = values.get("note_id");
    return Boolean(match && noteID && match[1].toLowerCase() === noteID.toLowerCase());
  }
  if (descriptor.context === "profile") {
    const match = /^\/user\/profile\/([a-fA-F0-9]{24})\/?$/.exec(referer.pathname);
    const userID = values.get("user_id");
    return Boolean(match && userID && match[1].toLowerCase() === userID.toLowerCase());
  }
  if (descriptor.context === "search") {
    return /^\/search_result\/?$/.test(referer.pathname);
  }
  return descriptor.context === "explore" && /^\/(?:explore)?\/?$/.test(referer.pathname);
}

export function isXiaohongshuTabUrl(value) {
  try {
    const parsed = new URL(value);
    return (
      parsed.origin === XIAOHONGSHU_ORIGIN &&
      !parsed.username &&
      !parsed.password &&
      !parsed.port
    );
  } catch {
    return false;
  }
}

export function sameXiaohongshuRequestContext(current, referer) {
  try {
    const currentURL = new URL(current);
    const refererURL = new URL(referer);
    return (
      isXiaohongshuTabUrl(current) &&
      isXiaohongshuTabUrl(referer) &&
      !currentURL.hash &&
      !refererURL.hash &&
      xsecQuery(currentURL, pathAllowsXsec(currentURL.pathname)) !== null &&
      xsecQuery(refererURL, pathAllowsXsec(refererURL.pathname)) !== null &&
      currentURL.pathname.replace(/\/$/, "").toLowerCase() ===
        refererURL.pathname.replace(/\/$/, "").toLowerCase() &&
      sameRequestedXsec(currentURL, refererURL)
    );
  } catch {
    return false;
  }
}

function sameRequestedXsec(current, requested) {
  const currentXsec = xsecQuery(current, pathAllowsXsec(current.pathname));
  const requestedXsec = xsecQuery(requested, pathAllowsXsec(requested.pathname));
  if (!currentXsec || !requestedXsec) {
    return false;
  }
  if (!requestedXsec.token && !requestedXsec.source) {
    return true;
  }
  if (currentXsec.token !== requestedXsec.token) {
    return false;
  }
  if (requestedXsec.sourcePresent && requestedXsec.source === "") {
    return currentXsec.sourcePresent;
  }
  return currentXsec.source === requestedXsec.source;
}

export function validXiaohongshuRequest(message) {
  if (
    !message ||
    typeof message.path !== "string" ||
    typeof message.method !== "string" ||
    FORBIDDEN_REQUEST_FIELDS.some((name) => Object.prototype.hasOwnProperty.call(message, name))
  ) {
    return false;
  }
  const descriptor = getXiaohongshuOperation(message.path);
  return Boolean(
    descriptor &&
    message.method === descriptor.method &&
    validOptionalRequestIntervalMs(message.request_interval_ms) &&
    validXiaohongshuReferer(message.path, message.entries, message.referer)
  );
}
