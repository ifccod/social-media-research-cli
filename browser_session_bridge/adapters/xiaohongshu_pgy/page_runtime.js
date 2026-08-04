// chrome.scripting 会将此函数序列化到页面的 MAIN world。依赖全部保留在
// 函数内部，避免 PGY 凭据离开标签页。
export async function invokeXiaohongshuPgyPageRuntime(input) {
  const MAX_RESULT_BYTES = 6 * 1024 * 1024;
  const OPERATION_ID = /^[A-Za-z0-9_-]{1,96}$/;
  const PARAMETER_NAME = /^[A-Za-z][A-Za-z0-9_]{0,79}$/;
  const XHS_ID = /^[a-fA-F0-9]{24}$/;
  const TRACK_ID = /^[^\r\n\0]{1,256}$/;
  const INTEGER = /^(?:0|[1-9][0-9]{0,3})$/;
  const DIGITS = /^[0-9]{0,20}$/;
  const ORIGIN = "https://pgy.xiaohongshu.com";
  const WEBPACK_GLOBAL = "webpackChunkpgy_pc";
  const TRANSPORT_TIMEOUT_MS = 20000;
  const SENSITIVE_NAME =
    /(?:cookie|authorization|token|(?:^|[-_])x[-_]?s(?:[-_]|$)|(?:^|[-_])x[-_]?t(?:[-_]|$)|signature|session|passport|csrf|sid(?:_|$)|a1(?:_|$)|webid)/i;

  const NOTE_DETAIL =
    "/bridge/v1/xiaohongshu-pgy/note-detail";
  const BLOGGER_DETAIL =
    "/bridge/v1/xiaohongshu-pgy/blogger-detail";
  const BLOGGER_NOTES =
    "/bridge/v1/xiaohongshu-pgy/blogger-notes";
  const BLOGGER_NOTES_RATE =
    "/bridge/v1/xiaohongshu-pgy/blogger-notes-rate";
  const BLOGGER_CORE_DATA =
    "/bridge/v1/xiaohongshu-pgy/blogger-core-data";
  const BLOGGER_DATA_SUMMARY =
    "/bridge/v1/xiaohongshu-pgy/blogger-data-summary";
  const BLOGGER_FANS_SUMMARY =
    "/bridge/v1/xiaohongshu-pgy/blogger-fans-summary";
  const BLOGGER_FANS_PROFILE =
    "/bridge/v1/xiaohongshu-pgy/blogger-fans-profile";
  const BLOGGER_FANS_HISTORY =
    "/bridge/v1/xiaohongshu-pgy/blogger-fans-history";
  const BLOGGER_LIST =
    "/bridge/v1/xiaohongshu-pgy/blogger-list";
  const GOOD_CASE_CLASSES =
    "/bridge/v1/xiaohongshu-pgy/good-case-classes";
  const GOOD_NOTES =
    "/bridge/v1/xiaohongshu-pgy/good-notes";
  const GOOD_LIVES =
    "/bridge/v1/xiaohongshu-pgy/good-lives";
  const TOP_BLOGGERS =
    "/bridge/v1/xiaohongshu-pgy/top-bloggers";
  const INDUSTRIES =
    "/bridge/v1/xiaohongshu-pgy/industries";

  const OPERATIONS = Object.freeze({
    [NOTE_DETAIL]: {
      method: "GET",
      tokens: ["/api/solar/note/", "/detail"],
      allowed: new Set(["note_id", "biz_code"]),
      required: new Set(["note_id"])
    },
    [BLOGGER_DETAIL]: {
      method: "GET",
      tokens: ["/api/solar/cooperator/user/blogger"],
      allowed: new Set(["user_id"]),
      required: new Set(["user_id"])
    },
    [BLOGGER_NOTES]: {
      method: "GET",
      tokens: ["/api/solar/kol/data_v2/notes_detail"],
      allowed: new Set([
        "user_id", "page_number", "page_size", "note_type", "order_type",
        "advertise_switch"
      ]),
      required: new Set(["user_id"])
    },
    [BLOGGER_NOTES_RATE]: {
      method: "GET",
      tokens: ["/api/solar/kol/data_v3/notes_rate"],
      allowed: new Set([
        "user_id", "business", "note_type", "date_type", "advertise_switch"
      ]),
      required: new Set(["user_id"])
    },
    [BLOGGER_CORE_DATA]: {
      method: "POST",
      tokens: ["/api/pgy/kol/data/core_data"],
      allowed: new Set([
        "user_id", "business", "note_type", "date_type", "advertise_switch"
      ]),
      required: new Set(["user_id"])
    },
    [BLOGGER_DATA_SUMMARY]: {
      method: "GET",
      tokens: ["/api/pgy/kol/data/data_summary"],
      allowed: new Set(["user_id", "business"]),
      required: new Set(["user_id"])
    },
    [BLOGGER_FANS_SUMMARY]: {
      method: "GET",
      tokens: ["/api/solar/kol/data_v3/fans_summary"],
      allowed: new Set(["user_id"]),
      required: new Set(["user_id"])
    },
    [BLOGGER_FANS_PROFILE]: {
      method: "GET",
      tokens: ["/fans_profile"],
      allowed: new Set(["user_id"]),
      required: new Set(["user_id"])
    },
    [BLOGGER_FANS_HISTORY]: {
      method: "GET",
      tokens: ["/fans_overall_new_history"],
      allowed: new Set(["user_id", "date_type", "increase_type"]),
      required: new Set(["user_id"])
    },
    [BLOGGER_LIST]: {
      method: "POST",
      tokens: ["/api/solar/cooperator/blogger/v2"],
      allowed: new Set([
        "brand_user_id", "page_num", "page_size", "fans_number_lower",
        "fans_number_upper"
      ]),
      required: new Set()
    },
    [GOOD_CASE_CLASSES]: {
      method: "GET",
      tokens: ["/api/solar/index/class_info"],
      allowed: new Set(),
      required: new Set()
    },
    [GOOD_NOTES]: {
      method: "GET",
      tokens: ["/api/solar/index/high_grade_note"],
      allowed: new Set(["category"]),
      required: new Set(["category"])
    },
    [GOOD_LIVES]: {
      method: "GET",
      tokens: ["/api/solar/index/high_grade_live"],
      allowed: new Set(["category"]),
      required: new Set(["category"])
    },
    [TOP_BLOGGERS]: {
      method: "GET",
      tokens: ["/api/solar/index/top_kols"],
      allowed: new Set(["rank_type"]),
      required: new Set(["rank_type"])
    },
    [INDUSTRIES]: {
      method: "GET",
      tokens: ["/api/solar/index/get_industry_data"],
      allowed: new Set(),
      required: new Set()
    }
  });

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function encodedSize(value) {
    return new TextEncoder().encode(JSON.stringify(value)).byteLength;
  }

  function sanitize(value, depth, seen, secrets) {
    if (depth > 14) {
      return null;
    }
    if (
      value === null ||
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      if (typeof value === "string" && secrets.some((secret) => secret && value.includes(secret))) {
        return "[redacted]";
      }
      return value;
    }
    if (Array.isArray(value)) {
      return value.slice(0, 20000).map((item) => sanitize(item, depth + 1, seen, secrets));
    }
    if (!isRecord(value) || seen.has(value)) {
      return null;
    }
    seen.add(value);
    const result = {};
    for (const [name, item] of Object.entries(value).slice(0, 20000)) {
      result[name] = SENSITIVE_NAME.test(name)
        ? "[redacted]"
        : sanitize(item, depth + 1, seen, secrets);
    }
    seen.delete(value);
    return result;
  }

  function verificationRequired() {
    const selectors = [
      "#captcha_container",
      ".red-captcha",
      "[class*='captcha']",
      "[id*='captcha']",
      "iframe[src*='captcha']"
    ];
    for (const selector of selectors) {
      const candidates = Array.from(document.querySelectorAll(selector)).slice(0, 20);
      for (const candidate of candidates) {
        const style = window.getComputedStyle(candidate);
        const rect = candidate.getBoundingClientRect();
        if (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          Number(style.opacity || "1") !== 0 &&
          rect.width > 0 &&
          rect.height > 0
        ) {
          return true;
        }
      }
    }
    return false;
  }

  function fingerprint() {
    const connection =
      navigator.connection || navigator.mozConnection || navigator.webkitConnection || {};
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

  function createOperation() {
    const controller = new AbortController();
    return {
      signal: controller.signal,
      cancel(reason) {
        if (!controller.signal.aborted) {
          controller.abort(reason);
        }
      },
      throwIfCancelled() {
        if (controller.signal.aborted) {
          throw new Error("request_cancelled");
        }
      }
    };
  }

  function operationRegistry() {
    const key = Symbol.for("local_browser_session_bridge.xiaohongshu_pgy.operations.v1");
    const current = window[key];
    if (current && current.version === 1 && current.active instanceof Map) {
      return current;
    }
    const registry = { version: 1, active: new Map() };
    Object.defineProperty(window, key, { configurable: true, value: registry });
    return registry;
  }

  function registerOperation(operationID) {
    const registry = operationRegistry();
    const previous = registry.active.get(operationID);
    if (previous) {
      previous.cancel("replaced");
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
    if (!operation) {
      return false;
    }
    operation.cancel("rpc_cancelled");
    return true;
  }

  function awaitTransport(value, operation) {
    operation.throwIfCancelled();
    return new Promise((resolve, reject) => {
      let settled = false;
      const timer = setTimeout(() => finish(() => reject(new Error("transport_timeout"))),
        TRANSPORT_TIMEOUT_MS);
      const abort = () => finish(() => reject(new Error("request_cancelled")));
      function finish(callback) {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        operation.signal.removeEventListener("abort", abort);
        callback();
      }
      operation.signal.addEventListener("abort", abort, { once: true });
      Promise.resolve(value).then(
        (result) => finish(() => resolve(result)),
        (error) => finish(() => reject(error))
      );
    });
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

  function sourceMatches(value, tokens) {
    const source = functionSource(value);
    return tokens.every((token) => source.includes(token));
  }

  function transportRegistry() {
    const key = Symbol.for("local_browser_session_bridge.xiaohongshu_pgy.transport.v1");
    const current = window[key];
    if (
      current &&
      current.version === 1 &&
      (current.require === null || typeof current.require === "function") &&
      isRecord(current.wrappers)
    ) {
      return current;
    }
    const registry = { version: 1, require: null, wrappers: {} };
    Object.defineProperty(window, key, { configurable: true, value: registry });
    return registry;
  }

  function captureWebpackRequire() {
    const registry = transportRegistry();
    if (typeof registry.require === "function" && isRecord(registry.require.m)) {
      return registry.require;
    }
    const chunks = window[WEBPACK_GLOBAL];
    if (!Array.isArray(chunks) || typeof chunks.push !== "function") {
      return null;
    }
    let runtimeRequire = null;
    const chunkID = `pgy_reverse_${Date.now()}_${Math.random().toString(16).slice(2)}`;
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

  function findBoundMethod(value, tokens, depth = 0, seen = new WeakSet()) {
    if (
      value === null ||
      (typeof value !== "object" && typeof value !== "function") ||
      depth > 4 ||
      seen.has(value)
    ) {
      return null;
    }
    seen.add(value);

    if (typeof value === "function" && sourceMatches(value, tokens)) {
      return value;
    }

    let prototype = null;
    try {
      prototype = Object.getPrototypeOf(value);
    } catch {
      prototype = null;
    }
    if (prototype && prototype !== Object.prototype && prototype !== Function.prototype) {
      for (const name of Reflect.ownKeys(prototype).slice(0, 512)) {
        if (name === "constructor") {
          continue;
        }
        let candidate;
        try {
          candidate = prototype[name];
        } catch {
          continue;
        }
        if (typeof candidate === "function" && sourceMatches(candidate, tokens)) {
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
    for (const name of keys) {
      let candidate;
      try {
        candidate = value[name];
      } catch {
        continue;
      }
      if (typeof candidate === "function" && sourceMatches(candidate, tokens)) {
        return candidate.bind(value);
      }
      const nested = findBoundMethod(candidate, tokens, depth + 1, seen);
      if (nested) {
        return nested;
      }
    }
    return null;
  }

  function discoverWrapper(runtimeRequire, cacheKey, tokens) {
    const registry = transportRegistry();
    const cached = registry.wrappers[cacheKey];
    if (typeof cached === "function") {
      return cached;
    }
    const factories = runtimeRequire.m;
    for (const moduleID of Reflect.ownKeys(factories).slice(0, 100000)) {
      const factory = factories[moduleID];
      if (!sourceMatches(factory, tokens)) {
        continue;
      }
      let exports;
      try {
        exports = runtimeRequire(moduleID);
      } catch {
        continue;
      }
      const wrapper = findBoundMethod(exports, tokens);
      if (typeof wrapper === "function") {
        registry.wrappers[cacheKey] = wrapper;
        return wrapper;
      }
    }
    return null;
  }

  async function locateWrapper(cacheKey, tokens, operation) {
    operation.throwIfCancelled();
    const runtimeRequire = captureWebpackRequire();
    if (runtimeRequire) {
      const wrapper = discoverWrapper(runtimeRequire, cacheKey, tokens);
      if (wrapper) {
        return wrapper;
      }
    }
    throw new Error("xiaohongshu_pgy_runtime_unavailable");
  }

  function validValue(name, value) {
    if (typeof value !== "string" || value.length > 1024 || /[\r\n\0]/.test(value)) {
      return false;
    }
    if (name === "note_id" || name === "user_id" || name === "brand_user_id") {
      return XHS_ID.test(value);
    }
    if (name === "fans_number_lower" || name === "fans_number_upper") {
      return DIGITS.test(value);
    }
    if (name === "biz_code") {
      return value.length <= 64 && /^[A-Za-z0-9_-]*$/.test(value);
    }
    if (name === "category") {
      return (
        value === value.trim() &&
        [...value].length >= 1 &&
        [...value].length <= 64
      );
    }
    return INTEGER.test(value);
  }

  function validEntries(path, entries) {
    const descriptor = OPERATIONS[path];
    if (!descriptor || !Array.isArray(entries) || entries.length > 16) {
      return false;
    }
    const seen = new Set();
    for (const entry of entries) {
      if (
        !Array.isArray(entry) ||
        entry.length !== 2 ||
        typeof entry[0] !== "string" ||
        !PARAMETER_NAME.test(entry[0]) ||
        !descriptor.allowed.has(entry[0]) ||
        seen.has(entry[0]) ||
        !validValue(entry[0], entry[1])
      ) {
        return false;
      }
      seen.add(entry[0]);
    }
    for (const name of descriptor.required) {
      if (!seen.has(name)) {
        return false;
      }
    }
    return true;
  }

  function currentContext() {
    let current;
    try {
      current = new URL(String(window.location && window.location.href || ""));
    } catch {
      throw new Error("invalid_request_context");
    }
    if (
      current.origin !== ORIGIN ||
      current.username ||
      current.password ||
      current.port
    ) {
      throw new Error("invalid_request_context");
    }
    return current;
  }

  function ownValue(value, name) {
    try {
      return isRecord(value) && Object.prototype.hasOwnProperty.call(value, name)
        ? value[name]
        : undefined;
    } catch {
      return undefined;
    }
  }

  function loginFlag(value) {
    if (typeof value === "boolean") {
      return value;
    }
    if (value === 1 || value === "1") {
      return true;
    }
    if (value === 0 || value === "0") {
      return false;
    }
    if (typeof value !== "string") {
      return null;
    }
    const normalized = value.trim().toLowerCase();
    if (["true", "logged_in", "loggedin", "success"].includes(normalized)) {
      return true;
    }
    if (["false", "logged_out", "loggedout", "unauthorized"].includes(normalized)) {
      return false;
    }
    return null;
  }

  function localStateRoots() {
    const roots = [];
    for (const name of [
      "__INITIAL_STATE__",
      "__INITIAL_DATA__",
      "__PRELOADED_STATE__",
      "__NEXT_DATA__"
    ]) {
      const value = ownValue(window, name);
      if (isRecord(value)) {
        roots.push(value);
      }
    }
    for (const storageName of ["localStorage", "sessionStorage"]) {
      let storage;
      try {
        storage = window[storageName];
      } catch {
        storage = null;
      }
      if (!storage || typeof storage.key !== "function" || typeof storage.getItem !== "function") {
        continue;
      }
      const length = Math.min(Number(storage.length) || 0, 32);
      for (let index = 0; index < length; index += 1) {
        let name;
        let raw;
        try {
          name = String(storage.key(index) || "");
          raw = storage.getItem(name);
        } catch {
          continue;
        }
        if (
          !/(?:user|account|login|session|pgy|solar|brand|customer)/i.test(name) ||
          typeof raw !== "string" ||
          raw.length === 0 ||
          raw.length > 100000
        ) {
          continue;
        }
        try {
          const parsed = JSON.parse(raw);
          if (isRecord(parsed)) {
            roots.push(parsed);
          }
        } catch {
          // 忽略非 JSON 本地状态。
        }
      }
    }
    return roots.slice(0, 40);
  }

  function localAccountState() {
    const accountNode =
      /^(?:user|userInfo|currentUser|loginUser|account|accountInfo|brand|brandInfo|customer|customerInfo|profile|profileInfo)$/i;
    const structuralNode = /^(?:data|state|props|pageProps|value)$/i;
    const loginNames = ["loggedIn", "isLogin", "isLoggedIn", "loginStatus"];
    const idNames = [
      "userId", "user_id", "brandUserId", "brand_user_id", "customerId", "customer_id"
    ];
    const queue = localStateRoots().map((value) => ({
      value,
      depth: 0,
      account: false
    }));
    const seen = new WeakSet();
    let loggedIn = null;
    let userID = "";
    let inspected = 0;

    while (queue.length > 0 && inspected < 80) {
      const current = queue.shift();
      if (
        !isRecord(current.value) ||
        seen.has(current.value) ||
        current.depth > 5
      ) {
        continue;
      }
      seen.add(current.value);
      inspected += 1;

      let recordLogin = null;
      for (const name of loginNames) {
        const state = loginFlag(ownValue(current.value, name));
        if (state !== null) {
          recordLogin = state;
          if (state === true) {
            loggedIn = true;
          } else if (loggedIn === null) {
            loggedIn = false;
          }
        }
      }
      if (!userID && (current.account || recordLogin !== null)) {
        for (const name of idNames) {
          const candidate = String(ownValue(current.value, name) || "");
          if (XHS_ID.test(candidate)) {
            userID = candidate;
            break;
          }
        }
      }

      let names;
      try {
        names = Reflect.ownKeys(current.value).slice(0, 128);
      } catch {
        names = [];
      }
      for (const name of names) {
        if (typeof name !== "string") {
          continue;
        }
        const nestedAccount = current.account || accountNode.test(name);
        if (!nestedAccount && !structuralNode.test(name)) {
          continue;
        }
        const nested = ownValue(current.value, name);
        if (isRecord(nested)) {
          queue.push({
            value: nested,
            depth: current.depth + 1,
            account: nestedAccount
          });
        }
      }
    }
    return { loggedIn, userID };
  }

  function hasPgySessionCookie() {
    let raw = "";
    try {
      raw = String(document.cookie || "");
    } catch {
      return false;
    }
    const sessionName =
      /^(?:access-token-pgy(?:\.xiaohongshu\.com)?|customer-sso-sid(?:\.sig)?|solar\.beaker\.session\.id(?:\.sig)?)$/i;
    return raw.split(";").some((part) => {
      const separator = part.indexOf("=");
      if (separator <= 0) {
        return false;
      }
      const name = part.slice(0, separator).trim();
      const value = part.slice(separator + 1).trim();
      return Boolean(value) && sessionName.test(name);
    });
  }

  function visibleElement(element) {
    if (!element || typeof element.getBoundingClientRect !== "function") {
      return false;
    }
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return (
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      Number(style.opacity || "1") !== 0 &&
      rect.width > 0 &&
      rect.height > 0
    );
  }

  function signedInNavigation() {
    if (!document || typeof document.querySelectorAll !== "function") {
      return false;
    }
    const selectors = [
      "[class*='user'] [class*='avatar']",
      "[class*='account'] [class*='avatar']",
      "[class*='header'] [class*='avatar']",
      "a[href*='/account']"
    ];
    for (const selector of selectors) {
      for (const element of Array.from(document.querySelectorAll(selector)).slice(0, 20)) {
        if (visibleElement(element)) {
          return true;
        }
      }
    }
    for (const element of Array.from(document.querySelectorAll("button,a")).slice(0, 200)) {
      const text = String(element.textContent || "").trim();
      if (text === "退出登录" && visibleElement(element)) {
        return true;
      }
    }
    return false;
  }

  function localLoginState() {
    const account = localAccountState();
    if (account.loggedIn === true || signedInNavigation()) {
      return { loggedIn: true, userID: account.userID };
    }
    if (account.loggedIn === false) {
      return { loggedIn: false, userID: account.userID };
    }
    return {
      loggedIn: hasPgySessionCookie(),
      userID: account.userID
    };
  }

  function integer(values, name, fallback) {
    const value = values.get(name);
    return value === undefined || value === "" ? fallback : Number(value);
  }

  function normalizedJSONResponse(value) {
    let parsed = value;
    if (typeof parsed === "string") {
      try {
        parsed = JSON.parse(parsed);
      } catch {
        throw new Error("xiaohongshu_pgy_invalid_response");
      }
    }
    if (!isRecord(parsed)) {
      throw new Error("xiaohongshu_pgy_invalid_response");
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
        classified === "forbidden"
      ) {
        throw new Error(`xiaohongshu_pgy_${classified}`);
      }
    }
    const cleaned = sanitize(parsed, 0, new WeakSet(), []);
    if (!isRecord(cleaned)) {
      throw new Error("xiaohongshu_pgy_invalid_response");
    }
    return cleaned;
  }

  async function invokeWrapper(wrapper, args, operation) {
    operation.throwIfCancelled();
    const raw = await awaitTransport(wrapper(...args), operation);
    operation.throwIfCancelled();
    return normalizedJSONResponse(raw);
  }

  function bloggerListBody(values, brandUserID) {
    return {
      searchType: 1,
      column: "comprehensiverank",
      sort: "desc",
      pageNum: integer(values, "page_num", 1),
      pageSize: integer(values, "page_size", 20),
      brandUserId: brandUserID,
      personalTags: [],
      featureTags: [],
      estimatePicReadPrice: [],
      estimateVideoReadPrice: [],
      fansNumberLower: values.get("fans_number_lower") || null,
      fansNumberUpper: values.get("fans_number_upper") || null,
      noteType: 0,
      gender: null,
      location: null,
      tradeType: "不限",
      fansAge: 0,
      fansGender: 0,
      fansNumUp: 0,
      cpc: false,
      excludeLowActive: false,
      newHighQuality: 0,
      efficiencyValid: 0,
      clothingIndustry: 0,
      firstIndustry: "",
      secondIndustry: "",
      activityCodes: []
    };
  }

  function bloggerListBrandUserID(values) {
    const requested = values.get("brand_user_id") || "";
    if (requested) {
      return requested;
    }
    const account = localLoginState();
    if (!account.loggedIn || !XHS_ID.test(account.userID)) {
      throw new Error("xiaohongshu_pgy_not_logged_in");
    }
    return account.userID;
  }

  async function callBloggerTrack(values, operation) {
    const brandUserID = bloggerListBrandUserID(values);
    const body = bloggerListBody(values, brandUserID);
    const track = await locateWrapper(
      "blogger_track",
      ["/api/solar/cooperator/blogger/track"],
      operation
    );
    const trackPayload = await invokeWrapper(track, [body], operation);
    const trackID = String(trackPayload.trackId || trackPayload.track_id || "");
    if (!trackID || trackID.length > 256 || /[\r\n\0]/.test(trackID)) {
      throw new Error("xiaohongshu_pgy_invalid_response");
    }
    return {
      brand_user_id: brandUserID,
      track_id: trackID
    };
  }

  async function callBloggerList(values, brandUserID, trackID, operation) {
    const requestedBrandUserID = values.get("brand_user_id") || "";
    if (
      !XHS_ID.test(brandUserID) ||
      !TRACK_ID.test(trackID) ||
      (requestedBrandUserID && requestedBrandUserID !== brandUserID)
    ) {
      throw new Error("invalid_request");
    }
    const body = bloggerListBody(values, brandUserID);
    const list = await locateWrapper(
      BLOGGER_LIST,
      OPERATIONS[BLOGGER_LIST].tokens,
      operation
    );
    return invokeWrapper(list, [{ ...body, trackId: trackID }], operation);
  }

  async function callOperation(path, entries, input, operation) {
    operation.throwIfCancelled();
    currentContext();
    if (verificationRequired()) {
      throw new Error("xiaohongshu_pgy_verification_required");
    }
    const values = new Map(entries);
    if (path === BLOGGER_LIST) {
      return input.stage === "track"
        ? callBloggerTrack(values, operation)
        : callBloggerList(
          values,
          input.brand_user_id,
          input.track_id,
          operation
        );
    }
    const descriptor = OPERATIONS[path];
    const wrapper = await locateWrapper(path, descriptor.tokens, operation);
    const userID = values.get("user_id") || "";
    const sharedData = {
      userId: userID,
      business: integer(values, "business", 0),
      noteType: integer(values, "note_type", 3),
      dateType: integer(values, "date_type", 1),
      advertiseSwitch: integer(values, "advertise_switch", 1)
    };
    switch (path) {
    case NOTE_DETAIL:
      return invokeWrapper(
        wrapper,
        [values.get("note_id"), values.get("biz_code") || ""],
        operation
      );
    case BLOGGER_DETAIL:
      return invokeWrapper(wrapper, [userID], operation);
    case BLOGGER_NOTES:
      return invokeWrapper(wrapper, [{
        userId: userID,
        advertiseSwitch: integer(values, "advertise_switch", 1),
        orderType: integer(values, "order_type", 1),
        pageNumber: integer(values, "page_number", 1),
        pageSize: integer(values, "page_size", 20),
        noteType: integer(values, "note_type", 0)
      }], operation);
    case BLOGGER_NOTES_RATE:
    case BLOGGER_CORE_DATA:
      return invokeWrapper(wrapper, [sharedData], operation);
    case BLOGGER_DATA_SUMMARY:
      return invokeWrapper(wrapper, [{
        userId: userID,
        business: integer(values, "business", 0)
      }], operation);
    case BLOGGER_FANS_SUMMARY:
    case BLOGGER_FANS_PROFILE:
      return invokeWrapper(wrapper, [userID], operation);
    case BLOGGER_FANS_HISTORY:
      return invokeWrapper(wrapper, [userID, {
        dateType: integer(values, "date_type", 1),
        increaseType: integer(values, "increase_type", 1)
      }], operation);
    case GOOD_CASE_CLASSES:
    case INDUSTRIES:
      return invokeWrapper(wrapper, [], operation);
    case GOOD_NOTES:
    case GOOD_LIVES:
      return invokeWrapper(wrapper, [{
        secondClass: values.get("category")
      }], operation);
    case TOP_BLOGGERS:
      return invokeWrapper(wrapper, [{
        rankType: integer(values, "rank_type", 6)
      }], operation);
    default:
      throw new Error("invalid_request");
    }
  }

  function captureSession() {
    currentContext();
    const verification = verificationRequired();
    const loggedIn = !verification && localLoginState().loggedIn;
    return {
      fingerprint: fingerprint(),
      logged_in: loggedIn,
      request_ready: loggedIn,
      verification_required: verification
    };
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
      messageMatches(/forbidden/i)
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
    if (messageMatches(/runtime_unavailable|transport_timeout/)) {
      return "runtime_unavailable";
    }
    if (messageMatches(/invalid_response/)) {
      return "invalid_response";
    }
    return "request_failed";
  }

  if (!isRecord(input)) {
    return { ok: false, error: "invalid_request" };
  }
  if (input.kind === "cancel") {
    if (typeof input.operation_id !== "string" || !OPERATION_ID.test(input.operation_id)) {
      return { ok: false, error: "invalid_request" };
    }
    return { ok: true, payload: { cancelled: cancelOperation(input.operation_id) } };
  }
  if (input.kind === "session") {
    try {
      const payload = captureSession();
      return encodedSize(payload) <= MAX_RESULT_BYTES
        ? { ok: true, payload }
        : { ok: false, error: "response_too_large" };
    } catch (error) {
      return { ok: false, error: errorCode(error) };
    }
  }
  const descriptor = OPERATIONS[input.path];
  const validStage = input.path === BLOGGER_LIST
    ? (
      input.stage === "track" ||
      (
        input.stage === "list" &&
        typeof input.brand_user_id === "string" &&
        XHS_ID.test(input.brand_user_id) &&
        typeof input.track_id === "string" &&
        TRACK_ID.test(input.track_id)
      )
    )
    : input.stage === undefined;
  if (
    input.kind !== "request" ||
    typeof input.operation_id !== "string" ||
    !OPERATION_ID.test(input.operation_id) ||
    !descriptor ||
    !validStage ||
    (input.method !== undefined && input.method !== descriptor.method) ||
    !validEntries(input.path, input.entries)
  ) {
    return { ok: false, error: "invalid_request" };
  }
  const registered = registerOperation(input.operation_id);
  try {
    const payload = await callOperation(
      input.path,
      input.entries,
      input,
      registered.operation
    );
    return encodedSize(payload) <= MAX_RESULT_BYTES
      ? { ok: true, payload }
      : { ok: false, error: "response_too_large" };
  } catch (error) {
    return { ok: false, error: errorCode(error) };
  } finally {
    registered.release();
  }
}
