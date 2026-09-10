// chrome.scripting 会将此函数序列化到页面的 MAIN world。
// Cookie、CSRF 和网页 GraphQL 操作 ID 只在当前 X 页面中使用。
export async function invokeTwitterPageRuntime(input) {
  const MAX_RESULT_BYTES = 6 * 1024 * 1024;
  const MAX_SCRIPT_COUNT = 40;
  const MAX_SCRIPT_BYTES = 1536 * 1024;
  const MAX_SCRIPT_TOTAL_BYTES = 6 * 1024 * 1024;
  const MAX_WEBPACK_MODULE_COUNT = 12000;
  const MAX_WEBPACK_TOTAL_BYTES = 8 * 1024 * 1024;
  const OPERATION_CACHE_KEY = Symbol.for(
    "browser-session-bridge.twitter.operations.v2"
  );
  const HOME_PATH = "/bridge/v1/twitter/home-feed";
  const SEARCH_PATH = "/bridge/v1/twitter/search-posts";
  const USER_PATH = "/bridge/v1/twitter/user";
  const USER_TWEETS_PATH = "/bridge/v1/twitter/user-tweets";
  const FOLLOWERS_PATH = "/bridge/v1/twitter/followers";
  const FOLLOWING_PATH = "/bridge/v1/twitter/following";
  const FEATURES_TABLE_KEY = Symbol.for(
    "browser-session-bridge.twitter.features.v1"
  );
  const FEATURES = {
    rweb_video_screen_enabled: false,
    rweb_cashtags_enabled: true,
    profile_label_improvements_pcf_label_in_post_enabled: true,
    responsive_web_profile_redirect_enabled: true,
    rweb_tipjar_consumption_enabled: false,
    verified_phone_label_enabled: false,
    creator_subscriptions_tweet_preview_api_enabled: true,
    responsive_web_graphql_timeline_navigation_enabled: true,
    premium_content_api_read_enabled: false,
    communities_web_enable_tweet_community_results_fetch: true,
    c9s_tweet_anatomy_moderator_badge_enabled: true,
    responsive_web_grok_analyze_button_fetch_trends_enabled: false,
    responsive_web_grok_analyze_post_followups_enabled: true,
    rweb_cashtags_composer_attachment_enabled: true,
    responsive_web_jetfuel_frame: true,
    responsive_web_grok_share_attachment_enabled: true,
    responsive_web_grok_annotations_enabled: true,
    articles_preview_enabled: true,
    responsive_web_edit_tweet_api_enabled: true,
    rweb_conversational_replies_downvote_enabled: false,
    graphql_is_translatable_rweb_tweet_is_translatable_enabled: true,
    view_counts_everywhere_api_enabled: true,
    longform_notetweets_consumption_enabled: true,
    responsive_web_twitter_article_tweet_consumption_enabled: true,
    content_disclosure_indicator_enabled: true,
    content_disclosure_ai_generated_indicator_enabled: true,
    responsive_web_grok_show_grok_translated_post: true,
    responsive_web_grok_analysis_button_from_backend: true,
    post_ctas_fetch_enabled: false,
    freedom_of_speech_not_reach_fetch_enabled: true,
    standardized_nudges_misinfo: true,
    tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled: true,
    longform_notetweets_rich_text_read_enabled: true,
    longform_notetweets_inline_media_enabled: false,
    responsive_web_grok_image_annotation_enabled: true,
    responsive_web_grok_imagine_annotation_enabled: true,
    responsive_web_grok_community_note_auto_translation_is_enabled: true,
    responsive_web_enhance_cards_enabled: false
  };
  // 2026-09-08 在已登录 pathname=/home 上取证：UserByScreenName queryId
  // 与 client-web/main 模块一致；features/fieldToggles 来自同模块 featureSwitches。
  const USER_GRAPHQL_FEATURES_CAPTURED = {
  "UserByScreenName": {
    "hidden_profile_subscriptions_enabled": true,
    "profile_label_improvements_pcf_label_in_post_enabled": true,
    "responsive_web_profile_redirect_enabled": true,
    "rweb_tipjar_consumption_enabled": false,
    "verified_phone_label_enabled": false,
    "subscriptions_verification_info_is_identity_verified_enabled": true,
    "subscriptions_verification_info_verified_since_enabled": true,
    "highlights_tweets_tab_ui_enabled": true,
    "responsive_web_twitter_article_notes_tab_enabled": true,
    "subscriptions_feature_can_gift_premium": true,
    "creator_subscriptions_tweet_preview_api_enabled": true,
    "responsive_web_graphql_timeline_navigation_enabled": true
  },
  "UserByRestId": {
    "hidden_profile_subscriptions_enabled": true,
    "profile_label_improvements_pcf_label_in_post_enabled": true,
    "responsive_web_profile_redirect_enabled": true,
    "rweb_tipjar_consumption_enabled": false,
    "verified_phone_label_enabled": false,
    "highlights_tweets_tab_ui_enabled": true,
    "responsive_web_twitter_article_notes_tab_enabled": true,
    "subscriptions_feature_can_gift_premium": true,
    "creator_subscriptions_tweet_preview_api_enabled": true,
    "responsive_web_graphql_timeline_navigation_enabled": true
  },
  "UserTweets": {
    "rweb_video_screen_enabled": false,
    "rweb_cashtags_enabled": true,
    "profile_label_improvements_pcf_label_in_post_enabled": true,
    "responsive_web_profile_redirect_enabled": true,
    "rweb_tipjar_consumption_enabled": false,
    "verified_phone_label_enabled": false,
    "creator_subscriptions_tweet_preview_api_enabled": true,
    "responsive_web_graphql_timeline_navigation_enabled": true,
    "premium_content_api_read_enabled": false,
    "communities_web_enable_tweet_community_results_fetch": true,
    "c9s_tweet_anatomy_moderator_badge_enabled": true,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": false,
    "responsive_web_grok_analyze_post_followups_enabled": true,
    "rweb_cashtags_composer_attachment_enabled": true,
    "responsive_web_jetfuel_frame": true,
    "responsive_web_grok_share_attachment_enabled": true,
    "responsive_web_grok_annotations_enabled": true,
    "articles_preview_enabled": true,
    "responsive_web_edit_tweet_api_enabled": true,
    "rweb_conversational_replies_downvote_enabled": false,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": true,
    "view_counts_everywhere_api_enabled": true,
    "longform_notetweets_consumption_enabled": true,
    "responsive_web_twitter_article_tweet_consumption_enabled": true,
    "content_disclosure_indicator_enabled": true,
    "content_disclosure_ai_generated_indicator_enabled": true,
    "responsive_web_grok_show_grok_translated_post": true,
    "responsive_web_grok_analysis_button_from_backend": true,
    "post_ctas_fetch_enabled": false,
    "freedom_of_speech_not_reach_fetch_enabled": true,
    "standardized_nudges_misinfo": true,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": true,
    "longform_notetweets_rich_text_read_enabled": true,
    "longform_notetweets_inline_media_enabled": false,
    "responsive_web_grok_image_annotation_enabled": true,
    "responsive_web_grok_imagine_annotation_enabled": true,
    "responsive_web_grok_community_note_auto_translation_is_enabled": true,
    "responsive_web_enhance_cards_enabled": false
  },
  "Followers": {
    "rweb_video_screen_enabled": false,
    "rweb_cashtags_enabled": true,
    "profile_label_improvements_pcf_label_in_post_enabled": true,
    "responsive_web_profile_redirect_enabled": true,
    "rweb_tipjar_consumption_enabled": false,
    "verified_phone_label_enabled": false,
    "creator_subscriptions_tweet_preview_api_enabled": true,
    "responsive_web_graphql_timeline_navigation_enabled": true,
    "premium_content_api_read_enabled": false,
    "communities_web_enable_tweet_community_results_fetch": true,
    "c9s_tweet_anatomy_moderator_badge_enabled": true,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": false,
    "responsive_web_grok_analyze_post_followups_enabled": true,
    "rweb_cashtags_composer_attachment_enabled": true,
    "responsive_web_jetfuel_frame": true,
    "responsive_web_grok_share_attachment_enabled": true,
    "responsive_web_grok_annotations_enabled": true,
    "articles_preview_enabled": true,
    "responsive_web_edit_tweet_api_enabled": true,
    "rweb_conversational_replies_downvote_enabled": false,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": true,
    "view_counts_everywhere_api_enabled": true,
    "longform_notetweets_consumption_enabled": true,
    "responsive_web_twitter_article_tweet_consumption_enabled": true,
    "content_disclosure_indicator_enabled": true,
    "content_disclosure_ai_generated_indicator_enabled": true,
    "responsive_web_grok_show_grok_translated_post": true,
    "responsive_web_grok_analysis_button_from_backend": true,
    "post_ctas_fetch_enabled": false,
    "freedom_of_speech_not_reach_fetch_enabled": true,
    "standardized_nudges_misinfo": true,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": true,
    "longform_notetweets_rich_text_read_enabled": true,
    "longform_notetweets_inline_media_enabled": false,
    "responsive_web_grok_image_annotation_enabled": true,
    "responsive_web_grok_imagine_annotation_enabled": true,
    "responsive_web_grok_community_note_auto_translation_is_enabled": true,
    "responsive_web_enhance_cards_enabled": false
  },
  "Following": {
    "rweb_video_screen_enabled": false,
    "rweb_cashtags_enabled": true,
    "profile_label_improvements_pcf_label_in_post_enabled": true,
    "responsive_web_profile_redirect_enabled": true,
    "rweb_tipjar_consumption_enabled": false,
    "verified_phone_label_enabled": false,
    "creator_subscriptions_tweet_preview_api_enabled": true,
    "responsive_web_graphql_timeline_navigation_enabled": true,
    "premium_content_api_read_enabled": false,
    "communities_web_enable_tweet_community_results_fetch": true,
    "c9s_tweet_anatomy_moderator_badge_enabled": true,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": false,
    "responsive_web_grok_analyze_post_followups_enabled": true,
    "rweb_cashtags_composer_attachment_enabled": true,
    "responsive_web_jetfuel_frame": true,
    "responsive_web_grok_share_attachment_enabled": true,
    "responsive_web_grok_annotations_enabled": true,
    "articles_preview_enabled": true,
    "responsive_web_edit_tweet_api_enabled": true,
    "rweb_conversational_replies_downvote_enabled": false,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": true,
    "view_counts_everywhere_api_enabled": true,
    "longform_notetweets_consumption_enabled": true,
    "responsive_web_twitter_article_tweet_consumption_enabled": true,
    "content_disclosure_indicator_enabled": true,
    "content_disclosure_ai_generated_indicator_enabled": true,
    "responsive_web_grok_show_grok_translated_post": true,
    "responsive_web_grok_analysis_button_from_backend": true,
    "post_ctas_fetch_enabled": false,
    "freedom_of_speech_not_reach_fetch_enabled": true,
    "standardized_nudges_misinfo": true,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": true,
    "longform_notetweets_rich_text_read_enabled": true,
    "longform_notetweets_inline_media_enabled": false,
    "responsive_web_grok_image_annotation_enabled": true,
    "responsive_web_grok_imagine_annotation_enabled": true,
    "responsive_web_grok_community_note_auto_translation_is_enabled": true,
    "responsive_web_enhance_cards_enabled": false
  }
};
  const USER_GRAPHQL_FIELD_TOGGLES_CAPTURED = {
  "UserByScreenName": {
    "withPayments": false,
    "withAuxiliaryUserLabels": false
  },
  "UserByRestId": {
    "withPayments": false,
    "withAuxiliaryUserLabels": false
  },
  "UserTweets": {
    "withPayments": false,
    "withAuxiliaryUserLabels": false,
    "withArticleRichContentState": false,
    "withArticlePlainText": false,
    "withArticleSummaryText": false,
    "withArticleVoiceOver": false,
    "withGrokAnalyze": false,
    "withDisallowedReplyControls": false
  },
  "Followers": {
    "withPayments": false,
    "withAuxiliaryUserLabels": false,
    "withArticleRichContentState": false,
    "withArticlePlainText": false,
    "withArticleSummaryText": false,
    "withArticleVoiceOver": false,
    "withGrokAnalyze": false,
    "withDisallowedReplyControls": false
  },
  "Following": {
    "withPayments": false,
    "withAuxiliaryUserLabels": false,
    "withArticleRichContentState": false,
    "withArticlePlainText": false,
    "withArticleSummaryText": false,
    "withArticleVoiceOver": false,
    "withGrokAnalyze": false,
    "withDisallowedReplyControls": false
  }
};

  const FEATURES_BY_OPERATION = {
    HomeTimeline: FEATURES,
    SearchTimeline: FEATURES,
    ...USER_GRAPHQL_FEATURES_CAPTURED
  };
  const FIELD_TOGGLES_BY_OPERATION = USER_GRAPHQL_FIELD_TOGGLES_CAPTURED;

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function response(value) {
    try {
      const size = new TextEncoder().encode(JSON.stringify(value)).byteLength;
      return size <= MAX_RESULT_BYTES
        ? value
        : { ok: false, error: "response_too_large" };
    } catch {
      return { ok: false, error: "invalid_response" };
    }
  }

  function visible(element) {
    if (!element || typeof element.getBoundingClientRect !== "function") {
      return false;
    }
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return (
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      Number(style.opacity || "1") !== 0 &&
      rect.width > 0 &&
      rect.height > 0
    );
  }

  function verificationRequired() {
    for (const selector of [
      "#arkose",
      "[data-testid='ocfEnterTextTextInput']",
      "iframe[src*='arkoselabs']",
      "iframe[src*='captcha']",
      "[class*='captcha']"
    ]) {
      for (const candidate of Array.from(
        document.querySelectorAll(selector)
      ).slice(0, 20)) {
        if (visible(candidate)) {
          return true;
        }
      }
    }
    return false;
  }

  function cookie(name) {
    const prefix = `${name}=`;
    for (const part of String(document.cookie || "").split(";")) {
      const item = part.trim();
      if (item.startsWith(prefix)) {
        return decodeURIComponent(item.slice(prefix.length));
      }
    }
    return "";
  }

  function restIdFromTwid() {
    const raw = String(cookie("twid") || "").replace(/^"|"$/g, "");
    const matched = /^u=(\d{1,20})$/.exec(raw) || /^(\d{1,20})$/.exec(raw);
    return matched ? matched[1] : "";
  }

  function featuresTable() {
    const override = globalThis[FEATURES_TABLE_KEY];
    return isRecord(override) ? override : FEATURES_BY_OPERATION;
  }

  function loggedIn() {
    if (/^\/i\/flow\/(?:login|signup)/.test(location.pathname)) {
      return false;
    }
    return Boolean(
      cookie("ct0") ||
      document.querySelector("[data-testid='AppTabBar_Home_Link']") ||
      document.querySelector("[data-testid='SideNav_AccountSwitcher_Button']")
    );
  }

  function sessionPayload() {
    return {
      logged_in: loggedIn(),
      verification_required: verificationRequired(),
      fingerprint: {
        origin: location.origin,
        pathname: location.pathname,
        language: navigator.language || "",
        cookie_enabled: navigator.cookieEnabled === true
      }
    };
  }

  function entriesObject(entries) {
    const result = {};
    for (const entry of Array.isArray(entries) ? entries : []) {
      if (
        !Array.isArray(entry) ||
        entry.length !== 2 ||
        typeof entry[0] !== "string" ||
        typeof entry[1] !== "string" ||
        Object.hasOwn(result, entry[0])
      ) {
        return null;
      }
      result[entry[0]] = entry[1];
    }
    return result;
  }

  function validQueryId(value) {
    return /^[A-Za-z0-9_-]{8,64}$/.test(String(value || ""));
  }

  function operationCache() {
    const current = globalThis[OPERATION_CACHE_KEY];
    if (isRecord(current)) {
      return current;
    }
    const created = {};
    try {
      Object.defineProperty(globalThis, OPERATION_CACHE_KEY, {
        configurable: true,
        value: created
      });
    } catch {
      // 页面禁止扩展全局对象时，本次调用仍可继续完成扫描。
    }
    return created;
  }

  function operationFromQueryId(operationName, queryId) {
    if (!validQueryId(queryId)) {
      return null;
    }
    return new URL(
      `/i/api/graphql/${queryId}/${operationName}`,
      location.origin
    );
  }

  function operationFromResources(operationName) {
    const suffix = `/${operationName}`;
    const entries = performance.getEntriesByType("resource");
    for (let index = entries.length - 1; index >= 0; index -= 1) {
      const name = String(entries[index]?.name || "");
      if (!name.includes("/i/api/graphql/") || !name.split("?")[0].endsWith(suffix)) {
        continue;
      }
      try {
        const parsed = new URL(name);
        if (parsed.origin === location.origin) {
          const queryId = parsed.pathname.split("/").at(-2) || "";
          if (validQueryId(queryId)) {
            operationCache()[operationName] = queryId;
          }
          return parsed;
        }
      } catch {
        // 忽略失效的 PerformanceResourceTiming。
      }
    }
    return null;
  }

  function queryIdFromSource(source, operationName) {
    const escapedName = operationName.replace(
      /[.*+?^${}()|[\]\\]/g,
      "\\$&"
    );
    const queryId = "[\"']([A-Za-z0-9_-]{8,64})[\"']";
    const name = `[\"']${escapedName}[\"']`;
    const pattern = new RegExp(
      `[\"']?queryId[\"']?\\s*:\\s*${queryId}` +
      `\\s*,\\s*[\"']?operationName[\"']?\\s*:\\s*${name}`
    );
    const match = pattern.exec(source);
    if (validQueryId(match?.[1])) {
      return match[1];
    }
    return "";
  }

  function cacheFeaturesFromSource(source, operationName, cache) {
    const key = `features:${operationName}`;
    if (isRecord(cache[key]) && Object.keys(cache[key]).length > 0) {
      return;
    }
    const marker = `"${operationName}"`;
    const alt = `'${operationName}'`;
    let index = source.indexOf(marker);
    if (index < 0) {
      index = source.indexOf(alt);
    }
    const windowed = index < 0
      ? source
      : source.slice(Math.max(0, index - 5000), index + 8000);
    const match = /featureSwitches"\s*:\s*\[([^\]]{0,12000})\]/.exec(windowed);
    if (!match) {
      return;
    }
    const names = [...match[1].matchAll(/"([^"]+)"/g)].map((item) => item[1]);
    if (!names.length) {
      return;
    }
    const features = {};
    for (const name of names) {
      features[name] = Object.hasOwn(FEATURES, name) ? FEATURES[name] : true;
    }
    cache[key] = features;
    const toggleMatch = /fieldToggles"\s*:\s*\[([^\]]{0,4000})\]/.exec(windowed);
    if (toggleMatch) {
      const toggles = {};
      for (const item of toggleMatch[1].matchAll(/"([^"]+)"/g)) {
        toggles[item[1]] = false;
      }
      if (Object.keys(toggles).length > 0) {
        cache[`fieldToggles:${operationName}`] = toggles;
      }
    }
  }

  function rememberOperation(source, operationName, queryId, cache) {
    cache[operationName] = queryId;
    cacheFeaturesFromSource(source, operationName, cache);
    return operationFromQueryId(operationName, queryId);
  }

  function bearerTokenFromSource(source) {
    const match = /Bearer (A{10,}[A-Za-z0-9_%=-]{60,180})/.exec(source);
    const token = String(match?.[1] || "");
    return /^A{10,}[A-Za-z0-9_%=-]{60,180}$/.test(token)
      ? token
      : "";
  }

  function transactionModuleIdFromSource(source) {
    const marker = source.indexOf("rweb_client_transaction_id_enabled");
    if (marker < 0) {
      return null;
    }
    const prefix = source.slice(Math.max(0, marker - 1800), marker);
    const pattern =
      /},([0-9]{3,8})\([A-Za-z_$][\w$]*,[A-Za-z_$][\w$]*,[A-Za-z_$][\w$]*\)\{/g;
    let moduleId = null;
    for (const match of prefix.matchAll(pattern)) {
      moduleId = Number(match[1]);
    }
    return Number.isSafeInteger(moduleId) && moduleId > 0
      ? moduleId
      : null;
  }

  function cacheRuntimeMetadata(source, cache) {
    const bearerToken = bearerTokenFromSource(source);
    if (bearerToken) {
      cache.bearerToken = bearerToken;
    }
    const transactionModuleId = transactionModuleIdFromSource(source);
    if (transactionModuleId) {
      cache.transactionModuleId = transactionModuleId;
    }
  }

  function webpackRequireFromPage() {
    const chunks = globalThis.webpackChunk_twitter_responsive_web;
    if (!Array.isArray(chunks) || typeof chunks.push !== "function") {
      return null;
    }
    let webpackRequire = null;
    const chunkId =
      `browser_session_bridge_${Date.now()}_` +
      Math.random().toString(36).slice(2);
    chunks.push([
      [chunkId],
      {},
      (runtime) => {
        webpackRequire = runtime;
      }
    ]);
    return typeof webpackRequire === "function"
      ? webpackRequire
      : null;
  }

  function operationFromWebpackModules(operationName) {
    const webpackRequire = webpackRequireFromPage();
    const factories = isRecord(webpackRequire?.m)
      ? webpackRequire.m
      : null;
    if (!factories) {
      return null;
    }
    const cache = operationCache();
    let inspected = 0;
    let totalBytes = 0;
    for (const [moduleId, factory] of Object.entries(factories)) {
      if (
        inspected >= MAX_WEBPACK_MODULE_COUNT ||
        totalBytes >= MAX_WEBPACK_TOTAL_BYTES
      ) {
        break;
      }
      if (typeof factory !== "function") {
        continue;
      }
      inspected += 1;
      const source = Function.prototype.toString.call(factory);
      totalBytes += source.length;
      if (totalBytes > MAX_WEBPACK_TOTAL_BYTES) {
        break;
      }
      const bearerToken = bearerTokenFromSource(source);
      if (bearerToken) {
        cache.bearerToken = bearerToken;
      }
      if (source.includes("rweb_client_transaction_id_enabled")) {
        const numericModuleId = Number(moduleId);
        if (Number.isSafeInteger(numericModuleId) && numericModuleId > 0) {
          cache.transactionModuleId = numericModuleId;
        }
      }
      const queryId = queryIdFromSource(source, operationName);
      if (queryId) {
        return rememberOperation(source, operationName, queryId, cache);
      }
    }
    return null;
  }

  function parseClientWebURL(value) {
    try {
      const parsed = new URL(String(value || ""), location.href);
      const supportedHost =
        parsed.origin === location.origin ||
        parsed.hostname === "abs.twimg.com";
      if (
        parsed.protocol === "https:" &&
        supportedHost &&
        parsed.pathname.includes("/responsive-web/client-web/")
      ) {
        return parsed.href;
      }
    } catch {
      // 忽略失效的 client-web 地址。
    }
    return "";
  }

  function rankClientWebURL(url, operationName) {
    const value = url.toLowerCase();
    if (value.includes(operationName.toLowerCase())) {
      return 0;
    }
    if (/\/main\.[^/]+\.js(?:\?|$)/.test(value)) {
      return 1;
    }
    return 2;
  }

  function takeRankedClientWebURLs(urls, operationName) {
    return urls
      .map((url, index) => ({
        url,
        index,
        rank: rankClientWebURL(url, operationName)
      }))
      .sort((left, right) =>
        left.rank - right.rank || left.index - right.index
      )
      .slice(0, MAX_SCRIPT_COUNT)
      .map((item) => item.url);
  }

  function operationScriptURLs(operationName) {
    const seen = new Set();
    const urls = [];
    const add = (value) => {
      const href = parseClientWebURL(value);
      if (!href || seen.has(href)) {
        return;
      }
      seen.add(href);
      urls.push(href);
    };
    for (const node of Array.from(document.scripts || [])) {
      add(node?.src);
    }
    for (const entry of performance.getEntriesByType("resource")) {
      add(entry?.name);
    }
    return takeRankedClientWebURLs(urls, operationName);
  }

  async function readBoundedScript(url, byteLimit) {
    const upstream = await fetch(url, {
      method: "GET",
      credentials: "omit",
      cache: "force-cache"
    });
    if (!upstream.ok) {
      return null;
    }
    const contentLength = Number(upstream.headers?.get?.("content-length"));
    if (
      Number.isFinite(contentLength) &&
      contentLength > 0 &&
      contentLength > byteLimit
    ) {
      return null;
    }
    if (upstream.body && typeof upstream.body.getReader === "function") {
      const reader = upstream.body.getReader();
      const decoder = new TextDecoder();
      let bytes = 0;
      let text = "";
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) {
          text += decoder.decode();
          return { bytes, text };
        }
        bytes += chunk.value.byteLength;
        if (bytes > byteLimit) {
          await reader.cancel().catch(() => undefined);
          return null;
        }
        text += decoder.decode(chunk.value, { stream: true });
      }
    }
    const text = await upstream.text();
    const bytes = new TextEncoder().encode(text).byteLength;
    return bytes <= byteLimit ? { bytes, text } : null;
  }

  async function operationFromScripts(operationName) {
    const cache = operationCache();
    const cached = operationFromQueryId(
      operationName,
      cache[operationName]
    );
    if (cached) {
      return cached;
    }
    let remainingBytes = MAX_SCRIPT_TOTAL_BYTES;
    for (const url of operationScriptURLs(operationName)) {
      if (remainingBytes <= 0) {
        break;
      }
      try {
        const script = await readBoundedScript(
          url,
          Math.min(MAX_SCRIPT_BYTES, remainingBytes)
        );
        if (!script) {
          continue;
        }
        remainingBytes -= script.bytes;
        cacheRuntimeMetadata(script.text, cache);
        const queryId = queryIdFromSource(script.text, operationName);
        if (queryId) {
          return rememberOperation(script.text, operationName, queryId, cache);
        }
      } catch {
        // 单个脚本读取失败不影响扫描其他已加载脚本。
      }
    }
    return null;
  }

  function loadedClientWebHrefs() {
    const loaded = new Set();
    for (const node of Array.from(document.scripts || [])) {
      const href = parseClientWebURL(node?.src);
      if (href) {
        loaded.add(href);
      }
    }
    return loaded;
  }

  function urlsFromWebpackChunkFunction(webpackRequire) {
    if (typeof webpackRequire?.u !== "function") {
      return [];
    }
    const urls = [];
    const publicPath = typeof webpackRequire.p === "string"
      ? webpackRequire.p
      : "";
    const source = Function.prototype.toString.call(webpackRequire.u);
    const ids = [];
    for (const match of source.matchAll(/[{,]\s*["']?(\d+)["']?\s*:/g)) {
      ids.push(match[1]);
    }
    for (const id of ids) {
      try {
        const file = webpackRequire.u(id);
        if (typeof file === "string" && file) {
          urls.push(new URL(file, publicPath || location.origin).href);
        }
      } catch {
        // 忽略无法解析的 chunk 文件名。
      }
    }
    for (const match of source.matchAll(/["']([^"']+\.js(?:\?[^"']*)?)["']/g)) {
      try {
        urls.push(new URL(match[1], publicPath || location.origin).href);
      } catch {
        // 忽略源码中的失效路径。
      }
    }
    return urls;
  }

  function unloadedClientWebURLs(operationName) {
    const seen = loadedClientWebHrefs();
    const urls = [];
    const add = (value) => {
      const href = parseClientWebURL(value);
      if (!href || seen.has(href)) {
        return;
      }
      seen.add(href);
      urls.push(href);
    };
    for (const node of Array.from(
      document.querySelectorAll(
        'link[rel="preload"],link[rel="modulepreload"],link[rel="prefetch"]'
      ) || []
    )) {
      add(node.href || node.getAttribute?.("href") || "");
    }
    const webpackRequire = webpackRequireFromPage();
    if (webpackRequire) {
      for (const url of urlsFromWebpackChunkFunction(webpackRequire)) {
        add(url);
      }
    }
    for (const entry of performance.getEntriesByType("resource")) {
      add(entry?.name);
    }
    return takeRankedClientWebURLs(urls, operationName);
  }

  async function operationFromUnloadedChunks(operationName) {
    const cache = operationCache();
    let remainingBytes = MAX_SCRIPT_TOTAL_BYTES;
    for (const url of unloadedClientWebURLs(operationName)) {
      if (remainingBytes <= 0) {
        break;
      }
      try {
        const script = await readBoundedScript(
          url,
          Math.min(MAX_SCRIPT_BYTES, remainingBytes)
        );
        if (!script) {
          continue;
        }
        remainingBytes -= script.bytes;
        cacheRuntimeMetadata(script.text, cache);
        const queryId = queryIdFromSource(script.text, operationName);
        if (queryId) {
          return rememberOperation(script.text, operationName, queryId, cache);
        }
      } catch {
        // 未加载 chunk 读取失败不影响扫描其他 URL。
      }
    }
    return null;
  }

  async function bearerTokenFromScripts() {
    const cache = operationCache();
    if (bearerTokenFromSource(`Bearer ${cache.bearerToken || ""}`)) {
      return cache.bearerToken;
    }
    let remainingBytes = MAX_SCRIPT_TOTAL_BYTES;
    for (const url of operationScriptURLs("Bearer")) {
      if (remainingBytes <= 0) {
        break;
      }
      try {
        const script = await readBoundedScript(
          url,
          Math.min(MAX_SCRIPT_BYTES, remainingBytes)
        );
        if (!script) {
          continue;
        }
        remainingBytes -= script.bytes;
        cacheRuntimeMetadata(script.text, cache);
        const token = bearerTokenFromSource(script.text);
        if (token) {
          cache.bearerToken = token;
          return token;
        }
      } catch {
        // 单个脚本读取失败不影响扫描其他已加载脚本。
      }
    }
    return "";
  }

  async function transactionModuleIdFromScripts() {
    const cache = operationCache();
    if (
      Number.isSafeInteger(cache.transactionModuleId) &&
      cache.transactionModuleId > 0
    ) {
      return cache.transactionModuleId;
    }
    let remainingBytes = MAX_SCRIPT_TOTAL_BYTES;
    for (const url of operationScriptURLs("transaction")) {
      if (remainingBytes <= 0) {
        break;
      }
      try {
        const script = await readBoundedScript(
          url,
          Math.min(MAX_SCRIPT_BYTES, remainingBytes)
        );
        if (!script) {
          continue;
        }
        remainingBytes -= script.bytes;
        cacheRuntimeMetadata(script.text, cache);
        if (
          Number.isSafeInteger(cache.transactionModuleId) &&
          cache.transactionModuleId > 0
        ) {
          return cache.transactionModuleId;
        }
      } catch {
        // 单个脚本读取失败不影响扫描其他已加载脚本。
      }
    }
    return null;
  }

  async function transactionId(method, operation) {
    const moduleId = await transactionModuleIdFromScripts();
    if (!moduleId) {
      return "";
    }
    const webpackRequire = webpackRequireFromPage();
    if (!webpackRequire) {
      return "";
    }
    const generator = webpackRequire(moduleId)?.kc;
    if (typeof generator !== "function") {
      return "";
    }
    const value = await generator(
      location.hostname,
      operation.pathname,
      method
    );
    return typeof value === "string" && /^[A-Za-z0-9+/=_-]{20,256}$/.test(value)
      ? value
      : "";
  }

  function isUserGraphOperation(operationName) {
    return (
      operationName === "UserByScreenName" ||
      operationName === "UserByRestId" ||
      operationName === "UserTweets" ||
      operationName === "Followers" ||
      operationName === "Following"
    );
  }

  async function discoverOperation(operationName) {
    const found = operationFromResources(operationName);
    if (found) {
      return found;
    }
    // home 页已加载的 webpack 里通常没有 User* 模块；先扫脚本/未加载 chunk，
    // 避免 上万 factory toString 把 35s 超时吃光、extra-fetch 根本跑不到。
    if (!isUserGraphOperation(operationName)) {
      const moduleOperation = operationFromWebpackModules(operationName);
      if (moduleOperation) {
        return moduleOperation;
      }
    }
    const scriptOperation = await operationFromScripts(operationName);
    if (scriptOperation) {
      return scriptOperation;
    }
    const unloaded = await operationFromUnloadedChunks(operationName);
    if (unloaded) {
      return unloaded;
    }
    if (isUserGraphOperation(operationName)) {
      return operationFromWebpackModules(operationName);
    }
    return null;
  }

  async function requestHeaders(
    operation,
    method,
    includeContentType = false
  ) {
    const csrf = cookie("ct0");
    const [bearerToken, clientTransactionId] = await Promise.all([
      bearerTokenFromScripts(),
      transactionId(method, operation)
    ]);
    if (!csrf || !bearerToken || !clientTransactionId) {
      return null;
    }
    const headers = {
      accept: "*/*",
      authorization: `Bearer ${bearerToken}`,
      "x-client-transaction-id": clientTransactionId,
      "x-csrf-token": csrf,
      "x-twitter-active-user": "yes",
      "x-twitter-auth-type": "OAuth2Session",
      "x-twitter-client-language": navigator.language || "en"
    };
    if (includeContentType) {
      headers["content-type"] = "application/json";
    }
    return headers;
  }

  function rateLimit(upstream) {
    const integer = (name) => {
      const value = upstream.headers.get(name);
      return value && /^[0-9]+$/.test(value) ? Number(value) : null;
    };
    return {
      limit: integer("x-rate-limit-limit"),
      remaining: integer("x-rate-limit-remaining"),
      reset: integer("x-rate-limit-reset")
    };
  }

  async function parseUpstream(upstream, operationName) {
    if (upstream.status === 401) {
      return { ok: false, error: "not_logged_in" };
    }
    if (upstream.status === 403) {
      return { ok: false, error: "forbidden" };
    }
    if (upstream.status === 429) {
      return { ok: false, error: "rate_limited" };
    }
    if (upstream.status === 404) {
      delete operationCache()[operationName];
      return { ok: false, error: "runtime_unavailable" };
    }
    if (upstream.status >= 400 && upstream.status < 500) {
      return { ok: false, error: "invalid_response" };
    }
    if (!upstream.ok) {
      return { ok: false, error: "request_failed" };
    }
    let payload;
    try {
      payload = await upstream.json();
    } catch {
      return { ok: false, error: "invalid_response" };
    }
    if (!isRecord(payload) || !isRecord(payload.data)) {
      return { ok: false, error: "invalid_response" };
    }
    return response({
      ok: true,
      payload: {
        source: "twitter_web_graphql",
        transport: "browser_web",
        endpoint: new URL(upstream.url).pathname,
        operation: operationName,
        rate_limit: rateLimit(upstream),
        data: payload.data
      }
    });
  }

  function restIdFromEntries(values) {
    if (values.user_id) {
      return values.user_id;
    }
    if (values.screen_name === "me") {
      return restIdFromTwid();
    }
    return "";
  }

  function encodedFeatures(operationName, operation) {
    const fromUrl = operation.searchParams.get("features");
    if (fromUrl) {
      return fromUrl;
    }
    const mapped = featuresTable()[operationName];
    if (isRecord(mapped) && Object.keys(mapped).length > 0) {
      return JSON.stringify(mapped);
    }
    const discovered = operationCache()[`features:${operationName}`];
    if (isRecord(discovered) && Object.keys(discovered).length > 0) {
      return JSON.stringify(discovered);
    }
    return "";
  }

  function encodedFieldToggles(operationName, operation) {
    const fromUrl = operation.searchParams.get("fieldToggles");
    if (fromUrl) {
      return fromUrl;
    }
    if (Object.hasOwn(FIELD_TOGGLES_BY_OPERATION, operationName)) {
      return JSON.stringify(FIELD_TOGGLES_BY_OPERATION[operationName]);
    }
    const discovered = operationCache()[`fieldToggles:${operationName}`];
    if (isRecord(discovered) && Object.keys(discovered).length > 0) {
      return JSON.stringify(discovered);
    }
    return "";
  }

  function isUserGraphList(operationName) {
    return (
      operationName === "UserTweets" ||
      operationName === "Followers" ||
      operationName === "Following"
    );
  }

  async function graphqlRequest(operationName, variables) {
    const operation = await discoverOperation(operationName);
    if (!operation) {
      return { ok: false, error: "runtime_unavailable" };
    }
    const featureParam = encodedFeatures(operationName, operation);
    if (!featureParam) {
      return { ok: false, error: "runtime_unavailable" };
    }
    const method = isUserGraphList(operationName) ? "POST" : "GET";
    const headers = await requestHeaders(operation, method, true);
    if (!headers) {
      return { ok: false, error: "runtime_unavailable" };
    }
    const queryId = operation.pathname.split("/").at(-2) || "";
    if (!validQueryId(queryId)) {
      return { ok: false, error: "runtime_unavailable" };
    }
    const toggleParam = encodedFieldToggles(operationName, operation);
    let upstream;
    if (method === "POST") {
      let features;
      try {
        features = JSON.parse(featureParam);
      } catch {
        return { ok: false, error: "runtime_unavailable" };
      }
      const body = { variables, features, queryId };
      if (toggleParam) {
        try {
          body.fieldToggles = JSON.parse(toggleParam);
        } catch {
          // 无 fieldToggles 仍可发请求。
        }
      }
      upstream = await fetch(operation.origin + operation.pathname, {
        method: "POST",
        credentials: "include",
        cache: "no-store",
        headers,
        body: JSON.stringify(body)
      });
    } else {
      const target = new URL(operation.origin + operation.pathname);
      target.searchParams.set("variables", JSON.stringify(variables));
      target.searchParams.set("features", featureParam);
      if (toggleParam) {
        target.searchParams.set("fieldToggles", toggleParam);
      }
      upstream = await fetch(target.toString(), {
        method: "GET",
        credentials: "include",
        cache: "no-store",
        headers
      });
    }
    return parseUpstream(upstream, operationName);
  }

  async function userProfile(values) {
    if (values.user_id) {
      return graphqlRequest("UserByRestId", { userId: values.user_id });
    }
    if (values.screen_name === "me") {
      const userId = restIdFromTwid();
      if (!userId) {
        return { ok: false, error: "not_logged_in" };
      }
      return graphqlRequest("UserByRestId", { userId });
    }
    return graphqlRequest("UserByScreenName", {
      screen_name: values.screen_name
    });
  }

  async function userGraph(operationName, values) {
    const userId = restIdFromEntries(values);
    if (!userId) {
      return {
        ok: false,
        error: values.screen_name === "me" ? "not_logged_in" : "invalid_request"
      };
    }
    const variables = {
      userId,
      count: Number(values.count),
      includePromotedContent: operationName === "UserTweets"
    };
    if (operationName === "UserTweets") {
      variables.withQuickPromoteEligibilityTweetFields = true;
      variables.withVoice = true;
      variables.withV2Timeline = true;
    }
    if (values.cursor) {
      variables.cursor = values.cursor;
    }
    return graphqlRequest(operationName, variables);
  }

  async function homeTimeline(values) {
    const operation = await discoverOperation("HomeTimeline");
    if (!operation) {
      return { ok: false, error: "runtime_unavailable" };
    }
    const headers = await requestHeaders(operation, "POST", true);
    if (!headers) {
      return { ok: false, error: "runtime_unavailable" };
    }
    const segments = operation.pathname.split("/");
    const queryId = segments.at(-2) || "";
    if (!validQueryId(queryId)) {
      return { ok: false, error: "runtime_unavailable" };
    }
    const variables = {
      count: Number(values.count),
      includePromotedContent: true,
      requestContext: values.cursor ? "load_more" : "launch",
      withCommunity: true,
      seenTweetIds: []
    };
    if (values.cursor) {
      variables.cursor = values.cursor;
    }
    const upstream = await fetch(operation.origin + operation.pathname, {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers,
      body: JSON.stringify({ variables, features: FEATURES, queryId })
    });
    return parseUpstream(upstream, "HomeTimeline");
  }

  async function searchTimeline(values) {
    const operation = await discoverOperation("SearchTimeline");
    if (!operation) {
      return { ok: false, error: "runtime_unavailable" };
    }
    const headers = await requestHeaders(operation, "GET", true);
    if (!headers) {
      return { ok: false, error: "runtime_unavailable" };
    }
    const variables = {
      rawQuery: values.query,
      count: Number(values.count),
      querySource: "typed_query",
      product: values.product,
      withGrokTranslatedBio: false,
      withQuickPromoteEligibilityTweetFields: false
    };
    if (values.cursor) {
      variables.cursor = values.cursor;
    }
    const target = new URL(operation.origin + operation.pathname);
    target.searchParams.set("variables", JSON.stringify(variables));
    target.searchParams.set(
      "features",
      operation.searchParams.get("features") || JSON.stringify(FEATURES)
    );
    const upstream = await fetch(target.toString(), {
      method: "GET",
      credentials: "include",
      cache: "no-store",
      headers
    });
    return parseUpstream(upstream, "SearchTimeline");
  }

  try {
    if (!isRecord(input)) {
      return { ok: false, error: "invalid_request" };
    }
    if (input.kind === "session") {
      return response({ ok: true, payload: sessionPayload() });
    }
    if (input.kind !== "request" || input.session_verified !== true) {
      return { ok: false, error: "invalid_request" };
    }
    const session = sessionPayload();
    if (session.verification_required) {
      return { ok: false, error: "verification_required" };
    }
    if (!session.logged_in) {
      return { ok: false, error: "not_logged_in" };
    }
    const values = entriesObject(input.entries);
    if (!values) {
      return { ok: false, error: "invalid_request" };
    }
    if (input.path === HOME_PATH) {
      return await homeTimeline(values);
    }
    if (input.path === SEARCH_PATH) {
      return await searchTimeline(values);
    }
    if (input.path === USER_PATH) {
      return await userProfile(values);
    }
    if (input.path === USER_TWEETS_PATH) {
      return await userGraph("UserTweets", values);
    }
    if (input.path === FOLLOWERS_PATH) {
      return await userGraph("Followers", values);
    }
    if (input.path === FOLLOWING_PATH) {
      return await userGraph("Following", values);
    }
    return { ok: false, error: "invalid_request" };
  } catch {
    return { ok: false, error: "request_failed" };
  }
}
