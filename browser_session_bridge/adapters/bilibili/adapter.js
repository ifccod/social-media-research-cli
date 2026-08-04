import { isRecord } from "../../core/protocol.js";
import { sanitizeBrowserPayload } from "../../core/sanitize.js";
import {
  BILIBILI_TAB_PATTERNS,
  isBilibiliTabUrl,
  sameBilibiliRequestContext,
  validBilibiliRequest
} from "./contract.js";
import { invokeBilibiliPageRuntime } from "./page_runtime.js";

const OPERATION_ID = /^[A-Za-z0-9_-]{1,96}$/;
let operationSequence = 0;

function nextOperationID(requestID) {
  if (typeof requestID === "string" && OPERATION_ID.test(requestID)) {
    return requestID;
  }
  operationSequence = (operationSequence + 1) % Number.MAX_SAFE_INTEGER;
  return `bilibili_${Date.now().toString(36)}_${operationSequence.toString(36)}`;
}

function throwIfAborted(signal) {
  if (signal?.aborted) throw new Error("request_aborted");
}

export class BilibiliSessionAdapter {
  constructor({ chromeApi }) {
    this.chrome = chromeApi;
    this.bridgeTabId = null;
  }

  registerLifecycle() {
    this.chrome.tabs.onRemoved.addListener((tabId) => {
      if (this.bridgeTabId === tabId) this.bridgeTabId = null;
    });
  }

  async routeRequest(message, context = {}) {
    if (!validBilibiliRequest(message)) return { error: "invalid_request" };
    const signal = context.signal;
    let removeAbort = () => {};
    let removeCancel = () => {};
    let cancelPage = null;
    try {
      throwIfAborted(signal);
      const tab = await this.pickTab(message.referer, signal);
      throwIfAborted(signal);
      if (!sameBilibiliRequestContext(tab.url || "", message.referer)) {
        throw new Error("tab_unavailable");
      }
      const operationID = nextOperationID(context.requestId);
      let cancellation = null;
      cancelPage = () => cancellation ||
        (cancellation = this.cancelInPage(tab.id, operationID));
      const onAbort = () => { void cancelPage(); };
      if (signal?.addEventListener) {
        signal.addEventListener("abort", onAbort, { once: true });
        removeAbort = () => signal.removeEventListener("abort", onAbort);
      }
      if (typeof context.onCancel === "function") {
        removeCancel = context.onCancel(() => cancelPage());
      }
      const result = await this.runInPage(tab.id, {
        kind: "request",
        operation_id: operationID,
        path: message.path,
        entries: message.entries,
        request_interval_ms: message.request_interval_ms
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
      const code = String(error?.message || "");
      if (["tab_unavailable", "invalid_response"].includes(code)) {
        return { error: code };
      }
      return {
        error: code === "request_aborted"
          ? "request_failed"
          : "runtime_unavailable"
      };
    } finally {
      removeAbort();
      removeCancel();
      if (signal?.aborted && cancelPage) {
        await cancelPage().catch(() => undefined);
      }
    }
  }

  async routeSession(context = {}) {
    try {
      const signal = context.signal;
      const tab = await this.pickTab(null, signal);
      throwIfAborted(signal);
      const result = await this.runInPage(tab.id, { kind: "session" });
      if (result.ok !== true) {
        return { error: result.error || "request_failed" };
      }
      const payload = this.sessionPayload(result.payload);
      return payload ? { payload } : { error: "invalid_response" };
    } catch (error) {
      return {
        error: String(error?.message || "") === "tab_unavailable"
          ? "tab_unavailable"
          : "runtime_unavailable"
      };
    }
  }

  async bilibiliTabs() {
    return this.chrome.tabs.query({ url: BILIBILI_TAB_PATTERNS });
  }

  async pickTab(expectedURL = null, signal = null) {
    throwIfAborted(signal);
    const tabs = await this.bilibiliTabs();
    const tab = expectedURL
      ? tabs.find((item) =>
        sameBilibiliRequestContext(item.url || "", expectedURL)
      )
      : tabs.find((item) => item.id === this.bridgeTabId) ||
        tabs.find((item) => item.active) ||
        tabs.find((item) => item.status === "complete") ||
        tabs[0];
    if (!tab?.id) throw new Error("tab_unavailable");
    this.bridgeTabId = tab.id;
    return tab;
  }

  async runInPage(tabId, input) {
    const tab = await this.chrome.tabs.get(tabId).catch(() => null);
    if (!tab || !isBilibiliTabUrl(tab.url || "")) {
      throw new Error("tab_unavailable");
    }
    if (tab.status && tab.status !== "complete") {
      throw new Error("runtime_unavailable");
    }
    const results = await this.chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      injectImmediately: true,
      func: invokeBilibiliPageRuntime,
      args: [input]
    });
    const result = Array.isArray(results) && results.length === 1
      ? results[0]?.result
      : null;
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
      typeof value.logged_in !== "boolean"
    ) {
      return null;
    }
    const fingerprint = sanitizeBrowserPayload(value.fingerprint);
    if (!isRecord(fingerprint)) return null;
    fingerprint.cookie_enabled = Boolean(value.fingerprint.cookie_enabled);
    return {
      fingerprint,
      logged_in: value.logged_in,
      verification_required: value.verification_required === true
    };
  }
}
