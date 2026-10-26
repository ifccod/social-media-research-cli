import { isRecord } from "../../core/protocol.js";
import { sanitizeBrowserPayload } from "../../core/sanitize.js";
import { SerialRequestPolicy } from "../../core/serial_request_policy.js";
import {
  XIAOHONGSHU_CREATOR_PUBLISH_NOTE_PATH,
  XIAOHONGSHU_CREATOR_TAB_PATTERNS,
  XIAOHONGSHU_CREATOR_UPLOAD_IMAGE_PATH,
  XIAOHONGSHU_CREATOR_UPLOAD_VIDEO_PATH,
  isXiaohongshuCreatorTabUrl,
  sameXiaohongshuCreatorRequestContext,
  validXiaohongshuCreatorRequest
} from "./contract.js";
import { invokeXiaohongshuCreatorPageRuntime } from "./page_runtime.js";

const OPERATION_ID = /^[A-Za-z0-9_-]{1,96}$/;
const WRITE_PATHS = new Set([
  XIAOHONGSHU_CREATOR_UPLOAD_IMAGE_PATH,
  XIAOHONGSHU_CREATOR_UPLOAD_VIDEO_PATH,
  XIAOHONGSHU_CREATOR_PUBLISH_NOTE_PATH
]);
let operationSequence = 0;

function nextOperationID(requestID) {
  if (typeof requestID === "string" && OPERATION_ID.test(requestID)) {
    return requestID;
  }
  operationSequence = (operationSequence + 1) % Number.MAX_SAFE_INTEGER;
  return `xiaohongshu_creator_${Date.now().toString(36)}_${operationSequence.toString(36)}`;
}

function throwIfAborted(signal) {
  if (signal && signal.aborted) {
    throw new Error("request_aborted");
  }
}

export class XiaohongshuCreatorSessionAdapter {
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
    if (!validXiaohongshuCreatorRequest(message)) {
      return { error: "invalid_request" };
    }
    const signal = context && context.signal;
    const operation = (beginPlatformRequest) => this.routeRequestSerial(
      message,
      context,
      beginPlatformRequest
    );
    try {
      // 写路径 429 不闩同族 www/PGY 读请求。
      const run = WRITE_PATHS.has(message.path)
        ? "runWithoutRiskLatch"
        : "runWithInterval";
      return await this.requestPolicy[run](
        signal,
        message.request_interval_ms,
        operation
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
      if (!sameXiaohongshuCreatorRequestContext(tab.url || "", message.referer)) {
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
      await beginPlatformRequest();
      const result = await this.runInPage(tab.id, {
        kind: "request",
        operation_id: operationID,
        method: message.method,
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
      const payload = isRecord(result.payload)
        ? sanitizeBrowserPayload(result.payload)
        : null;
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

  async creatorTabs() {
    return this.chrome.tabs.query({ url: XIAOHONGSHU_CREATOR_TAB_PATTERNS });
  }

  async pickTab(expectedURL = null, signal = null) {
    throwIfAborted(signal);
    const tabs = await this.creatorTabs();
    throwIfAborted(signal);
    const matching = tabs.filter((item) => isXiaohongshuCreatorTabUrl(item.url || ""));
    const tab = expectedURL
      ? matching.find((item) => sameXiaohongshuCreatorRequestContext(
        item.url || "",
        expectedURL
      ))
      : matching.find((item) => item.id === this.bridgeTabId) ||
        matching.find((item) => item.active) ||
        matching.find((item) => item.status === "complete") ||
        matching[0];
    if (!tab || !tab.id) {
      throw new Error("tab_unavailable");
    }
    this.bridgeTabId = tab.id;
    return tab;
  }

  async runInPage(tabId, input) {
    const tab = await this.chrome.tabs.get(tabId).catch(() => null);
    if (!tab || !isXiaohongshuCreatorTabUrl(tab.url || "")) {
      throw new Error("tab_unavailable");
    }
    if (tab.status && tab.status !== "complete") {
      throw new Error("runtime_unavailable");
    }
    const results = await this.chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      injectImmediately: true,
      func: invokeXiaohongshuCreatorPageRuntime,
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
