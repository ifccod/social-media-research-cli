// chrome.scripting 会将此函数序列化到 Reddit 的 MAIN world。凭据和
// Shreddit 专用续页元数据均保留在页面环境中。
export async function invokeRedditPageRuntime(input) {
  const ORIGIN = "https://www.reddit.com";
  const HOME_SORTS = new Set(["BEST", "HOT", "NEW", "TOP", "CONTROVERSIAL"]);
  const DISCOVERY_SORTS = new Set([
    "BEST", "HOT", "NEW", "TOP", "CONTROVERSIAL", "RISING"
  ]);
  const TIMES = new Set(["ALL", "HOUR", "DAY", "WEEK", "MONTH", "YEAR"]);
  const FEEDS = Object.freeze({
    "/bridge/v1/reddit/home-feed": {
      kind: "home_feed",
      source: "reddit_web_personalized_home",
      upstreamPath: "/svc/shreddit/feeds/home-feed",
      personalized: true,
      accountScoped: true,
      supportsTime: false,
      sorts: HOME_SORTS
    },
    "/bridge/v1/reddit/popular-feed": {
      kind: "popular_feed",
      source: "reddit_web_popular_feed",
      upstreamPath: "/svc/shreddit/feeds/popular-feed",
      personalized: false,
      accountScoped: false,
      supportsTime: true,
      sorts: DISCOVERY_SORTS
    },
    "/bridge/v1/reddit/news-feed": {
      kind: "news_feed",
      source: "reddit_web_news_feed",
      upstreamPath: "/svc/shreddit/feeds/news-feed",
      personalized: false,
      accountScoped: false,
      supportsTime: true,
      sorts: DISCOVERY_SORTS
    }
  });
  const MAX_RESULT_BYTES = 6 * 1024 * 1024;
  const MAX_HTML_BYTES = 6 * 1024 * 1024;
  const MINIMUM_START_INTERVAL_MS = 3000;
  const OPERATION_ID = /^[A-Za-z0-9_-]{1,96}$/;
  const FULLNAME = /^t3_[a-z0-9]+$/;
  const SUBREDDIT_FULLNAME = /^t5_[a-z0-9]+$/;
  const OPAQUE_AFTER = /^dDNf[A-Za-z0-9+/]{2,252}={0,2}$/;

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
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

  function cleanText(value, maximum) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    return text.length <= maximum && !/[\0]/.test(text) ? text : "";
  }

  function integerAttribute(element, name, minimum = 0) {
    const raw = element.getAttribute(name);
    if (!/^-?\d+$/.test(String(raw || ""))) return null;
    const value = Number(raw);
    return Number.isSafeInteger(value) && value >= minimum ? value : null;
  }

  function ratioAttribute(element, name) {
    const raw = element.getAttribute(name);
    if (raw === null || raw === "") return null;
    const value = Number(raw);
    return Number.isFinite(value) && value >= 0 && value <= 1 ? value : null;
  }

  function opaqueAfter(value) {
    if (typeof value !== "string" || !OPAQUE_AFTER.test(value)) return "";
    try {
      return FULLNAME.test(atob(value)) ? value : "";
    } catch {
      return "";
    }
  }

  function encodeAfter(fullname) {
    return FULLNAME.test(fullname) ? btoa(fullname) : "";
  }

  function validEntries(path, entries) {
    const feed = FEEDS[path];
    const expectedEntries = feed?.supportsTime ? 4 : 3;
    if (!feed || !Array.isArray(entries) || entries.length !== expectedEntries) {
      return false;
    }
    const allowed = new Set(["sort", "limit", "after"]);
    if (feed.supportsTime) allowed.add("time");
    const values = new Map();
    for (const entry of entries) {
      if (
        !Array.isArray(entry) ||
        entry.length !== 2 ||
        typeof entry[0] !== "string" ||
        typeof entry[1] !== "string" ||
        !allowed.has(entry[0]) ||
        values.has(entry[0]) ||
        /[\r\n\0]/.test(entry[1])
      ) {
        return false;
      }
      values.set(entry[0], entry[1]);
    }
    const limit = values.get("limit") || "";
    const after = values.get("after") || "";
    return feed.sorts.has(values.get("sort")) &&
      /^[1-9]\d{0,2}$/.test(limit) &&
      Number(limit) <= 100 &&
      (!feed.supportsTime || TIMES.has(values.get("time"))) &&
      (after === "" || opaqueAfter(after) !== "");
  }

  function verificationRequired() {
    if (/^\/(?:challenge|verification)(?:\/|$)/i.test(location.pathname)) {
      return true;
    }
    return [...document.querySelectorAll(
      'iframe[src*="captcha"], iframe[src*="recaptcha"], [id*="captcha"] iframe'
    )].some((element) => {
      const rect = element?.getBoundingClientRect?.();
      return Boolean(rect && rect.width > 0 && rect.height > 0);
    });
  }

  function loggedIn() {
    if (/^\/(?:login|register)(?:\/|$)/i.test(location.pathname)) return false;
    return Boolean(
      document.querySelector('shreddit-app[user-logged-in="true"]') ||
      document.querySelector('[data-testid="reddit-profile-menu-button"]')
    );
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
        width: Number(screen.width) || 0,
        height: Number(screen.height) || 0,
        avail_width: Number(screen.availWidth) || 0,
        avail_height: Number(screen.availHeight) || 0,
        color_depth: Number(screen.colorDepth) || 0,
        pixel_depth: Number(screen.pixelDepth) || 0,
        device_pixel_ratio: Number(window.devicePixelRatio) || 1
      },
      viewport: {
        width: Number(window.innerWidth) || 0,
        height: Number(window.innerHeight) || 0,
        outer_width: Number(window.outerWidth) || 0,
        outer_height: Number(window.outerHeight) || 0
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

  function registry() {
    const key = Symbol.for("local_browser_session_bridge.reddit.operations.v1");
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
    active.get(operationID)?.cancel?.();
    let cancelled = false;
    const controllers = new Set();
    const operation = {
      controller() {
        const controller = new AbortController();
        controllers.add(controller);
        return controller;
      },
      release(controller) {
        controllers.delete(controller);
      },
      cancel() {
        cancelled = true;
        for (const controller of controllers) controller.abort();
      },
      throwIfCancelled() {
        if (cancelled) throw new Error("reddit_request_cancelled");
      }
    };
    active.set(operationID, operation);
    return {
      operation,
      finish() {
        if (active.get(operationID) === operation) active.delete(operationID);
      }
    };
  }

  function cancelOperation(operationID) {
    const operation = registry().active.get(operationID);
    if (!operation) return false;
    operation.cancel();
    return true;
  }

  function canonicalPostURL(value, fullname) {
    try {
      const parsed = new URL(value, ORIGIN);
      const id = fullname.slice(3);
      if (
        parsed.origin !== ORIGIN ||
        parsed.username ||
        parsed.password ||
        parsed.port ||
        parsed.search ||
        parsed.hash ||
        !new RegExp(`^/r/[A-Za-z0-9_]{2,21}/comments/${id}(?:/|$)`, "i").test(parsed.pathname)
      ) {
        return "";
      }
      return `${ORIGIN}${parsed.pathname}`;
    } catch {
      return "";
    }
  }

  function normalizePost(element) {
    const fullname = cleanText(element.getAttribute("id"), 32).toLowerCase();
    if (!FULLNAME.test(fullname)) return null;
    const title = cleanText(element.getAttribute("post-title"), 1000);
    const url = canonicalPostURL(element.getAttribute("permalink"), fullname);
    const subreddit = cleanText(element.getAttribute("subreddit-name"), 21);
    const subredditID = cleanText(element.getAttribute("subreddit-id"), 32).toLowerCase();
    const score = integerAttribute(element, "score", -1000000000);
    const commentCount = integerAttribute(element, "comment-count");
    if (
      !title ||
      !url ||
      !/^[A-Za-z0-9_]{2,21}$/.test(subreddit) ||
      !SUBREDDIT_FULLNAME.test(subredditID) ||
      score === null ||
      commentCount === null
    ) {
      throw new Error("reddit_invalid_response");
    }
    const author = cleanText(element.getAttribute("author"), 64);
    const authorID = cleanText(element.getAttribute("author-id"), 32).toLowerCase();
    const createdAt = cleanText(element.getAttribute("created-timestamp"), 64);
    const parsedCreatedAt = Date.parse(createdAt);
    if (
      !author ||
      (authorID && !/^t2_[a-z0-9]+$/.test(authorID)) ||
      !Number.isFinite(parsedCreatedAt)
    ) {
      throw new Error("reddit_invalid_response");
    }
    const recommendationSource = cleanText(
      element.getAttribute("recommendation-source"),
      128
    ).toLowerCase();
    if (recommendationSource && !/^[a-z0-9_:-]+$/.test(recommendationSource)) {
      throw new Error("reddit_invalid_response");
    }
    return {
      id: fullname.slice(3),
      fullname,
      title,
      url,
      subreddit,
      subreddit_id: subredditID,
      author,
      author_id: authorID || null,
      created_at: new Date(parsedCreatedAt).toISOString(),
      score,
      comment_count: commentCount,
      upvote_ratio: ratioAttribute(element, "upvote-ratio"),
      domain: cleanText(element.getAttribute("domain"), 253),
      post_type: cleanText(element.getAttribute("post-type"), 64),
      language: cleanText(element.getAttribute("post-language"), 32),
      recommendation_source: recommendationSource || null
    };
  }

  function parseContinuation(documentValue, feed, sort, time) {
    const nodes = [...documentValue.querySelectorAll(
      `faceplate-partial[src*="${feed.upstreamPath}"]`
    )];
    if (nodes.length === 0) return null;
    if (nodes.length !== 1) throw new Error("reddit_invalid_response");
    const source = nodes[0].getAttribute("src") || "";
    let parsed;
    try {
      parsed = new URL(source, ORIGIN);
    } catch {
      throw new Error("reddit_invalid_response");
    }
    if (
      parsed.origin !== ORIGIN ||
      parsed.pathname !== feed.upstreamPath ||
      parsed.username ||
      parsed.password ||
      parsed.port ||
      parsed.hash
    ) {
      throw new Error("reddit_invalid_response");
    }
    const allowed = new Set([
      "after", "cursor", "sort", "distance", "adDistance",
      "navigationSessionId", "ad_posts_served", "referer"
    ]);
    if (feed.supportsTime) allowed.add("t");
    for (const [name, value] of parsed.searchParams) {
      if (!allowed.has(name) || value.length > 256) {
        throw new Error("reddit_invalid_response");
      }
    }
    const after = opaqueAfter(parsed.searchParams.get("after") || "");
    if (
      !after ||
      parsed.searchParams.get("cursor") !== after ||
      parsed.searchParams.get("sort") !== sort
    ) {
      throw new Error("reddit_invalid_response");
    }
    const continuationTime = parsed.searchParams.get("t");
    if (
      feed.supportsTime &&
      ((time === "ALL" && continuationTime !== null && continuationTime !== "ALL") ||
        (time !== "ALL" && continuationTime !== time))
    ) {
      throw new Error("reddit_invalid_response");
    }
    if (!feed.supportsTime && continuationTime !== null) {
      throw new Error("reddit_invalid_response");
    }
    for (const name of ["distance", "adDistance", "ad_posts_served"]) {
      const value = parsed.searchParams.get(name);
      if (value !== null && !/^\d{1,6}$/.test(value)) {
        throw new Error("reddit_invalid_response");
      }
    }
    const navigationSessionID = parsed.searchParams.get("navigationSessionId");
    if (
      navigationSessionID !== null &&
      !/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(navigationSessionID)
    ) {
      throw new Error("reddit_invalid_response");
    }
    const referer = parsed.searchParams.get("referer");
    if (referer !== null && referer !== "www.reddit.com") {
      throw new Error("reddit_invalid_response");
    }
    return {
      after,
      request_path: `${parsed.pathname}${parsed.search}`
    };
  }

  function parsePage(html, feed, sort, time) {
    if (new TextEncoder().encode(html).byteLength > MAX_HTML_BYTES) {
      throw new Error("reddit_response_too_large");
    }
    const parsed = new DOMParser().parseFromString(html, "text/html");
    if (!parsed || !parsed.querySelectorAll) throw new Error("reddit_invalid_response");
    const posts = [];
    for (const element of parsed.querySelectorAll("shreddit-post")) {
      const post = normalizePost(element);
      if (post) posts.push(post);
    }
    return { posts, continuation: parseContinuation(parsed, feed, sort, time) };
  }

  function initialRequestPath(feed, sort, time, after) {
    const query = new URLSearchParams();
    if (after) {
      query.set("after", after);
      query.set("cursor", after);
    }
    query.set("sort", sort);
    if (feed.supportsTime && time !== "ALL") query.set("t", time);
    return `${feed.upstreamPath}?${query.toString()}`;
  }

  async function waitForNextStart(lastStartedAt, interval, operation) {
    const wait = interval - (Date.now() - lastStartedAt);
    if (wait <= 0) return;
    await new Promise((resolve, reject) => {
      const controller = operation.controller();
      const timer = setTimeout(() => {
        operation.release(controller);
        resolve();
      }, wait);
      controller.signal.addEventListener("abort", () => {
        clearTimeout(timer);
        operation.release(controller);
        reject(new Error("reddit_request_cancelled"));
      }, { once: true });
    });
  }

  async function fetchPage(path, feed, operation) {
    operation.throwIfCancelled();
    const controller = operation.controller();
    try {
      const result = await fetch(`${ORIGIN}${path}`, {
        method: "GET",
        credentials: "include",
        redirect: "follow",
        headers: {
          Accept: "text/html, text/vnd.reddit.partial+html;q=0.9"
        },
        signal: controller.signal
      });
      operation.throwIfCancelled();
      if (result.status === 401 || result.status === 403) {
        throw new Error("reddit_not_logged_in");
      }
      if (result.status === 429) throw new Error("reddit_rate_limited");
      if (!result.ok) throw new Error("reddit_request_failed");
      const finalURL = new URL(result.url);
      if (finalURL.origin !== ORIGIN || finalURL.pathname !== feed.upstreamPath) {
        if (/^\/(?:login|register)(?:\/|$)/i.test(finalURL.pathname)) {
          throw new Error("reddit_not_logged_in");
        }
        throw new Error("reddit_invalid_response");
      }
      const contentType = result.headers?.get?.("content-type") || "";
      if (contentType && !/text\/html|text\/vnd\.reddit\.partial\+html/i.test(contentType)) {
        throw new Error("reddit_invalid_response");
      }
      return await result.text();
    } catch (error) {
      if (controller.signal.aborted) throw new Error("reddit_request_cancelled");
      throw error;
    } finally {
      operation.release(controller);
    }
  }

  async function collectFeed(feed, values, requestIntervalMS, operation) {
    if (verificationRequired()) throw new Error("reddit_verification_required");
    if (!loggedIn()) throw new Error("reddit_not_logged_in");
    const sort = values.get("sort");
    const time = feed.supportsTime ? values.get("time") : "";
    const limit = Number(values.get("limit"));
    const inputAfter = values.get("after") || "";
    const interval = Math.max(
      MINIMUM_START_INTERVAL_MS,
      Number.isInteger(requestIntervalMS) ? requestIntervalMS : 0
    );
    let path = initialRequestPath(feed, sort, time, inputAfter);
    let lastStartedAt = 0;
    let outputAfter = "";
    const posts = [];
    const seenPosts = new Set();
    const seenCursors = new Set(inputAfter ? [inputAfter] : []);

    for (let page = 0; page < 16 && posts.length < limit; page += 1) {
      if (lastStartedAt > 0) {
        await waitForNextStart(lastStartedAt, interval, operation);
      }
      lastStartedAt = Date.now();
      const parsed = parsePage(
        await fetchPage(path, feed, operation),
        feed,
        sort,
        time
      );
      let truncated = false;
      for (const post of parsed.posts) {
        if (seenPosts.has(post.fullname)) continue;
        seenPosts.add(post.fullname);
        posts.push(post);
        if (posts.length >= limit) {
          truncated = parsed.posts[parsed.posts.length - 1]?.fullname !== post.fullname;
          break;
        }
      }
      if (posts.length >= limit) {
        outputAfter = truncated
          ? encodeAfter(posts[posts.length - 1].fullname)
          : parsed.continuation?.after || "";
        break;
      }
      if (!parsed.continuation) {
        outputAfter = "";
        break;
      }
      if (seenCursors.has(parsed.continuation.after)) {
        throw new Error("reddit_pagination_loop");
      }
      if (parsed.posts.length === 0) {
        throw new Error("reddit_invalid_response");
      }
      seenCursors.add(parsed.continuation.after);
      outputAfter = parsed.continuation.after;
      path = parsed.continuation.request_path;
    }
    if (posts.length < limit && outputAfter && posts.length > 0) {
      throw new Error("reddit_pagination_limit");
    }
    const payload = {
      kind: feed.kind,
      source: feed.source,
      personalized: feed.personalized,
      account_scoped: feed.accountScoped,
      sort,
      requested_limit: limit,
      total: posts.length,
      posts,
      after: outputAfter || null,
      has_more: outputAfter !== ""
    };
    if (feed.supportsTime) payload.time = time;
    return payload;
  }

  function errorCode(error) {
    const message = String(error?.message || "");
    if (message.includes("verification_required")) return "verification_required";
    if (message.includes("not_logged_in")) return "not_logged_in";
    if (message.includes("rate_limited")) return "rate_limited";
    if (message.includes("response_too_large")) return "response_too_large";
    if (message.includes("cancelled")) return "request_failed";
    if (message.includes("invalid_response") || message.includes("pagination")) {
      return "invalid_response";
    }
    if (message.includes("request_failed")) return "request_failed";
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
  if (
    input.kind !== "request" ||
    typeof input.operation_id !== "string" ||
    !OPERATION_ID.test(input.operation_id) ||
    typeof input.path !== "string" ||
    !validEntries(input.path, input.entries) ||
    !Number.isInteger(input.request_interval_ms) ||
    input.request_interval_ms < 0 ||
    input.request_interval_ms > 30000
  ) {
    return { ok: false, error: "invalid_request" };
  }
  const registered = registerOperation(input.operation_id);
  const feed = FEEDS[input.path];
  try {
    return response({
      ok: true,
      payload: await collectFeed(
        feed,
        new Map(input.entries),
        input.request_interval_ms,
        registered.operation
      )
    });
  } catch (error) {
    return { ok: false, error: errorCode(error) };
  } finally {
    registered.finish();
  }
}
