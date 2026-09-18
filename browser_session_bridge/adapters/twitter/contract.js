const INTEGER = /^[1-9][0-9]{0,2}$/;
const CONTROL = /[\r\n\0]/;
const PRODUCTS = new Set(["Top", "Latest"]);

export const TWITTER_ORIGIN = "https://x.com";
export const TWITTER_HOME_URL = `${TWITTER_ORIGIN}/home`;
export const TWITTER_SEARCH_URL =
  `${TWITTER_ORIGIN}/search?q=social%20research&src=typed_query&f=top`;
export const TWITTER_TAB_PATTERNS = [
  "https://x.com/*",
  "https://www.x.com/*",
  "https://twitter.com/*",
  "https://www.twitter.com/*"
];
export const TWITTER_HOME_FEED_PATH = "/bridge/v1/twitter/home-feed";
export const TWITTER_SEARCH_POSTS_PATH = "/bridge/v1/twitter/search-posts";
export const TWITTER_USER_PATH = "/bridge/v1/twitter/user";
export const TWITTER_USER_TWEETS_PATH = "/bridge/v1/twitter/user-tweets";
export const TWITTER_FOLLOWERS_PATH = "/bridge/v1/twitter/followers";
export const TWITTER_FOLLOWING_PATH = "/bridge/v1/twitter/following";
export const TWITTER_FOLLOW_PATH = "/bridge/v1/twitter/follow";
export const TWITTER_UPLOAD_MEDIA_PATH = "/bridge/v1/twitter/upload-media";
export const TWITTER_CREATE_SCHEDULED_TWEET_PATH =
  "/bridge/v1/twitter/create-scheduled-tweet";
const USER_ID = /^[1-9][0-9]{0,19}$/;
const SCREEN_NAME = /^[A-Za-z0-9_]{1,15}$/;
const EXECUTE_AT = /^[1-9][0-9]{8,11}$/;
const MEDIA_IDS = /^[1-9][0-9]{0,19}(,[1-9][0-9]{0,19}){0,3}$/;
const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;
const TEXT_FORBIDDEN = /[\0\r]/;
const MIME_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const MAX_UPLOAD_BASE64 = 7 * 1024 * 1024;
const MAX_SCHEDULED_TEXT = 25000;

export const TWITTER_ERROR_CODES = new Set([
  "invalid_request",
  "runtime_unavailable",
  "request_failed",
  "timeout",
  "tab_unavailable",
  "not_logged_in",
  "verification_required",
  "rate_limited",
  "forbidden",
  "invalid_response",
  "response_too_large"
]);

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function validURL(value) {
  try {
    const parsed = new URL(value);
    return (
      parsed.protocol === "https:" &&
      ["x.com", "www.x.com", "twitter.com", "www.twitter.com"].includes(
        parsed.hostname.toLowerCase()
      ) &&
      !parsed.username &&
      !parsed.password &&
      !parsed.port &&
      !parsed.hash
    );
  } catch {
    return false;
  }
}

function normalizeXURL(value) {
  const parsed = new URL(value);
  parsed.protocol = "https:";
  parsed.hostname = "x.com";
  return parsed;
}

function entriesObject(entries) {
  if (!Array.isArray(entries) || entries.length > 8) {
    return null;
  }
  const result = {};
  for (const entry of entries) {
    if (
      !Array.isArray(entry) ||
      entry.length !== 2 ||
      typeof entry[0] !== "string" ||
      typeof entry[1] !== "string" ||
      Object.hasOwn(result, entry[0])
    ) {
      return null;
    }
    result[entry[0]] = entry[1];
  }
  return result;
}

function validCursor(value) {
  return (
    value === undefined ||
    (
      typeof value === "string" &&
      value.length >= 1 &&
      value.length <= 2048 &&
      !CONTROL.test(value)
    )
  );
}

function validCount(value) {
  return (
    typeof value === "string" &&
    INTEGER.test(value) &&
    Number(value) >= 1 &&
    Number(value) <= 100
  );
}

function validHomeEntries(entries) {
  const values = entriesObject(entries);
  if (!values) {
    return false;
  }
  const names = Object.keys(values);
  return (
    names.every((name) => ["count", "cursor"].includes(name)) &&
    validCount(values.count) &&
    validCursor(values.cursor)
  );
}

function validSearchEntries(entries) {
  const values = entriesObject(entries);
  if (!values) {
    return false;
  }
  const names = Object.keys(values);
  return (
    names.every((name) =>
      ["query", "count", "product", "cursor"].includes(name)
    ) &&
    typeof values.query === "string" &&
    values.query.trim().length >= 1 &&
    values.query.length <= 512 &&
    !CONTROL.test(values.query) &&
    validCount(values.count) &&
    PRODUCTS.has(values.product) &&
    validCursor(values.cursor)
  );
}

function validUserId(value) {
  return typeof value === "string" && USER_ID.test(value);
}

function validHandle(value) {
  return typeof value === "string" && SCREEN_NAME.test(value);
}

function validIdentity(values, allowHandle) {
  const hasUserId = Object.hasOwn(values, "user_id");
  const hasScreenName = Object.hasOwn(values, "screen_name");
  if (hasUserId === hasScreenName) {
    return false;
  }
  if (hasUserId) {
    return validUserId(values.user_id);
  }
  if (values.screen_name === "me") {
    return true;
  }
  return allowHandle && validHandle(values.screen_name);
}

function validUserEntries(entries) {
  const values = entriesObject(entries);
  if (!values) {
    return false;
  }
  const names = Object.keys(values);
  return (
    names.every((name) => ["user_id", "screen_name"].includes(name)) &&
    validIdentity(values, true)
  );
}

function validUserListEntries(entries) {
  const values = entriesObject(entries);
  if (!values) {
    return false;
  }
  const names = Object.keys(values);
  return (
    names.every((name) =>
      ["user_id", "screen_name", "count", "cursor"].includes(name)
    ) &&
    validIdentity(values, false) &&
    validCount(values.count) &&
    validCursor(values.cursor)
  );
}

function validFollowEntries(entries) {
  const values = entriesObject(entries);
  if (!values) {
    return false;
  }
  const names = Object.keys(values);
  return (
    names.every((name) => ["user_id", "screen_name"].includes(name)) &&
    validIdentity(values, true) &&
    values.screen_name !== "me"
  );
}

function validUploadMediaEntries(entries) {
  const values = entriesObject(entries);
  if (!values) {
    return false;
  }
  const names = Object.keys(values);
  const dataBase64 = values.dataBase64 || "";
  return (
    names.length === 2 &&
    names.every((name) => ["mimeType", "dataBase64"].includes(name)) &&
    MIME_TYPES.has(values.mimeType) &&
    dataBase64.length >= 4 &&
    dataBase64.length <= MAX_UPLOAD_BASE64 &&
    BASE64.test(dataBase64)
  );
}

function validScheduledTweetEntries(entries) {
  const values = entriesObject(entries);
  if (!values) {
    return false;
  }
  const names = Object.keys(values);
  if (
    !names.every((name) =>
      ["text", "execute_at", "media_ids"].includes(name)
    ) ||
    !Object.hasOwn(values, "text") ||
    !Object.hasOwn(values, "execute_at")
  ) {
    return false;
  }
  const text = values.text;
  return (
    typeof text === "string" &&
    text.length >= 1 &&
    text.length <= MAX_SCHEDULED_TEXT &&
    !TEXT_FORBIDDEN.test(text) &&
    EXECUTE_AT.test(values.execute_at) &&
    (
      !Object.hasOwn(values, "media_ids") ||
      MEDIA_IDS.test(values.media_ids)
    )
  );
}

export function isTwitterTabUrl(value) {
  return validURL(value);
}

export function validTwitterReferer(value, scope, entries = []) {
  if (!validURL(value)) {
    return false;
  }
  const parsed = normalizeXURL(value);
  if (scope === "home") {
    return parsed.pathname === "/home";
  }
  if (scope !== "search" || parsed.pathname !== "/search") {
    return false;
  }
  const values = entriesObject(entries);
  return (
    values !== null &&
    parsed.searchParams.get("q") === values.query &&
    parsed.searchParams.get("src") === "typed_query"
  );
}

export function sameTwitterRequestContext(current, expected, scope) {
  if (!validURL(current) || !validURL(expected)) {
    return false;
  }
  const currentURL = normalizeXURL(current);
  const expectedURL = normalizeXURL(expected);
  if (currentURL.pathname !== expectedURL.pathname) {
    return false;
  }
  if (scope === "search") {
    return currentURL.searchParams.get("q") === expectedURL.searchParams.get("q");
  }
  return scope === "home" && currentURL.pathname === "/home";
}

export function validTwitterRequest(message, scope) {
  if (
    !isRecord(message) ||
    !Number.isInteger(message.request_interval_ms) ||
    message.request_interval_ms < 0 ||
    message.request_interval_ms > 10000
  ) {
    return false;
  }
  if (scope === "home") {
    let homeEntries = false;
    if (message.path === TWITTER_HOME_FEED_PATH) {
      homeEntries = validHomeEntries(message.entries);
    } else if (message.path === TWITTER_USER_PATH) {
      homeEntries = validUserEntries(message.entries);
    } else if (
      message.path === TWITTER_USER_TWEETS_PATH ||
      message.path === TWITTER_FOLLOWERS_PATH ||
      message.path === TWITTER_FOLLOWING_PATH
    ) {
      homeEntries = validUserListEntries(message.entries);
    } else if (message.path === TWITTER_FOLLOW_PATH) {
      homeEntries = validFollowEntries(message.entries);
    } else if (message.path === TWITTER_UPLOAD_MEDIA_PATH) {
      homeEntries = validUploadMediaEntries(message.entries);
    } else if (message.path === TWITTER_CREATE_SCHEDULED_TWEET_PATH) {
      homeEntries = validScheduledTweetEntries(message.entries);
    }
    return (
      homeEntries &&
      validTwitterReferer(message.referer, scope, message.entries)
    );
  }
  if (
    scope === "search" &&
    message.path === TWITTER_SEARCH_POSTS_PATH &&
    validSearchEntries(message.entries)
  ) {
    return validTwitterReferer(message.referer, scope, message.entries);
  }
  return false;
}
