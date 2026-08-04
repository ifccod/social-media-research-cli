// chrome.scripting 会将此函数序列化到 Bilibili MAIN world。认证请求始终
// 在用户当前 Chrome 配置中执行。
export async function invokeBilibiliPageRuntime(input) {
  const API_ORIGIN = "https://api.bilibili.com";
  const UP_STAT_PATH = "/bridge/v1/bilibili/up-stat";
  const MAX_RESULT_BYTES = 1024 * 1024;
  const OPERATION_ID = /^[A-Za-z0-9_-]{1,96}$/;
  const MID = /^[1-9][0-9]{0,19}$/;

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function response(value) {
    try {
      if (
        new TextEncoder().encode(JSON.stringify(value)).byteLength <=
        MAX_RESULT_BYTES
      ) {
        return value;
      }
    } catch {
      return { ok: false, error: "invalid_response" };
    }
    return { ok: false, error: "response_too_large" };
  }

  function fingerprint() {
    const connection = navigator.connection ||
      navigator.mozConnection ||
      navigator.webkitConnection ||
      {};
    const uaData = navigator.userAgentData;
    return {
      user_agent: String(navigator.userAgent || ""),
      ua_ch: uaData ? {
        brands: Array.isArray(uaData.brands)
          ? uaData.brands.slice(0, 10).map((item) => ({
            brand: String(item.brand || ""),
            version: String(item.version || "")
          }))
          : [],
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
      timezone: String(Intl.DateTimeFormat().resolvedOptions().timeZone || ""),
      connection: {
        effective_type: String(connection.effectiveType || ""),
        round_trip_time: Number.isFinite(connection.rtt) ? connection.rtt : null,
        downlink: Number.isFinite(connection.downlink) ? connection.downlink : null,
        save_data: Boolean(connection.saveData)
      }
    };
  }

  function visible(element) {
    if (!element || typeof element.getBoundingClientRect !== "function") {
      return false;
    }
    const rect = element.getBoundingClientRect();
    return Boolean(rect && rect.width > 0 && rect.height > 0);
  }

  function verificationRequired() {
    return [
      ...document.querySelectorAll(
        'iframe[src*="captcha"], iframe[src*="geetest"], ' +
        '[class*="geetest_panel"], [class*="captcha"]'
      )
    ].some(visible);
  }

  function validEntries(path, entries) {
    return path === UP_STAT_PATH &&
      Array.isArray(entries) &&
      entries.length === 1 &&
      Array.isArray(entries[0]) &&
      entries[0].length === 2 &&
      entries[0][0] === "mid" &&
      typeof entries[0][1] === "string" &&
      MID.test(entries[0][1]);
  }

  function registry() {
    const key = Symbol.for("local_browser_session_bridge.bilibili.operations.v1");
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
    previous?.abort?.();
    const controller = new AbortController();
    active.set(operationID, controller);
    return {
      signal: controller.signal,
      finish() {
        if (active.get(operationID) === controller) {
          active.delete(operationID);
        }
      }
    };
  }

  function cancelOperation(operationID) {
    const controller = registry().active.get(operationID);
    if (!controller) return false;
    controller.abort();
    return true;
  }

  function upstreamError(payload, status) {
    const code = Number(isRecord(payload) ? payload.code : NaN);
    if (status === 401 || code === -101) return "bilibili_not_logged_in";
    if (status === 429 || code === -509) return "bilibili_rate_limited";
    if (status === 412 || code === -352 || code === -412) {
      return "bilibili_verification_required";
    }
    if (!Number.isFinite(code) || code !== 0) return "bilibili_request_failed";
    return "";
  }

  async function fetchJSON(path, signal) {
    let result;
    try {
      result = await fetch(`${API_ORIGIN}${path}`, {
        method: "GET",
        credentials: "include",
        redirect: "follow",
        headers: { Accept: "application/json, text/plain, */*" },
        signal
      });
    } catch (error) {
      if (signal?.aborted) throw new Error("bilibili_request_cancelled");
      throw error;
    }
    if (result.url && !String(result.url).startsWith(`${API_ORIGIN}/`)) {
      throw new Error("bilibili_invalid_response");
    }
    const length = Number(result.headers?.get?.("content-length") || 0);
    if (Number.isFinite(length) && length > MAX_RESULT_BYTES) {
      throw new Error("bilibili_response_too_large");
    }
    let payload;
    try {
      payload = await result.json();
    } catch {
      throw new Error("bilibili_invalid_response");
    }
    const upstream = upstreamError(payload, result.status);
    if (upstream) throw new Error(upstream);
    if (!result.ok || !isRecord(payload)) {
      throw new Error("bilibili_invalid_response");
    }
    return payload;
  }

  async function sessionPayload() {
    if (verificationRequired()) {
      return {
        fingerprint: fingerprint(),
        logged_in: false,
        verification_required: true
      };
    }
    const controller = new AbortController();
    try {
      const payload = await fetchJSON("/x/web-interface/nav", controller.signal);
      const data = isRecord(payload.data) ? payload.data : {};
      return {
        fingerprint: fingerprint(),
        logged_in: data.isLogin === true,
        verification_required: false
      };
    } catch (error) {
      if (String(error?.message || "").includes("not_logged_in")) {
        return {
          fingerprint: fingerprint(),
          logged_in: false,
          verification_required: false
        };
      }
      throw error;
    }
  }

  async function upStat(entries, signal) {
    if (verificationRequired()) {
      throw new Error("bilibili_verification_required");
    }
    const mid = entries[0][1];
    const payload = await fetchJSON(
      `/x/space/upstat?mid=${encodeURIComponent(mid)}`,
      signal
    );
    const data = isRecord(payload.data) ? payload.data : null;
    const archive = isRecord(data?.archive) ? data.archive : null;
    if (
      !archive ||
      !Number.isSafeInteger(archive.view) ||
      archive.view < 0 ||
      !Number.isSafeInteger(data.likes) ||
      data.likes < 0
    ) {
      // 匿名接口当前返回 code=0 和空 data 对象。
      throw new Error("bilibili_not_logged_in");
    }
    return {
      kind: "user_up_stat",
      source: "bilibili_web_browser",
      transport: "browser_web",
      endpoint: "/x/space/upstat",
      user_id: mid,
      archive: { view: archive.view },
      likes: data.likes
    };
  }

  function errorCode(error) {
    const message = String(error?.message || "");
    if (message.includes("verification_required")) return "verification_required";
    if (message.includes("not_logged_in")) return "not_logged_in";
    if (message.includes("rate_limited")) return "rate_limited";
    if (message.includes("response_too_large")) return "response_too_large";
    if (message.includes("cancelled")) return "request_failed";
    if (message.includes("invalid_response")) return "invalid_response";
    if (message.includes("request_failed")) return "request_failed";
    return "runtime_unavailable";
  }

  if (!isRecord(input)) return { ok: false, error: "invalid_request" };
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
    try {
      return response({ ok: true, payload: await sessionPayload() });
    } catch (error) {
      return { ok: false, error: errorCode(error) };
    }
  }
  if (
    input.kind !== "request" ||
    typeof input.operation_id !== "string" ||
    !OPERATION_ID.test(input.operation_id) ||
    !validEntries(input.path, input.entries) ||
    !Number.isInteger(input.request_interval_ms) ||
    input.request_interval_ms < 0 ||
    input.request_interval_ms > 30000
  ) {
    return { ok: false, error: "invalid_request" };
  }
  const operation = registerOperation(input.operation_id);
  try {
    return response({
      ok: true,
      payload: await upStat(input.entries, operation.signal)
    });
  } catch (error) {
    return { ok: false, error: errorCode(error) };
  } finally {
    operation.finish();
  }
}
