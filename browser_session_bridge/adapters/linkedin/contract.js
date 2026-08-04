const PARAMETER_NAME = /^[A-Za-z][A-Za-z0-9_]{0,79}$/;
const PROFILE_SLUG = /^[A-Za-z0-9][A-Za-z0-9-]{0,99}$/;

export const LINKEDIN_ORIGIN = "https://www.linkedin.com";
export const LINKEDIN_LOGIN_URL = `${LINKEDIN_ORIGIN}/`;
export const LINKEDIN_TAB_PATTERNS = [`${LINKEDIN_ORIGIN}/*`];
export const LINKEDIN_AUTHOR_ARTICLES_PATH = "/bridge/v1/linkedin/author-articles";
export const LINKEDIN_SEARCH_USERS_PATH = "/bridge/v1/linkedin/search-users";

export const LINKEDIN_ERROR_CODES = new Set([
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

const ALLOWED_PARAMETERS = Object.freeze({
  [LINKEDIN_AUTHOR_ARTICLES_PATH]: new Set(["slug", "limit"]),
  [LINKEDIN_SEARCH_USERS_PATH]: new Set(["first_name", "last_name", "limit"])
});

function cleanText(value, maximum) {
  return typeof value === "string" && value === value.trim() && value.length > 0 &&
    value.length <= maximum && !/[\r\n\0]/.test(value);
}

function validValue(path, name, value) {
  if (name === "limit") {
    return /^[1-9]\d{0,2}$/.test(value) && Number(value) <= 100;
  }
  if (path === LINKEDIN_AUTHOR_ARTICLES_PATH && name === "slug") {
    return PROFILE_SLUG.test(value);
  }
  return cleanText(value, 100);
}

export function validLinkedInEntries(path, value) {
  const allowed = ALLOWED_PARAMETERS[path];
  if (!allowed || !Array.isArray(value) || value.length !== allowed.size) {
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
      !allowed.has(name) ||
      names.has(name) ||
      !validValue(path, name, parameter)
    ) {
      return false;
    }
    names.add(name);
  }
  return [...allowed].every((name) => names.has(name));
}

function entryMap(entries) {
  return new Map(entries.map(([name, value]) => [name, value]));
}

export function validLinkedInReferer(path, entries, value) {
  if (!validLinkedInEntries(path, entries) || typeof value !== "string" || value.length > 4096) {
    return false;
  }
  let referer;
  try {
    referer = new URL(value);
  } catch {
    return false;
  }
  if (
    referer.origin !== LINKEDIN_ORIGIN || referer.username || referer.password ||
    referer.port || referer.hash
  ) {
    return false;
  }
  const values = entryMap(entries);
  if (path === LINKEDIN_AUTHOR_ARTICLES_PATH) {
    const match = /^\/in\/([^/]+)\/recent-activity\/articles\/?$/.exec(referer.pathname);
    return Boolean(match && !referer.search && match[1] === values.get("slug"));
  }
  if (path === LINKEDIN_SEARCH_USERS_PATH) {
    const keys = [...referer.searchParams.keys()];
    return referer.pathname === "/search/results/people/" &&
      keys.every((name) => ["firstName", "lastName", "origin"].includes(name)) &&
      new Set(keys).size === keys.length &&
      referer.searchParams.get("firstName") === values.get("first_name") &&
      referer.searchParams.get("lastName") === values.get("last_name") &&
      (!referer.searchParams.has("origin") || referer.searchParams.get("origin") === "FACETED_SEARCH");
  }
  return false;
}

export function isLinkedInTabUrl(value) {
  try {
    const parsed = new URL(value);
    return parsed.origin === LINKEDIN_ORIGIN && !parsed.username && !parsed.password && !parsed.port;
  } catch {
    return false;
  }
}

export function sameLinkedInRequestContext(current, referer) {
  try {
    const currentURL = new URL(current);
    const refererURL = new URL(referer);
    return isLinkedInTabUrl(current) && currentURL.pathname === refererURL.pathname &&
      currentURL.search === refererURL.search;
  } catch {
    return false;
  }
}

export function validLinkedInRequest(message) {
  return Boolean(
    message && typeof message.path === "string" &&
    Object.prototype.hasOwnProperty.call(ALLOWED_PARAMETERS, message.path) &&
    validLinkedInReferer(message.path, message.entries, message.referer)
  );
}
