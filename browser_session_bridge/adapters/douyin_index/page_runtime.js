// chrome.scripting 会将此函数序列化到页面的 MAIN world。依赖全部保留在
// 函数内部，避免创作者中心凭据离开页面。
export async function invokeDouyinIndexPageRuntime(input) {
  const MAX_RESULT_BYTES = 6 * 1024 * 1024;
  const OPERATION_ID = /^[A-Za-z0-9_-]{1,96}$/;
  const PATH = "/api/v2/index/get_multi_keyword_hot_trend";
  const MODULE_ID = 42487;
  const TRANSPORT_TIMEOUT_MS = 25000;
  const SENSITIVE_NAME =
    /(?:cookie|authorization|token|signature|session|passport|csrf|sid(?:_|$)|odin|encrypt)/i;

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function encodedSize(value) {
    return new TextEncoder().encode(JSON.stringify(value)).byteLength;
  }

  function sanitize(value, depth, seen) {
    if (depth > 14) {
      return null;
    }
    if (
      value === null ||
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      return value;
    }
    if (Array.isArray(value)) {
      return value
        .slice(0, 20000)
        .map((item) => sanitize(item, depth + 1, seen));
    }
    if (!isRecord(value) || seen.has(value)) {
      return null;
    }
    seen.add(value);
    const result = {};
    for (const [name, item] of Object.entries(value).slice(0, 20000)) {
      result[name] = SENSITIVE_NAME.test(name)
        ? "[redacted]"
        : sanitize(item, depth + 1, seen);
    }
    seen.delete(value);
    return result;
  }

  function response(value) {
    let size;
    try {
      size = encodedSize(value);
    } catch {
      return { ok: false, error: "invalid_response" };
    }
    return size <= MAX_RESULT_BYTES
      ? value
      : { ok: false, error: "response_too_large" };
  }

  function verificationRequired() {
    for (const selector of [
      "#captcha_container",
      ".red-captcha",
      "[class*='captcha']",
      "[id*='captcha']",
      "iframe[src*='captcha']",
      "iframe[src*='verify']"
    ]) {
      for (const candidate of Array.from(
        document.querySelectorAll(selector)
      ).slice(0, 20)) {
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

  function hasIdentity(value, depth = 0, seen = new Set()) {
    if (!isRecord(value) || depth > 4 || seen.has(value)) {
      return false;
    }
    seen.add(value);
    for (const name of [
      "uid",
      "user_id",
      "userId",
      "user_id_str",
      "sec_uid",
      "secUid",
      "unique_id"
    ]) {
      const item = value[name];
      if (
        (typeof item === "string" && item.trim().length > 0) ||
        (typeof item === "number" && Number.isFinite(item) && item > 0)
      ) {
        return true;
      }
    }
    return Object.values(value)
      .slice(0, 30)
      .some((item) => hasIdentity(item, depth + 1, seen));
  }

  function garfishInstance() {
    const candidates = [window.Gar, window.Garfish];
    return candidates.find((item) => isRecord(item)) || null;
  }

  function appGlobals() {
    const values = [window];
    const garfish = garfishInstance();
    if (!garfish) {
      return values;
    }
    const apps = [
      ...(Array.isArray(garfish.activeApps) ? garfish.activeApps : []),
      ...(
        isRecord(garfish.cacheApps)
          ? Object.values(garfish.cacheApps)
          : []
      )
    ];
    for (const app of apps.slice(0, 50)) {
      const globalObject =
        (isRecord(app) && app.global) ||
        (isRecord(app) && isRecord(app.vmSandbox) && app.vmSandbox.global);
      if (globalObject && !values.includes(globalObject)) {
        values.push(globalObject);
      }
    }
    return values;
  }

  function chunkArray(globalObject) {
    for (const name of [
      "webpackChunkcount_fe",
      "__LOADABLE_LOADED_CHUNKS__"
    ]) {
      let value;
      try {
        value = globalObject && globalObject[name];
      } catch {
        value = null;
      }
      if (Array.isArray(value) && typeof value.push === "function") {
        return value;
      }
    }
    return null;
  }

  function countRuntimeGlobal() {
    for (const globalObject of appGlobals()) {
      if (chunkArray(globalObject)) {
        return globalObject;
      }
    }
    return null;
  }

  function captureWebpackRequire(globalObject) {
    const chunks = chunkArray(globalObject);
    if (!chunks) {
      return null;
    }
    let runtimeRequire = null;
    const chunkID =
      `local_browser_bridge_${Date.now()}_${Math.floor(Math.random() * 1000000)}`;
    try {
      chunks.push([
        [chunkID],
        {},
        (candidate) => {
          runtimeRequire = candidate;
        }
      ]);
    } catch {
      return null;
    }
    return typeof runtimeRequire === "function" ? runtimeRequire : null;
  }

  function loggedIn() {
    const garfish = garfishInstance();
    if (
      garfish &&
      isRecord(garfish.externals) &&
      hasIdentity(garfish.externals["master-context"])
    ) {
      return true;
    }
    try {
      const names = String(document.cookie || "")
        .split(";")
        .map((part) => part.split("=", 1)[0].trim().toLowerCase());
      return names.some((name) =>
        ["sessionid", "sessionid_ss", "sid_guard"].includes(name)
      );
    } catch {
      return false;
    }
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
        round_trip_time: Number.isFinite(connection.rtt) ? connection.rtt : null,
        downlink: Number.isFinite(connection.downlink)
          ? connection.downlink
          : null,
        save_data: Boolean(connection.saveData)
      }
    };
  }

  function parseEntries(entries) {
    if (!Array.isArray(entries)) {
      return null;
    }
    const values = {};
    for (const entry of entries) {
      if (
        !Array.isArray(entry) ||
        entry.length !== 2 ||
        typeof entry[0] !== "string" ||
        typeof entry[1] !== "string" ||
        Object.prototype.hasOwnProperty.call(values, entry[0])
      ) {
        return null;
      }
      values[entry[0]] = entry[1];
    }
    try {
      const payload = {
        keyword_list: JSON.parse(values.keyword_list),
        start_date: values.start_date,
        end_date: values.end_date,
        app_name: values.app_name
      };
      if (Object.prototype.hasOwnProperty.call(values, "region")) {
        payload.region = JSON.parse(values.region);
      }
      return payload;
    } catch {
      return null;
    }
  }

  function errorCode(error) {
    if (verificationRequired()) {
      return "verification_required";
    }
    const message = String(
      (error && (error.message || error.msg || error.statusText)) || error || ""
    );
    if (/401|403|unauthorized|not[_ ]logged[_ ]in|请先登录|未登录/i.test(message)) {
      return "not_logged_in";
    }
    if (/429|rate.?limit|too many|频繁|限流/i.test(message)) {
      return "rate_limited";
    }
    if (/timeout/i.test(message)) {
      return "timeout";
    }
    if (/transport_modules_changed/i.test(message)) {
      return "transport_modules_changed";
    }
    return "request_failed";
  }

  async function requestKeywordTrend(payload) {
    if (verificationRequired()) {
      throw new Error("verification_required");
    }
    if (!loggedIn()) {
      throw new Error("not_logged_in");
    }
    const globalObject = countRuntimeGlobal();
    const runtimeRequire = captureWebpackRequire(globalObject);
    if (
      !runtimeRequire ||
      !runtimeRequire.m ||
      !runtimeRequire.m[MODULE_ID]
    ) {
      throw new Error("transport_modules_changed");
    }
    const module = runtimeRequire(MODULE_ID);
    const operation =
      module &&
      module.Ul &&
      module.Ul.get_multi_keyword_hot_trend;
    if (typeof operation !== "function") {
      throw new Error("transport_modules_changed");
    }
    let timer = null;
    try {
      const timeout = new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new Error("timeout")),
          TRANSPORT_TIMEOUT_MS
        );
      });
      return await Promise.race([Promise.resolve(operation(payload)), timeout]);
    } finally {
      if (timer !== null) {
        clearTimeout(timer);
      }
    }
  }

  if (!isRecord(input)) {
    return { ok: false, error: "invalid_request" };
  }
  if (input.kind === "session") {
    const runtimeReady = Boolean(countRuntimeGlobal());
    const signedIn = loggedIn();
    return response({
      ok: true,
      payload: {
        fingerprint: fingerprint(),
        logged_in: signedIn,
        request_ready: signedIn && runtimeReady,
        verification_required: verificationRequired()
      }
    });
  }
  if (
    input.kind !== "request" ||
    typeof input.operation_id !== "string" ||
    !OPERATION_ID.test(input.operation_id) ||
    input.path !== PATH
  ) {
    return { ok: false, error: "invalid_request" };
  }
  const payload = parseEntries(input.entries);
  if (!payload) {
    return { ok: false, error: "invalid_request" };
  }
  try {
    const result = await requestKeywordTrend(payload);
    if (!isRecord(result)) {
      return { ok: false, error: "invalid_response" };
    }
    return response({
      ok: true,
      payload: sanitize(result, 0, new Set())
    });
  } catch (error) {
    return { ok: false, error: errorCode(error) };
  }
}
