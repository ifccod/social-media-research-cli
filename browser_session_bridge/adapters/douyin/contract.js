const PARAMETER_NAME = /^[A-Za-z][A-Za-z0-9_]{0,79}$/;

export const DOUYIN_ORIGIN = "https://www.douyin.com";
export const DOUYIN_TAB_PATTERNS = [`${DOUYIN_ORIGIN}/*`];
export const DOUYIN_ERROR_CODES = new Set([
  "invalid_request",
  "runtime_unavailable",
  "transport_modules_changed",
  "request_failed",
  "timeout",
  "tab_unavailable",
  "invalid_response",
  "response_too_large",
  "verification_required"
]);

const EMPTY_ONLY_PARAMETERS = new Set(["insert_ids", "whale_cut_token", "rcFT"]);
const ALLOWED_PARAMETERS = Object.freeze({
  "/aweme/v1/web/aweme/post/": new Set([
    "sec_user_id", "max_cursor", "locate_query", "show_live_replay_strategy",
    "need_time_list", "time_list_query", "whale_cut_token", "cut_version", "count",
    "publish_video_strategy_type", "from_user_page"
  ]),
  "/aweme/v1/web/comment/list/": new Set([
    "aweme_id", "pc_img_format", "cursor", "count", "item_type", "insert_ids",
    "whale_cut_token", "cut_version", "rcFT"
  ]),
  "/aweme/v1/web/comment/list/reply/": new Set([
    "item_id", "comment_id", "cursor", "count", "item_type", "whale_cut_token",
    "cut_version"
  ]),
  "/aweme/v1/web/search/item/": new Set([
    "keyword", "search_channel", "search_source", "query_correct_type", "is_filter_search",
    "from_group_id", "offset", "count", "sort_type", "publish_time", "search_id"
  ]),
  "/aweme/v1/web/challenge/detail/": new Set([
    "ch_id", "query_type"
  ]),
  "/aweme/v1/web/challenge/aweme/": new Set([
    "ch_id", "hashtag_name", "query_type", "sort_type", "offset", "cursor", "count"
  ]),
  "/aweme/v1/web/music/detail/": new Set([
    "music_id", "scene"
  ]),
  "/aweme/v1/web/music/aweme/": new Set([
    "music_id", "cursor", "count"
  ]),
  "/aweme/v1/web/mix/detail/": new Set([
    "mix_id", "req_from"
  ]),
  "/aweme/v1/web/mix/aweme/": new Set([
    "mix_id", "cursor", "count", "mix_scene"
  ]),
  "/aweme/v1/web/series/detail/": new Set([
    "series_id", "req_from"
  ]),
  "/aweme/v1/web/series/list/": new Set([
    "sec_user_id", "req_from", "cursor", "count"
  ]),
  "/aweme/v1/web/series/aweme/": new Set([
    "series_id", "pull_type", "cursor", "count"
  ])
});

export function validDouyinEntries(path, value) {
  const allowed = ALLOWED_PARAMETERS[path];
  if (!allowed || !Array.isArray(value) || value.length > 32) {
    return false;
  }
  const names = new Set();
  return value.every((entry) => {
    if (!Array.isArray(entry) || entry.length !== 2) {
      return false;
    }
    const [name, parameter] = entry;
    if (
      typeof name !== "string" ||
      typeof parameter !== "string" ||
      !PARAMETER_NAME.test(name) ||
      !allowed.has(name) ||
      names.has(name) ||
      (EMPTY_ONLY_PARAMETERS.has(name) && parameter !== "") ||
      parameter.length > 4096 ||
      /[\r\n\0]/.test(parameter)
    ) {
      return false;
    }
    names.add(name);
    return true;
  });
}

export function validDouyinReferer(path, value) {
  if (typeof value !== "string" || value.length > 4096) {
    return false;
  }
  let referer;
  try {
    referer = new URL(value);
  } catch {
    return false;
  }
  if (
    referer.origin !== DOUYIN_ORIGIN ||
    referer.username ||
    referer.password ||
    referer.hash ||
    (referer.port && referer.port !== "443")
  ) {
    return false;
  }
  if (path === "/aweme/v1/web/aweme/post/") {
    return /^\/user\/MS4wLjAB[A-Za-z0-9_-]{16,180}\/?$/.test(referer.pathname);
  }
  if (
    path === "/aweme/v1/web/comment/list/" ||
    path === "/aweme/v1/web/comment/list/reply/"
  ) {
    return /^\/(?:video|note|slides)\/[1-9]\d{9,21}\/?$/.test(referer.pathname);
  }
  if (path === "/aweme/v1/web/search/item/") {
    return referer.pathname.startsWith("/search/") &&
      referer.pathname.length > 8 &&
      [...referer.searchParams.keys()].length === 1 &&
      referer.searchParams.get("type") === "video";
  }
  if (
    path === "/aweme/v1/web/challenge/detail/" ||
    path === "/aweme/v1/web/challenge/aweme/"
  ) {
    return /^\/hashtag\/[1-9]\d{9,21}\/?$/.test(referer.pathname) &&
      [...referer.searchParams.keys()].length === 0;
  }
  if (
    path === "/aweme/v1/web/music/detail/" ||
    path === "/aweme/v1/web/music/aweme/"
  ) {
    return /^\/music\/[1-9]\d{9,21}\/?$/.test(referer.pathname) &&
      [...referer.searchParams.keys()].length === 0;
  }
  if (
    path === "/aweme/v1/web/mix/detail/" ||
    path === "/aweme/v1/web/mix/aweme/"
  ) {
    return /^\/collection\/[1-9]\d{9,21}(?:\/[1-9]\d{0,8})?\/?$/.test(referer.pathname) &&
      [...referer.searchParams.keys()].length === 0;
  }
  if (path === "/aweme/v1/web/series/list/") {
    return /^\/user\/MS4wLjAB[A-Za-z0-9_-]{16,180}\/?$/.test(referer.pathname) &&
      [...referer.searchParams.keys()].length === 0;
  }
  if (
    path === "/aweme/v1/web/series/detail/" ||
    path === "/aweme/v1/web/series/aweme/"
  ) {
    return /^\/series\/?$/.test(referer.pathname) &&
      [...referer.searchParams.keys()].length === 1 &&
      /^[1-9]\d{9,21}$/.test(referer.searchParams.get("series_id") || "");
  }
  return false;
}

export function isDouyinTabUrl(value) {
  try {
    const parsed = new URL(value);
    return (
      parsed.origin === DOUYIN_ORIGIN &&
      !parsed.username &&
      !parsed.password &&
      (!parsed.port || parsed.port === "443")
    );
  } catch {
    return false;
  }
}

export function sameDouyinRequestContext(current, referer) {
  try {
    const currentUrl = new URL(current);
    const refererUrl = new URL(referer);
    return (
      isDouyinTabUrl(current) &&
      currentUrl.pathname === refererUrl.pathname &&
      currentUrl.search === refererUrl.search
    );
  } catch {
    return false;
  }
}

export function validDouyinRequest(message) {
  const valid = (
    message &&
    typeof message.path === "string" &&
    Object.prototype.hasOwnProperty.call(ALLOWED_PARAMETERS, message.path) &&
    validDouyinEntries(message.path, message.entries) &&
    validDouyinReferer(message.path, message.referer)
  );
  if (!valid) {
    return false;
  }
  if (
    message.path === "/aweme/v1/web/mix/detail/" ||
    message.path === "/aweme/v1/web/mix/aweme/"
  ) {
    const match = new URL(message.referer).pathname.match(
      /^\/collection\/([1-9]\d{9,21})(?:\/[1-9]\d{0,8})?\/?$/
    );
    const mixID = message.entries.find(([name]) => name === "mix_id");
    return Boolean(match && mixID && mixID[1] === match[1]);
  }
  if (message.path === "/aweme/v1/web/series/list/") {
    const match = new URL(message.referer).pathname.match(
      /^\/user\/(MS4wLjAB[A-Za-z0-9_-]{16,180})\/?$/
    );
    const secUID = message.entries.find(([name]) => name === "sec_user_id");
    return Boolean(match && secUID && secUID[1] === match[1]);
  }
  if (
    message.path === "/aweme/v1/web/series/detail/" ||
    message.path === "/aweme/v1/web/series/aweme/"
  ) {
    const referer = new URL(message.referer);
    const seriesID = message.entries.find(([name]) => name === "series_id");
    return Boolean(
      seriesID && seriesID[1] === referer.searchParams.get("series_id")
    );
  }
  return true;
}
