import { isRecord } from "../../core/protocol.js";
import { sanitizeBrowserPayload } from "../../core/sanitize.js";
import { SerialRequestPolicy } from "../../core/serial_request_policy.js";
import {
  TWITTER_CREATE_SCHEDULED_TWEET_PATH,
  TWITTER_FOLLOW_PATH,
  TWITTER_HOME_URL,
  TWITTER_SEARCH_URL,
  TWITTER_TAB_PATTERNS,
  TWITTER_UPLOAD_MEDIA_PATH,
  isTwitterTabUrl,
  sameTwitterRequestContext,
  validTwitterRequest
} from "./contract.js";
import { invokeTwitterPageRuntime } from "./page_runtime.js";

const WRITE_PATHS = new Set([
  TWITTER_FOLLOW_PATH,
  TWITTER_UPLOAD_MEDIA_PATH,
  TWITTER_CREATE_SCHEDULED_TWEET_PATH
]);

function throwIfAborted(signal) {
  if (signal?.aborted) {
    throw new Error("request_aborted");
  }
}

export class TwitterSessionAdapter {
  constructor({
    chromeApi,
    requestPolicy = null,
    scope = "home"
  }) {
    this.chrome = chromeApi;
    this.requestPolicy = requestPolicy || new SerialRequestPolicy();
    this.scope = scope === "search" ? "search" : "home";
    this.sessionURL = this.scope === "search"
      ? TWITTER_SEARCH_URL
      : TWITTER_HOME_URL;
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
    if (!validTwitterRequest(message, this.scope)) {
      return { error: "invalid_request" };
    }
    const signal = context.signal;
    const operation = async (beginPlatformRequest) => {
        try {
          throwIfAborted(signal);
          const tab = await this.pickTab(message.referer, signal);
          if (!sameTwitterRequestContext(
            tab.url || "",
            message.referer,
            this.scope
          )) {
            if (/\/i\/flow\/(?:login|signup)/.test(tab.url || "")) {
              return { error: "not_logged_in" };
            }
            throw new Error("tab_unavailable");
          }
          const session = await this.runInPage(tab.id, { kind: "session" });
          if (session.ok !== true) {
            return {
              error: typeof session.error === "string"
                ? session.error
                : "request_failed"
            };
          }
          const sessionPayload = this.sessionPayload(session.payload);
          if (!sessionPayload) {
            return { error: "invalid_response" };
          }
          if (sessionPayload.verification_required) {
            return { error: "verification_required" };
          }
          if (!sessionPayload.logged_in) {
            return { error: "not_logged_in" };
          }
          await beginPlatformRequest();
          const result = await this.runInPage(tab.id, {
            kind: "request",
            path: message.path,
            entries: message.entries,
            session_verified: true
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
          return isRecord(payload)
            ? { payload }
            : { error: "invalid_response" };
        } catch (error) {
          const code = String(error?.message || "");
          if ([
            "tab_unavailable",
            "invalid_response",
            "timeout"
          ].includes(code)) {
            return { error: code };
          }
          return {
            error: code === "request_aborted"
              ? "request_failed"
              : "runtime_unavailable"
          };
        }
    };
    // 写路径 429 不闩 twitter_home/search 读请求；verification_required 仍由页面返回。
    return WRITE_PATHS.has(message.path)
      ? this.requestPolicy.runWithoutRiskLatch(
          signal,
          message.request_interval_ms,
          operation
        )
      : this.requestPolicy.run(
          signal,
          message.request_interval_ms,
          operation
        );
  }

  async routeSession(context = {}) {
    try {
      const signal = context.signal;
      const tab = await this.pickTab(this.sessionURL, signal);
      throwIfAborted(signal);
      const result = await this.runInPage(tab.id, { kind: "session" });
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
        error: String(error?.message || "") === "tab_unavailable"
          ? "tab_unavailable"
          : "runtime_unavailable"
      };
    }
  }

  async twitterTabs() {
    return this.chrome.tabs.query({ url: TWITTER_TAB_PATTERNS });
  }

  async pickTab(expectedURL, signal = null) {
    throwIfAborted(signal);
    const tabs = await this.twitterTabs();
    const tab =
      tabs.find((item) =>
        sameTwitterRequestContext(
          item.url || "",
          expectedURL,
          this.scope
        )
      );
    if (!tab?.id) {
      throw new Error("tab_unavailable");
    }
    this.bridgeTabId = tab.id;
    return tab;
  }

  async runInPage(tabId, input) {
    const tab = await this.chrome.tabs.get(tabId).catch(() => null);
    if (!tab || !isTwitterTabUrl(tab.url || "")) {
      throw new Error("tab_unavailable");
    }
    if (tab.status && tab.status !== "complete") {
      throw new Error("runtime_unavailable");
    }
    const results = await this.chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      injectImmediately: true,
      func: invokeTwitterPageRuntime,
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

  sessionPayload(value) {
    if (
      !isRecord(value) ||
      !isRecord(value.fingerprint) ||
      typeof value.logged_in !== "boolean"
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
      request_ready: value.logged_in,
      verification_required: value.verification_required === true
    };
  }
}
