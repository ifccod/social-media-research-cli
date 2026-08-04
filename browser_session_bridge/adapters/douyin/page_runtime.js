// chrome.scripting 会将此函数序列化到页面的 MAIN world。依赖全部保留在
// 函数内部，避免捕获扩展状态。
export async function invokeDouyinPageRuntime(input) {
  const MAX_RESULT_BYTES = 6 * 1024 * 1024;
  const PARAMETER_NAME = /^[A-Za-z][A-Za-z0-9_]{0,79}$/;
  const OPERATION_ID = /^[A-Za-z0-9_-]{1,96}$/;
  const OPERATION_CANCEL_TTL_MS = 60 * 1000;
  const MAX_CANCELLED_OPERATIONS = 1024;
  const TRANSPORT_CANCEL_GRACE_MS = 1000;
  const TRANSPORT_CANCEL_POLL_MS = 10;
  const SENSITIVE_NAME = /(?:cookie|authorization|token|ms[_-]?token|a[_-]?bogus|x[_-]?bogus|signature|webid|uifid|session|passport|csrf|sid(?:_|$)|odin)/i;
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

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function validEntries(path, value) {
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

  function redactUrl(value) {
    try {
      const parsed = new URL(value);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
        return value;
      }
      for (const [name] of parsed.searchParams) {
        if (SENSITIVE_NAME.test(name)) {
          return `${parsed.protocol}//${parsed.host}${parsed.pathname}`;
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
      if (value.length > 32768 || SENSITIVE_NAME.test(value.split("=")[0] || "")) {
        return undefined;
      }
      return redactUrl(value);
    }
    if (typeof value === "number" || typeof value === "boolean") {
      return value;
    }
    if (Array.isArray(value)) {
      return value.slice(0, 10000).map((item) => sanitize(item, depth + 1, seen)).filter(
        (item) => item !== undefined
      );
    }
    if (!isRecord(value) || seen.has(value)) {
      return undefined;
    }
    seen.add(value);
    const output = {};
    for (const key of Object.keys(value).slice(0, 1000)) {
      if (SENSITIVE_NAME.test(key)) {
        continue;
      }
      const item = sanitize(value[key], depth + 1, seen);
      if (item !== undefined) {
        output[key] = item;
      }
    }
    seen.delete(value);
    return output;
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

  function operationRegistry() {
    const key = Symbol.for("local_browser_session_bridge.douyin.operations.v1");
    const current = window[key];
    if (
      current &&
      current.version === 1 &&
      current.active instanceof Map &&
      current.cancelled instanceof Map
    ) {
      return current;
    }
    const registry = {
      version: 1,
      active: new Map(),
      cancelled: new Map()
    };
    Object.defineProperty(window, key, {
      configurable: true,
      value: registry
    });
    return registry;
  }

  function pruneCancelledOperations(registry, now = Date.now()) {
    for (const [operationID, expiresAt] of registry.cancelled) {
      if (expiresAt <= now) {
        registry.cancelled.delete(operationID);
      }
    }
    while (registry.cancelled.size > MAX_CANCELLED_OPERATIONS) {
      registry.cancelled.delete(registry.cancelled.keys().next().value);
    }
  }

  function createOperation() {
    let cancelled = false;
    let cancelReason = "rpc_cancelled";
    let cancelCompletion = null;
    const listeners = new Set();
    return {
      get cancelled() {
        return cancelled;
      },
      cancel(reason = "rpc_cancelled") {
        if (cancelCompletion) {
          return cancelCompletion;
        }
        cancelled = true;
        cancelReason = String(reason || "rpc_cancelled");
        const tasks = [...listeners].map((listener) => (
          Promise.resolve().then(() => listener(cancelReason))
        ));
        listeners.clear();
        cancelCompletion = Promise.allSettled(tasks).then(() => undefined);
        return cancelCompletion;
      },
      onCancel(listener) {
        if (cancelled) {
          void Promise.resolve().then(() => listener(cancelReason)).catch(() => undefined);
          return () => {};
        }
        listeners.add(listener);
        return () => {
          listeners.delete(listener);
        };
      },
      throwIfCancelled() {
        if (cancelled) {
          throw new Error("douyin_request_cancelled");
        }
      }
    };
  }

  async function registerOperation(operationID) {
    const registry = operationRegistry();
    const now = Date.now();
    pruneCancelledOperations(registry, now);
    const previous = registry.active.get(operationID);
    if (previous && typeof previous.cancel === "function") {
      await previous.cancel("superseded");
    }
    const operation = createOperation();
    registry.active.set(operationID, operation);
    const expiresAt = registry.cancelled.get(operationID);
    if (typeof expiresAt === "number" && expiresAt > now) {
      registry.cancelled.delete(operationID);
      await operation.cancel("rpc_cancelled");
    }
    return {
      operation,
      finish() {
        if (registry.active.get(operationID) === operation) {
          registry.active.delete(operationID);
        }
      }
    };
  }

  async function cancelOperation(operationID) {
    const registry = operationRegistry();
    const now = Date.now();
    pruneCancelledOperations(registry, now);
    const operation = registry.active.get(operationID);
    if (operation && typeof operation.cancel === "function") {
      await operation.cancel("rpc_cancelled");
      return true;
    }
    registry.cancelled.set(operationID, now + OPERATION_CANCEL_TTL_MS);
    pruneCancelledOperations(registry, now);
    return false;
  }

  function errorCode(error) {
    const message = String(error && error.message ? error.message : "");
    if (message.includes("douyin_verification_required")) {
      return "verification_required";
    }
    if (message.includes("douyin_runtime") || message.includes("douyin_require")) {
      return "runtime_unavailable";
    }
    if (message.includes("douyin_transport")) {
      return "transport_modules_changed";
    }
    if (message.includes("invalid_request")) {
      return "invalid_request";
    }
    return "request_failed";
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
    return (
      style &&
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      style.visibility !== "collapse" &&
      style.opacity !== "0"
    );
  }

  function verificationRequired() {
    const pageDocument = window.document;
    if (!pageDocument || typeof pageDocument.getElementById !== "function") {
      return false;
    }
    const container = pageDocument.getElementById("captcha_container");
    if (!visibleElement(container) || typeof container.querySelectorAll !== "function") {
      return false;
    }
    for (const frame of container.querySelectorAll("iframe")) {
      if (visibleElement(frame)) {
        return true;
      }
    }
    return false;
  }

  async function callTransport(path, entries, operation) {
    operation.throwIfCancelled();
    if (verificationRequired()) {
      throw new Error("douyin_verification_required");
    }
    const webRuntime = {
      globalName: "webpackChunkdouyin_web",
      commonModuleID: 30995,
      transportModuleID: 911429
    };
    const searchRuntime = {
      globalName: "webpackChunkdouyin_search",
      commonModuleID: 437154,
      transportModuleID: 706726
    };
    const candidates = path === "/aweme/v1/web/search/item/"
      ? [searchRuntime, webRuntime]
      : [webRuntime, searchRuntime];
    let selectedRuntime = null;
    let sawRuntimeChunks = false;
    operation.throwIfCancelled();
    for (const candidate of candidates) {
      const chunks = window[candidate.globalName];
      if (!Array.isArray(chunks)) {
        continue;
      }
      sawRuntimeChunks = true;
      let runtimeRequire;
      const chunkId = `douyin_reverse_${Date.now()}_${Math.random().toString(16).slice(2)}`;
      chunks.push([[chunkId], {}, (require) => {
        runtimeRequire = require;
      }]);
      if (typeof runtimeRequire !== "function") {
        continue;
      }
      try {
        const commonModule = runtimeRequire(candidate.commonModuleID);
        const transportModule = runtimeRequire(candidate.transportModuleID);
        const common = commonModule && commonModule.COMMON_SEARCH_PARAMS;
        const request = transportModule && transportModule.U2;
        if (isRecord(common) && typeof request === "function") {
          selectedRuntime = { common, request };
          break;
        }
      } catch {
        // 页面可能暴露多个 chunk 全局对象，但只有一个运行时持有这些模块。
      }
    }
    operation.throwIfCancelled();
    if (!selectedRuntime) {
      throw new Error(
        sawRuntimeChunks
          ? "douyin_transport_modules_changed"
          : "douyin_runtime_unavailable"
      );
    }
    const { common, request } = selectedRuntime;

    const parameters = { ...common };
    for (const [name, value] of entries) {
      parameters[name] = value;
    }
    const cancelRef = { current: null };
    let transportCancelled = false;
    let transportSettled = false;
    let resolveTransportSettled;
    const transportSettledSignal = new Promise((resolve) => {
      resolveTransportSettled = resolve;
    });
    let transportCancellation = null;
    let verificationTimer = null;
    let stopVerificationWatch = false;
    let rejectVerificationWatch = null;
    let verificationCancellation = null;
    function markTransportSettled() {
      if (!transportSettled) {
        transportSettled = true;
        resolveTransportSettled();
      }
    }
    function cancelTransport(reason) {
      if (transportCancelled || typeof cancelRef.current !== "function") {
        return false;
      }
      transportCancelled = true;
      try {
        cancelRef.current(String(reason || "rpc_cancelled"));
      } catch {
        // 取消请求与页面传输竞争时，传输可能已结束。
      }
      return true;
    }
    function waitForTransportProgress(milliseconds) {
      if (transportSettled) {
        return Promise.resolve();
      }
      return new Promise((resolve) => {
        let settled = false;
        const timer = setTimeout(finish, milliseconds);
        function finish() {
          if (settled) {
            return;
          }
          settled = true;
          clearTimeout(timer);
          resolve();
        }
        void transportSettledSignal.then(finish);
      });
    }
    function ensureTransportCancelled(reason) {
      if (transportCancellation) {
        return transportCancellation;
      }
      transportCancellation = (async () => {
        const deadline = Date.now() + TRANSPORT_CANCEL_GRACE_MS;
        while (
          !transportSettled &&
          typeof cancelRef.current !== "function" &&
          Date.now() < deadline
        ) {
          await waitForTransportProgress(TRANSPORT_CANCEL_POLL_MS);
        }
        if (!transportSettled) {
          cancelTransport(reason);
        }
      })();
      return transportCancellation;
    }
    const verificationWatch = new Promise((resolve, reject) => {
      rejectVerificationWatch = reject;
      function check() {
        if (stopVerificationWatch) {
          resolve(undefined);
          return;
        }
        if (verificationRequired()) {
          verificationCancellation = ensureTransportCancelled("verification_required");
          reject(new Error("douyin_verification_required"));
          return;
        }
        verificationTimer = setTimeout(check, 100);
      }
      check();
    });
    const removeCancelListener = operation.onCancel((reason) => {
      const cancellation = ensureTransportCancelled(reason);
      if (rejectVerificationWatch) {
        rejectVerificationWatch(new Error("douyin_request_cancelled"));
      }
      return cancellation;
    });
    let raw;
    try {
      operation.throwIfCancelled();
      const transport = Promise.resolve(
        request(path, parameters, {}, undefined, null, undefined, cancelRef)
      );
      void transport.then(markTransportSettled, markTransportSettled);
      raw = await Promise.race([
        transport,
        verificationWatch
      ]);
    } catch (error) {
      if (
        String(error && error.message ? error.message : "").includes(
          "douyin_verification_required"
        )
      ) {
        await (
          verificationCancellation ||
          ensureTransportCancelled("verification_required")
        );
      }
      throw error;
    } finally {
      stopVerificationWatch = true;
      removeCancelListener();
      if (verificationTimer !== null) {
        clearTimeout(verificationTimer);
      }
    }
    const payload = isRecord(raw) && isRecord(raw.data) ? raw.data : raw;
    if (!isRecord(payload)) {
      throw new Error("douyin_invalid_response");
    }
    return sanitize(payload);
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

  function explicitLoginState(value) {
    if (!isRecord(value)) {
      return null;
    }
    for (const name of ["isLogin", "isLoggedIn", "loginStatus", "loggedIn", "is_login"]) {
      const state = loginFlag(value[name]);
      if (state !== null) {
        return state;
      }
    }
    return null;
  }

  function hasAccountIdentity(value) {
    if (!isRecord(value)) {
      return false;
    }
    for (
      const name of [
        "uid", "user_id", "id", "id_str", "sec_uid", "secUid",
        "sec_user_id", "userID", "secUserID"
      ]
    ) {
      const id = value[name];
      if (
        (typeof id === "string" && id.length > 0 && id !== "0") ||
        (typeof id === "number" && Number.isSafeInteger(id) && id > 0)
      ) {
        return true;
      }
    }
    return false;
  }

  function storeLoginState(root) {
    const store = isRecord(root) && isRecord(root.userStore) ? root.userStore : null;
    if (!store) {
      return null;
    }

    // 当前抖音页面将实时状态保存在 userInfo，账户对象保存在
    // userInfo.info。优先使用明确状态，避免依赖缓存 ID。
    const userInfo = isRecord(store.userInfo) ? store.userInfo : null;
    const userInfoState = explicitLoginState(userInfo);
    if (userInfoState !== null) {
      return userInfoState;
    }
    const storeState = explicitLoginState(store);
    if (storeState !== null) {
      return storeState;
    }

    const users = [
      userInfo && userInfo.info,
      userInfo && userInfo.user,
      userInfo,
      store.user,
      store.currentUser,
      store.profile
    ];
    return users.some(hasAccountIdentity) ? true : null;
  }

  function renderDataLoginState() {
    const pageDocument = window.document;
    if (!pageDocument || typeof pageDocument.querySelector !== "function") {
      return null;
    }
    const element = pageDocument.querySelector('script#RENDER_DATA[type="application/json"]');
    const source = element && typeof element.textContent === "string"
      ? element.textContent
      : "";
    if (source.length === 0 || source.length > 4 * 1024 * 1024) {
      return null;
    }
    try {
      const decoded = decodeURIComponent(source);
      const data = JSON.parse(decoded);
      const user = isRecord(data) && isRecord(data.app) && isRecord(data.app.user)
        ? data.app.user
        : null;
      return user ? loginFlag(user.isLogin) : null;
    } catch {
      return null;
    }
  }

  function hasSignedInAvatar() {
    const pageDocument = window.document;
    if (!pageDocument || typeof pageDocument.querySelectorAll !== "function") {
      return false;
    }
    const images = pageDocument.querySelectorAll(
      'a[href] [data-e2e="live-avatar"][role="listitem"] img'
    );
    for (const image of images) {
      const link = image && typeof image.closest === "function" ? image.closest("a[href]") : null;
      if (!link || typeof link.getAttribute !== "function") {
        continue;
      }
      try {
        const currentOrigin = window.location && window.location.origin;
        const href = link.getAttribute("href");
        const parsed = new URL(href, currentOrigin || "https://www.douyin.com");
        if (
          parsed.origin === (currentOrigin || "https://www.douyin.com") &&
          parsed.pathname === "/user/self"
        ) {
          return true;
        }
      } catch {
        // 忽略格式异常的 DOM 链接，继续检查数量受限的候选项。
      }
    }
    return false;
  }

  function loggedIn() {
    const renderedState = renderDataLoginState();
    if (renderedState !== null) {
      return renderedState;
    }
    const liveState = storeLoginState(window.__STORE__);
    if (liveState !== null) {
      return liveState;
    }
    const initialState = storeLoginState(window.INITIAL_STATE);
    if (initialState !== null) {
      return initialState;
    }
    return hasSignedInAvatar();
  }

  function captureSession() {
    const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection || {};
    const uaData = navigator.userAgentData;
    const brands = uaData && Array.isArray(uaData.brands)
      ? uaData.brands.slice(0, 10).map((item) => ({
        brand: String(item.brand || ""),
        version: String(item.version || "")
      }))
      : [];
    return {
      fingerprint: {
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
      },
      logged_in: loggedIn(),
      verification_required: verificationRequired()
    };
  }

  if (!isRecord(input)) {
    return { ok: false, error: "invalid_request" };
  }
  if (input.kind === "cancel") {
    if (typeof input.operation_id !== "string" || !OPERATION_ID.test(input.operation_id)) {
      return { ok: false, error: "invalid_request" };
    }
    return response({
      ok: true,
      payload: { cancelled: await cancelOperation(input.operation_id) }
    });
  }
  if (input.kind === "session") {
    return response({ ok: true, payload: captureSession() });
  }
  if (
    input.kind !== "request" ||
    typeof input.operation_id !== "string" ||
    !OPERATION_ID.test(input.operation_id) ||
    typeof input.path !== "string" ||
    !Object.prototype.hasOwnProperty.call(ALLOWED_PARAMETERS, input.path) ||
    !validEntries(input.path, input.entries)
  ) {
    return { ok: false, error: "invalid_request" };
  }
  const registered = await registerOperation(input.operation_id);
  try {
    return response({
      ok: true,
      payload: await callTransport(input.path, input.entries, registered.operation)
    });
  } catch (error) {
    return { ok: false, error: errorCode(error) };
  } finally {
    registered.finish();
  }
}
