// chrome.scripting 会将此函数序列化到 LinkedIn 的 MAIN world。仅读取当前
// 已渲染页面，浏览器凭据保留在 Chrome 中。
export async function invokeLinkedInPageRuntime(input) {
  const MAX_RESULT_BYTES = 6 * 1024 * 1024;
  const OPERATION_ID = /^[A-Za-z0-9_-]{1,96}$/;
  const PROFILE_SLUG = /^[A-Za-z0-9][A-Za-z0-9-]{0,99}$/;
  const AUTHOR_PATH = "/bridge/v1/linkedin/author-articles";
  const SEARCH_PATH = "/bridge/v1/linkedin/search-users";

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function cleanText(value, maximum = 4000) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, maximum);
  }

  function entryMap(entries) {
    return new Map(entries.map(([name, value]) => [name, value]));
  }

  function validEntries(path, entries) {
    if (!Array.isArray(entries)) {
      return false;
    }
    const required = path === AUTHOR_PATH
      ? new Set(["slug", "limit"])
      : path === SEARCH_PATH
        ? new Set(["first_name", "last_name", "limit"])
        : null;
    if (!required || entries.length !== required.size) {
      return false;
    }
    const names = new Set();
    for (const entry of entries) {
      if (!Array.isArray(entry) || entry.length !== 2 || typeof entry[0] !== "string" ||
        typeof entry[1] !== "string" || !required.has(entry[0]) || names.has(entry[0]) ||
        /[\r\n\0]/.test(entry[1])) {
        return false;
      }
      names.add(entry[0]);
    }
    const values = entryMap(entries);
    const limit = values.get("limit") || "";
    if (!/^[1-9]\d{0,2}$/.test(limit) || Number(limit) > 100) {
      return false;
    }
    if (path === AUTHOR_PATH) {
      return PROFILE_SLUG.test(values.get("slug") || "");
    }
    return [values.get("first_name"), values.get("last_name")].every(
      (value) => typeof value === "string" && value === value.trim() && value.length > 0 && value.length <= 100
    );
  }

  function response(value) {
    try {
      if (new TextEncoder().encode(JSON.stringify(value)).byteLength <= MAX_RESULT_BYTES) {
        return value;
      }
    } catch {
      return { ok: false, error: "invalid_response" };
    }
    return { ok: false, error: "response_too_large" };
  }

  function registry() {
    const key = Symbol.for("local_browser_session_bridge.linkedin.operations.v1");
    const current = window[key];
    if (current && current.version === 1 && current.active instanceof Map) {
      return current;
    }
    const created = { version: 1, active: new Map() };
    Object.defineProperty(window, key, { configurable: true, value: created });
    return created;
  }

  function registerOperation(operationID) {
    const active = registry().active;
    const previous = active.get(operationID);
    previous?.cancel?.();
    let cancelled = false;
    const operation = {
      cancel() { cancelled = true; },
      throwIfCancelled() {
        if (cancelled) {
          throw new Error("linkedin_request_cancelled");
        }
      }
    };
    active.set(operationID, operation);
    return {
      operation,
      finish() {
        if (active.get(operationID) === operation) {
          active.delete(operationID);
        }
      }
    };
  }

  function cancelOperation(operationID) {
    const operation = registry().active.get(operationID);
    if (!operation) {
      return false;
    }
    operation.cancel();
    return true;
  }

  function visible(element) {
    if (!element || typeof element.getBoundingClientRect !== "function") {
      return false;
    }
    const rect = element.getBoundingClientRect();
    return Boolean(rect && rect.width > 0 && rect.height > 0);
  }

  function verificationRequired() {
    if (/^\/(?:checkpoint|challenge)(?:\/|$)/i.test(location.pathname)) {
      return true;
    }
    return [...document.querySelectorAll('iframe[src*="captcha"], [id*="captcha"] iframe, [class*="captcha"] iframe')]
      .some(visible);
  }

  function loggedIn() {
    if (/^\/(?:authwall|login|signup|uas)(?:\/|$)/i.test(location.pathname)) {
      return false;
    }
    const cookieSignal = /(?:^|;\s*)(?:JSESSIONID|liap)=/.test(String(document.cookie || ""));
    const navigationSignal = Boolean(document.querySelector(
      'nav.global-nav, a[href^="/mynetwork/"], a[href*="/in/me"]'
    ));
    return cookieSignal || navigationSignal;
  }

  function fingerprint() {
    const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection || {};
    const uaData = navigator.userAgentData;
    return {
      user_agent: String(navigator.userAgent || ""),
      ua_ch: uaData ? {
        brands: Array.isArray(uaData.brands) ? uaData.brands.slice(0, 10).map((item) => ({
          brand: String(item.brand || ""), version: String(item.version || "")
        })) : [],
        mobile: Boolean(uaData.mobile),
        platform: String(uaData.platform || "")
      } : null,
      language: String(navigator.language || ""),
      languages: Array.from(navigator.languages || []).slice(0, 20).map(String),
      platform: String(navigator.platform || ""),
      vendor: String(navigator.vendor || ""),
      cookie_enabled: Boolean(navigator.cookieEnabled),
      online: navigator.onLine !== false,
      hardware_concurrency: Number.isFinite(navigator.hardwareConcurrency) ? navigator.hardwareConcurrency : null,
      device_memory: Number.isFinite(navigator.deviceMemory) ? navigator.deviceMemory : null,
      screen: {
        width: Number(screen.width) || 0, height: Number(screen.height) || 0,
        avail_width: Number(screen.availWidth) || 0, avail_height: Number(screen.availHeight) || 0,
        color_depth: Number(screen.colorDepth) || 0, pixel_depth: Number(screen.pixelDepth) || 0,
        device_pixel_ratio: Number(window.devicePixelRatio) || 1
      },
      viewport: {
        width: Number(window.innerWidth) || 0, height: Number(window.innerHeight) || 0,
        outer_width: Number(window.outerWidth) || 0, outer_height: Number(window.outerHeight) || 0
      },
      timezone: String(Intl.DateTimeFormat().resolvedOptions().timeZone || ""),
      connection: {
        effective_type: String(connection.effectiveType || ""),
        round_trip_time: Number.isFinite(connection.rtt) ? connection.rtt : null,
        downlink: Number.isFinite(connection.downlink) ? connection.downlink : null,
        save_data: Boolean(connection.saveData)
      }
    };
  }

  function canonicalLinkedInURL(value, route) {
    try {
      const parsed = new URL(value, "https://www.linkedin.com");
      if (parsed.origin !== "https://www.linkedin.com" || !route.test(parsed.pathname)) {
        return "";
      }
      return `${parsed.origin}${parsed.pathname.replace(/\/$/, "")}`;
    } catch {
      return "";
    }
  }

  function schemaTypes(value) {
    const raw = isRecord(value) ? value["@type"] : null;
    return new Set((Array.isArray(raw) ? raw : [raw]).filter((item) => typeof item === "string"));
  }

  function jsonLDItems() {
    const output = [];
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const parsed = JSON.parse(String(script.textContent || ""));
        const roots = Array.isArray(parsed) ? parsed : [parsed];
        for (const root of roots) {
          if (!isRecord(root)) continue;
          if (Array.isArray(root["@graph"])) {
            output.push(...root["@graph"].filter(isRecord));
          } else {
            output.push(root);
          }
        }
      } catch {
        // 无关 JSON-LD 块格式异常时，不影响当前页面。
      }
    }
    return output;
  }

  function normalizeArticle(item) {
    const url = canonicalLinkedInURL(item.url || item.mainEntityOfPage || "", /^\/pulse\/[^/]+\/?$/);
    if (!url) return null;
    const author = isRecord(item.author) ? item.author : {};
    const image = isRecord(item.image) ? item.image.url : Array.isArray(item.image) ? item.image[0] : item.image;
    return {
      kind: "article",
      slug: decodeURIComponent(url.split("/").pop() || ""),
      url,
      title: cleanText(item.headline || item.name, 1000),
      body: cleanText(item.articleBody || item.description, 8000),
      image: typeof image === "string" ? image : "",
      published_at: cleanText(item.datePublished, 128) || null,
      author: {
        name: cleanText(author.name, 500),
        url: canonicalLinkedInURL(author.url || "", /^\/in\/[^/]+\/?$/)
      }
    };
  }

  function domArticles() {
    const items = [];
    const seen = new Set();
    for (const anchor of document.querySelectorAll('a[href*="/pulse/"]')) {
      const url = canonicalLinkedInURL(anchor.href || anchor.getAttribute?.("href") || "", /^\/pulse\/[^/]+\/?$/);
      if (!url || seen.has(url)) continue;
      seen.add(url);
      const card = anchor.closest?.('article, li, .feed-shared-update-v2, .profile-creator-shared-feed-update__container') || anchor;
      const heading = card.querySelector?.('h1, h2, h3, [data-test-id*="title"]');
      const image = card.querySelector?.("img");
      const time = card.querySelector?.("time");
      items.push({
        kind: "article",
        slug: decodeURIComponent(url.split("/").pop() || ""),
        url,
        title: cleanText(heading?.textContent || anchor.textContent, 1000),
        body: cleanText(card.textContent, 8000),
        image: String(image?.currentSrc || image?.src || ""),
        published_at: cleanText(time?.dateTime || time?.textContent, 128) || null
      });
    }
    return items;
  }

  function authorArticles(values) {
    const limit = Number(values.get("limit"));
    const articles = [];
    const seen = new Set();
    for (const item of jsonLDItems()) {
      if (!schemaTypes(item).has("Article")) continue;
      const normalized = normalizeArticle(item);
      if (normalized && !seen.has(normalized.url)) {
        seen.add(normalized.url);
        articles.push(normalized);
      }
    }
    for (const item of domArticles()) {
      if (!seen.has(item.url)) {
        seen.add(item.url);
        articles.push(item);
      }
    }
    const slug = values.get("slug");
    const person = jsonLDItems().find((item) => schemaTypes(item).has("Person")) || {};
    return {
      kind: "author_articles",
      source: "browser_page",
      author: {
        slug,
        name: cleanText(person.name || document.querySelector("h1")?.textContent, 500),
        url: `https://www.linkedin.com/in/${slug}`
      },
      articles_url: `https://www.linkedin.com/in/${slug}/recent-activity/articles/`,
      requested_limit: limit,
      count: Math.min(limit, articles.length),
      items: articles.slice(0, limit),
      partial: true,
      embedded_lists_partial: true
    };
  }

  function searchUsers(values) {
    const limit = Number(values.get("limit"));
    const items = [];
    const seen = new Set();
    for (const anchor of document.querySelectorAll('a[href*="/in/"]')) {
      const url = canonicalLinkedInURL(anchor.href || anchor.getAttribute?.("href") || "", /^\/in\/[^/]+\/?$/);
      if (!url) continue;
      const slug = decodeURIComponent(url.split("/").pop() || "");
      if (!PROFILE_SLUG.test(slug) || slug === "me" || seen.has(slug.toLowerCase())) continue;
      const card = anchor.closest?.('[data-chameleon-result-urn], .reusable-search__result-container, li') || null;
      if (!card) continue;
      const name = cleanText(
        card.querySelector?.('.entity-result__title-text [aria-hidden="true"], .entity-result__title-text')?.textContent || anchor.textContent,
        500
      );
      if (!name) continue;
      seen.add(slug.toLowerCase());
      const image = card.querySelector?.("img");
      items.push({
        kind: "person",
        slug,
        url,
        name,
        headline: cleanText(card.querySelector?.(".entity-result__primary-subtitle")?.textContent, 1000),
        location: cleanText(card.querySelector?.(".entity-result__secondary-subtitle")?.textContent, 500),
        image: String(image?.currentSrc || image?.src || "")
      });
      if (items.length >= limit) break;
    }
    return {
      kind: "user_search",
      source: "browser_page",
      query: { first_name: values.get("first_name"), last_name: values.get("last_name") },
      requested_limit: limit,
      count: items.length,
      items,
      partial: true
    };
  }

  async function extract(path, values, operation) {
    operation.throwIfCancelled();
    if (verificationRequired()) throw new Error("linkedin_verification_required");
    if (!loggedIn()) throw new Error("linkedin_not_logged_in");
    const result = path === AUTHOR_PATH ? authorArticles(values) : searchUsers(values);
    if (
      result.count === 0 &&
      !/no results|没有结果|未找到/i.test(String(document.body?.innerText || ""))
    ) {
      throw new Error("linkedin_runtime_unavailable");
    }
    return result;
  }

  function errorCode(error) {
    const message = String(error?.message || "");
    if (message.includes("verification_required")) return "verification_required";
    if (message.includes("not_logged_in")) return "not_logged_in";
    if (message.includes("rate_limited")) return "rate_limited";
    if (message.includes("cancelled")) return "request_failed";
    return "runtime_unavailable";
  }

  if (!isRecord(input)) return { ok: false, error: "invalid_request" };
  if (input.kind === "cancel") {
    if (typeof input.operation_id !== "string" || !OPERATION_ID.test(input.operation_id)) {
      return { ok: false, error: "invalid_request" };
    }
    return response({ ok: true, payload: { cancelled: cancelOperation(input.operation_id) } });
  }
  if (input.kind === "session") {
    return response({
      ok: true,
      payload: {
        fingerprint: fingerprint(),
        logged_in: loggedIn(),
        verification_required: verificationRequired()
      }
    });
  }
  if (input.kind !== "request" || typeof input.operation_id !== "string" ||
    !OPERATION_ID.test(input.operation_id) || typeof input.path !== "string" ||
    !validEntries(input.path, input.entries)) {
    return { ok: false, error: "invalid_request" };
  }
  const registered = registerOperation(input.operation_id);
  try {
    return response({
      ok: true,
      payload: await extract(input.path, entryMap(input.entries), registered.operation)
    });
  } catch (error) {
    return { ok: false, error: errorCode(error) };
  } finally {
    registered.finish();
  }
}
