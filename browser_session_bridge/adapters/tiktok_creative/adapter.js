import { isRecord } from "../../core/protocol.js";
import { sanitizeBrowserPayload } from "../../core/sanitize.js";
import {
  DEFAULT_TRIPPING_ERRORS,
  SerialRequestPolicy
} from "../../core/serial_request_policy.js";
import {
  TIKTOK_ADS_KEYWORD_PATHS,
  TIKTOK_ADS_KEYWORD_PLANNER_URL,
  TIKTOK_CREATIVE_HASHTAG_PATHS,
  TIKTOK_CREATIVE_HASHTAG_URL,
  TIKTOK_CREATIVE_ORIGIN,
  TIKTOK_CREATIVE_TRENDING_VIDEO_PATHS,
  TIKTOK_CREATIVE_STUDIO_PATHS,
  TIKTOK_CREATIVE_STUDIO_URL,
  TIKTOK_CREATIVE_TAB_PATTERNS,
  TIKTOK_CREATIVE_TOP_ADS_PATHS,
  TIKTOK_CREATIVE_TOP_ADS_V2_URL,
  TIKTOK_ONE_CREATOR_PATHS,
  TIKTOK_ONE_CREATOR_URL,
  isTikTokAdsManagerHomeUrl,
  isTikTokCreativeProfileUrl,
  isTikTokCreativeScopeLoginUrl,
  isTikTokCreativeScopeTabUrl,
  sameTikTokCreativeRequestContext,
  validTikTokCreativeHashtagReferer,
  validTikTokCreativeTrendingVideoReferer,
  validTikTokCreativeHashtagDetailReferer,
  validTikTokCreativeRequest,
  validTikTokCreativeStudioReferer,
  validTikTokCreativeTopAdsInsightReferer,
  validTikTokCreativeTopAdsLibraryReferer,
  validTikTokCreativeTopAdsReferer,
  validTikTokCreativeTopAdsV2Referer,
  validTikTokAdsKeywordPlannerReferer,
  validTikTokOneCreatorReferer
} from "./contract.js";
import { invokeTikTokCreativePageRuntime } from "./page_runtime.js";

const READY_SESSION_CACHE_MS = 300000;
const PENDING_SESSION_CACHE_MS = 500;
const TRIPPING_ERRORS = new Set(DEFAULT_TRIPPING_ERRORS);
const SESSION_INVALIDATING_ERRORS = new Set([
  "advertiser_account_required",
  "csrf_or_signature_expired",
  "not_logged_in",
  "profile_required",
  "runtime_unavailable",
  "transport_modules_changed",
  "verification_required"
]);
const ADVERTISER_ID = /^[1-9][0-9]{0,31}$/;

function throwIfAborted(signal) {
  if (signal && signal.aborted) {
    throw new Error("request_aborted");
  }
}

function tiktokAdsManagerAdvertiserId(value) {
  try {
    const parsed = new URL(value);
    const advertiserIDs = parsed.searchParams.getAll("aadvid");
    if (
      parsed.origin !== TIKTOK_CREATIVE_ORIGIN ||
      !parsed.pathname.startsWith("/i18n/") ||
      advertiserIDs.length !== 1 ||
      !ADVERTISER_ID.test(advertiserIDs[0])
    ) {
      return "";
    }
    return advertiserIDs[0];
  } catch {
    return "";
  }
}

function tiktokAdsManagerReferer(current, fallback) {
  const advertiserID = tiktokAdsManagerAdvertiserId(current);
  if (!advertiserID) {
    return fallback;
  }
  const parsed = new URL(fallback);
  parsed.searchParams.set("aadvid", advertiserID);
  return parsed.toString();
}

export class TikTokCreativeSessionAdapter {
  constructor({
    chromeApi,
    requestPolicy = null,
    now = () => Date.now(),
    scope = "hashtag"
  }) {
    this.chrome = chromeApi;
    this.bridgeTabId = null;
    this.requestPolicy = requestPolicy || new SerialRequestPolicy();
    this.now = typeof now === "function" ? now : () => Date.now();
    this.sessionCache = null;
    this.forceSessionProbe = false;
    this.trippedError = "";
    this.scope = ["top_ads", "studio", "one", "ads_manager"].includes(scope)
      ? scope
      : "hashtag";
    if (this.scope === "top_ads") {
      this.allowedPaths = TIKTOK_CREATIVE_TOP_ADS_PATHS;
      this.sessionURL = TIKTOK_CREATIVE_TOP_ADS_V2_URL;
      this.validReferer = validTikTokCreativeTopAdsReferer;
    } else if (this.scope === "studio") {
      this.allowedPaths = TIKTOK_CREATIVE_STUDIO_PATHS;
      this.sessionURL = TIKTOK_CREATIVE_STUDIO_URL;
      this.validReferer = validTikTokCreativeStudioReferer;
    } else if (this.scope === "one") {
      this.allowedPaths = TIKTOK_ONE_CREATOR_PATHS;
      this.sessionURL = TIKTOK_ONE_CREATOR_URL;
      this.validReferer = validTikTokOneCreatorReferer;
    } else if (this.scope === "ads_manager") {
      this.allowedPaths = TIKTOK_ADS_KEYWORD_PATHS;
      this.sessionURL = TIKTOK_ADS_KEYWORD_PLANNER_URL;
      this.validReferer = validTikTokAdsKeywordPlannerReferer;
    } else {
      this.allowedPaths = new Set([
        ...TIKTOK_CREATIVE_HASHTAG_PATHS,
        ...TIKTOK_CREATIVE_TRENDING_VIDEO_PATHS
      ]);
      this.sessionURL = TIKTOK_CREATIVE_HASHTAG_URL;
      this.validReferer = (value) =>
        validTikTokCreativeHashtagReferer(value) ||
        validTikTokCreativeTrendingVideoReferer(value);
    }
  }

  registerLifecycle() {
    this.chrome.tabs.onRemoved.addListener((tabId) => {
      if (this.bridgeTabId === tabId) {
        this.bridgeTabId = null;
      }
      if (this.sessionCache && this.sessionCache.tabId === tabId) {
        this.sessionCache = null;
      }
    });
    if (
      this.chrome.tabs.onUpdated &&
      typeof this.chrome.tabs.onUpdated.addListener === "function"
    ) {
      this.chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
        if (
          this.sessionCache &&
          this.sessionCache.tabId === tabId &&
          (
            typeof changeInfo.url === "string" ||
            changeInfo.status === "loading"
          )
        ) {
          this.sessionCache = null;
        }
      });
    }
  }

  async routeRequest(message, context = {}) {
    if (!validTikTokCreativeRequest(message, this.allowedPaths)) {
      return { error: "invalid_request" };
    }
    if (this.trippedError) {
      return { error: this.trippedError };
    }
    const signal = context && context.signal;
    const operation = async (beginPlatformRequest) => {
      try {
        throwIfAborted(signal);
        const tab = await this.pickTab(message.referer, signal);
        if (
          this.scope === "ads_manager" &&
          isTikTokAdsManagerHomeUrl(tab.url || "")
        ) {
          return { error: "advertiser_account_required" };
        }
        const requestReferer = this.scope === "ads_manager"
          ? tiktokAdsManagerReferer(tab.url || "", message.referer)
          : message.referer;
        const adsAccountContext = (
          this.scope === "ads_manager" &&
          Boolean(tiktokAdsManagerAdvertiserId(tab.url || ""))
        );
        if (
          !adsAccountContext &&
          !sameTikTokCreativeRequestContext(tab.url || "", requestReferer)
        ) {
          if (
            ["top_ads", "studio"].includes(this.scope) &&
            isTikTokCreativeProfileUrl(tab.url || "")
          ) {
            return { error: "profile_required" };
          }
          if (isTikTokCreativeScopeLoginUrl(tab.url || "", this.scope)) {
            return { error: "not_logged_in" };
          }
          throw new Error("tab_unavailable");
        }
        const session = await this.resolveSession(
          tab,
          signal,
          beginPlatformRequest
        );
        if (session.error) {
          return session;
        }
        if (session.payload.verification_required) {
          return { error: "verification_required" };
        }
        if (session.payload.profile_required) {
          return { error: "profile_required" };
        }
        if (!session.payload.request_ready) {
          return {
            error: session.payload.logged_in
              ? "runtime_unavailable"
              : "not_logged_in"
          };
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
          if (SESSION_INVALIDATING_ERRORS.has(result.error)) {
            this.sessionCache = null;
            if (
              ["not_logged_in", "csrf_or_signature_expired"].includes(
                result.error
              )
            ) {
              this.forceSessionProbe = true;
            }
          }
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
          error: [
            "advertiser_account_required",
            "tab_unavailable",
            "invalid_response"
          ].includes(code)
            ? code
            : code === "request_aborted"
              ? "request_failed"
              : "runtime_unavailable"
        };
      }
    };
    const interval = message.request_interval_ms || 0;
    const result = typeof this.requestPolicy.runWithoutRiskLatch === "function"
      ? await this.requestPolicy.runWithoutRiskLatch(signal, interval, operation)
      : typeof this.requestPolicy.runWithInterval === "function"
        ? await this.requestPolicy.runWithInterval(signal, interval, operation)
        : await this.requestPolicy.run(signal, operation);
    if (result && TRIPPING_ERRORS.has(result.error)) {
      this.trippedError = result.error;
    }
    return result;
  }

  async routeSession(message = {}, context = {}) {
    const signal = (context && context.signal) || (message && message.signal);
    const expectedURL = (
      isRecord(message) &&
      Object.prototype.hasOwnProperty.call(message, "referer")
    )
      ? message.referer
      : null;
    if (
      expectedURL !== null &&
      (
        typeof expectedURL !== "string" ||
        !this.validReferer(expectedURL)
      )
    ) {
      return { error: "invalid_request" };
    }
    const operation = async (beginPlatformRequest) => {
      try {
        throwIfAborted(signal);
        const tab = await this.pickTab(expectedURL, signal);
        if (
          this.scope === "ads_manager" &&
          isTikTokAdsManagerHomeUrl(tab.url || "")
        ) {
          return { error: "advertiser_account_required" };
        }
        if (
          ["top_ads", "studio"].includes(this.scope) &&
          isTikTokCreativeProfileUrl(tab.url || "")
        ) {
          return await this.resolveSession(
            tab,
            signal,
            beginPlatformRequest
          );
        }
        const validHashtagDetail = (
          this.scope === "hashtag" &&
          validTikTokCreativeHashtagDetailReferer(tab.url || "")
        );
        const adsAccountContext = (
          this.scope === "ads_manager" &&
          Boolean(tiktokAdsManagerAdvertiserId(tab.url || ""))
        );
        if (
          !adsAccountContext &&
          !this.validReferer(tab.url || "") &&
          !validHashtagDetail
        ) {
          return {
            payload: {
              fingerprint: {},
              logged_in: false,
              request_ready: false,
              verification_required: false,
              profile_required: false
            }
          };
        }
        return await this.resolveSession(tab, signal, beginPlatformRequest);
      } catch (error) {
        return {
          error: String(error && error.message) === "tab_unavailable"
            ? "tab_unavailable"
            : "runtime_unavailable"
        };
      }
    };
    const result = typeof this.requestPolicy.runWithoutRiskLatch === "function"
      ? await this.requestPolicy.runWithoutRiskLatch(signal, 0, operation)
      : typeof this.requestPolicy.runWithInterval === "function"
        ? await this.requestPolicy.runWithInterval(signal, 0, operation)
        : await this.requestPolicy.run(signal, operation);
    if (
      this.trippedError === "verification_required" &&
      result &&
      result.payload &&
      result.payload.request_ready === true
    ) {
      this.trippedError = "";
    }
    return result;
  }

  async allTabs() {
    return await this.chrome.tabs.query({
      url: TIKTOK_CREATIVE_TAB_PATTERNS
    });
  }

  async tabs() {
    const tabs = await this.allTabs();
    return tabs.filter((tab) => this.isScopeTab(tab.url || ""));
  }

  isScopeTab(value) {
    return (
      isTikTokCreativeScopeTabUrl(value, this.scope) ||
      (
        this.scope === "ads_manager" &&
        (
          Boolean(tiktokAdsManagerAdvertiserId(value)) ||
          isTikTokAdsManagerHomeUrl(value)
        )
      )
    );
  }

  async pickTab(expectedURL = null, signal = null) {
    throwIfAborted(signal);
    const tabs = await this.tabs();
    const stickyTab = tabs.find((item) => item.id === this.bridgeTabId);
    const adsAccountTab = this.scope === "ads_manager"
      ? (
        (
          stickyTab &&
          tiktokAdsManagerAdvertiserId(stickyTab.url || "")
        )
          ? stickyTab
          : tabs.find((item) =>
            tiktokAdsManagerAdvertiserId(item.url || "")
          )
      )
      : null;
    const tab = expectedURL
      ? (
        tabs.find((item) =>
          sameTikTokCreativeRequestContext(item.url || "", expectedURL)
        ) || adsAccountTab
      )
      : adsAccountTab ||
        stickyTab ||
        tabs.find((item) => item.active) ||
        tabs.find((item) => item.status === "complete") ||
        tabs[0];
    if (!tab) {
      if (
        expectedURL &&
        this.scope === "ads_manager" &&
        tabs.some((item) => isTikTokAdsManagerHomeUrl(item.url || ""))
      ) {
        throw new Error("advertiser_account_required");
      }
      throw new Error("tab_unavailable");
    }
    throwIfAborted(signal);
    if (!tab || !tab.id) {
      throw new Error("tab_unavailable");
    }
    this.bridgeTabId = tab.id;
    return tab;
  }

  async runInPage(tabId, input) {
    const tab = await this.chrome.tabs.get(tabId).catch(() => null);
    const sessionOperation =
      isRecord(input) &&
      ["session", "session_probe"].includes(input.kind);
    const validHashtagDetail = (
      this.scope === "hashtag" &&
      validTikTokCreativeHashtagDetailReferer(tab && tab.url || "")
    );
    const adsAccountContext = (
      this.scope === "ads_manager" &&
      Boolean(tiktokAdsManagerAdvertiserId(tab && tab.url || ""))
    );
    if (
      !tab ||
      (
        sessionOperation
          ? (
            !adsAccountContext &&
            !isTikTokCreativeScopeTabUrl(tab.url || "", this.scope)
          )
          : (
            !adsAccountContext &&
            !this.validReferer(tab.url || "") &&
            !validHashtagDetail
          )
      )
    ) {
      throw new Error("tab_unavailable");
    }
    if (tab.status && tab.status !== "complete") {
      throw new Error("runtime_unavailable");
    }
    const results = await this.chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      injectImmediately: true,
      func: invokeTikTokCreativePageRuntime,
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

  async resolveSession(tab, signal, beginPlatformRequest) {
    const cached = this.forceSessionProbe
      ? null
      : this.cachedSession(tab.id, tab.url || "");
    if (cached) {
      return { payload: cached };
    }
    let result = await this.runInPage(tab.id, {
      kind: "session",
      scope: this.scope
    });
    throwIfAborted(signal);
    if (result.ok !== true) {
      return {
        error: typeof result.error === "string"
          ? result.error
          : "request_failed"
      };
    }
    let payload = this.sessionPayload(result.payload);
    if (!payload) {
      return { error: "invalid_response" };
    }
    const probeRequired =
      this.forceSessionProbe ||
      (
        isRecord(result.payload) &&
        result.payload.probe_required === true
      );
    if (probeRequired) {
      if (typeof beginPlatformRequest !== "function") {
        return { error: "runtime_unavailable" };
      }
      await beginPlatformRequest();
      result = await this.runInPage(tab.id, {
        kind: "session_probe",
        scope: this.scope
      });
      throwIfAborted(signal);
      if (result.ok !== true) {
        return {
          error: typeof result.error === "string"
            ? result.error
            : "request_failed"
        };
      }
      payload = this.sessionPayload(result.payload);
      if (!payload) {
        return { error: "invalid_response" };
      }
      if (!payload.verification_required) {
        this.forceSessionProbe = false;
      }
    }
    this.cacheSession(tab.id, tab.url || "", payload);
    return { payload };
  }

  sessionContext(value) {
    if (this.scope === "top_ads") {
      if (isTikTokCreativeProfileUrl(value)) {
        return "profile";
      }
      if (validTikTokCreativeTopAdsLibraryReferer(value)) {
        return "library";
      }
      if (validTikTokCreativeTopAdsInsightReferer(value)) {
        return "insight";
      }
      if (validTikTokCreativeTopAdsV2Referer(value)) {
        return "v2";
      }
      return "";
    }
    if (this.scope === "studio") {
      if (isTikTokCreativeProfileUrl(value)) {
        return "profile";
      }
      return validTikTokCreativeStudioReferer(value) ? "studio" : "";
    }
    if (this.scope === "one") {
      return validTikTokOneCreatorReferer(value) ? "one" : "";
    }
    if (this.scope === "ads_manager") {
      if (tiktokAdsManagerAdvertiserId(value)) {
        return "ads_manager_account";
      }
      return validTikTokAdsKeywordPlannerReferer(value)
        ? "ads_manager"
        : "";
    }
    if (validTikTokCreativeHashtagReferer(value)) {
      return "hashtag";
    }
    return validTikTokCreativeTrendingVideoReferer(value)
      ? "trending_video"
      : "";
  }

  cachedSession(tabId, tabURL) {
    if (
      !this.sessionCache ||
      this.sessionCache.tabId !== tabId ||
      this.sessionCache.context !== this.sessionContext(tabURL) ||
      this.sessionCache.expiresAt <= this.now()
    ) {
      this.sessionCache = null;
      return null;
    }
    return this.sessionCache.payload;
  }

  cacheSession(tabId, tabURL, payload) {
    const ttl = payload.request_ready
      ? READY_SESSION_CACHE_MS
      : PENDING_SESSION_CACHE_MS;
    this.sessionCache = {
      tabId,
      context: this.sessionContext(tabURL),
      expiresAt: this.now() + ttl,
      payload
    };
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
    const verificationRequired = value.verification_required === true;
    const profileRequired = value.profile_required === true;
    if (
      (value.request_ready && !value.logged_in && this.scope !== "top_ads") ||
      (verificationRequired && value.request_ready) ||
      (
        profileRequired &&
        (
          verificationRequired ||
          !value.logged_in ||
          value.request_ready
        )
      )
    ) {
      return null;
    }
    return {
      fingerprint,
      logged_in: value.logged_in,
      request_ready: value.request_ready,
      verification_required: verificationRequired,
      profile_required: profileRequired
    };
  }
}
