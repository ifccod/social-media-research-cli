// chrome.scripting 会将此函数序列化到页面的 MAIN world。依赖全部保留在
// 函数内部，避免浏览器凭据越过扩展边界。
export async function invokeXiaohongshuPageRuntime(input) {
  const MAX_RESULT_BYTES = 6 * 1024 * 1024;
  const OPERATION_ID = /^[A-Za-z0-9_-]{1,96}$/;
  const PARAMETER_NAME = /^[A-Za-z][A-Za-z0-9_]{0,79}$/;
  const XHS_ID = /^[a-fA-F0-9]{24}$/;
  const SEARCH_ID = /^[A-Za-z0-9_-]{8,128}$/;
  const CATEGORY = /^[A-Za-z][A-Za-z0-9_.-]{0,79}$/;
  const XSEC_TOKEN = /^[A-Za-z0-9_-]+={0,2}$/;
  const XSEC_SOURCE = /^[A-Za-z0-9_-]+$/;
  const USER_POSTED_PATH = "/api/sns/web/v1/user_posted";
  const SEARCH_NOTES_PATH = "/api/sns/web/v2/search/notes";
  const FEED_PATH = "/api/sns/web/v1/feed";
  const HOMEFEED_PATH = "/api/sns/web/v1/homefeed";
  const HOMEFEED_CATEGORY_PATH = "/api/sns/web/v1/homefeed/category";
  const SEARCH_HOTLIST_PATH = "/api/sns/web/v1/search/trending/query";
  const SEARCH_RECOMMEND_PATH = "/api/sns/web/v1/search/recommend";
  const SEARCH_FILTER_PATH = "/api/sns/web/v1/search/filter";
  const SEARCH_USERS_PATH = "/api/sns/web/v1/search/usersearch";
  const USER_INFO_PATH = "/api/sns/web/v1/user/otherinfo";
  const COLLECTED_NOTES_PATH = "/api/sns/web/v2/note/collect/page";
  const COMMENT_PATH = "/api/sns/web/v2/comment/page";
  const SUB_COMMENT_PATH = "/api/sns/web/v2/comment/sub/page";
  const WIDGETS_PATH = "/api/sns/web/v2/widgets";
  const WEBPACK_GLOBAL = "webpackChunkxhs_pc_web";
  const TRANSPORT_TIMEOUT_MS = 15000;
  const SENSITIVE_NAME = /(?:cookie|authorization|token|xsec|(?:^|[-_])x[-_]?s(?:[-_]|$)|(?:^|[-_])x[-_]?t(?:[-_]|$)|signature|session|passport|csrf|sid(?:_|$)|a1(?:_|$)|webid)/i;
  const OPERATIONS = Object.freeze({
    [USER_POSTED_PATH]: {
      method: "GET", context: "profile",
      allowed: new Set(["user_id", "cursor", "num", "image_formats"]),
      required: new Set(["user_id"])
    },
    [SEARCH_NOTES_PATH]: {
      method: "POST", context: "search",
      allowed: new Set(["keyword", "page", "page_size", "search_id", "sort", "note_type"]),
      required: new Set(["keyword", "page", "page_size", "search_id"]),
      wrapperNames: new Set(["getAiSearchNotesV2"]),
      factoryMarkers: new Set(["WEB_AI_SEARCH_NOTES_V2", "getAiSearchNotesV2"])
    },
    [FEED_PATH]: {
      method: "POST", context: "note",
      allowed: new Set(["note_id", "image_formats"]), required: new Set(["note_id"])
    },
    [HOMEFEED_PATH]: {
      method: "POST", context: "explore",
      allowed: new Set(["cursor_score", "num", "category", "need_filter_image"]),
      required: new Set()
    },
    [HOMEFEED_CATEGORY_PATH]: {
      method: "GET", context: "explore", allowed: new Set(), required: new Set()
    },
    [SEARCH_HOTLIST_PATH]: {
      method: "GET", context: "search", allowed: new Set(), required: new Set(),
      wrapperNames: new Set(["getAiSearchQueryTrending"]),
      factoryMarkers: new Set([
        "WEB_AI_SEARCH_QUERY_TRENDING",
        "getAiSearchQueryTrending"
      ])
    },
    [SEARCH_RECOMMEND_PATH]: {
      method: "GET", context: "search", allowed: new Set(["keyword"]), required: new Set()
    },
    [SEARCH_FILTER_PATH]: {
      method: "GET", context: "search",
      allowed: new Set(["keyword", "search_id"]),
      required: new Set(["keyword", "search_id"])
    },
    [SEARCH_USERS_PATH]: {
      method: "POST", context: "search",
      allowed: new Set(["keyword", "page", "page_size", "search_id"]),
      required: new Set(["keyword", "page", "page_size", "search_id"])
    },
    [USER_INFO_PATH]: {
      method: "GET", context: "profile",
      allowed: new Set(["user_id", "image_formats"]), required: new Set(["user_id"])
    },
    [COLLECTED_NOTES_PATH]: {
      method: "GET", context: "profile",
      allowed: new Set(["user_id", "cursor", "num", "image_formats"]),
      required: new Set(["user_id"])
    },
    [COMMENT_PATH]: {
      method: "GET", context: "note",
      allowed: new Set(["note_id", "cursor", "top_comment_id", "image_formats"]),
      required: new Set(["note_id"])
    },
    [SUB_COMMENT_PATH]: {
      method: "GET", context: "note",
      allowed: new Set([
        "note_id", "root_comment_id", "num", "cursor", "top_comment_id", "image_formats"
      ]),
      required: new Set(["note_id", "root_comment_id"])
    },
    [WIDGETS_PATH]: {
      method: "POST", context: "note",
      allowed: new Set(["note_id"]), required: new Set(["note_id"])
    }
  });

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function decimalInRange(value, minimum, maximum) {
    return /^(?:0|[1-9]\d*)$/.test(value) &&
      Number(value) >= minimum &&
      Number(value) <= maximum;
  }

  function validParameterValue(path, name, value) {
    if (name === "note_id" || name === "root_comment_id" || name === "user_id") {
      return XHS_ID.test(value);
    }
    if (name === "num") {
      return decimalInRange(value, 1, path === HOMEFEED_PATH ? 40 : 100);
    }
    if (name === "page") {
      return decimalInRange(value, 1, 10000);
    }
    if (name === "page_size") {
      return decimalInRange(value, 1, path === SEARCH_NOTES_PATH ? 20 : 50);
    }
    if (name === "search_id") {
      return SEARCH_ID.test(value);
    }
    if (name === "image_formats") {
      return value === "jpg,webp,avif";
    }
    if (name === "top_comment_id") {
      return value === "";
    }
    if (name === "sort") {
      return [
        "general",
        "popularity_descending",
        "time_descending",
        "comment_descending",
        "collect_descending"
      ].includes(value);
    }
    if (name === "note_type") {
      return value === "0" || value === "1" || value === "2";
    }
    if (name === "need_filter_image") {
      return value === "true" || value === "false";
    }
    if (name === "category") {
      return CATEGORY.test(value);
    }
    if (name === "keyword") {
      return (path === SEARCH_RECOMMEND_PATH || value.trim().length > 0) && value.length <= 256;
    }
    return true;
  }

  function validEntries(path, value) {
    const descriptor = OPERATIONS[path];
    if (!descriptor || !Array.isArray(value) || value.length > 16) {
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
        !descriptor.allowed.has(name) ||
        names.has(name) ||
        parameter.length > 4096 ||
        /[\r\n\0]/.test(parameter) ||
        !validParameterValue(path, name, parameter)
      ) {
        return false;
      }
      names.add(name);
    }
    for (const name of descriptor.required) {
      if (!names.has(name)) {
        return false;
      }
    }
    return true;
  }

  function xsecQuery(value, allowXsec) {
    const names = [...value.searchParams.keys()];
    if (names.length === 0) {
      return { xsecToken: "", xsecSource: "", xsecSourcePresent: false };
    }
    if (!allowXsec || names.length > 2 || new Set(names).size !== names.length) {
      return null;
    }
    for (const name of names) {
      if (name !== "xsec_token" && name !== "xsec_source") {
        return null;
      }
    }
    const tokens = value.searchParams.getAll("xsec_token");
    const sources = value.searchParams.getAll("xsec_source");
    const validToken = tokens.length === 1 &&
      tokens[0].length > 0 &&
      tokens[0].length <= 512 &&
      tokens[0] === tokens[0].trim() &&
      XSEC_TOKEN.test(tokens[0]);
    if (
      tokens.length > 1 ||
      sources.length > 1 ||
      (tokens.length === 1 && !validToken) ||
      (sources.length === 1 && (
        sources[0].length === 0
          ? !validToken
          : sources[0].length > 64 ||
            sources[0] !== sources[0].trim() ||
            !XSEC_SOURCE.test(sources[0])
      ))
    ) {
      return null;
    }
    return {
      xsecToken: tokens[0] || "",
      xsecSource: sources[0] || "",
      xsecSourcePresent: sources.length === 1
    };
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

  function sanitize(value, depth = 0, seen = new WeakSet(), secretValues = []) {
    if (depth > 14 || value === null) {
      return value === null ? null : undefined;
    }
    if (typeof value === "string") {
      const separator = value.indexOf("=");
      const assignmentName = separator > 0 ? value.slice(0, separator).trim() : "";
      if (
        value.length > 32768 ||
        (
          /^[A-Za-z][A-Za-z0-9_-]{0,79}$/.test(assignmentName) &&
          SENSITIVE_NAME.test(assignmentName)
        )
      ) {
        return undefined;
      }
      const redacted = redactURL(value);
      return secretValues.some((secret) => secret && redacted.includes(secret))
        ? undefined
        : redacted;
    }
    if (typeof value === "number" || typeof value === "boolean") {
      return typeof value === "number" && !Number.isFinite(value) ? undefined : value;
    }
    if (Array.isArray(value)) {
      return value.slice(0, 10000).map(
        (item) => sanitize(item, depth + 1, seen, secretValues)
      ).filter(
        (item) => item !== undefined
      );
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
      let raw;
      try {
        raw = value[key];
      } catch {
        continue;
      }
      const item = sanitize(raw, depth + 1, seen, secretValues);
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
    const key = Symbol.for("local_browser_session_bridge.xiaohongshu.operations.v1");
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
          throw new Error("xiaohongshu_request_cancelled");
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
        finish(() => reject(new Error("xiaohongshu_timeout")));
      }, TRANSPORT_TIMEOUT_MS);
      const onAbort = () => finish(() => reject(new Error(
        timedOut ? "xiaohongshu_timeout" : "xiaohongshu_request_cancelled"
      )));
      operation.signal.addEventListener("abort", onAbort, { once: true });
      function finish(callback) {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        operation.signal.removeEventListener("abort", onAbort);
        callback();
      }
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
      finish() {
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
    const candidates = pageDocument.querySelectorAll(
      'iframe[src*="captcha"], [id*="captcha"] iframe, [class*="captcha"] iframe'
    );
    for (const candidate of candidates) {
      if (visibleElement(candidate)) {
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
    const root = isRecord(window.__INITIAL_STATE__) ? window.__INITIAL_STATE__ : null;
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

  function hasWebSessionCookie() {
    const pageDocument = window.document;
    if (!pageDocument || typeof pageDocument.cookie !== "string") {
      return false;
    }
    return /(?:^|;\s*)web_session=[^;]+/.test(pageDocument.cookie);
  }

  function hasVisitorIdentityCookie() {
    const pageDocument = window.document;
    if (!pageDocument || typeof pageDocument.cookie !== "string") {
      return false;
    }
    return /(?:^|;\s*)a1=[^;]+/.test(pageDocument.cookie);
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
    const notifications = visibleMatches('a[href^="/notification"]');
    const messages = visibleMatches('a[href^="/chat"]');
    return account && notifications && messages;
  }

  function loggedIn() {
    const explicit = initialLoginState();
    if (explicit === true || signedInNavigation()) {
      return true;
    }
    return explicit === false ? false : hasWebSessionCookie();
  }

  function requestReady() {
    return loggedIn() || hasVisitorIdentityCookie();
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
      request_ready: requestReady(),
      verification_required: verificationRequired()
    };
  }

  function currentURLSecretValues(value) {
    return [
      ...value.searchParams.getAll("xsec_token"),
      ...value.searchParams.getAll("xsec_source")
    ].filter((item) => typeof item === "string" && item.length > 0);
  }

  function currentRequestContext(path, entries, contextMode) {
    let current;
    try {
      current = new URL(String(window.location && window.location.href || ""));
    } catch {
      throw new Error("invalid_request_context");
    }
    const secretValues = currentURLSecretValues(current);
    if (
      current.origin !== "https://www.xiaohongshu.com" ||
      current.username ||
      current.password ||
      current.port
    ) {
      throw new Error("invalid_request_context");
    }
    if (contextMode === "session") {
      return {
        xsecToken: "",
        xsecSource: "",
        xsecSourcePresent: false,
        secretValues
      };
    }
    if (current.hash) {
      throw new Error("invalid_request_context");
    }
    const descriptor = OPERATIONS[path];
    const values = new Map(entries);
    let matches = false;
    if (descriptor.context === "note") {
      const match = /^\/(?:explore|discovery\/item)\/([a-fA-F0-9]{24})\/?$/.exec(
        current.pathname
      );
      const noteID = values.get("note_id");
      matches = Boolean(
        match && noteID && match[1].toLowerCase() === noteID.toLowerCase()
      );
    } else if (descriptor.context === "profile") {
      const match = /^\/user\/profile\/([a-fA-F0-9]{24})\/?$/.exec(current.pathname);
      const userID = values.get("user_id");
      matches = Boolean(
        match && userID && match[1].toLowerCase() === userID.toLowerCase()
      );
    } else if (descriptor.context === "search") {
      matches = /^\/search_result\/?$/.test(current.pathname);
    } else {
      matches = /^\/(?:explore)?\/?$/.test(current.pathname);
    }
    if (!matches) {
      throw new Error("invalid_request_context");
    }

    const context = xsecQuery(
      current,
      descriptor.context === "note" || descriptor.context === "profile"
    );
    if (!context) {
      throw new Error("invalid_request_context");
    }
    return { ...context, secretValues };
  }

  function parameterName(path, name) {
    if (name === "user_id") {
      return path === USER_INFO_PATH ? "targetUserId" : "userId";
    }
    return {
      note_id: "noteId",
      root_comment_id: "rootCommentId",
      top_comment_id: "topCommentId",
      image_formats: "imageFormats",
      page_size: "pageSize",
      search_id: "searchId",
      note_type: "noteType",
      cursor_score: "cursorScore",
      need_filter_image: "needFilterImage"
    }[name] || name;
  }

  function transportOptions(operation) {
    return {
      signal: operation.signal,
      timeout: TRANSPORT_TIMEOUT_MS
    };
  }

  function getRequestOptions(path, entries, context, operation) {
    const parameters = {};
    for (const [name, value] of entries) {
      parameters[parameterName(path, name)] = name === "num" ? Number(value) : value;
    }
    if (path === SEARCH_HOTLIST_PATH) {
      Object.assign(parameters, {
        source: "search",
        searchType: "trend",
        lastQuery: "",
        lastQueryTime: 0,
        wordRequestSituation: "FIRST_ENTER",
        hintWord: "",
        hintWordType: "",
        hintWordRequestId: ""
      });
    } else if (path === COMMENT_PATH || path === SUB_COMMENT_PATH) {
      parameters.xsecToken = context.xsecToken;
    } else if (
      path === USER_POSTED_PATH ||
      path === USER_INFO_PATH ||
      path === COLLECTED_NOTES_PATH
    ) {
      parameters.xsecToken = context.xsecToken;
      parameters.xsecSource = context.xsecSource;
    }
    return {
      params: parameters,
      ...transportOptions(operation)
    };
  }

  function requestIdentifier() {
    const randomUUID = globalThis.crypto && typeof globalThis.crypto.randomUUID === "function"
      ? globalThis.crypto.randomUUID()
      : "";
    return randomUUID || `xhs_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`;
  }

  function postRequestBody(path, entries, context) {
    const values = new Map(entries);
    if (path === FEED_PATH) {
      const body = {
        sourceNoteId: values.get("note_id"),
        imageFormats: (values.get("image_formats") || "jpg,webp,avif").split(",")
      };
      if (context.xsecToken) {
        body.xsecToken = context.xsecToken;
      }
      if (context.xsecSourcePresent) {
        body.xsecSource = context.xsecSource;
      }
      return body;
    }
    if (path === WIDGETS_PATH) {
      return {
        noteId: values.get("note_id"),
        scene: "web",
        mode: 1,
        source: "web_feed",
        expFlags: {
          webSupportRelatedSearch: true
        }
      };
    }
    if (path === SEARCH_USERS_PATH) {
      return {
        searchUserRequest: {
          keyword: values.get("keyword"),
          searchId: values.get("search_id"),
          page: Number(values.get("page")),
          pageSize: Number(values.get("page_size")),
          bizType: "web_search_user",
          requestId: requestIdentifier()
        }
      };
    }

    const body = {};
    for (const [name, value] of entries) {
      const mapped = parameterName(path, name);
      if (name === "page" || name === "page_size" || name === "num" || name === "note_type") {
        body[mapped] = Number(value);
      } else if (name === "need_filter_image") {
        body[mapped] = value === "true";
      } else {
        body[mapped] = value;
      }
    }
    if (path === SEARCH_NOTES_PATH) {
      body.extFlags = [];
      body.filters = [];
      body.geo = "";
      body.imageFormats = ["jpg", "webp", "avif"];
      body.sessionId = "";
    }
    return body;
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
    const key = Symbol.for("local_browser_session_bridge.xiaohongshu.transport.v1");
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
      moduleID: null,
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
    const chunkID = `xhs_reverse_${Date.now()}_${Math.random().toString(16).slice(2)}`;
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
    registry.moduleID = null;
    registry.wrappers = {};
    return runtimeRequire;
  }

  function wrapperMatches(value, path) {
    if (typeof value !== "function") {
      return false;
    }
    const descriptor = OPERATIONS[path];
    const source = functionSource(value);
    return source.includes(path) ||
      (descriptor.wrapperNames instanceof Set &&
        descriptor.wrapperNames.has(String(value.name || ""))) ||
      (descriptor.factoryMarkers instanceof Set &&
        [...descriptor.factoryMarkers].some((marker) => source.includes(marker)));
  }

  function factoryMatches(source, path) {
    const descriptor = OPERATIONS[path];
    return source.includes(path) ||
      (descriptor.factoryMarkers instanceof Set &&
        [...descriptor.factoryMarkers].some((marker) => source.includes(marker)));
  }

  function findExportedWrapper(value, path, depth = 0, seen = new WeakSet()) {
    if (wrapperMatches(value, path)) {
      return value;
    }
    if (
      depth >= 3 ||
      value === null ||
      (typeof value !== "object" && typeof value !== "function") ||
      seen.has(value)
    ) {
      return null;
    }
    seen.add(value);
    let keys;
    try {
      keys = Reflect.ownKeys(value).slice(0, 512);
    } catch {
      return null;
    }
    for (const key of keys) {
      let item;
      try {
        item = value[key];
      } catch {
        continue;
      }
      const found = findExportedWrapper(item, path, depth + 1, seen);
      if (found) {
        return found;
      }
    }
    return null;
  }

  function discoverPageWrapper(runtimeRequire, path) {
    const registry = transportRegistry();
    const cached = registry.wrappers[path];
    if (wrapperMatches(cached, path)) {
      return cached;
    }

    const factories = runtimeRequire.m;
    for (const moduleID of Reflect.ownKeys(factories).slice(0, 50000)) {
      const factory = factories[moduleID];
      const source = functionSource(factory);
      if (!factoryMatches(source, path)) {
        continue;
      }
      let moduleExports;
      try {
        moduleExports = runtimeRequire(moduleID);
      } catch {
        continue;
      }
      const wrapper = findExportedWrapper(moduleExports, path);
      if (typeof wrapper === "function") {
        registry.moduleID = String(moduleID);
        registry.wrappers[path] = wrapper;
        return wrapper;
      }
    }
    return null;
  }

  async function locatePageWrapper(path, operation) {
    if (!Array.isArray(window[WEBPACK_GLOBAL])) {
      throw new Error("xiaohongshu_runtime_unavailable");
    }
    operation.throwIfCancelled();
    const runtimeRequire = captureWebpackRequire();
    if (runtimeRequire) {
      const wrapper = discoverPageWrapper(runtimeRequire, path);
      if (typeof wrapper === "function") {
        return wrapper;
      }
    }
    throw new Error("xiaohongshu_runtime_unavailable");
  }

  function normalizedJSONResponse(value, secretValues) {
    let parsed = value;
    if (typeof parsed === "string") {
      try {
        parsed = JSON.parse(parsed);
      } catch {
        throw new Error("xiaohongshu_invalid_response");
      }
    }
    if (!isRecord(parsed)) {
      throw new Error("xiaohongshu_invalid_response");
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
        throw new Error(`xiaohongshu_${classified}`);
      }
    }
    const cleaned = sanitize(parsed, 0, new WeakSet(), secretValues);
    if (!isRecord(cleaned)) {
      throw new Error("xiaohongshu_invalid_response");
    }
    return cleaned;
  }

  async function callPageTransport(path, entries, contextMode, operation) {
    operation.throwIfCancelled();
    if (verificationRequired()) {
      throw new Error("xiaohongshu_verification_required");
    }
    if (!requestReady()) {
      throw new Error("xiaohongshu_not_logged_in");
    }
    if (
      (path === COLLECTED_NOTES_PATH || path === SEARCH_HOTLIST_PATH) &&
      !loggedIn()
    ) {
      throw new Error("xiaohongshu_not_logged_in");
    }
    const descriptor = OPERATIONS[path];
    const context = currentRequestContext(path, entries, contextMode);
    const request = await locatePageWrapper(path, operation);
    operation.throwIfCancelled();
    const invocation = descriptor.method === "GET"
      ? request(getRequestOptions(path, entries, context, operation))
      : request(postRequestBody(path, entries, context), transportOptions(operation));
    const raw = await awaitTransport(
      invocation,
      operation
    );
    operation.throwIfCancelled();
    return normalizedJSONResponse(raw, context.secretValues);
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
      messageMatches(
        /xiaohongshu_verification_required|captcha|verification|verify required|验证码|安全验证/i
      ) ||
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
      messageMatches(/xiaohongshu_forbidden/) ||
      statusIs(403) ||
      codeIs("-10000")
    ) {
      return "forbidden";
    }
    if (
      messageMatches(/xiaohongshu_not_logged_in/) ||
      statusIs(401) ||
      codeIs("104") ||
      messageMatches(/not.?logged.?in|login required|请先登录/i)
    ) {
      return "not_logged_in";
    }
    if (
      messageMatches(/xiaohongshu_timeout|\btimeout\b/i) ||
      signals.names.includes("TimeoutError") ||
      codeIs("ECONNABORTED", "ETIMEDOUT")
    ) {
      return "timeout";
    }
    if (messageMatches(/xiaohongshu_runtime/)) {
      return "runtime_unavailable";
    }
    if (messageMatches(/xiaohongshu_invalid_response/)) {
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
    if (typeof input.operation_id !== "string" || !OPERATION_ID.test(input.operation_id)) {
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
  if (
    input.kind !== "request" ||
    typeof input.operation_id !== "string" ||
    !OPERATION_ID.test(input.operation_id) ||
    typeof input.path !== "string" ||
    typeof input.method !== "string" ||
    !Object.prototype.hasOwnProperty.call(OPERATIONS, input.path) ||
    input.method !== OPERATIONS[input.path].method ||
    (
      input.context_mode !== undefined &&
      input.context_mode !== "strict" &&
      input.context_mode !== "session"
    ) ||
    !validEntries(input.path, input.entries)
  ) {
    return { ok: false, error: "invalid_request" };
  }

  const registered = registerOperation(input.operation_id);
  const contextMode = input.context_mode || "strict";
  try {
    return response({
      ok: true,
      payload: await callPageTransport(
        input.path,
        input.entries,
        contextMode,
        registered.operation
      )
    });
  } catch (error) {
    return { ok: false, error: errorCode(error) };
  } finally {
    registered.finish();
  }
}
