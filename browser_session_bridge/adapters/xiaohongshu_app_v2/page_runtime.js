// chrome.scripting 会将此函数序列化到页面的 MAIN world。依赖全部保留在
// 函数内部，确保凭据留在浏览器中。
export async function invokeXiaohongshuAppV2PageRuntime(input) {
  const MAX_RESULT_BYTES = 6 * 1024 * 1024;
  const OPERATION_ID = /^[A-Za-z0-9_-]{1,96}$/;
  const PARAMETER_NAME = /^[A-Za-z][A-Za-z0-9_]{0,79}$/;
  const XHS_ID = /^[a-fA-F0-9]{24}$/;
  const OPAQUE = /^[A-Za-z0-9_.:-]{0,256}$/;
  const DIGITS = /^[0-9]{0,20}$/;
  const WEBPACK_GLOBAL = "webpackChunkxhs_pc_web";
  const TRANSPORT_TIMEOUT_MS = 15000;
  const SENSITIVE_NAME =
    /(?:cookie|authorization|token|xsec|(?:^|[-_])x[-_]?s(?:[-_]|$)|(?:^|[-_])x[-_]?t(?:[-_]|$)|signature|passport|csrf|sid(?:_|$)|a1(?:_|$)|webid)/i;

  const SEARCH_IMAGES =
    "/bridge/v1/xiaohongshu-app-v2/search-images";
  const SEARCH_PRODUCTS =
    "/bridge/v1/xiaohongshu-app-v2/search-products";
  const SEARCH_GROUPS =
    "/bridge/v1/xiaohongshu-app-v2/search-groups";
  const PRODUCT_DETAIL =
    "/bridge/v1/xiaohongshu-app-v2/product-detail";
  const PRODUCT_REVIEW_OVERVIEW =
    "/bridge/v1/xiaohongshu-app-v2/product-review-overview";
  const PRODUCT_REVIEWS =
    "/bridge/v1/xiaohongshu-app-v2/product-reviews";
  const PRODUCT_RECOMMENDATIONS =
    "/bridge/v1/xiaohongshu-app-v2/product-recommendations";
  const TOPIC_INFO =
    "/bridge/v1/xiaohongshu-app-v2/topic-info";
  const TOPIC_FEED =
    "/bridge/v1/xiaohongshu-app-v2/topic-feed";
  const CREATOR_INSPIRATION =
    "/bridge/v1/xiaohongshu-app-v2/creator-inspiration";
  const CREATOR_HOT_INSPIRATION =
    "/bridge/v1/xiaohongshu-app-v2/creator-hot-inspiration";

  function operation(
    context,
    allowed,
    required = [],
    webPath = null,
    wrapperNames = [],
    factoryMarkers = [],
    method = "GET"
  ) {
    return {
      method,
      context,
      allowed: new Set(allowed),
      required: new Set(required),
      webPath,
      wrapperNames: new Set(wrapperNames),
      factoryMarkers: new Set(factoryMarkers)
    };
  }

  // xhs-pc-web 6.34.3 仅发现这两个 PC 端封装。其他契约保持显式，
  // 在观察到 Web 封装前返回 runtime_unavailable，避免猜测 App 端点。
  const OPERATIONS = Object.freeze({
    [SEARCH_IMAGES]: operation(
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
      "/api/sns/web/v2/search/notes",
      ["getAiSearchNotesV2"],
      ["WEB_AI_SEARCH_NOTES_V2", "getAiSearchNotesV2"],
      "POST"
    ),
    [SEARCH_PRODUCTS]: operation(
      "search",
      ["keyword", "page", "search_id", "source"],
      ["keyword"]
    ),
    [SEARCH_GROUPS]: operation(
      "chat",
      ["keyword", "page_no", "search_id", "source", "is_recommend"],
      ["keyword"],
      "/api/im/v1/group/square/search",
      ["searchGroup"]
    ),
    [PRODUCT_DETAIL]: operation(
      "explore",
      ["sku_id", "source", "pre_page"],
      ["sku_id"]
    ),
    [PRODUCT_REVIEW_OVERVIEW]: operation(
      "explore",
      ["sku_id", "tab"],
      ["sku_id"]
    ),
    [PRODUCT_REVIEWS]: operation(
      "explore",
      ["sku_id", "page", "sort_strategy_type", "share_pics_only", "from_page"],
      ["sku_id"]
    ),
    [PRODUCT_RECOMMENDATIONS]: operation(
      "explore",
      ["sku_id", "cursor_score", "region"],
      ["sku_id"]
    ),
    [TOPIC_INFO]: operation(
      "search",
      ["page_id", "source", "note_id"],
      ["page_id"]
    ),
    [TOPIC_FEED]: operation(
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
    [CREATOR_INSPIRATION]: operation(
      "explore",
      ["cursor", "tab", "source"]
    ),
    [CREATOR_HOT_INSPIRATION]: operation(
      "explore",
      ["cursor"]
    )
  });

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function decimalInRange(value, minimum, maximum) {
    return /^(?:0|[1-9][0-9]*)$/.test(value) &&
      Number(value) >= minimum &&
      Number(value) <= maximum;
  }

  function validSource(path, value) {
    const expected = {
      [SEARCH_IMAGES]: "explore_feed",
      [SEARCH_PRODUCTS]: "explore_feed",
      [SEARCH_GROUPS]: "unifiedSearchGroup",
      [PRODUCT_DETAIL]: "mall_search",
      [TOPIC_INFO]: "normal",
      [TOPIC_FEED]: "normal",
      [CREATOR_INSPIRATION]: "creator_center"
    }[path];
    return expected !== undefined && value === expected;
  }

  function validValue(path, name, value) {
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
      return value === ""
        ? name === "note_id" || name === "last_note_id"
        : XHS_ID.test(value);
    }
    if (name === "keyword") {
      return value.trim().length > 0 && value.length <= 256;
    }
    if (name === "page") {
      return decimalInRange(
        value,
        path === PRODUCT_REVIEWS ? 0 : 1,
        10000
      );
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

  function validEntries(path, entries) {
    const descriptor = OPERATIONS[path];
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
        !validValue(path, entry[0], entry[1])
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

  function redactURL(value) {
    try {
      const absolute = /^https?:\/\//i.test(value);
      const parsed = new URL(value, "https://www.xiaohongshu.com");
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
        return value;
      }
      for (const [name] of parsed.searchParams) {
        if (SENSITIVE_NAME.test(name)) {
          return absolute
            ? `${parsed.protocol}//${parsed.host}${parsed.pathname}`
            : parsed.pathname;
        }
      }
      return value;
    } catch {
      return value;
    }
  }

  function sanitize(value, depth = 0, seen = new WeakSet()) {
    if (depth > 14 || value === null) {
      return value === null ? null : undefined;
    }
    if (typeof value === "string") {
      const separator = value.indexOf("=");
      const assignment = separator > 0 ? value.slice(0, separator).trim() : "";
      if (
        value.length > 32768 ||
        (
          /^[A-Za-z][A-Za-z0-9_-]{0,79}$/.test(assignment) &&
          SENSITIVE_NAME.test(assignment)
        )
      ) {
        return undefined;
      }
      return redactURL(value);
    }
    if (typeof value === "number" || typeof value === "boolean") {
      return typeof value === "number" && !Number.isFinite(value)
        ? undefined
        : value;
    }
    if (Array.isArray(value)) {
      return value.slice(0, 10000).map(
        (item) => sanitize(item, depth + 1, seen)
      ).filter((item) => item !== undefined);
    }
    if (!isRecord(value) || seen.has(value)) {
      return undefined;
    }
    seen.add(value);
    const output = {};
    for (const key of Object.keys(value).slice(0, 1000)) {
      if (
        key === "__proto__" ||
        key === "prototype" ||
        key === "constructor" ||
        SENSITIVE_NAME.test(key)
      ) {
        continue;
      }
      let item;
      try {
        item = sanitize(value[key], depth + 1, seen);
      } catch {
        item = undefined;
      }
      if (item !== undefined) {
        output[key] = item;
      }
    }
    seen.delete(value);
    return output;
  }

  function response(value) {
    try {
      const bytes = new TextEncoder().encode(JSON.stringify(value)).byteLength;
      return bytes <= MAX_RESULT_BYTES
        ? value
        : { ok: false, error: "response_too_large" };
    } catch {
      return { ok: false, error: "invalid_response" };
    }
  }

  function operationRegistry() {
    const key = Symbol.for(
      "local_browser_session_bridge.xiaohongshu_app_v2.operations.v1"
    );
    const current = window[key];
    if (current && current.version === 1 && current.active instanceof Map) {
      return current;
    }
    const registry = { version: 1, active: new Map() };
    Object.defineProperty(window, key, {
      configurable: true,
      value: registry
    });
    return registry;
  }

  function createOperation() {
    const controller = new AbortController();
    return {
      signal: controller.signal,
      cancel(reason = "rpc_cancelled") {
        if (!controller.signal.aborted) {
          controller.abort(String(reason || "rpc_cancelled"));
        }
      },
      throwIfCancelled() {
        if (controller.signal.aborted) {
          throw new Error("xiaohongshu_app_v2_request_cancelled");
        }
      }
    };
  }

  function awaitTransport(value, operation) {
    operation.throwIfCancelled();
    return new Promise((resolve, reject) => {
      let settled = false;
      let timedOut = false;
      const timer = setTimeout(() => {
        timedOut = true;
        operation.cancel("timeout");
        finish(() => reject(new Error("xiaohongshu_app_v2_timeout")));
      }, TRANSPORT_TIMEOUT_MS);
      const onAbort = () => finish(() => reject(new Error(
        timedOut
          ? "xiaohongshu_app_v2_timeout"
          : "xiaohongshu_app_v2_request_cancelled"
      )));
      function finish(callback) {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        operation.signal.removeEventListener("abort", onAbort);
        callback();
      }
      operation.signal.addEventListener("abort", onAbort, { once: true });
      Promise.resolve(value).then(
        (result) => finish(() => resolve(result)),
        (error) => finish(() => reject(error))
      );
      if (operation.signal.aborted) {
        onAbort();
      }
    });
  }

  function registerOperation(operationID) {
    const registry = operationRegistry();
    const previous = registry.active.get(operationID);
    if (previous && typeof previous.cancel === "function") {
      previous.cancel("superseded");
    }
    const operation = createOperation();
    registry.active.set(operationID, operation);
    return {
      operation,
      release() {
        if (registry.active.get(operationID) === operation) {
          registry.active.delete(operationID);
        }
      }
    };
  }

  function cancelOperation(operationID) {
    const operation = operationRegistry().active.get(operationID);
    if (!operation || typeof operation.cancel !== "function") {
      return false;
    }
    operation.cancel("rpc_cancelled");
    return true;
  }

  function visibleElement(element) {
    if (!element || typeof element.getBoundingClientRect !== "function") {
      return false;
    }
    const rect = element.getBoundingClientRect();
    if (!rect || rect.width <= 0 || rect.height <= 0) {
      return false;
    }
    if (typeof window.getComputedStyle !== "function") {
      return true;
    }
    const style = window.getComputedStyle(element);
    return Boolean(
      style &&
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      style.visibility !== "collapse" &&
      style.opacity !== "0"
    );
  }

  function verificationRequired() {
    const pageDocument = window.document;
    if (!pageDocument || typeof pageDocument.querySelectorAll !== "function") {
      return false;
    }
    const elements = pageDocument.querySelectorAll(
      'iframe[src*="captcha"], [id*="captcha"] iframe, [class*="captcha"] iframe'
    );
    for (const element of elements) {
      if (visibleElement(element)) {
        return true;
      }
    }
    return false;
  }

  function loginFlag(value) {
    if (value === true || value === 1 || value === "1" || value === "true") {
      return true;
    }
    if (value === false || value === 0 || value === "0" || value === "false") {
      return false;
    }
    return null;
  }

  function initialLoginState() {
    const root = isRecord(window.__INITIAL_STATE__)
      ? window.__INITIAL_STATE__
      : null;
    const user = root && isRecord(root.user) ? root.user : null;
    if (!user) {
      return null;
    }
    for (const name of ["loggedIn", "isLogin", "isLoggedIn", "loginStatus"]) {
      const state = loginFlag(user[name]);
      if (state !== null) {
        return state;
      }
    }
    return null;
  }

  function hasCookie(name) {
    const pageDocument = window.document;
    if (!pageDocument || typeof pageDocument.cookie !== "string") {
      return false;
    }
    return new RegExp(`(?:^|;\\s*)${name}=[^;]+`).test(pageDocument.cookie);
  }

  function signedInNavigation() {
    const pageDocument = window.document;
    if (!pageDocument || typeof pageDocument.querySelectorAll !== "function") {
      return false;
    }
    const visibleMatches = (selector, predicate = () => true) => {
      for (const element of pageDocument.querySelectorAll(selector)) {
        if (visibleElement(element) && predicate(element)) {
          return true;
        }
      }
      return false;
    };
    const account = visibleMatches('a[href^="/user/profile/"]', (element) => {
      const label = String(
        typeof element.getAttribute === "function"
          ? element.getAttribute("aria-label") || ""
          : ""
      ).trim();
      return label === "我" || String(element.textContent || "").trim() === "我";
    });
    return account &&
      visibleMatches('a[href^="/notification"]') &&
      visibleMatches('a[href^="/chat"]');
  }

  function loggedIn() {
    const explicit = initialLoginState();
    if (explicit === true || signedInNavigation()) {
      return true;
    }
    return explicit === false ? false : hasCookie("web_session");
  }

  function requestReady() {
    return loggedIn() || hasCookie("a1");
  }

  function fingerprint() {
    const connection =
      navigator.connection ||
      navigator.mozConnection ||
      navigator.webkitConnection ||
      {};
    const uaData = navigator.userAgentData;
    const brands = uaData && Array.isArray(uaData.brands)
      ? uaData.brands.slice(0, 10).map((item) => ({
        brand: String(item.brand || ""),
        version: String(item.version || "")
      }))
      : [];
    return {
      user_agent: String(navigator.userAgent || ""),
      ua_ch: uaData ? {
        brands,
        mobile: Boolean(uaData.mobile),
        platform: String(uaData.platform || "")
      } : null,
      language: String(navigator.language || ""),
      languages: Array.from(navigator.languages || []).slice(0, 20).map(String),
      platform: String(navigator.platform || ""),
      vendor: String(navigator.vendor || ""),
      cookie_enabled: Boolean(navigator.cookieEnabled),
      online: navigator.onLine !== false,
      hardware_concurrency: Number.isFinite(navigator.hardwareConcurrency)
        ? navigator.hardwareConcurrency
        : null,
      device_memory: Number.isFinite(navigator.deviceMemory)
        ? navigator.deviceMemory
        : null,
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
      timezone: String(
        Intl.DateTimeFormat().resolvedOptions().timeZone || ""
      ),
      connection: {
        effective_type: String(connection.effectiveType || ""),
        round_trip_time: Number.isFinite(connection.rtt)
          ? connection.rtt
          : null,
        downlink: Number.isFinite(connection.downlink)
          ? connection.downlink
          : null,
        save_data: Boolean(connection.saveData)
      }
    };
  }

  function captureSession() {
    return {
      fingerprint: fingerprint(),
      logged_in: loggedIn(),
      request_ready: requestReady(),
      verification_required: verificationRequired()
    };
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

  function currentContext(path) {
    let current;
    try {
      current = new URL(String(window.location && window.location.href || ""));
    } catch {
      throw new Error("invalid_request_context");
    }
    const descriptor = OPERATIONS[path];
    if (
      current.origin !== "https://www.xiaohongshu.com" ||
      current.username ||
      current.password ||
      current.port ||
      !descriptor ||
      !contextPath(descriptor.context, current.pathname)
    ) {
      throw new Error("invalid_request_context");
    }
  }

  function functionSource(value) {
    if (typeof value !== "function") {
      return "";
    }
    try {
      return Function.prototype.toString.call(value);
    } catch {
      return "";
    }
  }

  function transportRegistry() {
    const key = Symbol.for(
      "local_browser_session_bridge.xiaohongshu_app_v2.transport.v1"
    );
    const current = window[key];
    if (
      current &&
      current.version === 1 &&
      (current.require === null || typeof current.require === "function") &&
      isRecord(current.wrappers)
    ) {
      return current;
    }
    const registry = {
      version: 1,
      require: null,
      wrappers: {}
    };
    Object.defineProperty(window, key, {
      configurable: true,
      value: registry
    });
    return registry;
  }

  function captureWebpackRequire() {
    const registry = transportRegistry();
    if (
      typeof registry.require === "function" &&
      isRecord(registry.require.m)
    ) {
      return registry.require;
    }
    const chunks = window[WEBPACK_GLOBAL];
    if (!Array.isArray(chunks) || typeof chunks.push !== "function") {
      return null;
    }
    let runtimeRequire = null;
    const chunkID =
      `xhs_app_v2_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    try {
      chunks.push([[chunkID], {}, (require) => {
        runtimeRequire = require;
      }]);
    } catch {
      return null;
    }
    if (typeof runtimeRequire !== "function" || !isRecord(runtimeRequire.m)) {
      return null;
    }
    registry.require = runtimeRequire;
    registry.wrappers = {};
    return runtimeRequire;
  }

  function matchesWrapper(value, descriptor) {
    if (typeof value !== "function") {
      return false;
    }
    const source = functionSource(value);
    return source.includes(descriptor.webPath) ||
      descriptor.wrapperNames.has(String(value.name || "")) ||
      [...descriptor.factoryMarkers].some((marker) => source.includes(marker));
  }

  function findWrapper(value, descriptor, depth = 0, seen = new WeakSet()) {
    if (matchesWrapper(value, descriptor)) {
      return value;
    }
    if (
      depth >= 5 ||
      value === null ||
      (typeof value !== "object" && typeof value !== "function") ||
      seen.has(value)
    ) {
      return null;
    }
    seen.add(value);

    let prototype = null;
    try {
      prototype = Object.getPrototypeOf(value);
    } catch {
      prototype = null;
    }
    if (
      prototype &&
      prototype !== Object.prototype &&
      prototype !== Function.prototype
    ) {
      for (const key of Reflect.ownKeys(prototype).slice(0, 512)) {
        if (key === "constructor") {
          continue;
        }
        let candidate;
        try {
          candidate = prototype[key];
        } catch {
          continue;
        }
        if (
          typeof candidate === "function" &&
          (
            descriptor.wrapperNames.has(String(key)) ||
            matchesWrapper(candidate, descriptor)
          )
        ) {
          return candidate.bind(value);
        }
      }
    }

    let keys;
    try {
      keys = Reflect.ownKeys(value).slice(0, 512);
    } catch {
      return null;
    }
    for (const key of keys) {
      let candidate;
      try {
        candidate = value[key];
      } catch {
        continue;
      }
      if (
        typeof candidate === "function" &&
        (
          descriptor.wrapperNames.has(String(key)) ||
          matchesWrapper(candidate, descriptor)
        )
      ) {
        return candidate.bind(value);
      }
      const nested = findWrapper(candidate, descriptor, depth + 1, seen);
      if (nested) {
        return nested;
      }
    }
    return null;
  }

  function discoverWrapper(runtimeRequire, path) {
    const descriptor = OPERATIONS[path];
    const registry = transportRegistry();
    const cached = registry.wrappers[path];
    if (typeof cached === "function") {
      return cached;
    }
    for (const moduleID of Reflect.ownKeys(runtimeRequire.m).slice(0, 100000)) {
      const factory = runtimeRequire.m[moduleID];
      const source = functionSource(factory);
      if (
        !source.includes(descriptor.webPath) &&
        ![...descriptor.factoryMarkers].some((marker) => source.includes(marker))
      ) {
        continue;
      }
      let exports;
      try {
        exports = runtimeRequire(moduleID);
      } catch {
        continue;
      }
      const wrapper = findWrapper(exports, descriptor);
      if (typeof wrapper === "function") {
        registry.wrappers[path] = wrapper;
        return wrapper;
      }
    }
    return null;
  }

  async function locateWrapper(path, operation) {
    const descriptor = OPERATIONS[path];
    if (!descriptor.webPath) {
      throw new Error("xiaohongshu_app_v2_runtime_unavailable");
    }
    if (!Array.isArray(window[WEBPACK_GLOBAL])) {
      throw new Error("xiaohongshu_app_v2_runtime_unavailable");
    }
    operation.throwIfCancelled();
    const runtimeRequire = captureWebpackRequire();
    if (runtimeRequire) {
      const wrapper = discoverWrapper(runtimeRequire, path);
      if (typeof wrapper === "function") {
        return wrapper;
      }
    }
    throw new Error("xiaohongshu_app_v2_runtime_unavailable");
  }

  function normalizedJSONResponse(value) {
    let parsed = value;
    if (typeof parsed === "string") {
      try {
        parsed = JSON.parse(parsed);
      } catch {
        throw new Error("xiaohongshu_app_v2_invalid_response");
      }
    }
    if (!isRecord(parsed)) {
      throw new Error("xiaohongshu_app_v2_invalid_response");
    }
    const businessCode = Number(
      parsed.code !== undefined
        ? parsed.code
        : isRecord(parsed.data) && parsed.data.code !== undefined
          ? parsed.data.code
          : NaN
    );
    if (businessCode !== 0) {
      const classified = errorCode(parsed);
      if (
        classified === "verification_required" ||
        classified === "rate_limited" ||
        classified === "forbidden" ||
        classified === "not_logged_in"
      ) {
        throw new Error(`xiaohongshu_app_v2_${classified}`);
      }
    }
    const cleaned = sanitize(parsed);
    if (!isRecord(cleaned)) {
      throw new Error("xiaohongshu_app_v2_invalid_response");
    }
    return cleaned;
  }

  function createSearchID() {
    const timestamp = Date.now();
    const random = Math.ceil(0x7ffffffe * Math.random());
    if (typeof BigInt !== "function") {
      return Number.parseInt(`${timestamp}${random}`, 10).toString(36);
    }
    return (
      (BigInt(timestamp) << BigInt(64)) + BigInt(random)
    ).toString(36);
  }

  function integer(values, name, fallback) {
    const value = values.get(name);
    return value === undefined || value === "" ? fallback : Number(value);
  }

  function transportOptions(operation) {
    return {
      signal: operation.signal,
      timeout: TRANSPORT_TIMEOUT_MS
    };
  }

  async function callOperation(path, entries, operation) {
    operation.throwIfCancelled();
    currentContext(path);
    if (verificationRequired()) {
      throw new Error("xiaohongshu_app_v2_verification_required");
    }
    if (!requestReady()) {
      throw new Error("xiaohongshu_app_v2_not_logged_in");
    }
    if (path === SEARCH_GROUPS && !loggedIn()) {
      throw new Error("xiaohongshu_app_v2_not_logged_in");
    }
    const descriptor = OPERATIONS[path];
    if (!descriptor.webPath) {
      throw new Error("xiaohongshu_app_v2_runtime_unavailable");
    }
    const values = new Map(entries);
    const wrapper = await locateWrapper(path, operation);
    let invocation;
    if (path === SEARCH_IMAGES) {
      invocation = wrapper({
        keyword: values.get("keyword"),
        page: integer(values, "page", 1),
        pageSize: 20,
        searchId: values.get("search_id") || createSearchID(),
        sort: "general",
        noteType: 2,
        extFlags: [],
        filters: [],
        geo: "",
        imageFormats: ["jpg", "webp", "avif"],
        sessionId: values.get("search_session_id") || ""
      }, transportOptions(operation));
    } else if (path === SEARCH_GROUPS) {
      invocation = wrapper({
        keyword: values.get("keyword"),
        pageNo: integer(values, "page_no", 0),
        searchId: values.get("search_id") || "",
        source: values.get("source") || "unifiedSearchGroup",
        isRecommend: integer(values, "is_recommend", 0)
      }, transportOptions(operation));
    } else {
      throw new Error("xiaohongshu_app_v2_runtime_unavailable");
    }
    const raw = await awaitTransport(invocation, operation);
    operation.throwIfCancelled();
    return normalizedJSONResponse(raw);
  }

  function errorSignals(error) {
    const records = [];
    const queue = [{ value: error, depth: 0 }];
    const seen = new WeakSet();
    while (queue.length > 0 && records.length < 8) {
      const current = queue.shift();
      if (!isRecord(current.value) || seen.has(current.value)) {
        continue;
      }
      seen.add(current.value);
      records.push(current.value);
      if (current.depth >= 3) {
        continue;
      }
      for (const name of ["response", "data", "cause"]) {
        let nested;
        try {
          nested = Object.prototype.hasOwnProperty.call(current.value, name)
            ? current.value[name]
            : undefined;
        } catch {
          nested = undefined;
        }
        if (isRecord(nested)) {
          queue.push({ value: nested, depth: current.depth + 1 });
        }
      }
    }

    const messages = [];
    const names = [];
    const codes = [];
    const statuses = [];
    function own(record, name) {
      try {
        return Object.prototype.hasOwnProperty.call(record, name)
          ? record[name]
          : undefined;
      } catch {
        return undefined;
      }
    }
    function addText(target, value) {
      const bounded = typeof value === "string" ? value.slice(0, 256) : "";
      if (target.length < 8 && bounded && !target.includes(bounded)) {
        target.push(bounded);
      }
    }
    try {
      addText(messages, error && error.message);
      addText(names, error && error.name);
    } catch {
      // 在受限记录遍历中继续检查对象自身字段。
    }
    for (const record of records) {
      for (const name of ["message", "msg", "errorMessage", "error_message"]) {
        addText(messages, own(record, name));
      }
      addText(names, own(record, "name"));
      for (const name of [
        "code", "errorCode", "error_code", "businessCode", "business_code"
      ]) {
        const value = own(record, name);
        if (
          codes.length < 8 &&
          (typeof value === "string" ||
            (typeof value === "number" && Number.isFinite(value)))
        ) {
          codes.push(String(value).slice(0, 64));
        }
      }
      for (const name of ["status", "statusCode", "httpStatus", "http_status"]) {
        const value = own(record, name);
        const parsed = typeof value === "number"
          ? value
          : typeof value === "string" && /^[0-9]{3}$/.test(value)
            ? Number(value)
            : NaN;
        if (statuses.length < 8 && Number.isFinite(parsed)) {
          statuses.push(parsed);
        }
      }
    }
    return { messages, names, codes, statuses };
  }

  function errorCode(error) {
    const signals = errorSignals(error);
    const messageMatches = (pattern) =>
      signals.messages.some((value) => pattern.test(value));
    const codeIs = (...values) =>
      signals.codes.some((value) => values.includes(value));
    const statusIs = (...values) =>
      signals.statuses.some((value) => values.includes(value));
    if (
      messageMatches(/verification_required|captcha|验证码|安全验证/i) ||
      statusIs(461, 462, 465, 471)
    ) {
      return "verification_required";
    }
    if (
      statusIs(429) ||
      codeIs("429") ||
      messageMatches(/rate.?limit|too many requests|请求频繁|操作频繁/i)
    ) {
      return "rate_limited";
    }
    if (
      statusIs(403) ||
      codeIs("-10000") ||
      messageMatches(/xiaohongshu_app_v2_forbidden/)
    ) {
      return "forbidden";
    }
    if (
      messageMatches(/not_logged_in|login required|请先登录|未登录/i) ||
      statusIs(401) ||
      codeIs("104") ||
      messageMatches(/unauthorized|登录失效|登录过期/i)
    ) {
      return "not_logged_in";
    }
    if (
      messageMatches(/xiaohongshu_app_v2_timeout/) ||
      signals.names.includes("TimeoutError") ||
      codeIs("ECONNABORTED", "ETIMEDOUT")
    ) {
      return "timeout";
    }
    if (messageMatches(/runtime_unavailable/)) {
      return "runtime_unavailable";
    }
    if (messageMatches(/invalid_response/)) {
      return "invalid_response";
    }
    if (messageMatches(/invalid_request/)) {
      return "invalid_request";
    }
    return "request_failed";
  }

  if (!isRecord(input)) {
    return { ok: false, error: "invalid_request" };
  }
  if (input.kind === "cancel") {
    if (
      typeof input.operation_id !== "string" ||
      !OPERATION_ID.test(input.operation_id)
    ) {
      return { ok: false, error: "invalid_request" };
    }
    return response({
      ok: true,
      payload: { cancelled: cancelOperation(input.operation_id) }
    });
  }
  if (input.kind === "session") {
    return response({ ok: true, payload: captureSession() });
  }
  const descriptor = OPERATIONS[input.path];
  if (
    input.kind !== "request" ||
    typeof input.operation_id !== "string" ||
    !OPERATION_ID.test(input.operation_id) ||
    !descriptor ||
    input.method !== descriptor.method ||
    !validEntries(input.path, input.entries)
  ) {
    return { ok: false, error: "invalid_request" };
  }

  const registered = registerOperation(input.operation_id);
  try {
    return response({
      ok: true,
      payload: await callOperation(
        input.path,
        input.entries,
        registered.operation
      )
    });
  } catch (error) {
    return { ok: false, error: errorCode(error) };
  } finally {
    registered.release();
  }
}
