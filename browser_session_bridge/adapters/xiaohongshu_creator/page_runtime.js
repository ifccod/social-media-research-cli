// chrome.scripting 会将此函数序列化到页面的 MAIN world。依赖全部保留在
// 函数内部，避免创作者 Cookie / 许可 token / x-s 离开标签页。
export async function invokeXiaohongshuCreatorPageRuntime(input) {
  const MAX_RESULT_BYTES = 6 * 1024 * 1024;
  const OPERATION_ID = /^[A-Za-z0-9_-]{1,96}$/;
  const ORIGIN = "https://creator.xiaohongshu.com";
  const PUBLISH_PATH = "/publish/publish";
  function creatorAppPath(pathname) {
    const path = normalizePathname(pathname);
    if (path === PUBLISH_PATH) {
      return true;
    }
    return path.startsWith("/new/") && !path.includes("/login");
  }
  const WEBPACK_GLOBAL = "webpackChunkugc";
  const TRANSPORT_TIMEOUT_MS = 40000;
  const LOGIN_PROBE_TIMEOUT_MS = 8000;
  const PERMIT_TIMEOUT_MS = 8000;
  const IMAGE_PUT_TIMEOUT_MS = 20000;
  const VIDEO_UPLOAD_TIMEOUT_MS = 80000;
  const LOGIN_CACHE_MS = 15000;
  const PERMIT_PATH = "/api/media/v1/upload/creator/permit";
  const NOTE_URL = "https://edith.xiaohongshu.com/web_api/sns/v2/note";
  const USER_INFO_FALLBACKS = [
    "https://creator.xiaohongshu.com/api/galaxy/user/info",
    "https://creator.xiaohongshu.com/api/galaxy/creator/home/personal_info"
  ];
  const MAX_TITLE_CHARS = 20;
  const MAX_CONTENT_CHARS = 1000;
  const MAX_IMAGES = 9;
  const MIME_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
  const VIDEO_MIME_TYPES = new Set(["video/mp4", "video/quicktime"]);
  const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;
  const FILE_ID = /^(?:spectrum\/)?[A-Za-z0-9._-]{1,128}$/;
  const UPLOAD_ID = /^[A-Za-z0-9_-]{8,64}$/;
  const TOTAL_BYTES = /^[1-9][0-9]{0,7}$/;
  const SEGMENT_INDEX = /^(?:0|[1-9][0-9]{0,2})$/;
  const DIMENSION = /^(?:0|[1-9][0-9]{0,4})$/;
  const MAX_UPLOAD_BASE64 = 7 * 1024 * 1024;
  const MAX_VIDEO_BYTES = 64_000_000;
  const VIDEO_CHUNK_BYTES = 4_194_304;
  const SENSITIVE_NAME =
    /(?:cookie|authorization|token|(?:^|[-_])x[-_]?s(?:[-_]|$)|(?:^|[-_])x[-_]?t(?:[-_]|$)|signature|session|passport|csrf|sid(?:_|$)|a1(?:_|$)|webid|permit)/i;
  const UPLOAD_IMAGE_PATH = "/bridge/v1/xiaohongshu-creator/upload-image";
  const UPLOAD_VIDEO_PATH = "/bridge/v1/xiaohongshu-creator/upload-video";
  const PUBLISH_NOTE_PATH = "/bridge/v1/xiaohongshu-creator/publish-note";

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

  function characterCount(value) {
    return [...value].length;
  }

  function normalizePathname(pathname) {
    if (pathname.length > 1 && pathname.endsWith("/")) {
      return pathname.slice(0, -1);
    }
    return pathname;
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
        if (visibleElement(candidate)) {
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
    const key = Symbol.for("local_browser_session_bridge.xiaohongshu_creator.operations.v1");
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

  function awaitTransport(value, operation, timeoutMs) {
    operation.throwIfCancelled();
    const limit = Number.isFinite(timeoutMs) ? timeoutMs : TRANSPORT_TIMEOUT_MS;
    return new Promise((resolve, reject) => {
      let settled = false;
      const timer = setTimeout(
        () => finish(() => reject(new Error("transport_timeout"))),
        limit
      );
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
    const key = Symbol.for("local_browser_session_bridge.xiaohongshu_creator.transport.v1");
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

  function webpackChunkArrays() {
    const names = new Set([WEBPACK_GLOBAL]);
    try {
      for (const name of Object.getOwnPropertyNames(window)) {
        if (/^webpackChunk[A-Za-z0-9_$]*$/.test(name)) {
          names.add(name);
        }
      }
    } catch {
      // 枚举失败时仍尝试默认全局名。
    }
    const arrays = [];
    for (const name of names) {
      let value;
      try {
        value = window[name];
      } catch {
        continue;
      }
      if (Array.isArray(value) && typeof value.push === "function") {
        arrays.push(value);
      }
    }
    return arrays;
  }

  function captureRequireFromChunks(chunks) {
    if (!Array.isArray(chunks) || typeof chunks.push !== "function") {
      return null;
    }
    if (chunks.push === Array.prototype.push) {
      return null;
    }
    let runtimeRequire = null;
    const chunkID = `xhs_creator_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    try {
      chunks.push([[chunkID], {}, (require) => {
        runtimeRequire = require;
      }]);
    } catch {
      return null;
    }
    return typeof runtimeRequire === "function" && isRecord(runtimeRequire.m)
      ? runtimeRequire
      : null;
  }

  function captureWebpackRequire() {
    const registry = transportRegistry();
    if (typeof registry.require === "function" && isRecord(registry.require.m)) {
      return registry.require;
    }
    for (const chunks of webpackChunkArrays()) {
      const runtimeRequire = captureRequireFromChunks(chunks);
      if (runtimeRequire) {
        registry.require = runtimeRequire;
        registry.wrappers = {};
        return runtimeRequire;
      }
    }
    return null;
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

  function factoryMatchesPostNote(source) {
    return source.includes("POST_NOTE") ||
      source.includes("/web_api/sns/v2/note");
  }

  function factoryMatchesConstants(source) {
    return source.includes("UPLOADER_TOKEN_NEWV2");
  }

  function factoryMatchesHttpClient(source) {
    // 只认带拦截器的 HTTP 客户端。Vue imageUploader / getToken 的工厂不能进这里。
    return source.includes("interceptor") &&
      /\bput\b/.test(source) &&
      (source.includes("LV") || /\bget\b/.test(source));
  }

  function locatePostNote(exports) {
    const byMarker = findBoundMethod(exports, ["POST_NOTE"]);
    if (typeof byMarker === "function") {
      const source = functionSource(byMarker);
      if (!source.includes("UPDATE_NOTE_INFO") || source.includes("POST_NOTE")) {
        return byMarker;
      }
    }
    return findBoundMethod(exports, ["web_api/sns/v2/note"]);
  }

  function isHttpClient(value) {
    return isRecord(value) &&
      typeof value.get === "function" &&
      typeof value.post === "function" &&
      typeof value.put === "function" &&
      typeof value.getToken !== "function";
  }

  function locateConstants(exports) {
    const queue = [exports];
    const seen = new WeakSet();
    const nestedNames = ["S", "default", "constants"];
    while (queue.length > 0) {
      const current = queue.shift();
      if (!isRecord(current) || seen.has(current)) {
        continue;
      }
      seen.add(current);
      const permit = current.UPLOADER_TOKEN_NEWV2;
      if (typeof permit === "string" && permit.includes(PERMIT_PATH)) {
        return current;
      }
      for (const name of nestedNames) {
        if (isRecord(current[name])) {
          queue.push(current[name]);
        }
      }
    }
    return null;
  }

  function locateHttpClient(exports) {
    const queue = [exports];
    const seen = new WeakSet();
    let scanned = 0;
    while (queue.length > 0 && scanned < 8) {
      const current = queue.shift();
      scanned += 1;
      if (
        current === null ||
        (typeof current !== "object" && typeof current !== "function") ||
        seen.has(current)
      ) {
        continue;
      }
      seen.add(current);
      if (isHttpClient(current)) {
        return current;
      }
      if (isRecord(current)) {
        if (current.LV) {
          queue.push(current.LV);
        }
        if (current.default) {
          queue.push(current.default);
        }
      }
    }
    return null;
  }

  function isUserInfoUrl(value) {
    return typeof value === "string" &&
      /user|personal/i.test(value) &&
      !/permit|upload|token/i.test(value) &&
      (
        value.startsWith("/api/") ||
        value.startsWith(`${ORIGIN}/api/`)
      );
  }

  function absoluteCreatorUrl(value) {
    if (value.startsWith("https://")) {
      return value;
    }
    return `${ORIGIN}${value.startsWith("/") ? value : `/${value}`}`;
  }

  function userInfoUrl(constants) {
    const preferred = [
      "USER_INFO",
      "GET_USER_INFO",
      "PERSONAL_INFO",
      "CREATOR_USER_INFO",
      "ACCOUNT_INFO"
    ];
    for (const name of preferred) {
      if (isUserInfoUrl(constants[name])) {
        return absoluteCreatorUrl(constants[name]);
      }
    }
    for (const value of Object.values(constants)) {
      if (isUserInfoUrl(value)) {
        return absoluteCreatorUrl(value);
      }
    }
    return "";
  }

  function loadMatchedExport(runtimeRequire, moduleID) {
    try {
      return runtimeRequire(moduleID);
    } catch {
      return null;
    }
  }

  function discoverWrappers(runtimeRequire) {
    const registry = transportRegistry();
    const wrappers = registry.wrappers;
    if (
      typeof wrappers.postNote === "function" &&
      isHttpClient(wrappers.client) &&
      typeof wrappers.permitUrl === "string" &&
      wrappers.permitUrl
    ) {
      return wrappers;
    }
    const factories = runtimeRequire.m;
    for (const moduleID of Reflect.ownKeys(factories).slice(0, 100000)) {
      const source = functionSource(factories[moduleID]);
      if (!source) {
        continue;
      }
      const wantPost = typeof wrappers.postNote !== "function" && factoryMatchesPostNote(source);
      const wantConstants = !wrappers.permitUrl && factoryMatchesConstants(source);
      const wantClient = !isHttpClient(wrappers.client) && factoryMatchesHttpClient(source);
      if (!wantPost && !wantConstants && !wantClient) {
        continue;
      }
      const exports = loadMatchedExport(runtimeRequire, moduleID);
      if (wantPost) {
        const wrapper = locatePostNote(exports);
        if (typeof wrapper === "function") {
          wrappers.postNote = wrapper;
        }
      }
      if (wantConstants) {
        const constants = locateConstants(exports);
        if (constants) {
          wrappers.permitUrl = String(constants.UPLOADER_TOKEN_NEWV2);
          wrappers.userInfoUrl = userInfoUrl(constants);
        }
      }
      if (wantClient) {
        const client = locateHttpClient(exports);
        if (client) {
          wrappers.client = client;
        }
      }
      if (
        typeof wrappers.postNote === "function" &&
        isHttpClient(wrappers.client) &&
        wrappers.permitUrl
      ) {
        break;
      }
    }
    return wrappers;
  }

  function requireWrapper(name) {
    const runtimeRequire = captureWebpackRequire();
    const wrapper = runtimeRequire && discoverWrappers(runtimeRequire)[name];
    if (!wrapper) {
      throw new Error("xiaohongshu_creator_runtime_unavailable");
    }
    return wrapper;
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
      !creatorAppPath(current.pathname) ||
      current.username ||
      current.password ||
      current.port
    ) {
      throw new Error("invalid_request_context");
    }
    return current;
  }

  function webpackReady() {
    return Boolean(captureWebpackRequire());
  }

  function loginRecord(raw) {
    const status = isRecord(raw) && Number.isFinite(Number(raw.status))
      ? Number(raw.status)
      : 0;
    const body = isRecord(raw) && isRecord(raw.data) ? raw.data : raw;
    if (status === 401 || !isRecord(body)) {
      return false;
    }
    const nested = isRecord(body.data) ? body.data : null;
    const code = body.code !== undefined ? body.code : nested && nested.code;
    if (code === -100 || code === 401 || String(code) === "-100") {
      return false;
    }
    const message = String(body.msg || body.message || (nested && nested.msg) || "");
    if (/无登录信息|未登录|登录失效|登录过期/.test(message)) {
      return false;
    }
    return hasUserIdentity(nested || body, 0);
  }

  function hasUserIdentity(value, depth) {
    if (!isRecord(value) || depth > 4) {
      return false;
    }
    if (
      value.userId || value.user_id || value.redId || value.red_id ||
      value.userName || value.nickname || value.nickName
    ) {
      return true;
    }
    for (const name of ["userInfo", "user", "info", "account", "creator", "data", "result"]) {
      if (hasUserIdentity(value[name], depth + 1)) {
        return true;
      }
    }
    return false;
  }

  async function pageFetchJson(url, operation) {
    if (typeof fetch !== "function") {
      throw new Error("xiaohongshu_creator_runtime_unavailable");
    }
    const response = await fetch(url, {
      credentials: "include",
      signal: operation.signal
    });
    let data = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    return { status: response.status, data };
  }

  async function probeLoggedIn(operation) {
    const registry = transportRegistry();
    const cached = registry.login;
    // ponytail: 登录成功缓存 15 秒，批量上传少打用户信息；失败不缓存。
    if (cached && cached.value === true && Date.now() - cached.at < LOGIN_CACHE_MS) {
      return true;
    }
    const runtimeRequire = captureWebpackRequire();
    const apis = runtimeRequire ? discoverWrappers(runtimeRequire) : {};
    const urls = [];
    if (apis.userInfoUrl) {
      urls.push(apis.userInfoUrl);
    }
    for (const fallback of USER_INFO_FALLBACKS) {
      if (!urls.includes(fallback)) {
        urls.push(fallback);
      }
    }
    for (const url of urls) {
      try {
        const raw = isHttpClient(apis.client)
          ? await awaitTransport(apis.client.get(url), operation, LOGIN_PROBE_TIMEOUT_MS)
          : await awaitTransport(pageFetchJson(url, operation), operation, LOGIN_PROBE_TIMEOUT_MS);
        if (loginRecord(raw)) {
          registry.login = { value: true, at: Date.now() };
          return true;
        }
      } catch {
        // 这一条用户信息接口失败时再试下一条，不要把标题当成已登录。
      }
    }
    return false;
  }

  async function captureSession() {
    currentContext();
    const verification = verificationRequired();
    const operation = createOperation();
    const signedIn = !verification && await probeLoggedIn(operation);
    return {
      fingerprint: fingerprint(),
      logged_in: signedIn,
      request_ready: signedIn && webpackReady(),
      verification_required: verification
    };
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

  function validFileIds(value) {
    if (typeof value !== "string" || !value) {
      return false;
    }
    const items = value.split(",");
    if (items.length < 1 || items.length > MAX_IMAGES) {
      return false;
    }
    const seen = new Set();
    for (const item of items) {
      if (!FILE_ID.test(item) || seen.has(item)) {
        return false;
      }
      seen.add(item);
    }
    return true;
  }

  function validFileId(value) {
    return typeof value === "string" && FILE_ID.test(value);
  }

  function validTitleContent(values) {
    return (
      characterCount(values.title) >= 1 &&
      characterCount(values.title) <= MAX_TITLE_CHARS &&
      !/[\r\n\0]/.test(values.title) &&
      characterCount(values.content) >= 1 &&
      characterCount(values.content) <= MAX_CONTENT_CHARS &&
      !/[\r\0]/.test(values.content)
    );
  }

  function validUploadEntries(values) {
    const dataBase64 = values.dataBase64 || "";
    const names = Object.keys(values);
    return (
      names.length === 2 &&
      names.every((name) => ["mimeType", "dataBase64"].includes(name)) &&
      MIME_TYPES.has(values.mimeType) &&
      dataBase64.length >= 4 &&
      dataBase64.length <= MAX_UPLOAD_BASE64 &&
      BASE64.test(dataBase64)
    );
  }

  function validUploadVideoEntries(values) {
    const names = Object.keys(values);
    if (values.command === "begin") {
      return (
        names.length === 3 &&
        names.every((name) => ["command", "mimeType", "total_bytes"].includes(name)) &&
        VIDEO_MIME_TYPES.has(values.mimeType) &&
        TOTAL_BYTES.test(values.total_bytes) &&
        Number(values.total_bytes) <= MAX_VIDEO_BYTES
      );
    }
    if (values.command === "chunk") {
      const dataBase64 = values.dataBase64 || "";
      return (
        names.length === 4 &&
        names.every((name) =>
          ["command", "upload_id", "segment_index", "dataBase64"].includes(name)
        ) &&
        UPLOAD_ID.test(values.upload_id) &&
        SEGMENT_INDEX.test(values.segment_index) &&
        dataBase64.length >= 4 &&
        dataBase64.length <= MAX_UPLOAD_BASE64 &&
        BASE64.test(dataBase64)
      );
    }
    if (values.command === "finish") {
      return (
        names.length === 2 &&
        names.every((name) => ["command", "upload_id"].includes(name)) &&
        UPLOAD_ID.test(values.upload_id)
      );
    }
    return false;
  }

  function validPublishEntries(values) {
    const names = Object.keys(values);
    if (!validTitleContent(values)) {
      return false;
    }
    if (names.includes("file_ids")) {
      return (
        names.length === 3 &&
        names.every((name) => ["title", "content", "file_ids"].includes(name)) &&
        validFileIds(values.file_ids)
      );
    }
    return (
      names.length === 6 &&
      names.every((name) =>
        ["title", "content", "video_file_id", "cover_file_id", "width", "height"].includes(name)
      ) &&
      validFileId(values.video_file_id) &&
      validFileId(values.cover_file_id) &&
      DIMENSION.test(values.width) &&
      DIMENSION.test(values.height)
    );
  }

  function bytesFromBase64(dataBase64) {
    let binary;
    try {
      binary = atob(dataBase64);
    } catch {
      throw new Error("invalid_request");
    }
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return bytes;
  }

  function fileFromBase64(mimeType, dataBase64) {
    const bytes = bytesFromBase64(dataBase64);
    const name = mimeType === "image/png"
      ? "image.png"
      : mimeType === "image/webp"
        ? "image.webp"
        : "image.jpg";
    if (typeof File !== "function") {
      throw new Error("xiaohongshu_creator_runtime_unavailable");
    }
    return new File([bytes], name, { type: mimeType });
  }

  function videoUploadRegistry() {
    const key = Symbol.for("local_browser_session_bridge.xiaohongshu_creator.video_uploads.v1");
    const current = window[key];
    if (current && current.version === 1 && current.active instanceof Map) {
      return current;
    }
    const registry = { version: 1, active: new Map() };
    Object.defineProperty(window, key, { configurable: true, value: registry });
    return registry;
  }

  function newUploadId() {
    if (!globalThis.crypto || typeof globalThis.crypto.getRandomValues !== "function") {
      throw new Error("xiaohongshu_creator_runtime_unavailable");
    }
    const bytes = new Uint8Array(16);
    globalThis.crypto.getRandomValues(bytes);
    return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  }

  function spectrumFileId(value) {
    const text = String(value || "").trim();
    if (!text) {
      return "";
    }
    return text.startsWith("spectrum/") ? text : `spectrum/${text}`;
  }

  function rememberFile(fileId, meta) {
    const registry = transportRegistry();
    if (!isRecord(registry.files)) {
      registry.files = {};
    }
    registry.files[String(fileId || "")] = meta;
  }

  function rememberedFile(fileId) {
    const registry = transportRegistry();
    const files = isRecord(registry.files) ? registry.files : {};
    return files[String(fileId || "")] || files[spectrumFileId(fileId)] || null;
  }

  function snakeKey(name) {
    return name.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
  }

  function toSnake(value) {
    if (Array.isArray(value)) {
      return value.map((item) => toSnake(item));
    }
    if (!isRecord(value)) {
      return value;
    }
    const result = {};
    for (const key of Object.keys(value)) {
      result[snakeKey(key)] = toSnake(value[key]);
    }
    return result;
  }

  async function imageSize(file) {
    if (typeof createImageBitmap !== "function") {
      return { width: 0, height: 0 };
    }
    try {
      const bitmap = await createImageBitmap(file);
      const size = {
        width: Number(bitmap.width) || 0,
        height: Number(bitmap.height) || 0
      };
      if (typeof bitmap.close === "function") {
        bitmap.close();
      }
      return size;
    } catch {
      return { width: 0, height: 0 };
    }
  }

  function permitRequestUrl(base, scene) {
    let url;
    try {
      url = new URL(base, ORIGIN);
    } catch {
      throw new Error("xiaohongshu_creator_runtime_unavailable");
    }
    if (url.origin !== ORIGIN || url.pathname !== PERMIT_PATH) {
      throw new Error("xiaohongshu_creator_runtime_unavailable");
    }
    url.search = new URLSearchParams({
      biz_name: "spectrum",
      scene,
      file_count: "1",
      version: "1",
      source: "web"
    }).toString();
    return url.toString();
  }

  function readPermit(raw) {
    const envelope = isRecord(raw) && isRecord(raw.data) ? raw.data : raw;
    const body = isRecord(envelope) && isRecord(envelope.data) &&
      !Array.isArray(envelope.uploadTempPermits)
      ? envelope.data
      : envelope;
    const permit = isRecord(body) && Array.isArray(body.uploadTempPermits)
      ? body.uploadTempPermits[0]
      : null;
    if (!isRecord(permit)) {
      return null;
    }
    const fileId = Array.isArray(permit.fileIds) ? String(permit.fileIds[0] || "").trim() : "";
    const uploadAddr = String(permit.uploadAddr || "").trim();
    const token = String(permit.token || "");
    if (!FILE_ID.test(fileId) || !/^[A-Za-z0-9.-]+$/.test(uploadAddr) || !token) {
      return null;
    }
    return { fileId: fileId.replace(/^spectrum\//, ""), uploadAddr, token };
  }

  function readU32(bytes, offset) {
    if (offset < 0 || offset + 4 > bytes.length) {
      return 0;
    }
    return (
      (bytes[offset] << 24) |
      (bytes[offset + 1] << 16) |
      (bytes[offset + 2] << 8) |
      bytes[offset + 3]
    ) >>> 0;
  }

  function mp4Dimensions(bytes) {
    function walk(start, end, depth) {
      let offset = start;
      while (offset + 8 <= end) {
        let size = readU32(bytes, offset);
        const type = String.fromCharCode(
          bytes[offset + 4],
          bytes[offset + 5],
          bytes[offset + 6],
          bytes[offset + 7]
        );
        if (size < 8 || offset + size > bytes.length) {
          return null;
        }
        if (size === 0) {
          size = end - offset;
        }
        const content = offset + 8;
        if (type === "tkhd") {
          const version = bytes[content];
          const base = content + (version === 1 ? 84 : 72);
          return {
            width: readU32(bytes, base) >>> 16,
            height: readU32(bytes, base + 4) >>> 16
          };
        }
        if ((type === "moov" || type === "trak" || type === "mdia") && depth < 4) {
          const found = walk(content, offset + size, depth + 1);
          if (found && found.width > 0 && found.height > 0) {
            return found;
          }
        }
        offset += size;
      }
      return null;
    }
    return walk(0, bytes.length, 0);
  }

  async function uploadByPermit(file, operation, scene) {
    const runtimeRequire = captureWebpackRequire();
    const apis = runtimeRequire ? discoverWrappers(runtimeRequire) : {};
    if (!isHttpClient(apis.client) || !apis.permitUrl) {
      throw new Error("xiaohongshu_creator_runtime_unavailable");
    }
    const raw = await awaitTransport(
      apis.client.get(permitRequestUrl(apis.permitUrl, scene)),
      operation,
      PERMIT_TIMEOUT_MS
    );
    operation.throwIfCancelled();
    if (isRecord(raw)) {
      classifyResolved(raw);
    }
    const permit = readPermit(raw);
    if (!permit) {
      throw new Error("xiaohongshu_creator_invalid_response");
    }
    // ponytail: 签名客户端的 put 会给 COS 带上拦截器，浏览器直接报 Network Error。
    // 许可仍走 LV.get；文件 PUT 只用页面 fetch，不带 Cookie。
    const putUrl = `https://${permit.uploadAddr}/spectrum/${permit.fileId}`;
    const timeout = scene === "video" ? VIDEO_UPLOAD_TIMEOUT_MS : IMAGE_PUT_TIMEOUT_MS;
    const putResult = await awaitTransport(
      fetch(putUrl, {
        method: "PUT",
        body: file,
        credentials: "omit",
        headers: {
          "Content-Type": file.type || "application/octet-stream",
          "x-cos-security-token": permit.token
        }
      }),
      operation,
      timeout
    );
    operation.throwIfCancelled();
    const status = putResult && typeof putResult.status === "number" ? putResult.status : 0;
    if (status === 401) {
      throw new Error("xiaohongshu_creator_not_logged_in");
    }
    if (status === 403) {
      throw new Error("xiaohongshu_creator_forbidden");
    }
    if (status < 200 || status >= 300) {
      throw new Error("xiaohongshu_creator_request_failed");
    }
    return permit.fileId;
  }

  function commonNote(type, title, content) {
    return {
      type,
      title,
      noteId: "",
      desc: content,
      source: JSON.stringify({
        type: "web",
        ids: "",
        extraInfo: JSON.stringify({ subType: "official", systemId: "web" })
      }),
      businessBinds: JSON.stringify({
        version: 1,
        noteId: 0,
        notePostTiming: { postTime: "", postTimeTs: 0 },
        noteCollectionBind: { id: "", name: "", type: "" }
      }),
      ats: [],
      hashTag: [],
      privacyInfo: { opType: 1, type: 0, userIds: [] },
      goodsInfo: {},
      bizRelations: []
    };
  }

  function publishBody(title, content, fileIds) {
    return {
      common: {
        type: "normal",
        title,
        note_id: "",
        desc: content,
        source: JSON.stringify({
          type: "web",
          ids: "",
          extraInfo: JSON.stringify({ subType: "official", systemId: "web" })
        }),
        business_binds: JSON.stringify({
          version: 1,
          noteId: 0,
          notePostTiming: { postTime: "", postTimeTs: 0 },
          noteCollectionBind: { id: "", name: "", type: "" }
        }),
        ats: [],
        hash_tag: [],
        privacy_info: { op_type: 1, type: 0, user_ids: [] },
        goods_info: {},
        biz_relations: []
      },
      image_info: {
        images: fileIds.map((fileId) => {
          const meta = rememberedFile(fileId) || {};
          const width = Number(meta.width) || 0;
          const height = Number(meta.height) || 0;
          const mime = typeof meta.mime === "string" ? meta.mime : "image/jpeg";
          return {
            file_id: spectrumFileId(fileId),
            width,
            height,
            metadata: { source: -1 },
            extra_info_json: JSON.stringify({
              mimeType: mime,
              image_metadata: { bg_color: "", origin_size: 0 }
            })
          };
        })
      },
      video_info: null
    };
  }

  function publishVideoBody(title, content, videoFileId, coverFileId, width, height) {
    const fileId = spectrumFileId(videoFileId);
    const coverId = spectrumFileId(coverFileId);
    return {
      common: commonNote("video", title, content),
      imageInfo: null,
      videoInfo: {
        fileid: fileId,
        fileId,
        formatWidth: width,
        formatHeight: height,
        cover: {
          fileid: coverId,
          fileId: coverId,
          width,
          height,
          frame: {
            ts: 0,
            isUserSelect: false,
            isUpload: true
          }
        },
        timelines: [],
        chapters: [],
        entrance: "web"
      }
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
      codeIs("429", "300013") ||
      messageMatches(/rate.?limit|too many requests|请求频繁|操作频繁|频次异常/i)
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
      messageMatches(/not_logged_in|login required|请先登录|未登录|无登录/i) ||
      statusIs(401) ||
      codeIs("-100", "401") ||
      messageMatches(/unauthorized|登录失效|登录过期/i)
    ) {
      return "not_logged_in";
    }
    if (messageMatches(/runtime_unavailable/)) {
      return "runtime_unavailable";
    }
    if (messageMatches(/invalid_response/)) {
      return "invalid_response";
    }
    if (messageMatches(/invalid_request|invalid_request_context/)) {
      return "invalid_request";
    }
    if (
      messageMatches(/transport_timeout/) ||
      messageMatches(/\btimeout\b/i) ||
      signals.names.includes("TimeoutError")
    ) {
      return "timeout";
    }
    return "request_failed";
  }

  function classifyResolved(value) {
    const classified = errorCode(value);
    if (
      classified === "verification_required" ||
      classified === "rate_limited" ||
      classified === "forbidden" ||
      classified === "not_logged_in"
    ) {
      throw new Error(`xiaohongshu_creator_${classified}`);
    }
  }

  async function requireReady(operation) {
    operation.throwIfCancelled();
    currentContext();
    if (verificationRequired()) {
      throw new Error("xiaohongshu_creator_verification_required");
    }
    if (!webpackReady()) {
      throw new Error("xiaohongshu_creator_runtime_unavailable");
    }
    if (!await probeLoggedIn(operation)) {
      throw new Error("xiaohongshu_creator_not_logged_in");
    }
  }

  async function uploadImage(values, operation) {
    await requireReady(operation);
    const file = fileFromBase64(values.mimeType, values.dataBase64);
    const fileId = await uploadByPermit(file, operation, "image");
    const size = await imageSize(file);
    rememberFile(fileId, {
      width: size.width,
      height: size.height,
      mime: file.type || values.mimeType
    });
    return {
      file_id: fileId,
      width: size.width,
      height: size.height
    };
  }

  async function uploadVideo(values, operation) {
    if (values.command === "begin") {
      await requireReady(operation);
      const registry = videoUploadRegistry();
      registry.active.clear();
      const uploadId = newUploadId();
      registry.active.set(uploadId, {
        mimeType: values.mimeType,
        totalBytes: Number(values.total_bytes),
        chunks: [],
        received: 0
      });
      return { upload_id: uploadId };
    }
    if (values.command === "chunk") {
      const session = videoUploadRegistry().active.get(values.upload_id);
      if (!session) {
        throw new Error("invalid_request");
      }
      const segmentIndex = Number(values.segment_index);
      if (segmentIndex !== session.chunks.length) {
        throw new Error("invalid_request");
      }
      const bytes = bytesFromBase64(values.dataBase64);
      if (bytes.length < 1 || bytes.length > VIDEO_CHUNK_BYTES) {
        throw new Error("invalid_request");
      }
      if (session.received + bytes.length > session.totalBytes) {
        throw new Error("invalid_request");
      }
      session.chunks.push(bytes);
      session.received += bytes.length;
      return {
        upload_id: values.upload_id,
        segment_index: segmentIndex
      };
    }
    if (values.command !== "finish") {
      throw new Error("invalid_request");
    }
    await requireReady(operation);
    const registry = videoUploadRegistry();
    const session = registry.active.get(values.upload_id);
    if (!session || session.received !== session.totalBytes || session.chunks.length < 1) {
      throw new Error("invalid_request");
    }
    registry.active.delete(values.upload_id);
    if (typeof File !== "function") {
      throw new Error("xiaohongshu_creator_runtime_unavailable");
    }
    // File 直接拼接分片，避免再复制一份完整视频。
    const file = new File(
      session.chunks,
      session.mimeType === "video/quicktime" ? "video.mov" : "video.mp4",
      { type: session.mimeType }
    );
    const fileId = await uploadByPermit(file, operation, "video");
    let width = 0;
    let height = 0;
    try {
      const parsed = mp4Dimensions(new Uint8Array(await file.arrayBuffer()));
      width = parsed && parsed.width || 0;
      height = parsed && parsed.height || 0;
    } catch {
      width = 0;
      height = 0;
    }
    return { file_id: fileId, width, height };
  }

  async function publishNote(values, operation) {
    await requireReady(operation);
    const runtimeRequire = captureWebpackRequire();
    const apis = runtimeRequire ? discoverWrappers(runtimeRequire) : {};
    if (!isHttpClient(apis.client)) {
      throw new Error("xiaohongshu_creator_runtime_unavailable");
    }
    // 页面包装函数依赖 toSnakeCase，笔记管理页上那个依赖是空的。
    // 这里直接把蛇形正文交给已签名的 HTTP 客户端。
    const body = toSnake(values.file_ids
      ? publishBody(values.title, values.content, values.file_ids.split(","))
      : publishVideoBody(
        values.title,
        values.content,
        values.video_file_id,
        values.cover_file_id,
        Number(values.width),
        Number(values.height)
      ));
    const raw = await awaitTransport(apis.client.post(NOTE_URL, body), operation);
    operation.throwIfCancelled();
    let parsed = raw;
    if (typeof parsed === "string") {
      try {
        parsed = JSON.parse(parsed);
      } catch {
        throw new Error("xiaohongshu_creator_invalid_response");
      }
    }
    if (!isRecord(parsed)) {
      throw new Error("xiaohongshu_creator_invalid_response");
    }
    classifyResolved(parsed);
    if (parsed.success === false) {
      const error = new Error("xiaohongshu_creator_request_failed");
      error.response = parsed;
      throw error;
    }
    const cleaned = sanitize(parsed, 0, new WeakSet(), []);
    if (!isRecord(cleaned)) {
      throw new Error("xiaohongshu_creator_invalid_response");
    }
    return cleaned;
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
      const payload = await captureSession();
      return encodedSize(payload) <= MAX_RESULT_BYTES
        ? { ok: true, payload }
        : { ok: false, error: "response_too_large" };
    } catch (error) {
      return { ok: false, error: errorCode(error) };
    }
  }
  const values = entriesObject(input.entries);
  const validEntries = input.path === UPLOAD_IMAGE_PATH
    ? Boolean(values && validUploadEntries(values))
    : input.path === UPLOAD_VIDEO_PATH
      ? Boolean(values && validUploadVideoEntries(values))
      : input.path === PUBLISH_NOTE_PATH
        ? Boolean(values && validPublishEntries(values))
        : false;
  if (
    input.kind !== "request" ||
    typeof input.operation_id !== "string" ||
    !OPERATION_ID.test(input.operation_id) ||
    (input.method !== undefined && input.method !== "POST") ||
    !validEntries
  ) {
    return { ok: false, error: "invalid_request" };
  }
  const registered = registerOperation(input.operation_id);
  try {
    const payload = input.path === UPLOAD_IMAGE_PATH
      ? await uploadImage(values, registered.operation)
      : input.path === UPLOAD_VIDEO_PATH
        ? await uploadVideo(values, registered.operation)
        : await publishNote(values, registered.operation);
    return encodedSize(payload) <= MAX_RESULT_BYTES
      ? { ok: true, payload }
      : { ok: false, error: "response_too_large" };
  } catch (error) {
    return { ok: false, error: errorCode(error) };
  } finally {
    registered.release();
  }
}
