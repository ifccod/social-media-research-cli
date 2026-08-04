const PARAMETER_NAME = /^[A-Za-z][A-Za-z0-9_]{0,79}$/;
const FULLNAME = /^t3_[a-z0-9]+$/;
const OPAQUE_AFTER = /^dDNf[A-Za-z0-9+/]{2,252}={0,2}$/;
const TOPIC_ID = /^[a-z0-9]{1,16}$/;
const TOPIC_SLUG = /^[a-z0-9]+(?:_[a-z0-9]+){0,15}$/;
const HOME_SORTS = new Set(["BEST", "HOT", "NEW", "TOP", "CONTROVERSIAL"]);
const DISCOVERY_SORTS = new Set([
  "BEST", "HOT", "NEW", "TOP", "CONTROVERSIAL", "RISING"
]);
const TIMES = new Set(["ALL", "HOUR", "DAY", "WEEK", "MONTH", "YEAR"]);

export const REDDIT_ORIGIN = "https://www.reddit.com";
export const REDDIT_LOGIN_URL = `${REDDIT_ORIGIN}/`;
export const REDDIT_TAB_PATTERNS = [
  "https://www.reddit.com/*",
  "https://reddit.com/*"
];
export const REDDIT_HOME_FEED_PATH = "/bridge/v1/reddit/home-feed";
export const REDDIT_POPULAR_FEED_PATH = "/bridge/v1/reddit/popular-feed";
export const REDDIT_NEWS_FEED_PATH = "/bridge/v1/reddit/news-feed";
export const REDDIT_EXPLORE_FEED_PATH = "/bridge/v1/reddit/explore-feed";
export const REDDIT_TOPIC_FEED_PATH = "/bridge/v1/reddit/topic-feed";

const FEEDS = Object.freeze({
  [REDDIT_HOME_FEED_PATH]: {
    refererPath: "/",
    refererSearch: "",
    supportsTime: false,
    sorts: HOME_SORTS
  },
  [REDDIT_POPULAR_FEED_PATH]: {
    refererPath: "/r/popular/",
    refererSearch: "",
    supportsTime: true,
    sorts: DISCOVERY_SORTS
  },
  [REDDIT_NEWS_FEED_PATH]: {
    refererPath: "/news",
    refererSearch: "?feed=news",
    supportsTime: true,
    sorts: DISCOVERY_SORTS
  }
});

const COMMUNITY_PAGES = new Set([
  REDDIT_EXPLORE_FEED_PATH,
  REDDIT_TOPIC_FEED_PATH
]);

export const REDDIT_ERROR_CODES = new Set([
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

function validOpaqueAfter(value) {
  if (value === "") return true;
  if (!OPAQUE_AFTER.test(value)) return false;
  try {
    return FULLNAME.test(atob(value));
  } catch {
    return false;
  }
}

function validOptionalRequestIntervalMs(value) {
  return value === undefined ||
    (Number.isInteger(value) && value >= 0 && value <= 30000);
}

function entryValues(entries, allowed, expectedEntries) {
  if (!Array.isArray(entries) || entries.length !== expectedEntries) return null;
  const values = new Map();
  for (const entry of entries) {
    if (
      !Array.isArray(entry) ||
      entry.length !== 2 ||
      typeof entry[0] !== "string" ||
      typeof entry[1] !== "string" ||
      !PARAMETER_NAME.test(entry[0]) ||
      !allowed.has(entry[0]) ||
      values.has(entry[0]) ||
      /[\r\n\0]/.test(entry[1])
    ) {
      return null;
    }
    values.set(entry[0], entry[1]);
  }
  return values;
}

export function validRedditEntries(path, entries) {
  if (COMMUNITY_PAGES.has(path)) {
    const topic = path === REDDIT_TOPIC_FEED_PATH;
    const allowed = new Set(topic ? ["topic_id", "slug", "limit"] : ["limit"]);
    const values = entryValues(entries, allowed, topic ? 3 : 1);
    const limit = values?.get("limit") || "";
    if (
      !values ||
      !/^[1-9]\d?$/.test(limit) ||
      Number(limit) > 50
    ) {
      return false;
    }
    return !topic || (
      TOPIC_ID.test(values.get("topic_id") || "") &&
      (values.get("slug") || "").length <= 80 &&
      TOPIC_SLUG.test(values.get("slug") || "")
    );
  }
  const feed = FEEDS[path];
  const expectedEntries = feed?.supportsTime ? 4 : 3;
  if (!feed) return false;
  const allowed = new Set(["sort", "limit", "after"]);
  if (feed.supportsTime) allowed.add("time");
  const values = entryValues(entries, allowed, expectedEntries);
  if (!values) return false;
  const limit = values.get("limit") || "";
  return feed.sorts.has(values.get("sort")) &&
    /^[1-9]\d{0,2}$/.test(limit) &&
    Number(limit) <= 100 &&
    (!feed.supportsTime || TIMES.has(values.get("time"))) &&
    validOpaqueAfter(values.get("after") || "");
}

export function validRedditReferer(
  value,
  path = REDDIT_HOME_FEED_PATH,
  entries = []
) {
  const feed = FEEDS[path];
  const communityPage = COMMUNITY_PAGES.has(path);
  if ((!feed && !communityPage) || typeof value !== "string" || value.length > 180) {
    return false;
  }
  try {
    const parsed = new URL(value);
    if (
      parsed.origin !== REDDIT_ORIGIN ||
      parsed.hash !== "" ||
      parsed.username ||
      parsed.password ||
      parsed.port
    ) {
      return false;
    }
    if (communityPage) {
      if (parsed.search !== "") return false;
      if (path === REDDIT_EXPLORE_FEED_PATH) {
        return parsed.pathname === "/explore/";
      }
      const values = entryValues(
        entries,
        new Set(["topic_id", "slug", "limit"]),
        3
      );
      return Boolean(
        values &&
        parsed.pathname ===
          `/explore/${values.get("topic_id")}/${values.get("slug")}/`
      );
    }
    return parsed.origin === REDDIT_ORIGIN &&
      parsed.pathname === feed.refererPath &&
      parsed.search === feed.refererSearch &&
      parsed.hash === "" &&
      !parsed.username &&
      !parsed.password &&
      !parsed.port;
  } catch {
    return false;
  }
}

export function isRedditCommunityPagePath(value) {
  return COMMUNITY_PAGES.has(value);
}

export function isRedditTabUrl(value) {
  try {
    const parsed = new URL(value);
    return parsed.origin === REDDIT_ORIGIN &&
      !parsed.username &&
      !parsed.password &&
      !parsed.port;
  } catch {
    return false;
  }
}

export function sameRedditRequestContext(current, referer) {
  try {
    const currentURL = new URL(current);
    const refererURL = new URL(referer);
    return isRedditTabUrl(current) &&
      currentURL.pathname === refererURL.pathname &&
      currentURL.search === refererURL.search;
  } catch {
    return false;
  }
}

export function validRedditRequest(message) {
  return Boolean(
    message &&
    (FEEDS[message.path] || COMMUNITY_PAGES.has(message.path)) &&
    validRedditEntries(message.path, message.entries) &&
    validRedditReferer(message.referer, message.path, message.entries) &&
    validOptionalRequestIntervalMs(message.request_interval_ms)
  );
}
