import { isRecord } from "../../core/protocol.js";
import { sanitizeBrowserPayload } from "../../core/sanitize.js";
import { SerialRequestPolicy } from "../../core/serial_request_policy.js";
import {
  XIAOHONGSHU_PGY_BLOGGER_LIST_PATH,
  XIAOHONGSHU_PGY_TAB_PATTERNS,
  isXiaohongshuPgyTabUrl,
  sameXiaohongshuPgyRequestContext,
  validXiaohongshuPgyRequest
} from "./contract.js";
import { invokeXiaohongshuPgyPageRuntime } from "./page_runtime.js";

const OPERATION_ID = /^[A-Za-z0-9_-]{1,96}$/;
let operationSequence = 0;

function nextOperationID(requestID) {
  if (typeof requestID === "string" && OPERATION_ID.test(requestID)) {
    return requestID;
  }
  operationSequence = (operationSequence + 1) % Number.MAX_SAFE_INTEGER;
  return `xiaohongshu_pgy_${Date.now().toString(36)}_${operationSequence.toString(36)}`;
}

function throwIfAborted(signal) {
  if (signal && signal.aborted) {
    throw new Error("request_aborted");
  }
}

function bloggerListContinuation(value) {
  if (
    !isRecord(value) ||
    typeof value.brand_user_id !== "string" ||
    !/^[a-fA-F0-9]{24}$/.test(value.brand_user_id) ||
    typeof value.track_id !== "string" ||
    value.track_id.length === 0 ||
    value.track_id.length > 256 ||
    /[\r\n\0]/.test(value.track_id)
  ) {
    return null;
  }
  return {
    brandUserID: value.brand_user_id,
    trackID: value.track_id
  };
}

export class XiaohongshuPgySessionAdapter {
  constructor({ chromeApi, requestPolicy = null }) {
    this.chrome = chromeApi;
    this.bridgeTabId = null;
    this.requestPolicy = requestPolicy || new SerialRequestPolicy();
  }

  registerLifecycle() {
    this.chrome.tabs.onRemoved.addListener((tabId) => {
      if (this.bridgeTabId === tabId) {
        this.bridgeTabId = null;
      }
    });
  }

  async routeRequest(message, context = {}) {
    if (!validXiaohongshuPgyRequest(message)) {
      return { error: "invalid_request" };
    }
    const signal = context && context.signal;
    const operation = (beginPlatformRequest) => this.routeRequestSerial(
      message,
      context,
      beginPlatformRequest
    );
    try {
      return await (
        typeof this.requestPolicy.runWithInterval === "function"
          ? this.requestPolicy.runWithInterval(
            signal,
            message.request_interval_ms,
            operation
          )
          : this.requestPolicy.run(signal, operation)
      );
    } catch (error) {
      return {
        error: String(error && error.message) === "request_aborted"
          ? "request_failed"
          : "runtime_unavailable"
      };
    }
  }

  async routeRequestSerial(message, context, beginPlatformRequest) {
    const signal = context && context.signal;
    let removeAbortListener = () => {};
    let removeCancelHandler = () => {};
    let cancelPageOperation = null;
    try {
      throwIfAborted(signal);
      const tab = await this.pickTab(message.referer, signal);
      if (!sameXiaohongshuPgyRequestContext(tab.url || "", message.referer)) {
        throw new Error("tab_unavailable");
      }

      const operationID = nextOperationID(context && context.requestId);
      let cancellation = null;
      cancelPageOperation = () => {
        if (!cancellation) {
          cancellation = this.cancelInPage(tab.id, operationID);
        }
        return cancellation;
      };
      const onAbort = () => {
        void cancelPageOperation();
      };
      if (signal && typeof signal.addEventListener === "function") {
        signal.addEventListener("abort", onAbort, { once: true });
        removeAbortListener = () => signal.removeEventListener("abort", onAbort);
      }
      if (context && typeof context.onCancel === "function") {
        removeCancelHandler = context.onCancel(() => cancelPageOperation());
      }
      if (signal && signal.aborted) {
        await cancelPageOperation();
        throwIfAborted(signal);
      }
      const pageInput = {
        kind: "request",
        operation_id: operationID,
        method: message.method,
        path: message.path,
        entries: message.entries
      };
      let result;
      if (message.path === XIAOHONGSHU_PGY_BLOGGER_LIST_PATH) {
        await beginPlatformRequest();
        const trackResult = await this.runInPage(tab.id, {
          ...pageInput,
          stage: "track"
        });
        if (trackResult.ok !== true) {
          return {
            error: typeof trackResult.error === "string"
              ? trackResult.error
              : "request_failed"
          };
        }
        const continuation = bloggerListContinuation(trackResult.payload);
        if (!continuation) {
          return { error: "invalid_response" };
        }
        throwIfAborted(signal);
        await beginPlatformRequest();
        result = await this.runInPage(tab.id, {
          ...pageInput,
          stage: "list",
          brand_user_id: continuation.brandUserID,
          track_id: continuation.trackID
        });
      } else {
        await beginPlatformRequest();
        result = await this.runInPage(tab.id, pageInput);
      }
      if (signal && signal.aborted) {
        await cancelPageOperation();
        throwIfAborted(signal);
      }
      if (result.ok !== true) {
        return { error: typeof result.error === "string" ? result.error : "request_failed" };
      }
      const payload = isRecord(result.payload) ? sanitizeBrowserPayload(result.payload) : null;
      return payload ? { payload } : { error: "invalid_response" };
    } catch (error) {
      const code = String(error && error.message);
      return {
        error: code === "tab_unavailable" || code === "invalid_response"
          ? code
          : code === "request_aborted"
            ? "request_failed"
            : "runtime_unavailable"
      };
    } finally {
      removeAbortListener();
      removeCancelHandler();
      if (signal && signal.aborted && cancelPageOperation) {
        await cancelPageOperation().catch(() => undefined);
      }
    }
  }

  async routeSession(context = {}) {
    try {
      const signal = context && context.signal;
      throwIfAborted(signal);
      const tab = await this.pickTab(null, signal);
      throwIfAborted(signal);
      const result = await this.runInPage(tab.id, { kind: "session" });
      throwIfAborted(signal);
      if (result.ok !== true) {
        return { error: typeof result.error === "string" ? result.error : "request_failed" };
      }
      const payload = this.sessionPayload(result.payload);
      return payload ? { payload } : { error: "invalid_response" };
    } catch (error) {
      return {
        error: String(error && error.message) === "tab_unavailable"
          ? "tab_unavailable"
          : "runtime_unavailable"
      };
    }
  }

  async pgyTabs() {
    return this.chrome.tabs.query({ url: XIAOHONGSHU_PGY_TAB_PATTERNS });
  }

  async pickTab(expectedURL = null, signal = null) {
    throwIfAborted(signal);
    const tabs = await this.pgyTabs();
    throwIfAborted(signal);
    const tab = expectedURL
      ? tabs.find((item) => sameXiaohongshuPgyRequestContext(
        item.url || "",
        expectedURL
      ))
      : tabs.find((item) => item.id === this.bridgeTabId) ||
        tabs.find((item) => item.active) ||
        tabs.find((item) => item.status === "complete") ||
        tabs[0];
    if (!tab || !tab.id) {
      throw new Error("tab_unavailable");
    }
    this.bridgeTabId = tab.id;
    return tab;
  }

  async runInPage(tabId, input) {
    const tab = await this.chrome.tabs.get(tabId).catch(() => null);
    if (!tab || !isXiaohongshuPgyTabUrl(tab.url || "")) {
      throw new Error("tab_unavailable");
    }
    if (tab.status && tab.status !== "complete") {
      throw new Error("runtime_unavailable");
    }
    const results = await this.chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      injectImmediately: true,
      func: invokeXiaohongshuPgyPageRuntime,
      args: [input]
    });
    const injection = Array.isArray(results) && results.length === 1 ? results[0] : null;
    const result = isRecord(injection) ? injection.result : null;
    if (!isRecord(result) || typeof result.ok !== "boolean") {
      throw new Error("invalid_response");
    }
    return result;
  }

  async cancelInPage(tabId, operationID) {
    try {
      const result = await this.runInPage(tabId, {
        kind: "cancel",
        operation_id: operationID
      });
      return result.ok === true;
    } catch {
      return false;
    }
  }

  sessionPayload(value) {
    if (
      !isRecord(value) ||
      !isRecord(value.fingerprint) ||
      typeof value.logged_in !== "boolean" ||
      typeof value.request_ready !== "boolean"
    ) {
      return null;
    }
    const valueFingerprint = sanitizeBrowserPayload(value.fingerprint);
    if (!isRecord(valueFingerprint)) {
      return null;
    }
    valueFingerprint.cookie_enabled = Boolean(value.fingerprint.cookie_enabled);
    return {
      fingerprint: valueFingerprint,
      logged_in: value.logged_in,
      request_ready: value.request_ready,
      verification_required: value.verification_required === true
    };
  }
}
