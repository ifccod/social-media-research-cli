import { isRecord } from "../../core/protocol.js";
import { sanitizeBrowserPayload } from "../../core/sanitize.js";
import {
  DOUYIN_TAB_PATTERNS,
  isDouyinTabUrl,
  sameDouyinRequestContext,
  validDouyinRequest
} from "./contract.js";
import { invokeDouyinPageRuntime } from "./page_runtime.js";

const OPERATION_ID = /^[A-Za-z0-9_-]{1,96}$/;
let operationSequence = 0;

function nextOperationID(requestID) {
  if (typeof requestID === "string" && OPERATION_ID.test(requestID)) {
    return requestID;
  }
  operationSequence = (operationSequence + 1) % Number.MAX_SAFE_INTEGER;
  return `douyin_${Date.now().toString(36)}_${operationSequence.toString(36)}`;
}

function throwIfAborted(signal) {
  if (signal && signal.aborted) {
    throw new Error("request_aborted");
  }
}

/**
 * 抖音浏览器端实现，仅负责抖音标签页、平台请求白名单和 MAIN world
 * 运行时调用。本地 WebSocket 认证状态由 core/local_bridge_v2.js 管理。
 */
export class DouyinSessionAdapter {
  constructor({ chromeApi }) {
    this.chrome = chromeApi;
    this.bridgeTabId = null;
  }

  registerLifecycle() {
    this.chrome.tabs.onRemoved.addListener((tabId) => {
      if (this.bridgeTabId === tabId) {
        this.bridgeTabId = null;
      }
    });
  }

  async routeRequest(message, context = {}) {
    if (!validDouyinRequest(message)) {
      return { error: "invalid_request" };
    }
    const signal = context && context.signal;
    let removeAbortListener = () => {};
    let removeCancelHandler = () => {};
    let cancelPageOperation = null;
    try {
      throwIfAborted(signal);
      const tab = await this.pickDouyinTab(message.referer, signal);
      if (!sameDouyinRequestContext(tab.url || "", message.referer)) {
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
      const result = await this.runInPage(tab.id, {
        kind: "request",
        operation_id: operationID,
        path: message.path,
        entries: message.entries
      });
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
      const tab = await this.pickDouyinTab(null, signal);
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

  async douyinTabs() {
    return this.chrome.tabs.query({ url: DOUYIN_TAB_PATTERNS });
  }

  async pickDouyinTab(expectedURL = null, signal = null) {
    throwIfAborted(signal);
    const tabs = await this.douyinTabs();
    throwIfAborted(signal);
    const tab = expectedURL
      ? tabs.find((item) =>
        sameDouyinRequestContext(item.url || "", expectedURL)
      )
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
    if (!tab || !isDouyinTabUrl(tab.url || "")) {
      throw new Error("tab_unavailable");
    }
    if (tab.status && tab.status !== "complete") {
      throw new Error("runtime_unavailable");
    }
    const results = await this.chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      injectImmediately: true,
      func: invokeDouyinPageRuntime,
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
      // 关闭或导航标签页也会销毁待处理的页面传输。
      return false;
    }
  }

  sessionPayload(value) {
    if (!isRecord(value) || !isRecord(value.fingerprint) || typeof value.logged_in !== "boolean") {
      return null;
    }
    const fingerprint = sanitizeBrowserPayload(value.fingerprint);
    if (!isRecord(fingerprint)) {
      return null;
    }
    // 此 navigator 能力标记不是 Cookie 值。
    fingerprint.cookie_enabled = Boolean(value.fingerprint.cookie_enabled);
    return {
      fingerprint,
      logged_in: value.logged_in,
      verification_required: value.verification_required === true
    };
  }
}
