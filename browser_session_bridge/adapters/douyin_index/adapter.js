import { isRecord } from "../../core/protocol.js";
import { sanitizeBrowserPayload } from "../../core/sanitize.js";
import {
  DOUYIN_INDEX_TAB_PATTERNS,
  isDouyinIndexTabUrl,
  sameDouyinIndexRequestContext,
  validDouyinIndexRequest
} from "./contract.js";
import { invokeDouyinIndexPageRuntime } from "./page_runtime.js";

const OPERATION_ID = /^[A-Za-z0-9_-]{1,96}$/;
let operationSequence = 0;

function nextOperationID(requestID) {
  if (typeof requestID === "string" && OPERATION_ID.test(requestID)) {
    return requestID;
  }
  operationSequence = (operationSequence + 1) % Number.MAX_SAFE_INTEGER;
  return `douyin_index_${Date.now().toString(36)}_${operationSequence.toString(36)}`;
}

function throwIfAborted(signal) {
  if (signal && signal.aborted) {
    throw new Error("request_aborted");
  }
}

export class DouyinIndexSessionAdapter {
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
    if (!validDouyinIndexRequest(message)) {
      return { error: "invalid_request" };
    }
    const signal = context && context.signal;
    try {
      throwIfAborted(signal);
      const tab = await this.pickTab(message.referer, signal);
      if (!sameDouyinIndexRequestContext(tab.url || "", message.referer)) {
        throw new Error("tab_unavailable");
      }
      const result = await this.runInPage(tab.id, {
        kind: "request",
        operation_id: nextOperationID(context && context.requestId),
        path: message.path,
        entries: message.entries
      });
      throwIfAborted(signal);
      if (result.ok !== true) {
        return {
          error: typeof result.error === "string"
            ? result.error
            : "request_failed"
        };
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
        return {
          error: typeof result.error === "string"
            ? result.error
            : "request_failed"
        };
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

  async tabs() {
    return this.chrome.tabs.query({ url: DOUYIN_INDEX_TAB_PATTERNS });
  }

  async pickTab(expectedURL = null, signal = null) {
    throwIfAborted(signal);
    const tabs = await this.tabs();
    const tab = expectedURL
      ? tabs.find((item) =>
        sameDouyinIndexRequestContext(item.url || "", expectedURL)
      )
      : tabs.find((item) => item.id === this.bridgeTabId) ||
        tabs.find((item) => item.active) ||
        tabs.find((item) => item.status === "complete") ||
        tabs[0];
    throwIfAborted(signal);
    if (!tab || !tab.id) {
      throw new Error("tab_unavailable");
    }
    this.bridgeTabId = tab.id;
    return tab;
  }

  async runInPage(tabId, input) {
    const tab = await this.chrome.tabs.get(tabId).catch(() => null);
    if (!tab || !isDouyinIndexTabUrl(tab.url || "")) {
      throw new Error("tab_unavailable");
    }
    if (tab.status && tab.status !== "complete") {
      throw new Error("runtime_unavailable");
    }
    const results = await this.chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      injectImmediately: true,
      func: invokeDouyinIndexPageRuntime,
      args: [input]
    });
    const injection = Array.isArray(results) && results.length === 1
      ? results[0]
      : null;
    const result = isRecord(injection) ? injection.result : null;
    if (!isRecord(result) || typeof result.ok !== "boolean") {
      throw new Error("invalid_response");
    }
    return result;
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
    const fingerprint = sanitizeBrowserPayload(value.fingerprint);
    if (!isRecord(fingerprint)) {
      return null;
    }
    fingerprint.cookie_enabled = Boolean(value.fingerprint.cookie_enabled);
    return {
      fingerprint,
      logged_in: value.logged_in,
      request_ready: value.request_ready,
      verification_required: value.verification_required === true
    };
  }
}
