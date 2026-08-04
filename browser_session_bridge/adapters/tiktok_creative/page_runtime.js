// chrome.scripting 会将此函数序列化到页面的 MAIN world。
// 依赖全部保留在函数内部，避免凭据离开 Chrome。
export async function invokeTikTokCreativePageRuntime(input) {
  const MAX_RESULT_BYTES = 6 * 1024 * 1024;
  const HASHTAG_MODULE_ID = 28474;
  const TOP_ADS_MODULE_ID = 90444;
  const LIST_PATH = "/CreativeOne/KnowledgeAPI/GetHashtagList";
  const DETAIL_PATH = "/CreativeOne/KnowledgeAPI/GetHashtagDetail";
  const TRENDING_VIDEO_OVERVIEW_PATH =
    "/CreativeOne/Report/GetTopContentsOverview";
  const TRENDING_VIDEO_LIST_PATH =
    "/CreativeOne/Report/CreativeCenterGetTopContentsList";
  const TRENDING_VIDEO_ROOT_PATH = "/creative/creativeCenter/trends";
  const TRENDING_VIDEO_PAGE_PATH = `${TRENDING_VIDEO_ROOT_PATH}/video`;
  const TRENDING_VIDEO_LEGACY_PAGE_PATH =
    "/business/creativecenter/inspiration/popular/video/pc/en";
  const TOP_ADS_FILTERS_PATH = "/CreativeOne/TopAds/Filters";
  const TOP_ADS_SEARCH_PATH = "/CreativeOne/TopAds/SearchMaterial";
  const TOP_ADS_V2_FILTERS_PATH =
    "/creative_radar_api/v1/top_ads/v2/filters";
  const TOP_ADS_V2_LIST_PATH =
    "/creative_radar_api/v1/top_ads/v2/list";
  const TOP_ADS_SUGGEST_PATH =
    "/creative_radar_api/v1/top_ads/query_suggestion";
  const TOP_ADS_V2_DETAIL_PATH =
    "/creative_radar_api/v1/top_ads/v2/detail";
  const TOP_ADS_V2_RECOMMEND_PATH =
    "/creative_radar_api/v1/top_ads/v2/recommend";
  const TOP_ADS_KEYFRAME_PATH =
    "/creative_radar_api/v1/top_ads/keyframe";
  const TOP_ADS_PERCENTILE_PATH =
    "/creative_radar_api/v1/top_ads/percentile";
  const TOP_ADS_V2_ANALYSIS_PATH =
    "/creative_radar_api/v1/top_ads/v2/detail_analysis";
  const TOP_ADS_V2_MAX_VIDEO_DURATION_SECONDS = 7200;
  const STUDIO_CREDITS_PATH =
    "/CreativeOne/SymphonyPlatform/QueryCreditAccount";
  const STUDIO_GENERATE_PATH =
    "/creative_bff_i18n/api/cue/t2v/create_generate_task";
  const STUDIO_UPLOAD_IMAGE_PATH =
    "/creative_bff_i18n/api/cue/upload/local-image";
  const STUDIO_I2V_GENERATE_PATH =
    "/creative_bff_i18n/api/cue/i2v/create_generate_task";
  const STUDIO_TASK_PATH =
    "/creative_bff_i18n/api/cue/generate-task/check";
  const STUDIO_PERMISSIONS_PATH =
    "/creative_bff_i18n/api/cue/get_miniapp_permission_with_allowlist";
  const STUDIO_GENERATING_COUNT_PATH =
    "/creative_bff_i18n/api/cue/generating-task-count";
  const STUDIO_MAX_COUNT_PATH =
    "/creative_bff_i18n/api/cue/get_generate_max_count";
  const STUDIO_LEDGER_PATH =
    "/CreativeOne/SymphonyPlatform/QueryCreditLedgerEntries";
  const STUDIO_HISTORY_PATH =
    "/creative_bff_i18n/api/cue/history/tasks";
  const STUDIO_TASK_DETAIL_PATH =
    "/creative_bff_i18n/api/cue/history/task/detail";
  const STUDIO_VIDEO_INFO_PATH =
    "/creative_bff_i18n/api/cue/video_info";
  const STUDIO_PAGE_PATH = "/creative/creativestudio/create";
  const STUDIO_T2V_PAGE_PATH = "/creative/creativestudio/image-to-video";
  const STUDIO_T2V_SUB_APP = "CreativeStudio/MiniApp/TextToVideo";
  const STUDIO_MODEL_ID = "5000005";
  const STUDIO_I2V_MODEL_ID = "4000005";
  const ONE_FILTERS_PATH =
    "/CreativeOne/MatchMaking/QueryPartnerSearchFilterOption";
  const ONE_SUGGEST_PATH =
    "/CreativeOne/MatchMaking/QueryPartnerSearchSuggestWords";
  const ONE_SEARCH_PATH =
    "/CreativeOne/MatchMaking/QueryPartnerCreatorSquare";
  const ONE_PAGE_PATH = "/creative/forpartners/creator/explore";
  const ADS_KEYWORD_IDEAS_PATH =
    "/api/v4/i18n/search_ads/search_keyword/mget_keyword_ideas/";
  const ADS_KEYWORD_SUMMARY_PATH =
    "/api/v4/i18n/search_ads/search_keyword/keyword_plan_summary/";
  const ADS_KEYWORD_NOGO_PATH =
    "/api/v4/i18n/search_ads/search_keyword/check_nogo_list/";
  const ADS_KEYWORD_IDS_PATH =
    "/api/v4/i18n/search_ads/search_keyword/check_get_word_ids/";
  const ADS_KEYWORD_PAGE_PATH =
    "/i18n/search_ads_center/keyword-planner/creation";
  const ADS_KEYWORD_COUNTRY_IDS = new Set([
    290557,
    2077456,
    3469034,
    6251999,
    2921044,
    2510769,
    3017382,
    2635167,
    1643084,
    3175395,
    3996063,
    1733045,
    1694008,
    102358,
    1605651,
    6252001,
    1562822
  ]);
  const ADS_KEYWORD_COUNTRIES = new Set([
    "AE",
    "AU",
    "BR",
    "CA",
    "DE",
    "ES",
    "FR",
    "GB",
    "ID",
    "IT",
    "MX",
    "MY",
    "PH",
    "SA",
    "TH",
    "US",
    "VN"
  ]);
  const TOP_ADS_LIBRARY_PATH = "/creative/inspiration/top-ads/library";
  const TOP_ADS_INSIGHT_PATH = "/creative/inspiration/top-ads/insight";
  const TOP_ADS_V2_PAGE_PATH =
    "/business/creativecenter/inspiration/topads/pc/en";
  const SIGNUP_PATH = "/creative/signup";
  const HASHTAG_ID = /^[1-9][0-9]{0,31}$/;
  const COUNTRY_CODE = /^[A-Z]{2}$/;
  const SENSITIVE_NAME =
    /(?:cookie|authorization|token|signature|session|passport|csrf|sid(?:_|$)|encrypt|headers?)/i;

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function encodedSize(value) {
    return new TextEncoder().encode(JSON.stringify(value)).byteLength;
  }

  function sanitize(value, depth = 0, seen = new Set()) {
    if (depth > 14) {
      return null;
    }
    if (
      value === null ||
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      return value;
    }
    if (Array.isArray(value)) {
      return value
        .slice(0, 20000)
        .map((item) => sanitize(item, depth + 1, seen));
    }
    if (!isRecord(value) || seen.has(value)) {
      return null;
    }
    seen.add(value);
    const result = {};
    for (const [name, item] of Object.entries(value).slice(0, 20000)) {
      if (name === "relatedInterests") {
        continue;
      }
      result[name] = SENSITIVE_NAME.test(name)
        ? "[redacted]"
        : sanitize(item, depth + 1, seen);
    }
    seen.delete(value);
    return result;
  }

  function response(value) {
    try {
      return encodedSize(value) <= MAX_RESULT_BYTES
        ? value
        : { ok: false, error: "response_too_large" };
    } catch {
      return { ok: false, error: "invalid_response" };
    }
  }

  function visible(element) {
    if (!(element instanceof Element)) {
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
      "#captcha_container",
      ".red-captcha",
      "[class*='captcha']",
      "[id*='captcha']",
      "iframe[src*='captcha']",
      "iframe[src*='verify']"
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

  function routerAccountState() {
    const element = document.getElementById("__MODERN_ROUTER_DATA__");
    if (!element) {
      return { loaded: false, loggedIn: false };
    }
    let data;
    try {
      data = JSON.parse(element.textContent || "{}");
    } catch {
      return { loaded: false, loggedIn: false };
    }
    const queries = data &&
      data.loaderData &&
      data.loaderData["creativeCenter/layout"] &&
      data.loaderData["creativeCenter/layout"].dehydratedState &&
      data.loaderData["creativeCenter/layout"].dehydratedState.queries;
    if (!Array.isArray(queries)) {
      return { loaded: false, loggedIn: false };
    }
    let accountLoaded = false;
    let userLoaded = false;
    let account = null;
    let user = null;
    for (const query of queries.slice(0, 100)) {
      if (!isRecord(query) || !Array.isArray(query.queryKey)) {
        continue;
      }
      const name = query.queryKey[0];
      const state = isRecord(query.state) ? query.state : {};
      const settled = state.status === "success" || state.status === "error";
      if (name === "account-info") {
        accountLoaded = settled;
        account = state.data;
      } else if (name === "tt4b-user-info") {
        userLoaded = settled;
        user = state.data;
      }
    }
    const accountID = isRecord(account)
      ? String(account.aioClientID || "").trim()
      : "";
    const userID = isRecord(user)
      ? String(user.tt4bUID || "").trim()
      : "";
    return {
      loaded: accountLoaded && userLoaded,
      loggedIn:
        (accountID !== "" && accountID !== "0") ||
        (userID !== "" && userID !== "0")
    };
  }

  function anonymousLoginCue() {
    const exactLabels = new Set([
      "Log in",
      "Log In",
      "Log in or sign up",
      "Log in TikTok One to view more"
    ]);
    for (const element of Array.from(
      document.querySelectorAll("button, a, [role='button']")
    ).slice(0, 500)) {
      const text = String(element.textContent || "")
        .replace(/\s+/g, " ")
        .trim();
      if (exactLabels.has(text) && visible(element)) {
        return true;
      }
    }
    return false;
  }

  function profileCompletionRequired() {
    if (location.pathname === SIGNUP_PATH) {
      return true;
    }
    const labels = new Set([
      "Complete your profile",
      "Business type",
      "Business info"
    ]);
    let matches = 0;
    for (const element of Array.from(
      document.querySelectorAll("h1, h2, h3, p, [role='heading']")
    ).slice(0, 300)) {
      const text = String(element.textContent || "")
        .replace(/\s+/g, " ")
        .trim();
      if (labels.has(text) && visible(element)) {
        matches += 1;
      }
    }
    return matches >= 2;
  }

  function fingerprint() {
    const connection =
      navigator.connection ||
      navigator.mozConnection ||
      navigator.webkitConnection ||
      {};
    const uaData = navigator.userAgentData;
    const brands = uaData && Array.isArray(uaData.brands)
      ? uaData.brands.slice(0, 10).map((item) => ({
        brand: String(item.brand || ""),
        version: String(item.version || "")
      }))
      : [];
    return {
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
      timezone: String(
        Intl.DateTimeFormat().resolvedOptions().timeZone || ""
      ),
      connection: {
        effective_type: String(connection.effectiveType || ""),
        round_trip_time: Number.isFinite(connection.rtt) ? connection.rtt : null,
        downlink: Number.isFinite(connection.downlink)
          ? connection.downlink
          : null,
        save_data: Boolean(connection.saveData)
      }
    };
  }

  function captureWebpackRequire(chunks, scope) {
    if (!Array.isArray(chunks) || typeof chunks.push !== "function") {
      return null;
    }
    let runtimeRequire = null;
    const chunkID =
      `local_browser_bridge_${scope}_${Date.now()}_` +
      `${Math.floor(Math.random() * 1000000)}`;
    try {
      chunks.push([
        [chunkID],
        {},
        (candidate) => {
          runtimeRequire = candidate;
        }
      ]);
    } catch {
      return null;
    }
    return typeof runtimeRequire === "function" ? runtimeRequire : null;
  }

  function transportModule() {
    const runtimeRequire = captureWebpackRequire(
      window.webpackChunkserver,
      "hashtag"
    );
    if (!runtimeRequire) {
      return null;
    }
    try {
      const module = runtimeRequire(HASHTAG_MODULE_ID);
      return (
        isRecord(module) &&
        typeof module.U5 === "function" &&
        typeof module.N6 === "function"
      ) ? module : null;
    } catch {
      return null;
    }
  }

  function topAdsTransportModule() {
    const runtimeRequire = captureWebpackRequire(
      window.webpackChunkclient,
      "top_ads"
    );
    if (!runtimeRequire) {
      return null;
    }
    try {
      const module = runtimeRequire(TOP_ADS_MODULE_ID);
      return (
        isRecord(module) &&
        typeof module.hP === "function" &&
        typeof module.in === "function"
      ) ? module : null;
    } catch {
      return null;
    }
  }

  function topAdsRadarTransportModule() {
    let runtimeRequire = typeof window.__next_require__ === "function"
      ? window.__next_require__
      : captureWebpackRequire(window.webpackChunk_N_E, "top_ads_v2");
    if (
      typeof runtimeRequire !== "function" ||
      !isRecord(runtimeRequire.m)
    ) {
      return null;
    }
    for (const [moduleID, factory] of Object.entries(runtimeRequire.m)) {
      const source = String(factory);
      if (
        !source.includes("cc-user-id") ||
        !source.includes("__tea_cache_tokens_3874") ||
        !source.includes("maxiosGlobalConfig")
      ) {
        continue;
      }
      try {
        const module = runtimeRequire(moduleID);
        if (
          isRecord(module) &&
          typeof module.U2 === "function" &&
          typeof module.v_ === "function"
        ) {
          return module;
        }
      } catch {
        return null;
      }
    }
    return null;
  }

  function studioRuntimeRequire() {
    if (typeof window.__cueWebpackRequire === "function") {
      return window.__cueWebpackRequire;
    }
    for (const name of Object.keys(window)) {
      if (!name.startsWith("@creative-ai/cue:")) {
        continue;
      }
      const runtimeRequire = captureWebpackRequire(window[name], "studio");
      if (runtimeRequire) {
        window.__cueWebpackRequire = runtimeRequire;
        return runtimeRequire;
      }
    }
    return null;
  }

  function validStudioImageUrl(value) {
    if (
      typeof value !== "string" ||
      value.length < 1 ||
      value.length > 2048 ||
      /[\r\n\0]/.test(value)
    ) {
      return false;
    }
    let parsed;
    try {
      parsed = new URL(value);
    } catch {
      return false;
    }
    return (
      parsed.protocol === "https:" &&
      !parsed.username &&
      !parsed.password &&
      !parsed.hash &&
      parsed.pathname.startsWith("/") &&
      (
        parsed.hostname.endsWith(".ibyteimg.com") ||
        parsed.hostname.endsWith(".tiktokcdn.com")
      )
    );
  }

  function parseEntries(path, entries) {
    if (!Array.isArray(entries)) {
      return null;
    }
    let required;
    let optional;
    if (path === LIST_PATH) {
      required = new Set(["timeRange", "countryCode", "page", "limit"]);
      optional = new Set(["industryID"]);
    } else if (path === DETAIL_PATH) {
      required = new Set(["hashtagID", "timeRange", "countryCode"]);
      optional = new Set();
    } else if (path === TRENDING_VIDEO_OVERVIEW_PATH) {
      required = new Set();
      optional = new Set();
    } else if (path === TRENDING_VIDEO_LIST_PATH) {
      required = new Set([
        "periodDimension",
        "periodEndTimestamp",
        "orderByMetric",
        "countryCode",
        "contentLabelIDs",
        "page",
        "limit"
      ]);
      optional = new Set();
    } else if (path === TOP_ADS_FILTERS_PATH) {
      required = new Set(["sourceModule"]);
      optional = new Set();
    } else if (path === TOP_ADS_SEARCH_PATH) {
      required = new Set([
        "timeRange",
        "orderField",
        "page",
        "limit",
        "sourceModule"
      ]);
      optional = new Set([
        "industryLabelList",
        "countryCodeList",
        "searchWord",
        "objectiveList",
        "adFormat",
        "likeCntFilter"
      ]);
    } else if (path === TOP_ADS_V2_FILTERS_PATH) {
      required = new Set();
      optional = new Set();
    } else if (path === TOP_ADS_V2_LIST_PATH) {
      required = new Set(["period", "orderBy", "countryCode", "page", "limit"]);
      optional = new Set([
        "industry",
        "keyword",
        "objective",
        "duration",
        "like",
        "patternLabel",
        "adFormat",
        "adLanguage"
      ]);
    } else if (path === TOP_ADS_SUGGEST_PATH) {
      required = new Set(["query", "count", "scenario", "countryCode"]);
      optional = new Set();
    } else if (
      path === TOP_ADS_V2_DETAIL_PATH ||
      path === TOP_ADS_V2_ANALYSIS_PATH
    ) {
      required = new Set(["materialId"]);
      optional = new Set();
    } else if (path === TOP_ADS_V2_RECOMMEND_PATH) {
      required = new Set(["materialId", "industry", "countryCode"]);
      optional = new Set();
    } else if (path === TOP_ADS_KEYFRAME_PATH) {
      required = new Set(["materialId", "metric"]);
      optional = new Set();
    } else if (path === TOP_ADS_PERCENTILE_PATH) {
      required = new Set(["materialId", "metric", "periodType"]);
      optional = new Set();
    } else if (path === STUDIO_CREDITS_PATH) {
      required = new Set();
      optional = new Set();
    } else if (path === STUDIO_GENERATE_PATH) {
      required = new Set(["prompt", "duration"]);
      optional = new Set(["enhancePrompt"]);
    } else if (path === STUDIO_UPLOAD_IMAGE_PATH) {
      required = new Set(["name", "mimeType", "dataBase64"]);
      optional = new Set();
    } else if (path === STUDIO_I2V_GENERATE_PATH) {
      required = new Set(["prompt", "duration", "firstFrameUrl"]);
      optional = new Set(["lastFrameUrl"]);
    } else if (path === STUDIO_TASK_PATH) {
      required = new Set(["taskId"]);
      optional = new Set();
    } else if (
      [
        STUDIO_PERMISSIONS_PATH,
        STUDIO_GENERATING_COUNT_PATH,
        STUDIO_MAX_COUNT_PATH
      ].includes(path)
    ) {
      required = new Set();
      optional = new Set();
    } else if (path === STUDIO_LEDGER_PATH) {
      required = new Set(["pageSize"]);
      optional = new Set(["cursor"]);
    } else if (path === STUDIO_HISTORY_PATH) {
      required = new Set(["offset", "limit"]);
      optional = new Set();
    } else if (path === STUDIO_TASK_DETAIL_PATH) {
      required = new Set(["draftId"]);
      optional = new Set();
    } else if (path === STUDIO_VIDEO_INFO_PATH) {
      required = new Set(["vid"]);
      optional = new Set();
    } else if (path === ONE_FILTERS_PATH) {
      required = new Set();
      optional = new Set();
    } else if (path === ONE_SUGGEST_PATH) {
      required = new Set(["query"]);
      optional = new Set();
    } else if (path === ONE_SEARCH_PATH) {
      required = new Set([
        "page",
        "limit",
        "query",
        "sortField",
        "sortType"
      ]);
      optional = new Set([
        "countryCodeList",
        "languageList",
        "minFansCnt",
        "maxFansCnt",
        "minMedianViews",
        "maxMedianViews",
        "minEngagementRate",
        "maxEngagementRate"
      ]);
    } else if (path === ADS_KEYWORD_IDEAS_PATH) {
      required = new Set([
        "keywords",
        "startTime",
        "endTime",
        "brandOption",
        "sortField",
        "sortOrder",
        "countryId",
        "languageCode",
        "languageName"
      ]);
      optional = new Set();
    } else if (path === ADS_KEYWORD_SUMMARY_PATH) {
      required = new Set(["words", "countryName"]);
      optional = new Set();
    } else {
      return null;
    }
    if (
      entries.length < required.size ||
      entries.length > required.size + optional.size
    ) {
      return null;
    }
    const values = {};
    for (const entry of entries) {
      if (
        !Array.isArray(entry) ||
        entry.length !== 2 ||
        typeof entry[0] !== "string" ||
        typeof entry[1] !== "string" ||
        (!required.has(entry[0]) && !optional.has(entry[0])) ||
        Object.prototype.hasOwnProperty.call(values, entry[0])
      ) {
        return null;
      }
      values[entry[0]] = entry[1];
    }
    if ([...required].some((name) =>
      !Object.prototype.hasOwnProperty.call(values, name)
    )) {
      return null;
    }
    const positiveInteger = (value, maximum) => {
      if (!/^[1-9][0-9]*$/.test(value || "")) {
        return null;
      }
      const parsed = Number(value);
      return Number.isSafeInteger(parsed) && parsed <= maximum
        ? parsed
        : null;
    };
    if (
      path === TOP_ADS_V2_FILTERS_PATH ||
      path === TRENDING_VIDEO_OVERVIEW_PATH
    ) {
      return {};
    }
    if (path === TOP_ADS_V2_LIST_PATH) {
      const period = Number(values.period);
      const page = positiveInteger(values.page, 1000);
      const limit = positiveInteger(values.limit, 20);
      const orderBy = values.orderBy;
      const countryCode = values.countryCode;
      if (
        ![7, 30, 180].includes(period) ||
        !["for_you", "impression", "ctr", "like"].includes(orderBy) ||
        page === null ||
        limit === null
      ) {
        return null;
      }
      const countryItems = String(countryCode || "").split(",");
      if (
        countryItems.length < 1 ||
        countryItems.length > 50 ||
        new Set(countryItems).size !== countryItems.length ||
        countryItems.some((item) => !COUNTRY_CODE.test(item))
      ) {
        return null;
      }
      const body = { period, orderBy, countryCode, page, limit };
      for (const name of ["industry", "objective", "patternLabel"]) {
        if (values[name] === undefined) {
          continue;
        }
        const items = values[name].split(",");
        if (
          items.length < 1 ||
          items.length > 50 ||
          new Set(items).size !== items.length ||
          items.some((item) => !HASHTAG_ID.test(item))
        ) {
          return null;
        }
        body[name] = values[name];
      }
      if (values.keyword !== undefined) {
        const keyword = values.keyword.trim();
        if (!keyword || keyword.length > 256) {
          return null;
        }
        body.keyword = keyword;
      }
      if (
        values.duration !== undefined &&
        !["0-15", "15-30", "30-60", "60-999"].includes(values.duration)
      ) {
        return null;
      }
      if (
        values.like !== undefined &&
        !["0-100", "100-1000", "1000-10000", "10000-999999999"].includes(
          values.like
        )
      ) {
        return null;
      }
      if (
        values.adFormat !== undefined &&
        !["spark", "non_spark"].includes(values.adFormat)
      ) {
        return null;
      }
      if (values.adLanguage !== undefined) {
        const languages = values.adLanguage.split(",");
        if (
          languages.length < 1 ||
          languages.length > 20 ||
          new Set(languages).size !== languages.length ||
          languages.some((item) =>
            !/^[A-Za-z]{2,8}(?:-[A-Za-z]{2,8})?$/.test(item)
          )
        ) {
          return null;
        }
      }
      for (const name of ["duration", "like", "adFormat", "adLanguage"]) {
        if (values[name] !== undefined) {
          body[name] = values[name];
        }
      }
      return body;
    }
    if (path === TOP_ADS_SUGGEST_PATH) {
      const query = values.query;
      const count = positiveInteger(values.count, 50);
      const scenario = Number(values.scenario);
      if (
        query.length > 256 ||
        count === null ||
        ![1, 2].includes(scenario) ||
        (scenario === 1 && query !== "") ||
        (scenario === 2 && query.trim() === "") ||
        !COUNTRY_CODE.test(values.countryCode)
      ) {
        return null;
      }
      return { query, count, scenario, countryCode: values.countryCode };
    }
    if (
      path === TOP_ADS_V2_DETAIL_PATH ||
      path === TOP_ADS_V2_ANALYSIS_PATH
    ) {
      return HASHTAG_ID.test(values.materialId || "")
        ? { materialId: values.materialId }
        : null;
    }
    if (path === TOP_ADS_V2_RECOMMEND_PATH) {
      return (
        HASHTAG_ID.test(values.materialId || "") &&
        HASHTAG_ID.test(values.industry || "") &&
        COUNTRY_CODE.test(values.countryCode || "")
      ) ? {
          materialId: values.materialId,
          industry: values.industry,
          countryCode: values.countryCode
        }
        : null;
    }
    if (path === TOP_ADS_KEYFRAME_PATH) {
      return (
        HASHTAG_ID.test(values.materialId || "") &&
        [
          "retain_ctr",
          "retain_cvr",
          "click_cnt",
          "convert_cnt",
          "play_retain_cnt"
        ].includes(values.metric)
      ) ? { materialId: values.materialId, metric: values.metric }
        : null;
    }
    if (path === TOP_ADS_PERCENTILE_PATH) {
      return (
        HASHTAG_ID.test(values.materialId || "") &&
        values.metric === "ctr_percentile" &&
        ["7", "30", "180"].includes(values.periodType)
      ) ? {
          materialId: values.materialId,
          metric: values.metric,
          periodType: Number(values.periodType)
        }
        : null;
    }
    if (path === STUDIO_CREDITS_PATH) {
      return {};
    }
    if (path === STUDIO_GENERATE_PATH) {
      const prompt = String(values.prompt || "").trim();
      const duration = Number(values.duration);
      if (
        prompt === "" ||
        prompt.length > 5000 ||
        !Number.isInteger(duration) ||
        duration < 4 ||
        duration > 15 ||
        (
          values.enhancePrompt !== undefined &&
          !["0", "1"].includes(values.enhancePrompt)
        )
      ) {
        return null;
      }
      const enhancePrompt = values.enhancePrompt === "1";
      const settings = {
        aiModel: STUDIO_MODEL_ID,
        duration,
        prompt,
        useEnhancePrompt: enhancePrompt,
        useReferencePrompt: false
      };
      return {
        prompt,
        gokuModel: STUDIO_MODEL_ID,
        model: STUDIO_MODEL_ID,
        duration,
        settings: JSON.stringify(settings)
      };
    }
    if (path === STUDIO_UPLOAD_IMAGE_PATH) {
      const name = String(values.name || "");
      const mimeType = String(values.mimeType || "");
      const dataBase64 = String(values.dataBase64 || "");
      if (
        name.length < 1 ||
        name.length > 255 ||
        /[\\/\r\n\0]/.test(name) ||
        !["image/png", "image/jpeg", "image/webp"].includes(mimeType) ||
        dataBase64.length < 4 ||
        dataBase64.length > 7 * 1024 * 1024 ||
        !/^[A-Za-z0-9+/]+={0,2}$/.test(dataBase64)
      ) {
        return null;
      }
      return { name, mimeType, dataBase64 };
    }
    if (path === STUDIO_I2V_GENERATE_PATH) {
      const prompt = String(values.prompt || "").trim();
      const duration = Number(values.duration);
      const firstFrameUrl = String(values.firstFrameUrl || "");
      const lastFrameUrl = String(values.lastFrameUrl || "");
      if (
        prompt === "" ||
        prompt.length > 5000 ||
        !Number.isInteger(duration) ||
        duration < 4 ||
        duration > 15 ||
        !validStudioImageUrl(firstFrameUrl) ||
        (lastFrameUrl !== "" && !validStudioImageUrl(lastFrameUrl))
      ) {
        return null;
      }
      const frameUrls = [firstFrameUrl];
      if (lastFrameUrl) {
        frameUrls.push(lastFrameUrl);
      }
      const images = frameUrls.map((previewUrl, index) => ({
        id: previewUrl,
        name: index === 0 ? "first-frame" : "last-frame",
        previewUrl,
        fileType: "image"
      }));
      const settings = {
        rawImage: firstFrameUrl,
        image: firstFrameUrl,
        images,
        aiModel: STUDIO_I2V_MODEL_ID,
        imageIndex: 0,
        animationType: "prompt",
        duration,
        isBgGenerated: false,
        prompt
      };
      return {
        image: firstFrameUrl,
        images: frameUrls,
        prompt,
        duration,
        model: STUDIO_I2V_MODEL_ID,
        settings: JSON.stringify(settings)
      };
    }
    if (path === STUDIO_TASK_PATH) {
      return HASHTAG_ID.test(values.taskId || "")
        ? { taskId: values.taskId }
        : null;
    }
    if (
      [
        STUDIO_PERMISSIONS_PATH,
        STUDIO_GENERATING_COUNT_PATH,
        STUDIO_MAX_COUNT_PATH
      ].includes(path)
    ) {
      return {};
    }
    if (path === STUDIO_LEDGER_PATH) {
      const pageSize = positiveInteger(values.pageSize, 100);
      const cursor = values.cursor;
      if (
        pageSize === null ||
        (
          cursor !== undefined &&
          (
            cursor.trim() === "" ||
            cursor.length > 1024 ||
            /[\r\n\0]/.test(cursor)
          )
        )
      ) {
        return null;
      }
      return cursor === undefined
        ? { page_size: pageSize }
        : { cursor, page_size: pageSize };
    }
    if (path === STUDIO_HISTORY_PATH) {
      const offset = Number(values.offset);
      const limit = positiveInteger(values.limit, 100);
      return (
        /^(?:0|[1-9][0-9]*)$/.test(values.offset || "") &&
        Number.isSafeInteger(offset) &&
        offset <= 100000 &&
        limit !== null
      ) ? {
          isAbridged: true,
          showPlayInfo: true,
          sorted: 2,
          pageOffset: offset,
          pageLimit: limit
        }
        : null;
    }
    if (path === STUDIO_TASK_DETAIL_PATH) {
      return HASHTAG_ID.test(values.draftId || "")
        ? { draftId: values.draftId }
        : null;
    }
    if (path === STUDIO_VIDEO_INFO_PATH) {
      return /^[A-Za-z0-9_-]{1,256}$/.test(values.vid || "")
        ? { vid: values.vid }
        : null;
    }
    if (path === ONE_FILTERS_PATH) {
      return {};
    }
    if (path === ONE_SUGGEST_PATH) {
      const query = String(values.query || "").trim();
      return query && query.length <= 256 ? { query } : null;
    }
    if (path === ONE_SEARCH_PATH) {
      const page = positiveInteger(values.page, 1000);
      const query = String(values.query || "").trim();
      const sortField = Number(values.sortField);
      const sortType = Number(values.sortType);
      if (
        page === null ||
        values.limit !== "24" ||
        query.length > 256 ||
        ![1, 2, 3, 4, 5, 6, 7, 8, 9, 10].includes(sortField) ||
        ![1, 2].includes(sortType)
      ) {
        return null;
      }
      const list = (name, pattern, maximum = 50) => {
        if (values[name] === undefined) {
          return [];
        }
        const items = values[name].split(",");
        const unique = new Set(items);
        return (
          items.length <= maximum &&
          unique.size === items.length &&
          items.every((item) => pattern.test(item))
        ) ? items : null;
      };
      const countries = list("countryCodeList", COUNTRY_CODE);
      const languages = list(
        "languageList",
        /^[A-Za-z]{2,8}(?:-[A-Za-z]{2,8})?$/,
        20
      );
      if (countries === null || languages === null) {
        return null;
      }
      const filterParam = {
        contentLabels: [],
        potentialIndustryLabels: [],
        creatorPriceFilter: { currency: "USD" },
        languages,
        audienceMaxDistriCountry: "",
        audienceMaxDistriAge: "",
        storeCountryCodeList: countries,
        subRegions: [],
        audienceMaxDistrPersonaList: [],
        creatorValueList: [],
        recommendationTypeList: []
      };
      for (const name of [
        "minFansCnt",
        "maxFansCnt",
        "minMedianViews",
        "maxMedianViews"
      ]) {
        if (values[name] !== undefined) {
          const parsed = Number(values[name]);
          if (!Number.isSafeInteger(parsed) || parsed < 0 || parsed > 1_000_000_000) {
            return null;
          }
          filterParam[name] = parsed;
        }
      }
      for (const name of ["minEngagementRate", "maxEngagementRate"]) {
        if (values[name] !== undefined) {
          const parsed = Number(values[name]);
          if (!Number.isFinite(parsed) || parsed < 0 || parsed > 1) {
            return null;
          }
          filterParam[name] = parsed;
        }
      }
      for (const [minimum, maximum] of [
        ["minFansCnt", "maxFansCnt"],
        ["minMedianViews", "maxMedianViews"],
        ["minEngagementRate", "maxEngagementRate"]
      ]) {
        if (
          filterParam[minimum] !== undefined &&
          filterParam[maximum] !== undefined &&
          filterParam[minimum] > filterParam[maximum]
        ) {
          return null;
        }
      }
      return {
        page,
        limit: 24,
        query,
        filterParam,
        sortParam: { sortType, sortField },
        dataVDCRegion: 1,
        searchType: 6
      };
    }
    if (path === ADS_KEYWORD_IDEAS_PATH) {
      let keywords;
      try {
        keywords = JSON.parse(values.keywords);
      } catch {
        return null;
      }
      const startTime = Number(values.startTime);
      const endTime = Number(values.endTime);
      const brandOption = Number(values.brandOption);
      const sortField = Number(values.sortField);
      const sortOrder = Number(values.sortOrder);
      const countryId = Number(values.countryId);
      const seen = new Set();
      if (
        !Array.isArray(keywords) ||
        keywords.length < 1 ||
        keywords.length > 10 ||
        keywords.some((keyword) => {
          if (
            typeof keyword !== "string" ||
            keyword.trim() === "" ||
            keyword.length > 80 ||
            /[\r\n\0]/.test(keyword) ||
            seen.has(keyword)
          ) {
            return true;
          }
          seen.add(keyword);
          return false;
        }) ||
        !Number.isSafeInteger(startTime) ||
        !Number.isSafeInteger(endTime) ||
        startTime <= 0 ||
        endTime <= startTime ||
        endTime - startTime > 370 * 24 * 60 * 60 ||
        endTime > 4_102_444_800 ||
        ![0, 1, 2].includes(brandOption) ||
        ![0, 1, 2, 3, 4, 5, 6].includes(sortField) ||
        ![0, 1, 2].includes(sortOrder) ||
        !ADS_KEYWORD_COUNTRY_IDS.has(countryId) ||
        values.languageCode !== "en" ||
        values.languageName !== "English"
      ) {
        return null;
      }
      return {
        inputKeywords: keywords.map((keyword) => ({ keyword })),
        timeRange: { startTime, endTime },
        brandOption,
        planSortType: [{ field: sortField, sort: sortOrder }],
        countryId: [countryId],
        language: [{ name: "English", code: "en" }]
      };
    }
    if (path === ADS_KEYWORD_SUMMARY_PATH) {
      let words;
      try {
        words = JSON.parse(values.words);
      } catch {
        return null;
      }
      const seen = new Set();
      if (
        !Array.isArray(words) ||
        words.length < 1 ||
        words.length > 20 ||
        !ADS_KEYWORD_COUNTRIES.has(values.countryName) ||
        words.some((word) => {
          if (
            !isRecord(word) ||
            Object.keys(word).length !== 3 ||
            typeof word.keyword !== "string" ||
            word.keyword.trim() === "" ||
            word.keyword.length > 80 ||
            /[\r\n\0]/.test(word.keyword) ||
            seen.has(word.keyword) ||
            ![1, 2, 3].includes(word.matchType) ||
            !Number.isSafeInteger(word.sourceType) ||
            word.sourceType < 1 ||
            word.sourceType > 20
          ) {
            return true;
          }
          seen.add(word.keyword);
          return false;
        })
      ) {
        return null;
      }
      return { words, countryName: values.countryName };
    }
    if (path === TOP_ADS_FILTERS_PATH) {
      return ["1", "2"].includes(values.sourceModule)
        ? { sourceModule: Number(values.sourceModule) }
        : null;
    }
    if (path === TOP_ADS_SEARCH_PATH) {
      const decimalCSV = (value, maximumItems = 20) => {
        const items = String(value || "").split(",");
        if (items.length < 1 || items.length > maximumItems) {
          return null;
        }
        const seen = new Set();
        for (const item of items) {
          if (
            !HASHTAG_ID.test(item) ||
            !Number.isSafeInteger(Number(item)) ||
            seen.has(item)
          ) {
            return null;
          }
          seen.add(item);
        }
        return items;
      };
      const countryCSV = (value, maximumItems = 249) => {
        const items = String(value || "").split(",");
        if (items.length < 1 || items.length > maximumItems) {
          return null;
        }
        const seen = new Set();
        for (const item of items) {
          if (!COUNTRY_CODE.test(item) || seen.has(item)) {
            return null;
          }
          seen.add(item);
        }
        return items;
      };
      const enumCSV = (value, allowed, maximumItems = 20) => {
        const items = String(value || "").split(",");
        if (items.length < 1 || items.length > maximumItems) {
          return null;
        }
        const seen = new Set();
        const parsed = [];
        for (const item of items) {
          const number = Number(item);
          if (!allowed.has(number) || seen.has(number)) {
            return null;
          }
          seen.add(number);
          parsed.push(number);
        }
        return parsed;
      };
      if (
        !["7", "30", "180"].includes(values.timeRange) ||
        !["1", "2", "3", "4"].includes(values.orderField) ||
        positiveInteger(values.page, 1000) === null ||
        positiveInteger(values.limit, 20) === null ||
        values.sourceModule !== "2"
      ) {
        return null;
      }
      const body = {
        timeRange: Number(values.timeRange),
        orderField: Number(values.orderField),
        page: values.page,
        limit: values.limit,
        sourceModule: 2,
        sellingPointList: [],
        excludeMid: false,
        excludeKA: false
      };
      if (values.industryLabelList !== undefined) {
        const industries = decimalCSV(values.industryLabelList);
        if (!industries) {
          return null;
        }
        body.industryLabelList = industries;
      }
      if (values.countryCodeList !== undefined) {
        const countries = countryCSV(values.countryCodeList);
        if (!countries) {
          return null;
        }
        body.countryCodeList = countries;
      }
      if (values.searchWord !== undefined) {
        const searchWord = values.searchWord.trim();
        if (!searchWord || searchWord.length > 256) {
          return null;
        }
        body.searchWord = searchWord;
      }
      if (values.objectiveList !== undefined) {
        const objectives = enumCSV(
          values.objectiveList,
          new Set([1, 2, 3, 4, 5, 6, 8, 9, 14, 15, 16])
        );
        if (!objectives) {
          return null;
        }
        body.objectiveList = objectives;
      }
      if (values.adFormat !== undefined) {
        if (![1, 2, 3, 4, 99, 100].includes(Number(values.adFormat))) {
          return null;
        }
        body.adFormat = Number(values.adFormat);
      }
      if (values.likeCntFilter !== undefined) {
        if (![1, 2, 3, 4, 5].includes(Number(values.likeCntFilter))) {
          return null;
        }
        body.likeCntFilter = Number(values.likeCntFilter);
      }
      return body;
    }
    if (path === TRENDING_VIDEO_LIST_PATH) {
      const periodDimension = Number(values.periodDimension);
      const periodEndTimestamp = positiveInteger(
        values.periodEndTimestamp,
        4_102_444_800
      );
      const orderByMetric = Number(values.orderByMetric);
      const page = positiveInteger(values.page, 1000);
      const limit = positiveInteger(values.limit, 20);
      const labels = values.contentLabelIDs === ""
        ? []
        : values.contentLabelIDs.split(",");
      if (
        ![3, 5].includes(periodDimension) ||
        periodEndTimestamp === null ||
        ![1, 2, 3].includes(orderByMetric) ||
        !COUNTRY_CODE.test(values.countryCode || "") ||
        page === null ||
        limit === null ||
        labels.length > 20 ||
        new Set(labels).size !== labels.length ||
        labels.some((item) =>
          !HASHTAG_ID.test(item) || !Number.isSafeInteger(Number(item))
        )
      ) {
        return null;
      }
      return {
        periodDimension,
        periodEndTimestamp,
        orderByMetric,
        countryCode: values.countryCode,
        contentLabelIDs: labels,
        organicOnly: false,
        page,
        limit
      };
    }
    if (
      !["7", "30", "90"].includes(values.timeRange) ||
      !COUNTRY_CODE.test(values.countryCode || "")
    ) {
      return null;
    }
    if (
      path === LIST_PATH &&
      (
        positiveInteger(values.page, 1000) === null ||
        positiveInteger(values.limit, 100) === null ||
        (
          values.industryID !== undefined &&
          (
            !HASHTAG_ID.test(values.industryID) ||
            !Number.isSafeInteger(Number(values.industryID))
          )
        )
      )
    ) {
      return null;
    }
    if (
      path === DETAIL_PATH &&
      !HASHTAG_ID.test(values.hashtagID || "")
    ) {
      return null;
    }
    const body = {
      timeRange: Number(values.timeRange),
      countryCode: values.countryCode
    };
    if (values.industryID !== undefined) {
      body.industryID = Number(values.industryID);
    }
    if (values.page !== undefined) {
      body.page = Number(values.page);
    }
    if (values.limit !== undefined) {
      body.limit = Number(values.limit);
    }
    if (values.hashtagID !== undefined) {
      body.hashtagID = values.hashtagID;
    }
    return body;
  }

  function projectFields(value, fields) {
    const projected = {};
    for (const name of fields) {
      if (Object.prototype.hasOwnProperty.call(value, name)) {
        projected[name] = value[name];
      }
    }
    return projected;
  }

  function projectListItem(value) {
    if (
      !isRecord(value) ||
      !HASHTAG_ID.test(String(value.hashtagID || "")) ||
      typeof value.hashtagName !== "string" ||
      value.hashtagName.trim() === "" ||
      value.hashtagName.length > 512
    ) {
      return null;
    }
    for (const name of ["industryIDs", "popularityCurve", "topCreators"]) {
      if (
        value[name] !== undefined &&
        (!Array.isArray(value[name]) || value[name].length > 1000)
      ) {
        return null;
      }
    }
    return projectFields(value, [
      "hashtagID",
      "hashtagName",
      "industryIDs",
      "popularityCurve",
      "publishCnt",
      "rankIndex",
      "topCreators",
      "vv"
    ]);
  }

  function normalizeListResult(value, body) {
    if (
      !isRecord(value) ||
      !Array.isArray(value.items) ||
      value.items.length > 100 ||
      !isRecord(value.pagination)
    ) {
      throw new Error("invalid_response");
    }
    const items = value.items.map(projectListItem);
    if (items.some((item) => item === null)) {
      throw new Error("invalid_response");
    }
    const rawPage = Number(value.pagination.page);
    const rawLimit = Number(value.pagination.limit);
    const rawTotal = Number(value.pagination.totalCount);
    const page = Number.isSafeInteger(rawPage) && rawPage > 0
      ? rawPage
      : body.page;
    const limit = Number.isSafeInteger(rawLimit) && rawLimit > 0
      ? rawLimit
      : body.limit;
    if (
      !Number.isSafeInteger(rawTotal) ||
      rawTotal < 0 ||
      typeof value.pagination.hasMore !== "boolean"
    ) {
      throw new Error("invalid_response");
    }
    return {
      items,
      pagination: {
        page,
        limit,
        totalCount: rawTotal,
        hasMore: value.pagination.hasMore
      }
    };
  }

  function normalizeDetailResult(value, expectedID = "") {
    if (
      !isRecord(value) ||
      !HASHTAG_ID.test(String(value.hashtagID || "")) ||
      (
        expectedID !== "" &&
        String(value.hashtagID) !== String(expectedID)
      ) ||
      typeof value.hashtagName !== "string" ||
      value.hashtagName.trim() === "" ||
      value.hashtagName.length > 512 ||
      !Array.isArray(value.popularityCurve) ||
      value.popularityCurve.length > 1000
    ) {
      throw new Error("invalid_response");
    }
    for (const name of [
      "industryIDs",
      "videoList",
      "ageProfile",
      "representativeCountryProfile"
    ]) {
      if (
        value[name] !== undefined &&
        (!Array.isArray(value[name]) || value[name].length > 1000)
      ) {
        throw new Error("invalid_response");
      }
    }
    return projectFields(value, [
      "hashtagID",
      "hashtagName",
      "industryIDs",
      "popularityCurve",
      "publishCnt",
      "vv",
      "videoList",
      "ageProfile",
      "representativeCountryProfile"
    ]);
  }

  function projectTrendingVideoItem(value) {
    if (!isRecord(value) || !isRecord(value.itemInfo)) {
      return null;
    }
    const itemID = decimalIdentifier(value.itemInfo.itemID);
    if (!itemID) {
      return null;
    }
    const itemInfo = { itemID };
    for (const name of ["authorID", "creatorID"]) {
      const identifier = decimalIdentifier(value.itemInfo[name]);
      if (identifier) {
        itemInfo[name] = identifier;
      }
    }
    for (const name of ["title", "coverURL", "videoURL"]) {
      const text = value.itemInfo[name];
      if (
        typeof text === "string" &&
        text.length <= 16384 &&
        !/[\u0000-\u001f\u007f]/.test(text)
      ) {
        itemInfo[name] = text;
      }
    }
    for (const name of ["createTime", "contentType"]) {
      const number = value.itemInfo[name];
      if (Number.isSafeInteger(number) && number >= 0) {
        itemInfo[name] = number;
      }
    }
    const result = { itemInfo };
    if (isRecord(value.itemAuthorInfo)) {
      result.itemAuthorInfo = projectFields(value.itemAuthorInfo, [
        "handlerName",
        "nickName",
        "avatarURI",
        "bio"
      ]);
    }
    if (isRecord(value.itemAuthorMetrics)) {
      const followers = value.itemAuthorMetrics.followers;
      if (Number.isSafeInteger(followers) && followers >= 0) {
        result.itemAuthorMetrics = { followers };
      }
    }
    if (isRecord(value.itemMetrics)) {
      result.itemMetrics = projectFields(value.itemMetrics, [
        "videoViews",
        "organicVideoViews",
        "engagementRate",
        "sixSecondsVTR"
      ]);
    }
    return result;
  }

  function normalizeTrendingVideoList(value, body) {
    if (
      !isRecord(value) ||
      !Array.isArray(value.entityInfos) ||
      value.entityInfos.length > body.limit ||
      !isRecord(value.pagination)
    ) {
      throw new Error("invalid_response");
    }
    const items = value.entityInfos.map(projectTrendingVideoItem);
    if (items.some((item) => item === null)) {
      throw new Error("invalid_response");
    }
    const pagination = value.pagination;
    const page = Number(pagination.page);
    const limit = Number(pagination.limit);
    const totalCount = Number(pagination.totalCount);
    const hasMore = pagination.hasMore;
    const consumed = (body.page - 1) * body.limit + items.length;
    if (
      !Number.isSafeInteger(page) ||
      page !== body.page ||
      !Number.isSafeInteger(limit) ||
      limit !== body.limit ||
      !Number.isSafeInteger(totalCount) ||
      totalCount < consumed ||
      typeof hasMore !== "boolean" ||
      hasMore !== (consumed < totalCount)
    ) {
      throw new Error("invalid_response");
    }
    return {
      entityInfos: items,
      pagination: { page, limit, totalCount, hasMore }
    };
  }

  function normalizeTrendingVideoOverview(value) {
    if (!isRecord(value)) {
      throw new Error("invalid_response");
    }
    const timestamp = nonNegativeInteger(value.lastDailyEndTimestamp);
    if (
      timestamp === null ||
      timestamp < 1 ||
      timestamp > 4_102_444_800
    ) {
      throw new Error("invalid_response");
    }
    return { lastDailyEndTimestamp: timestamp };
  }

  function decimalIdentifier(value, allowZero = false) {
    const text = typeof value === "string"
      ? value
      : Number.isSafeInteger(value)
        ? String(value)
        : "";
    const pattern = allowZero
      ? /^(?:0|[1-9][0-9]{0,31})$/
      : HASHTAG_ID;
    return pattern.test(text) ? text : "";
  }

  function nonNegativeMetric(value) {
    if (typeof value === "number") {
      return Number.isFinite(value) && value >= 0 ? value : null;
    }
    if (
      typeof value === "string" &&
      value.length <= 64 &&
      /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value)
    ) {
      return value;
    }
    return null;
  }

  function httpsAsset(value, allowEmpty = false) {
    if (typeof value !== "string" || value.length > 16384) {
      return null;
    }
    if (allowEmpty && value === "") {
      return "";
    }
    let parsed;
    try {
      parsed = new URL(value);
    } catch {
      return null;
    }
    return (
      parsed.protocol === "https:" &&
      parsed.username === "" &&
      parsed.password === ""
    ) ? value : null;
  }

  function industryNodeField(item, names) {
    const present = names.filter((name) =>
      Object.prototype.hasOwnProperty.call(item, name)
    );
    if (present.length === 0) {
      return null;
    }
    const first = item[present[0]];
    if (present.some((name) => item[name] !== first)) {
      return null;
    }
    return { name: present[0], value: first };
  }

  function normalizeTopAdsIndustryNodes(items, depth, state) {
    if (!Array.isArray(items) || depth > 8) {
      throw new Error("invalid_response");
    }
    return items.map((item) => {
      state.count += 1;
      if (!isRecord(item) || state.count > 5000) {
        throw new Error("invalid_response");
      }
      const idField = industryNodeField(item, [
        "value",
        "industryLabelID"
      ]);
      const labelField = industryNodeField(item, [
        "label",
        "industryLabelName",
        "name"
      ]);
      const id = idField
        ? decimalIdentifier(idField.value)
        : "";
      const label = labelField && typeof labelField.value === "string"
        ? labelField.value
        : "";
      if (
        !id ||
        state.ids.has(id) ||
        label === "" ||
        label !== label.trim() ||
        label.length > 1024 ||
        /[\u0000-\u001f\u007f]/.test(label)
      ) {
        throw new Error("invalid_response");
      }
      state.ids.add(id);
      const projected = {
        [idField.name]: id,
        [labelField.name]: label
      };
      if (Object.prototype.hasOwnProperty.call(item, "parentID")) {
        const parentID = decimalIdentifier(item.parentID, true);
        if (!parentID) {
          throw new Error("invalid_response");
        }
        projected.parentID = parentID;
      }
      if (Object.prototype.hasOwnProperty.call(item, "children")) {
        projected.children = normalizeTopAdsIndustryNodes(
          item.children,
          depth + 1,
          state
        );
      }
      return projected;
    });
  }

  function normalizeTopAdsFilterCountries(value) {
    if (
      !Array.isArray(value) ||
      value.length < 1 ||
      value.length > 249
    ) {
      throw new Error("invalid_response");
    }
    const countries = new Set();
    const projected = value.map((item) => {
      if (
        typeof item !== "string" ||
        !COUNTRY_CODE.test(item) ||
        countries.has(item)
      ) {
        return null;
      }
      countries.add(item);
      return item;
    });
    if (projected.some((item) => item === null)) {
      throw new Error("invalid_response");
    }
    return projected;
  }

  function normalizeTopAdsInsightIndustries(value) {
    if (!Array.isArray(value) || value.length > 5000) {
      throw new Error("invalid_response");
    }
    const ids = new Set();
    return value.map((item) => {
      const id = decimalIdentifier(item);
      if (
        !id ||
        !Number.isSafeInteger(Number(id)) ||
        ids.has(id)
      ) {
        throw new Error("invalid_response");
      }
      ids.add(id);
      return id;
    });
  }

  function normalizeTopAdsFilterObjectives(value) {
    const allowedObjectives = new Set([
      1, 2, 3, 4, 5, 6, 8, 9, 14, 15, 16
    ]);
    if (
      !Array.isArray(value) ||
      value.length < 1 ||
      value.length > allowedObjectives.size
    ) {
      throw new Error("invalid_response");
    }
    const objectives = new Set();
    const projected = value.map((item) => {
      const objective = Number(item);
      if (
        !allowedObjectives.has(objective) ||
        objectives.has(objective)
      ) {
        return null;
      }
      objectives.add(objective);
      return objective;
    });
    if (projected.some((item) => item === null)) {
      throw new Error("invalid_response");
    }
    return projected;
  }

  function topAdsV2Text(value, maximum = 5000, allowEmpty = true) {
    if (
      typeof value !== "string" ||
      value.length > maximum ||
      /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value) ||
      (!allowEmpty && value.trim() === "")
    ) {
      return null;
    }
    return value;
  }

  function normalizeTopAdsV2Filters(value) {
    if (!isRecord(value)) {
      throw new Error("invalid_response");
    }
    const result = {};
    for (const name of [
      "adLanguage",
      "country",
      "industry",
      "objective",
      "patternLabel",
      "period"
    ]) {
      const items = value[name];
      if (!Array.isArray(items) || items.length < 1 || items.length > 2000) {
        throw new Error("invalid_response");
      }
      result[name] = items.map((item) => {
        if (!isRecord(item)) {
          throw new Error("invalid_response");
        }
        const label = topAdsV2Text(String(item.label || ""), 256, false);
        const displayValue = topAdsV2Text(
          String(item.value || ""),
          1024,
          false
        );
        const id = String(item.id ?? "");
        if (
          label === null ||
          displayValue === null ||
          !/^[A-Za-z0-9_-]{1,64}$/.test(id)
        ) {
          throw new Error("invalid_response");
        }
        const projected = { id, label, value: displayValue };
        if (item.parentId !== undefined) {
          const parentID = String(item.parentId);
          if (!/^[1-9][0-9]{0,31}$/.test(parentID)) {
            throw new Error("invalid_response");
          }
          projected.parentId = parentID;
        }
        if (item.hasConversion !== undefined) {
          if (typeof item.hasConversion !== "boolean") {
            throw new Error("invalid_response");
          }
          projected.hasConversion = item.hasConversion;
        }
        return projected;
      });
    }
    return result;
  }

  function projectTopAdsV2Video(value) {
    if (!isRecord(value) || !isRecord(value.videoUrl)) {
      return null;
    }
    const vid = topAdsV2Text(String(value.vid || ""), 256, false);
    const cover = httpsAsset(String(value.cover || ""));
    const duration = Number(value.duration);
    const width = Number(value.width);
    const height = Number(value.height);
    const videoUrl = {};
    for (const [name, url] of Object.entries(value.videoUrl).slice(0, 20)) {
      const asset = httpsAsset(String(url || ""));
      if (!/^[A-Za-z0-9_-]{1,32}$/.test(name) || asset === null) {
        return null;
      }
      videoUrl[name] = asset;
    }
    if (
      vid === null ||
      cover === null ||
      !Number.isFinite(duration) ||
      duration <= 0 ||
      duration > TOP_ADS_V2_MAX_VIDEO_DURATION_SECONDS ||
      !Number.isSafeInteger(width) ||
      width <= 0 ||
      !Number.isSafeInteger(height) ||
      height <= 0 ||
      Object.keys(videoUrl).length < 1
    ) {
      return null;
    }
    return { vid, duration, width, height, cover, videoUrl };
  }

  function projectTopAdsV2Material(value) {
    if (!isRecord(value)) {
      return null;
    }
    const id = decimalIdentifier(value.id);
    const adTitle = topAdsV2Text(String(value.adTitle || ""), 10000);
    const brandName = topAdsV2Text(String(value.brandName || ""), 1024);
    const industryKey = topAdsV2Text(
      String(value.industryKey || ""),
      128,
      false
    );
    const objectiveKey = topAdsV2Text(
      String(value.objectiveKey || ""),
      128,
      false
    );
    const cost = nonNegativeMetric(value.cost);
    const ctr = nonNegativeMetric(value.ctr);
    const like = nonNegativeMetric(value.like);
    const videoInfo = projectTopAdsV2Video(value.videoInfo);
    if (
      !id ||
      adTitle === null ||
      brandName === null ||
      industryKey === null ||
      objectiveKey === null ||
      cost === null ||
      ctr === null ||
      like === null ||
      videoInfo === null
    ) {
      return null;
    }
    const projected = {
      id,
      adTitle,
      brandName,
      cost,
      ctr,
      like,
      industryKey,
      objectiveKey,
      favorite: value.favorite === true,
      isSearch: value.isSearch === true,
      videoInfo
    };
    for (const name of ["comment", "share", "sourceKey"]) {
      if (value[name] !== undefined) {
        const metric = nonNegativeMetric(value[name]);
        if (metric === null) {
          return null;
        }
        projected[name] = metric;
      }
    }
    for (const name of ["source", "highlightText"]) {
      if (value[name] !== undefined) {
        const text = topAdsV2Text(String(value[name] || ""), 10000);
        if (text === null) {
          return null;
        }
        projected[name] = text;
      }
    }
    if (value.landingPage !== undefined) {
      const landingPage = httpsAsset(String(value.landingPage || ""), true);
      if (landingPage === null) {
        return null;
      }
      projected.landingPage = landingPage;
    }
    if (value.countryCode !== undefined) {
      if (
        !Array.isArray(value.countryCode) ||
        value.countryCode.length > 50 ||
        value.countryCode.some((item) => !COUNTRY_CODE.test(item))
      ) {
        return null;
      }
      projected.countryCode = [...value.countryCode];
    }
    for (const name of ["keywordList", "objectives", "patternLabel"]) {
      if (value[name] === null) {
        projected[name] = null;
      } else if (value[name] !== undefined) {
        if (!Array.isArray(value[name]) || value[name].length > 200) {
          return null;
        }
        projected[name] = sanitize(value[name]);
      }
    }
    if (value.hasSummary !== undefined) {
      projected.hasSummary = value.hasSummary === true;
    }
    if (value.voiceOver !== undefined) {
      projected.voiceOver = value.voiceOver === true;
    }
    return projected;
  }

  function normalizeTopAdsV2List(value, body) {
    if (
      !isRecord(value) ||
      !Array.isArray(value.materials) ||
      value.materials.length > body.limit ||
      !isRecord(value.pagination)
    ) {
      throw new Error("invalid_response");
    }
    const materials = value.materials.map(projectTopAdsV2Material);
    const page = positivePageValue(value.pagination.page, 1000);
    const size = positivePageValue(value.pagination.size, 20);
    const totalCount = nonNegativeInteger(value.pagination.totalCount);
    const hasMore = value.pagination.hasMore;
    if (
      materials.some((item) => item === null) ||
      page !== body.page ||
      size !== body.limit ||
      totalCount === null ||
      totalCount < (page - 1) * size + materials.length ||
      typeof hasMore !== "boolean"
    ) {
      throw new Error("invalid_response");
    }
    return {
      materials,
      pagination: { page, size, totalCount, hasMore }
    };
  }

  function normalizeTopAdsV2Suggestions(value) {
    if (
      !isRecord(value) ||
      !Array.isArray(value.query) ||
      value.query.length > 50
    ) {
      throw new Error("invalid_response");
    }
    const seen = new Set();
    const query = value.query.map((item) => {
      const text = topAdsV2Text(item, 256, false);
      if (text === null || seen.has(text)) {
        throw new Error("invalid_response");
      }
      seen.add(text);
      return text;
    });
    return { query };
  }

  function normalizeTopAdsV2Detail(value, materialID) {
    const material = projectTopAdsV2Material(value);
    if (!material || material.id !== materialID) {
      throw new Error("invalid_response");
    }
    return material;
  }

  function normalizeTopAdsV2Recommend(value) {
    if (
      !isRecord(value) ||
      !Array.isArray(value.materials) ||
      value.materials.length > 100
    ) {
      throw new Error("invalid_response");
    }
    const materials = value.materials.map(projectTopAdsV2Material);
    if (materials.some((item) => item === null)) {
      throw new Error("invalid_response");
    }
    return { materials };
  }

  function normalizeTopAdsKeyframe(value) {
    if (
      !isRecord(value) ||
      !Array.isArray(value.analysis) ||
      value.analysis.length > 600 ||
      !Array.isArray(value.highlight) ||
      value.highlight.length > 100
    ) {
      throw new Error("invalid_response");
    }
    const duration = positivePageValue(value.duration, 600);
    const analysis = value.analysis.map((item) => {
      const second = isRecord(item) ? nonNegativeInteger(item.second) : null;
      const metric = isRecord(item) ? nonNegativeMetric(item.value) : null;
      if (second === null || metric === null || second > 600) {
        throw new Error("invalid_response");
      }
      return { second, value: metric };
    });
    const highlight = value.highlight.map((item) => {
      const second = nonNegativeInteger(item);
      if (second === null || second > 600) {
        throw new Error("invalid_response");
      }
      return second;
    });
    if (duration === null) {
      throw new Error("invalid_response");
    }
    return { duration, analysis, highlight };
  }

  function normalizeTopAdsPercentile(value) {
    if (!isRecord(value)) {
      throw new Error("invalid_response");
    }
    const ctrPercentile = nonNegativeMetric(value.ctrPercentile);
    if (ctrPercentile === null || Number(ctrPercentile) > 1) {
      throw new Error("invalid_response");
    }
    return { ctrPercentile };
  }

  function normalizeTopAdsV2Analysis(value) {
    if (!isRecord(value)) {
      throw new Error("invalid_response");
    }
    const projected = sanitize(value);
    if (!isRecord(projected)) {
      throw new Error("invalid_response");
    }
    return projected;
  }

  function normalizeTopAdsFilters(value, body) {
    if (!isRecord(value) || !isRecord(body)) {
      throw new Error("invalid_response");
    }
    const countryCodeList = normalizeTopAdsFilterCountries(
      value.countryCodeList
    );
    if (body.sourceModule === 1) {
      return {
        industryLabel: normalizeTopAdsInsightIndustries(
          value.industryLabel
        ),
        countryCodeList
      };
    }
    if (body.sourceModule !== 2) {
      throw new Error("invalid_response");
    }
    return {
      industryLabelTree: normalizeTopAdsIndustryNodes(
        value.industryLabelTree,
        0,
        { count: 0, ids: new Set() }
      ),
      countryCodeList,
      objectiveList: normalizeTopAdsFilterObjectives(value.objectiveList)
    };
  }

  function projectTopAdsMaterial(value) {
    if (!isRecord(value) || !isRecord(value.videoInfo)) {
      return null;
    }
    const materialID = decimalIdentifier(value.materialID);
    const videoURLs = value.videoInfo.video_url;
    const video720p = isRecord(videoURLs)
      ? httpsAsset(videoURLs["720p"])
      : null;
    const cover = httpsAsset(value.videoInfo.cover);
    const coverAvif = httpsAsset(value.videoInfo.coverAvif, true);
    const videoView = nonNegativeMetric(value.videoView);
    const clickRate = nonNegativeMetric(value.clickRate);
    const ctrRank = nonNegativeMetric(value.ctrRank);
    const engagementRate = nonNegativeMetric(value.engagementRate);
    const videoView6sRank = nonNegativeMetric(value.videoView6sRank);
    const sellingPointList = Array.isArray(value.sellingPointList) &&
      value.sellingPointList.length <= 100
      ? value.sellingPointList
      : null;
    const sellingPoints = new Set();
    if (
      sellingPointList &&
      sellingPointList.some((item) => {
        if (
          typeof item !== "string" ||
          item === "" ||
          item !== item.trim() ||
          item.length > 1024 ||
          /[\u0000-\u001f\u007f]/.test(item) ||
          sellingPoints.has(item)
        ) {
          return true;
        }
        sellingPoints.add(item);
        return false;
      })
    ) {
      return null;
    }
    if (
      !materialID ||
      video720p === null ||
      cover === null ||
      coverAvif === null ||
      videoView === null ||
      clickRate === null ||
      ctrRank === null ||
      engagementRate === null ||
      videoView6sRank === null ||
      sellingPointList === null
    ) {
      return null;
    }
    const videoInfo = {
      video_url: { "720p": video720p },
      cover
    };
    if (coverAvif !== "") {
      videoInfo.coverAvif = coverAvif;
    }
    return {
      materialID,
      videoInfo,
      videoView,
      clickRate,
      ctrRank,
      engagementRate,
      videoView6sRank,
      sellingPointList: [...sellingPointList]
    };
  }

  function positivePageValue(value, maximum) {
    const parsed = typeof value === "string" && /^[1-9][0-9]*$/.test(value)
      ? Number(value)
      : value;
    return (
      Number.isSafeInteger(parsed) &&
      parsed > 0 &&
      parsed <= maximum
    ) ? parsed : null;
  }

  function nonNegativeInteger(value) {
    const parsed = typeof value === "string" &&
      /^(?:0|[1-9][0-9]*)$/.test(value)
      ? Number(value)
      : value;
    return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : null;
  }

  function normalizeTopAdsSearch(value, body) {
    if (
      !isRecord(value) ||
      !Array.isArray(value.itemList) ||
      value.itemList.length > body.limit ||
      !isRecord(value.pagination) ||
      typeof value.pagination.hasMore !== "boolean"
    ) {
      throw new Error("invalid_response");
    }
    const itemList = value.itemList.map(projectTopAdsMaterial);
    const page = positivePageValue(value.pagination.page, 1000);
    const hasSize = Object.prototype.hasOwnProperty.call(
      value.pagination,
      "size"
    );
    const hasLimit = Object.prototype.hasOwnProperty.call(
      value.pagination,
      "limit"
    );
    const size = hasSize
      ? positivePageValue(value.pagination.size, 20)
      : hasLimit
        ? positivePageValue(value.pagination.limit, 20)
        : null;
    const alternateSize = hasSize && hasLimit
      ? positivePageValue(value.pagination.limit, 20)
      : size;
    if (
      itemList.some((item) => item === null) ||
      page === null ||
      page !== Number(body.page) ||
      size === null ||
      alternateSize !== size
    ) {
      throw new Error("invalid_response");
    }
    const pagination = {
      page,
      [hasSize ? "size" : "limit"]: size,
      hasMore: value.pagination.hasMore
    };
    const hasTotal = Object.prototype.hasOwnProperty.call(
      value.pagination,
      "total"
    );
    const hasTotalCount = Object.prototype.hasOwnProperty.call(
      value.pagination,
      "totalCount"
    );
    const total = hasTotal
      ? nonNegativeInteger(value.pagination.total)
      : null;
    const alternateTotal = hasTotal && hasTotalCount
      ? nonNegativeInteger(value.pagination.totalCount)
      : total;
    const consumed = (page - 1) * size + itemList.length;
    if (
      !hasTotal ||
      total === null ||
      alternateTotal !== total ||
      total < consumed ||
      value.pagination.hasMore !== (consumed < total)
    ) {
      throw new Error("invalid_response");
    }
    pagination.total = total;
    if (hasTotalCount) {
      pagination.totalCount = total;
    }
    return { itemList, pagination };
  }

  function oneText(value, maximum = 2000, allowEmpty = true) {
    if (
      typeof value !== "string" ||
      value.length > maximum ||
      /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value) ||
      (!allowEmpty && value.trim() === "")
    ) {
      return null;
    }
    return value;
  }

  function oneMetric(value, maximum = Number.MAX_SAFE_INTEGER) {
    const parsed = typeof value === "string" &&
      /^(?:0|[1-9][0-9]*)$/.test(value)
      ? Number(value)
      : value;
    return (
      Number.isFinite(parsed) &&
      parsed >= 0 &&
      parsed <= maximum
    ) ? parsed : null;
  }

  function oneDecimal(value, allowEmpty = true) {
    if (allowEmpty && (value === undefined || value === null || value === "")) {
      return "";
    }
    const text = String(value);
    return /^(?:0|[1-9][0-9]{0,31})$/.test(text) ? text : null;
  }

  function projectOneRecentVideo(value) {
    if (!isRecord(value)) {
      return null;
    }
    const id = decimalIdentifier(value.itemID);
    const title = oneText(String(value.title || ""), 2000);
    const createdAt = oneDecimal(value.createTime);
    const views = oneDecimal(value.views);
    const likes = oneMetric(value.heart);
    const comments = oneMetric(value.comment);
    const shares = oneMetric(value.share);
    const coverURL = httpsAsset(String(value.coverURL || ""));
    const videoURL = httpsAsset(String(value.videoURL || ""));
    if (
      !id ||
      title === null ||
      createdAt === null ||
      views === null ||
      likes === null ||
      comments === null ||
      shares === null ||
      coverURL === null ||
      videoURL === null
    ) {
      return null;
    }
    return {
      id,
      title,
      created_at: createdAt,
      views,
      likes,
      comments,
      shares,
      sponsored: value.isSponsoredVideo === true,
      cover_url: coverURL,
      video_url: videoURL
    };
  }

  function projectOneRate(price, amountName, currencyName) {
    if (!isRecord(price)) {
      return null;
    }
    const amount100k = oneDecimal(price[amountName]);
    const currency = oneText(String(price[currencyName] || ""), 8, false);
    if (amount100k === null || currency === null) {
      return null;
    }
    if (amount100k === "" || currency === "") {
      return null;
    }
    return {
      amount_100k: amount100k,
      currency
    };
  }

  function projectOneCreator(value) {
    if (
      !isRecord(value) ||
      !isRecord(value.creatorTTInfo) ||
      !isRecord(value.statisticData) ||
      !isRecord(value.statisticData.overallPerformance)
    ) {
      return null;
    }
    const creatorID = decimalIdentifier(value.aioCreatorID);
    const tiktokUID = decimalIdentifier(value.ttUID);
    const info = value.creatorTTInfo;
    const handle = oneText(info.handleName, 128, false);
    const nickname = oneText(info.nickName, 512, false);
    const bio = oneText(String(info.bio || ""), 2000);
    const region = oneText(String(info.storeRegion || ""), 8, false);
    const avatarURL = httpsAsset(String(info.avatarURL || ""));
    const performance = value.statisticData.overallPerformance;
    const followers = oneMetric(performance.followerCount);
    const medianViews = oneMetric(performance.medianViews);
    const engagementRate = oneMetric(performance.engagementRate, 1);
    if (
      !creatorID ||
      !tiktokUID ||
      handle === null ||
      nickname === null ||
      bio === null ||
      region === null ||
      avatarURL === null ||
      followers === null ||
      medianViews === null ||
      engagementRate === null
    ) {
      return null;
    }
    const scores = {};
    if (isRecord(value.creatorValueStat)) {
      for (const [source, target] of [
        ["commercialScore", "commercial"],
        ["collaborationScore", "collaboration"],
        ["broadcastingScore", "broadcasting"],
        ["comprehensiveScore", "comprehensive"]
      ]) {
        const score = oneMetric(value.creatorValueStat[source], 100);
        if (score !== null) {
          scores[target] = score;
        }
      }
    }
    const labels = Array.isArray(value.contentLabels)
      ? value.contentLabels.slice(0, 100).map((item) => {
        if (!isRecord(item)) {
          return null;
        }
        const id = oneDecimal(item.labelID);
        const level = oneMetric(item.labelLevel, 20);
        const type = oneMetric(item.labelType, 20);
        return id && level !== null && type !== null
          ? { id, level, type }
          : null;
      })
      : [];
    const recentVideos = Array.isArray(value.recentItems)
      ? value.recentItems.slice(0, 20).map(projectOneRecentVideo)
      : [];
    if (
      labels.some((item) => item === null) ||
      recentVideos.some((item) => item === null)
    ) {
      return null;
    }
    const price = isRecord(value.esData) && isRecord(value.esData.price)
      ? value.esData.price
      : {};
    const rates = {};
    for (const [name, amountName, currencyName] of [
      ["recommended", "recommendRate100k", "currency"],
      ["starting", "startingRate100k", "currency"],
      [
        "regional_starting",
        "storeRegionStartingRate100k",
        "storeRegionCurrency"
      ]
    ]) {
      const rate = projectOneRate(price, amountName, currencyName);
      if (rate) {
        rates[name] = rate;
      }
    }
    const risk = isRecord(value.riskInfo)
      ? value.riskInfo
      : isRecord(info.riskInfo)
        ? info.riskInfo
        : {};
    const discipline = Array.isArray(risk.disciplineInfoList)
      ? risk.disciplineInfoList.length
      : 0;
    const events = Array.isArray(risk.riskEventInfoList)
      ? risk.riskEventInfoList.length
      : 0;
    return {
      creator_id: creatorID,
      tiktok_uid: tiktokUID,
      handle,
      nickname,
      bio,
      region,
      avatar_url: avatarURL,
      banned: info.isBannedInTT === true,
      metrics: {
        followers,
        median_views: medianViews,
        engagement_rate: engagementRate
      },
      scores,
      rates,
      content_labels: labels,
      recent_videos: recentVideos,
      risk: {
        discipline_count: discipline,
        event_count: events
      }
    };
  }

  function normalizeOneFilters(value) {
    if (!isRecord(value)) {
      throw new Error("invalid_response");
    }
    const result = {};
    for (const name of [
      "allDataVDCRegions",
      "audienceEngagedFilterGroup",
      "audienceReachedFilterGroup",
      "audienceRegionIndustryList",
      "commercialReadinessOptions",
      "defaultDataVDCRegion",
      "defaultRegion",
      "defaultRegionLabelInfoList",
      "followerRegions",
      "languages",
      "personaList",
      "recommendationTypeOptions",
      "regionPriceSegment",
      "regionToSubRegionList",
      "storeRegions",
      "vdcDefaultRegionList"
    ]) {
      if (Object.prototype.hasOwnProperty.call(value, name)) {
        result[name] = value[name];
      }
    }
    if (
      !Array.isArray(result.languages) ||
      result.languages.length < 1 ||
      !Array.isArray(result.allDataVDCRegions) ||
      !Number.isSafeInteger(Number(result.defaultDataVDCRegion))
    ) {
      throw new Error("invalid_response");
    }
    return result;
  }

  function normalizeOneSuggestions(value) {
    if (
      !isRecord(value) ||
      !Array.isArray(value.suggestedWords) ||
      value.suggestedWords.length > 100
    ) {
      throw new Error("invalid_response");
    }
    const seen = new Set();
    const suggestedWords = value.suggestedWords.map((item) => {
      const word = isRecord(item)
        ? oneText(item.suggestedWord, 256, false)
        : null;
      if (!word || seen.has(word)) {
        return null;
      }
      seen.add(word);
      return word;
    });
    if (suggestedWords.some((item) => item === null)) {
      throw new Error("invalid_response");
    }
    return { suggestedWords };
  }

  function normalizeOneSearch(value, body) {
    if (
      !isRecord(value) ||
      !Array.isArray(value.creators) ||
      value.creators.length > body.limit ||
      !isRecord(value.pagination)
    ) {
      throw new Error("invalid_response");
    }
    const creators = value.creators.map(projectOneCreator);
    const page = positivePageValue(value.pagination.page, 1000);
    const limit = positivePageValue(value.pagination.limit, 24);
    const totalCount = nonNegativeInteger(value.pagination.totalCount);
    const hasMore = value.pagination.hasMore;
    if (
      creators.some((item) => item === null) ||
      page !== body.page ||
      limit !== body.limit ||
      totalCount === null ||
      totalCount < (page - 1) * limit + creators.length ||
      typeof hasMore !== "boolean"
    ) {
      throw new Error("invalid_response");
    }
    return {
      creators,
      pagination: {
        page,
        limit,
        totalCount,
        hasMore
      },
      hasMoreMatchCreators: value.hasMoreMatchCreators === true,
      hasMoreRecommendedCreators: value.hasMoreRecommendedCreators === true
    };
  }

  function studioText(value, maximum = 5000, allowEmpty = true) {
    if (
      typeof value !== "string" ||
      value.length > maximum ||
      (!allowEmpty && value.trim() === "")
    ) {
      return null;
    }
    return value;
  }

  function studioAssetID(value, allowEmpty = true) {
    if (allowEmpty && value === "") {
      return "";
    }
    return typeof value === "string" &&
      /^[A-Za-z0-9_-]{1,256}$/.test(value)
      ? value
      : null;
  }

  function studioTaskStatus(draftStatus, renderStatus, vid, value) {
    if (draftStatus === 0 && renderStatus === 0 && vid !== "") {
      return "succeeded";
    }
    if (
      draftStatus === 3 ||
      renderStatus === 3 ||
      value.generateErrorCode ||
      value.renderErrorCode
    ) {
      return "failed";
    }
    return "processing";
  }

  function projectStudioDraft(value, expectedTaskID = "") {
    if (!isRecord(value)) {
      return null;
    }
    const taskID = decimalIdentifier(value.taskId);
    const draftID = decimalIdentifier(value.id);
    const draftStatus = Number(value.draftTaskStatus);
    const renderStatus = Number(value.renderTaskStatus);
    const vid = studioAssetID(value.vid);
    const watermarkVid = studioAssetID(value.watermarkVid);
    const coverImage = httpsAsset(String(value.coverImage || ""), true);
    const previewLink = httpsAsset(String(value.previewLink || ""), true);
    const name = studioText(value.name, 1024);
    const miniAppType = studioText(value.miniAppType, 64, false);
    if (
      !taskID ||
      !draftID ||
      (expectedTaskID && taskID !== expectedTaskID) ||
      !Number.isInteger(draftStatus) ||
      draftStatus < 0 ||
      draftStatus > 4 ||
      !Number.isInteger(renderStatus) ||
      renderStatus < 0 ||
      renderStatus > 4 ||
      vid === null ||
      watermarkVid === null ||
      coverImage === null ||
      previewLink === null ||
      name === null ||
      miniAppType === null
    ) {
      return null;
    }
    let settings = {};
    if (typeof value.settings === "string" && value.settings.length <= 20000) {
      try {
        const parsed = JSON.parse(value.settings);
        if (isRecord(parsed)) {
          const prompt = studioText(parsed.prompt, 5000);
          const duration = Number(parsed.duration);
          settings = {
            model_id: String(parsed.aiModel || ""),
            duration: Number.isInteger(duration) ? duration : null,
            prompt,
            enhance_prompt: parsed.useEnhancePrompt === true
          };
        }
      } catch {
        settings = {};
      }
    }
    const generateErrorCode = studioText(
      String(value.generateErrorCode || ""),
      128
    );
    const generateErrorMessage = studioText(
      String(value.generateErrorMessage || ""),
      2000
    );
    const renderErrorCode = studioText(
      String(value.renderErrorCode || ""),
      128
    );
    const renderErrorMessage = studioText(
      String(value.renderErrorMessage || ""),
      2000
    );
    if (
      [
        generateErrorCode,
        generateErrorMessage,
        renderErrorCode,
        renderErrorMessage
      ].some((item) => item === null)
    ) {
      return null;
    }
    return {
      task_id: taskID,
      draft_id: draftID,
      name,
      mini_app_type: miniAppType,
      status: studioTaskStatus(draftStatus, renderStatus, vid, value),
      draft_status: draftStatus,
      render_status: renderStatus,
      has_content: value.hasContent === true,
      vid,
      watermark_vid: watermarkVid,
      cover_image: coverImage,
      preview_link: previewLink,
      settings,
      errors: {
        generate_code: generateErrorCode,
        generate_message: generateErrorMessage,
        render_code: renderErrorCode,
        render_message: renderErrorMessage
      }
    };
  }

  function normalizeStudioTask(value, expectedTaskID = "") {
    const data = isRecord(value) && isRecord(value.data) ? value.data : null;
    const taskID = decimalIdentifier(
      String((data && data.task_id) || expectedTaskID || "")
    );
    const rawDrafts = data && Array.isArray(data.draft_infos)
      ? data.draft_infos
      : null;
    if (!taskID || !rawDrafts || rawDrafts.length < 1 || rawDrafts.length > 20) {
      throw new Error("invalid_response");
    }
    const drafts = rawDrafts.map((item) => projectStudioDraft(item, taskID));
    if (drafts.some((item) => item === null)) {
      throw new Error("invalid_response");
    }
    const status = drafts.some((item) => item.status === "failed")
      ? "failed"
      : drafts.every((item) => item.status === "succeeded")
        ? "succeeded"
        : "processing";
    return {
      task_id: taskID,
      status,
      poll_after_ms: status === "processing" ? 5000 : 0,
      drafts
    };
  }

  function normalizeStudioCredits(value) {
    const numericString = (item) => {
      const text = String(item ?? "");
      return /^(?:0|[1-9][0-9]{0,31})$/.test(text) ? text : null;
    };
    const credits = numericString(value && value.credits);
    const bonus = numericString(value && value.bonus);
    const weeklySpent = numericString(value && value.weekly_spent);
    const tier = Number(value && value.tier);
    if (
      !isRecord(value) ||
      credits === null ||
      bonus === null ||
      weeklySpent === null ||
      !Number.isSafeInteger(tier) ||
      tier < 0 ||
      typeof value.is_unlimited !== "boolean"
    ) {
      throw new Error("invalid_response");
    }
    return {
      credits,
      bonus,
      weekly_spent: weeklySpent,
      tier,
      is_unlimited: value.is_unlimited
    };
  }

  function normalizeStudioPermissions(value) {
    const data = isRecord(value) && isRecord(value.data) ? value.data : null;
    const rawPermissions = data && isRecord(data.miniappPermissions)
      ? data.miniappPermissions
      : null;
    const rawAllowlist = data && Array.isArray(data.allowlist)
      ? data.allowlist
      : null;
    if (
      !rawPermissions ||
      !rawAllowlist ||
      Object.keys(rawPermissions).length > 100 ||
      rawAllowlist.length > 100
    ) {
      throw new Error("invalid_response");
    }
    const permissions = {};
    for (const [name, item] of Object.entries(rawPermissions)) {
      if (
        !/^[A-Za-z0-9/_-]{1,128}$/.test(name) ||
        !isRecord(item)
      ) {
        throw new Error("invalid_response");
      }
      const projected = {};
      for (const [source, target] of [
        ["entryPass", "entry_pass"],
        ["allowListPass", "allowlist_pass"],
        ["ipPass", "ip_pass"]
      ]) {
        if (item[source] !== undefined) {
          if (typeof item[source] !== "boolean") {
            throw new Error("invalid_response");
          }
          projected[target] = item[source];
        }
      }
      permissions[name] = projected;
    }
    const allowlist = rawAllowlist.map((item) => {
      if (
        !isRecord(item) ||
        typeof item.tool !== "string" ||
        !/^[A-Za-z0-9/_-]{1,128}$/.test(item.tool) ||
        !Array.isArray(item.auth) ||
        item.auth.length > 20 ||
        item.auth.some((auth) =>
          typeof auth !== "string" ||
          !/^[A-Za-z0-9/_-]{1,32}$/.test(auth)
        )
      ) {
        return null;
      }
      return {
        tool: item.tool,
        auth: [...new Set(item.auth)]
      };
    });
    if (allowlist.some((item) => item === null)) {
      throw new Error("invalid_response");
    }
    return { permissions, allowlist };
  }

  function normalizeStudioGeneratingCount(value) {
    const data = isRecord(value) && isRecord(value.data) ? value.data : null;
    const total = Number(data && data.total);
    if (!Number.isSafeInteger(total) || total < 0 || total > 100000) {
      throw new Error("invalid_response");
    }
    return { total };
  }

  function normalizeStudioMaxCount(value) {
    const data = isRecord(value) && isRecord(value.data) ? value.data : null;
    if (!data || Object.keys(data).length < 1 || Object.keys(data).length > 100) {
      throw new Error("invalid_response");
    }
    const limits = {};
    for (const [name, rawLimit] of Object.entries(data)) {
      const limit = Number(rawLimit);
      if (
        !/^[A-Za-z0-9/_-]{1,128}$/.test(name) ||
        !Number.isSafeInteger(limit) ||
        limit < 0 ||
        limit > 100000
      ) {
        throw new Error("invalid_response");
      }
      limits[name] = limit;
    }
    return { limits };
  }

  function normalizeStudioLedger(value) {
    const rawEntries = isRecord(value) &&
      Array.isArray(value.credit_ledger_entries)
      ? value.credit_ledger_entries
      : null;
    if (
      !rawEntries ||
      rawEntries.length > 100 ||
      typeof value.has_more !== "boolean"
    ) {
      throw new Error("invalid_response");
    }
    const entries = rawEntries.map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const action = studioText(item.action, 128, false);
      const appSource = studioText(item.app_source, 128);
      const transactionID = studioText(item.transaction_id, 256);
      const amount = Number(item.amount);
      const duration = Number(item.duration);
      const createdAt = Number(item.created_at);
      const updatedAt = Number(item.updated_at);
      const type = Number(item.type);
      if (
        action === null ||
        appSource === null ||
        transactionID === null ||
        !Number.isSafeInteger(amount) ||
        !Number.isSafeInteger(duration) ||
        duration < 0 ||
        !Number.isSafeInteger(createdAt) ||
        createdAt < 0 ||
        !Number.isSafeInteger(updatedAt) ||
        updatedAt < 0 ||
        !Number.isSafeInteger(type)
      ) {
        return null;
      }
      return {
        action,
        amount,
        duration,
        app_source: appSource,
        created_at: createdAt,
        updated_at: updatedAt,
        transaction_id: transactionID,
        type
      };
    });
    if (entries.some((item) => item === null)) {
      throw new Error("invalid_response");
    }
    const nextCursor = value.next_cursor;
    if (
      value.has_more &&
      (
        typeof nextCursor !== "string" ||
        nextCursor.trim() === "" ||
        nextCursor.length > 1024 ||
        /[\r\n\0]/.test(nextCursor)
      )
    ) {
      throw new Error("invalid_response");
    }
    return {
      entries,
      has_more: value.has_more,
      next_cursor: value.has_more ? nextCursor : ""
    };
  }

  function normalizeStudioHistory(value, expectedOffset, expectedLimit) {
    const data = isRecord(value) && isRecord(value.data) ? value.data : null;
    const rawDrafts = data && Array.isArray(data.draft_infos)
      ? data.draft_infos
      : null;
    const offset = Number(data && data.pageOffset);
    const limit = Number(data && data.pageLimit);
    const total = Number(data && data.total);
    if (
      !rawDrafts ||
      rawDrafts.length > expectedLimit ||
      offset !== expectedOffset ||
      limit !== expectedLimit ||
      !Number.isSafeInteger(total) ||
      total < rawDrafts.length ||
      (rawDrafts.length > 0 && total < offset + rawDrafts.length)
    ) {
      throw new Error("invalid_response");
    }
    const drafts = rawDrafts.map((item) => projectStudioDraft(item));
    if (drafts.some((item) => item === null)) {
      throw new Error("invalid_response");
    }
    return {
      offset,
      limit,
      total,
      has_more: offset + drafts.length < total,
      next_offset: offset + drafts.length,
      drafts
    };
  }

  function normalizeStudioTaskDetail(value, expectedDraftID) {
    const data = isRecord(value) && isRecord(value.data) ? value.data : null;
    const draft = projectStudioDraft(data);
    if (!draft || draft.draft_id !== expectedDraftID) {
      throw new Error("invalid_response");
    }
    return draft;
  }

  function normalizeStudioVideoInfo(value, expectedVid) {
    const data = isRecord(value) && isRecord(value.data) ? value.data : null;
    const video = data && isRecord(data[expectedVid]) ? data[expectedVid] : null;
    const poster = httpsAsset(String((video && video.PosterUrl) || ""));
    const duration = Number(video && video.Duration);
    const rawVariants = video && Array.isArray(video.VideoInfos)
      ? video.VideoInfos
      : null;
    if (
      !video ||
      poster === null ||
      !Number.isFinite(duration) ||
      duration <= 0 ||
      duration > 120 ||
      !rawVariants ||
      rawVariants.length < 1 ||
      rawVariants.length > 20
    ) {
      throw new Error("invalid_response");
    }
    const variants = rawVariants.map((item) => {
      const meta = isRecord(item) && isRecord(item.VideoMeta)
        ? item.VideoMeta
        : null;
      const mainURL = httpsAsset(String((item && item.MainUrl) || ""));
      const backupURL = httpsAsset(String((item && item.BackupUrl) || ""));
      const width = Number(meta && meta.Width);
      const height = Number(meta && meta.Height);
      const size = Number(meta && meta.Size);
      const bitrate = Number(meta && meta.Bitrate);
      const fps = Number(meta && meta.FPS);
      const definition = studioText(String((meta && meta.Definition) || ""), 64);
      const format = studioText(String((meta && meta.Format) || ""), 32);
      if (
        mainURL === null ||
        backupURL === null ||
        !Number.isSafeInteger(width) ||
        width <= 0 ||
        !Number.isSafeInteger(height) ||
        height <= 0 ||
        !Number.isSafeInteger(size) ||
        size <= 0 ||
        !Number.isSafeInteger(bitrate) ||
        bitrate <= 0 ||
        !Number.isFinite(fps) ||
        fps <= 0 ||
        definition === null ||
        format === null
      ) {
        return null;
      }
      return {
        url: mainURL,
        backup_url: backupURL,
        width,
        height,
        size,
        bitrate,
        fps,
        definition,
        format
      };
    });
    if (variants.some((item) => item === null)) {
      throw new Error("invalid_response");
    }
    variants.sort((left, right) =>
      (right.width * right.height) - (left.width * left.height)
    );
    return {
      vid: expectedVid,
      duration,
      poster_url: poster,
      video_url: variants[0].url,
      variants
    };
  }

  function adsKeywordNumber(value, maximum = Number.MAX_SAFE_INTEGER) {
    const parsed = typeof value === "string" && value.trim() !== ""
      ? Number(value)
      : value;
    return (
      typeof parsed === "number" &&
      Number.isFinite(parsed) &&
      parsed >= 0 &&
      parsed <= maximum
    ) ? parsed : null;
  }

  function adsKeywordRange(value, minimumName, maximumName) {
    if (!isRecord(value)) {
      return null;
    }
    const minimum = adsKeywordNumber(value[minimumName]);
    const maximum = adsKeywordNumber(value[maximumName]);
    return minimum !== null && maximum !== null && minimum <= maximum
      ? { [minimumName]: minimum, [maximumName]: maximum }
      : null;
  }

  function projectAdsKeywordIdea(value) {
    if (!isRecord(value)) {
      return null;
    }
    const keyword = typeof value.keyword === "string"
      ? value.keyword
      : "";
    const searchVol = adsKeywordRange(
      value.searchVol,
      "volumeMin",
      "volumeMax"
    );
    const estimatedCpc = adsKeywordRange(
      value.estimatedCpc,
      "estimatedCpcLow",
      "estimatedCpcHigh"
    );
    const countryId = value.countryId === null
      ? null
      : adsKeywordNumber(value.countryId);
    if (
      keyword.trim() === "" ||
      keyword.length > 80 ||
      !searchVol ||
      !estimatedCpc ||
      (
        value.threeMonthChange !== null &&
        (
          typeof value.threeMonthChange !== "number" ||
          !Number.isFinite(value.threeMonthChange)
        )
      ) ||
      (
        value.yoyChange !== null &&
        (
          typeof value.yoyChange !== "number" ||
          !Number.isFinite(value.yoyChange)
        )
      ) ||
      ![1, 2, 3].includes(value.competition) ||
      ![0, 1, 2].includes(value.brandOption) ||
      !Number.isSafeInteger(value.sourceType) ||
      value.sourceType < 0 ||
      ![1, 2, 3].includes(value.matchType) ||
      value.language !== "en" ||
      (value.countryId !== null && !Number.isSafeInteger(countryId))
    ) {
      return null;
    }
    return {
      keyword,
      searchVol,
      threeMonthChange: value.threeMonthChange,
      yoyChange: value.yoyChange,
      trend: sanitize(value.trend),
      competition: value.competition,
      estimatedCpc,
      brandOption: value.brandOption,
      sourceType: value.sourceType,
      matchType: value.matchType,
      language: "en",
      countryId
    };
  }

  function normalizeAdsKeywordIdeas(value, validation) {
    if (
      !isRecord(value) ||
      !Array.isArray(value.keywordIdeaInfoList) ||
      value.keywordIdeaInfoList.length > 200
    ) {
      throw new Error("invalid_response");
    }
    const keywordIdeaInfoList = value.keywordIdeaInfoList.map(
      projectAdsKeywordIdea
    );
    const hasTotalSearchVol = value.totalSearchVol != null;
    const totalSearchVol = !hasTotalSearchVol
      ? null
      : adsKeywordRange(
          value.totalSearchVol,
          "volumeMin",
          "volumeMax"
        );
    const hasTotalBudgetEstimate = value.totalBudgetEstimate != null;
    const totalBudgetEstimate = !hasTotalBudgetEstimate
      ? null
      : adsKeywordRange(
          value.totalBudgetEstimate,
          "volumeMin",
          "volumeMax"
        );
    if (
      keywordIdeaInfoList.some((item) => item === null) ||
      (hasTotalSearchVol && !totalSearchVol) ||
      (keywordIdeaInfoList.length > 0 && !totalSearchVol) ||
      (hasTotalBudgetEstimate && !totalBudgetEstimate)
    ) {
      throw new Error("invalid_response");
    }
    return {
      keywordIdeaInfoList,
      totalSearchVol,
      totalBudgetEstimate,
      validation
    };
  }

  function normalizeAdsKeywordSummary(value) {
    if (!isRecord(value)) {
      throw new Error("invalid_response");
    }
    const totalSearchVol = adsKeywordRange(
      value.totalSearchVol,
      "volumeMin",
      "volumeMax"
    );
    const totalBudgetEstimate = value.totalBudgetEstimate === null
      ? null
      : adsKeywordRange(
          value.totalBudgetEstimate,
          "volumeMin",
          "volumeMax"
        );
    if (
      !totalSearchVol ||
      (value.totalBudgetEstimate !== null && !totalBudgetEstimate)
    ) {
      throw new Error("invalid_response");
    }
    return { totalSearchVol, totalBudgetEstimate };
  }

  function upstreamError(payload) {
    if (!isRecord(payload)) {
      return "";
    }
    const base = isRecord(payload.BaseResp)
      ? payload.BaseResp
      : isRecord(payload.baseResp)
        ? payload.baseResp
        : null;
    const code = Number(base && base.StatusCode);
    if (Number.isFinite(code) && code !== 0) {
      return `${code} ${String(base.StatusMessage || "")}`.trim();
    }
    if (
      payload.code !== undefined &&
      String(payload.code) !== "" &&
      String(payload.code) !== "0"
    ) {
      return `${String(payload.code)} ${String(
        payload.message || payload.msg || ""
      )}`.trim();
    }
    return "";
  }

  function errorCode(error) {
    if (verificationRequired()) {
      return "verification_required";
    }
    if (profileCompletionRequired()) {
      return "profile_required";
    }
    const message = String(
      (error && (error.message || error.msg || error.statusText)) || error || ""
    );
    if (/profile[_ ]required|complete your profile|business (?:type|info)/i.test(message)) {
      return "profile_required";
    }
    if (/verification[_ ]required|two.?step|2sv|captcha/i.test(message)) {
      return "verification_required";
    }
    if (/advertiser_account_required/i.test(message)) {
      return "advertiser_account_required";
    }
    if (/csrf_or_signature_expired/i.test(message)) {
      return "csrf_or_signature_expired";
    }
    if (/keyword_not_allowed/i.test(message)) {
      return "keyword_not_allowed";
    }
    if (/keyword_invalid/i.test(message)) {
      return "keyword_invalid";
    }
    if (/38001001|invalidlogin|401|unauthorized|not[_ ]logged[_ ]in/i.test(message)) {
      return "not_logged_in";
    }
    if (/403|forbidden|permission/i.test(message)) {
      return "forbidden";
    }
    if (/429|rate.?limit|too many/i.test(message)) {
      return "rate_limited";
    }
    if (/timeout|timed out/i.test(message)) {
      return "timeout";
    }
    if (/invalid_response/i.test(message)) {
      return "invalid_response";
    }
    return "request_failed";
  }

  function cookieValue(name) {
    const prefix = `${name}=`;
    for (const part of String(document.cookie || "").split(";")) {
      const item = part.trim();
      if (!item.startsWith(prefix)) {
        continue;
      }
      try {
        return decodeURIComponent(item.slice(prefix.length));
      } catch {
        return "";
      }
    }
    return "";
  }

  function studioHeaders(includeContentType = false) {
    const headers = {
      "accept": "application/json, text/plain, */*",
      "agw-js-conv": "str",
      "x-creative-source": "cue/avatar"
    };
    if (includeContentType) {
      headers["content-type"] = "application/json";
    }
    const csrf = cookieValue("csrftoken");
    if (csrf) {
      headers["x-csrftoken"] = csrf;
    }
    const creativeCsrf = cookieValue("x-creative-csrf-token");
    if (creativeCsrf) {
      headers["x-creative-csrf-token"] = creativeCsrf;
    }
    return headers;
  }

  function oneHeaders(includeContentType = false) {
    const headers = {
      "accept": "application/json, text/plain, */*",
      "agw-js-conv": "str"
    };
    if (includeContentType) {
      headers["content-type"] = "application/json";
    }
    const csrf = cookieValue("csrftoken");
    if (csrf) {
      headers["x-csrftoken"] = csrf;
    }
    return headers;
  }

  function adsKeywordAccountID() {
    const accountID = new URLSearchParams(location.search || "").get("aadvid");
    return /^[1-9][0-9]{0,31}$/.test(accountID || "") ? accountID : "";
  }

  function adsManagerAccountPage() {
    return (
      location.origin === "https://ads.tiktok.com" &&
      location.pathname.startsWith("/i18n/") &&
      adsKeywordAccountID() !== ""
    );
  }

  function adsKeywordHeaders() {
    const csrf = cookieValue("csrftoken");
    if (!csrf) {
      throw new Error("csrf_or_signature_expired");
    }
    return {
      "accept": "application/json, text/plain, */*",
      "content-type": "application/json",
      "x-csrftoken": csrf
    };
  }

  async function rawAdsKeywordRequest(path, body) {
    const accountID = adsKeywordAccountID();
    if (!accountID) {
      throw new Error("advertiser_account_required");
    }
    const requestBody = { ...body, aadvid: accountID };
    const result = await window.fetch(
      `${path}?aadvid=${encodeURIComponent(accountID)}`,
      {
        method: "POST",
        credentials: "include",
        headers: adsKeywordHeaders(),
        body: JSON.stringify(requestBody)
      }
    );
    if (!result.ok) {
      throw new Error(`HTTP ${result.status}`);
    }
    let payload;
    try {
      payload = await result.json();
    } catch {
      throw new Error("invalid_response");
    }
    const upstream = upstreamError(payload);
    if (upstream) {
      throw new Error(upstream);
    }
    if (!isRecord(payload) || !isRecord(payload.data)) {
      throw new Error("invalid_response");
    }
    return payload.data;
  }

  async function validateAdsKeywords(keywords) {
    const nogo = await rawAdsKeywordRequest(
      ADS_KEYWORD_NOGO_PATH,
      { keywords, regions: [] }
    );
    const nogoMap = nogo.keywordsInNoGoList;
    if (!isRecord(nogoMap)) {
      throw new Error("invalid_response");
    }
    for (const keyword of keywords) {
      if (nogoMap[keyword] === true) {
        throw new Error("keyword_not_allowed");
      }
      if (nogoMap[keyword] !== false) {
        throw new Error("invalid_response");
      }
    }
    const identifiers = await rawAdsKeywordRequest(
      ADS_KEYWORD_IDS_PATH,
      { keywords }
    );
    if (
      !Array.isArray(identifiers.keywords) ||
      identifiers.keywords.length !== keywords.length
    ) {
      throw new Error("invalid_response");
    }
    const wordIDs = identifiers.keywords.map((item, index) => {
      const expected = keywords[index];
      const keywordID = String((item && item.keywordId) || "");
      if (
        !isRecord(item) ||
        item.keyword !== expected ||
        ![null, -1].includes(item.invalidCode)
      ) {
        throw new Error("keyword_invalid");
      }
      if (!/^[1-9][0-9]{0,31}$/.test(keywordID)) {
        throw new Error("invalid_response");
      }
      return {
        keyword: expected,
        keywordId: keywordID,
        invalidCode: null
      };
    });
    return {
      keywordsInNoGoList: Object.fromEntries(
        keywords.map((keyword) => [keyword, false])
      ),
      keywords: wordIDs
    };
  }

  async function directAdsKeywordRequest(path, body) {
    if (path === ADS_KEYWORD_IDEAS_PATH) {
      const keywords = body.inputKeywords.map((item) => item.keyword);
      const validation = await validateAdsKeywords(keywords);
      const data = await rawAdsKeywordRequest(path, body);
      return normalizeAdsKeywordIdeas(data, validation);
    }
    if (path === ADS_KEYWORD_SUMMARY_PATH) {
      await validateAdsKeywords(body.words.map((item) => item.keyword));
      return normalizeAdsKeywordSummary(
        await rawAdsKeywordRequest(path, body)
      );
    }
    throw new Error("invalid_request");
  }

  async function directStudioVideoInfo(vid) {
    const requestURL =
      `${STUDIO_VIDEO_INFO_PATH}?vid=${encodeURIComponent(vid)}` +
      "&aid=585599&app_name=creative_aio_client&device_platform=web";
    const result = await fetch(requestURL, {
      method: "GET",
      credentials: "include",
      headers: studioHeaders()
    });
    if (!result.ok) {
      throw new Error(`HTTP ${result.status}`);
    }
    let payload;
    try {
      payload = await result.json();
    } catch {
      throw new Error("invalid_response");
    }
    const upstream = upstreamError(payload);
    if (upstream) {
      throw new Error(upstream);
    }
    return normalizeStudioVideoInfo(payload, vid);
  }

  async function uploadStudioImage(body) {
    const runtimeRequire = studioRuntimeRequire();
    if (!runtimeRequire) {
      throw new Error("transport_modules_changed");
    }
    let uploadModule;
    let tokenModule;
    try {
      uploadModule = runtimeRequire(35970);
      tokenModule = runtimeRequire(91304);
    } catch {
      throw new Error("transport_modules_changed");
    }
    if (
      !isRecord(uploadModule) ||
      typeof uploadModule.rh !== "function" ||
      !isRecord(tokenModule) ||
      typeof tokenModule.getToken !== "function"
    ) {
      throw new Error("transport_modules_changed");
    }
    let binary;
    try {
      binary = atob(body.dataBase64);
    } catch {
      throw new Error("invalid_request");
    }
    if (binary.length < 1 || binary.length > 5 * 1024 * 1024) {
      throw new Error("invalid_request");
    }
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    const file = new File([bytes], body.name, { type: body.mimeType });
    const result = await uploadModule.rh(file, {
      fromModule: "i2v",
      getUploadToken: () => tokenModule.getToken({})
    });
    if (
      !isRecord(result) ||
      !validStudioImageUrl(result.imageUrl) ||
      typeof result.imageUri !== "string" ||
      result.imageUri.length < 1 ||
      !Number.isInteger(result.imageWidth) ||
      result.imageWidth <= 0 ||
      !Number.isInteger(result.imageHeight) ||
      result.imageHeight <= 0
    ) {
      throw new Error("invalid_response");
    }
    return {
      image_url: result.imageUrl,
      image_uri: result.imageUri,
      width: result.imageWidth,
      height: result.imageHeight
    };
  }

  async function directTrendingVideoOverviewRequest() {
    const result = await fetch(TRENDING_VIDEO_OVERVIEW_PATH, {
      method: "GET",
      credentials: "include",
      headers: { accept: "application/json, text/plain, */*" }
    });
    if (!result.ok) {
      throw new Error(`HTTP ${result.status}`);
    }
    let payload;
    try {
      payload = await result.json();
    } catch {
      throw new Error("invalid_response");
    }
    const upstream = upstreamError(payload);
    if (upstream) {
      throw new Error(upstream);
    }
    return normalizeTrendingVideoOverview(payload);
  }

  function parseTrendingVideoListPayload(text) {
    if (typeof text !== "string") {
      throw new Error("invalid_response");
    }
    // itemID、authorID 和 creatorID 常以超出 JavaScript 安全整数范围的裸数字返回。
    // 在 JSON.parse 前把这些已知标识符转为字符串，避免生成错误的公开视频 URL。
    const normalized = text.replace(
      /("(?:itemID|authorID|creatorID)"\s*:\s*)([1-9][0-9]{15,})(?=\s*[,}])/g,
      "$1\"$2\""
    );
    try {
      return JSON.parse(normalized);
    } catch {
      throw new Error("invalid_response");
    }
  }

  async function directTrendingVideoListRequest(body) {
    const parameters = new URLSearchParams({
      periodDimension: String(body.periodDimension),
      periodEndTimestamp: String(body.periodEndTimestamp),
      orderByMetric: String(body.orderByMetric),
      countryCode: body.countryCode,
      contentLabelIDs: body.contentLabelIDs.join(","),
      organicOnly: String(body.organicOnly),
      limit: String(body.limit),
      page: String(body.page)
    });
    const result = await fetch(
      `${TRENDING_VIDEO_LIST_PATH}?${parameters.toString()}`,
      {
        method: "GET",
        credentials: "include",
        headers: { accept: "application/json, text/plain, */*" }
      }
    );
    if (!result.ok) {
      throw new Error(`HTTP ${result.status}`);
    }
    let payload;
    try {
      payload = parseTrendingVideoListPayload(await result.text());
    } catch {
      throw new Error("invalid_response");
    }
    const upstream = upstreamError(payload);
    if (upstream) {
      throw new Error(upstream);
    }
    return normalizeTrendingVideoList(payload, body);
  }

  async function directRequest(path, body) {
    const isFilters = path === TOP_ADS_FILTERS_PATH;
    const studioPaths = [
      STUDIO_CREDITS_PATH,
      STUDIO_GENERATE_PATH,
      STUDIO_I2V_GENERATE_PATH,
      STUDIO_TASK_PATH,
      STUDIO_PERMISSIONS_PATH,
      STUDIO_GENERATING_COUNT_PATH,
      STUDIO_MAX_COUNT_PATH,
      STUDIO_LEDGER_PATH,
      STUDIO_HISTORY_PATH,
      STUDIO_TASK_DETAIL_PATH
    ];
    const isStudio = studioPaths.includes(path);
    const isStudioGet = [
      STUDIO_PERMISSIONS_PATH,
      STUDIO_MAX_COUNT_PATH,
      STUDIO_TASK_DETAIL_PATH
    ].includes(path);
    const isStudioBodylessPost = path === STUDIO_GENERATING_COUNT_PATH;
    const isOneFilters = path === ONE_FILTERS_PATH;
    const isOneSuggest = path === ONE_SUGGEST_PATH;
    const isOneSearch = path === ONE_SEARCH_PATH;
    const isOne = isOneFilters || isOneSuggest || isOneSearch;
    let requestURL = isFilters
      ? `${path}?sourceModule=${encodeURIComponent(String(body.sourceModule))}`
      : isStudio
        ? `${path}?aid=585599&app_name=creative_aio_client&device_platform=web`
        : isOneFilters
          ? `${path}?dataVDCRegion=1`
          : isOneSuggest
            ? `${path}?query=${encodeURIComponent(body.query)}`
            : path;
    if (path === STUDIO_TASK_DETAIL_PATH) {
      requestURL += `&draftId=${encodeURIComponent(body.draftId)}`;
    }
    const method = isFilters || isOneFilters || isOneSuggest || isStudioGet
      ? "GET"
      : "POST";
    const options = {
      method,
      credentials: "include",
      headers: {
        "accept": "application/json, text/plain, */*"
      }
    };
    if (
      method === "POST" &&
      !isStudioBodylessPost
    ) {
      options.headers["content-type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    if (isStudio) {
      options.headers = studioHeaders(
        method === "POST" && !isStudioBodylessPost
      );
    } else if (isOne) {
      options.headers = oneHeaders(isOneSearch);
    }
    const result = await fetch(requestURL, options);
    if (!result.ok) {
      throw new Error(`HTTP ${result.status}`);
    }
    let payload;
    try {
      payload = await result.json();
    } catch {
      throw new Error("invalid_response");
    }
    const upstream = upstreamError(payload);
    if (upstream) {
      throw new Error(upstream);
    }
    return payload;
  }

  async function invokeRequest(path, body) {
    if (path === TRENDING_VIDEO_OVERVIEW_PATH) {
      if (typeof window.fetch !== "function") {
        throw new Error("transport_modules_changed");
      }
      return await directTrendingVideoOverviewRequest();
    }
    if (path === TRENDING_VIDEO_LIST_PATH) {
      if (typeof window.fetch !== "function") {
        throw new Error("transport_modules_changed");
      }
      return await directTrendingVideoListRequest(body);
    }
    if ([ADS_KEYWORD_IDEAS_PATH, ADS_KEYWORD_SUMMARY_PATH].includes(path)) {
      if (typeof window.fetch !== "function") {
        throw new Error("transport_modules_changed");
      }
      return await directAdsKeywordRequest(path, body);
    }
    if (
      [
        TOP_ADS_V2_FILTERS_PATH,
        TOP_ADS_V2_LIST_PATH,
        TOP_ADS_SUGGEST_PATH,
        TOP_ADS_V2_DETAIL_PATH,
        TOP_ADS_V2_RECOMMEND_PATH,
        TOP_ADS_KEYFRAME_PATH,
        TOP_ADS_PERCENTILE_PATH,
        TOP_ADS_V2_ANALYSIS_PATH
      ].includes(path)
    ) {
      const module = topAdsRadarTransportModule();
      if (!module) {
        throw new Error("transport_modules_changed");
      }
      const result = await module.U2(path, body);
      if (!isRecord(result)) {
        throw new Error("invalid_response");
      }
      const upstream = upstreamError(result);
      if (upstream) {
        throw new Error(upstream);
      }
      const data = result.data;
      if (path === TOP_ADS_V2_FILTERS_PATH) {
        return normalizeTopAdsV2Filters(data);
      }
      if (path === TOP_ADS_V2_LIST_PATH) {
        return normalizeTopAdsV2List(data, body);
      }
      if (path === TOP_ADS_SUGGEST_PATH) {
        return normalizeTopAdsV2Suggestions(data);
      }
      if (path === TOP_ADS_V2_DETAIL_PATH) {
        return normalizeTopAdsV2Detail(data, body.materialId);
      }
      if (path === TOP_ADS_V2_RECOMMEND_PATH) {
        return normalizeTopAdsV2Recommend(data);
      }
      if (path === TOP_ADS_KEYFRAME_PATH) {
        return normalizeTopAdsKeyframe(data);
      }
      if (path === TOP_ADS_PERCENTILE_PATH) {
        return normalizeTopAdsPercentile(data);
      }
      return normalizeTopAdsV2Analysis(data);
    }
    if (path === TOP_ADS_FILTERS_PATH || path === TOP_ADS_SEARCH_PATH) {
      const module = topAdsTransportModule();
      if (module) {
        const result = path === TOP_ADS_FILTERS_PATH
          ? await module.hP(body)
          : await module.in(body);
        if (!isRecord(result)) {
          throw new Error("invalid_response");
        }
        const upstream = upstreamError(result);
        if (upstream) {
          throw new Error(upstream);
        }
        return path === TOP_ADS_FILTERS_PATH
          ? normalizeTopAdsFilters(result, body)
          : normalizeTopAdsSearch(result, body);
      }
    }
    const module = transportModule();
    if (module) {
      if (path === LIST_PATH) {
        const result = await module.U5({
          period: body.timeRange,
          countryCode: body.countryCode,
          industryIds: body.industryID,
          page: body.page,
          limit: body.limit
        });
        if (!isRecord(result) || !Array.isArray(result.data)) {
          throw new Error("invalid_response");
        }
        return normalizeListResult({
          items: result.data,
          pagination: isRecord(result.pagination) ? result.pagination : {}
        }, body);
      }
      if (path === DETAIL_PATH) {
        const result = await module.N6({
          hashtagId: body.hashtagID,
          period: body.timeRange,
          countryCode: body.countryCode
        });
        if (!isRecord(result)) {
          throw new Error("invalid_response");
        }
        return normalizeDetailResult(result, body.hashtagID);
      }
    }
    if (typeof window.fetch !== "function") {
      throw new Error("transport_modules_changed");
    }
    if (path === STUDIO_VIDEO_INFO_PATH) {
      return await directStudioVideoInfo(body.vid);
    }
    if (path === STUDIO_UPLOAD_IMAGE_PATH) {
      return await uploadStudioImage(body);
    }
    const result = await directRequest(path, body);
    if (path === LIST_PATH) {
      return normalizeListResult(result, body);
    }
    if (path === DETAIL_PATH) {
      return normalizeDetailResult(result, body.hashtagID);
    }
    if (path === TOP_ADS_FILTERS_PATH) {
      return normalizeTopAdsFilters(result, body);
    }
    if (path === TOP_ADS_SEARCH_PATH) {
      return normalizeTopAdsSearch(result, body);
    }
    if (path === STUDIO_CREDITS_PATH) {
      return normalizeStudioCredits(result);
    }
    if (
      path === STUDIO_GENERATE_PATH ||
      path === STUDIO_I2V_GENERATE_PATH
    ) {
      const task = normalizeStudioTask(result);
      if (task.status === "succeeded") {
        for (const draft of task.drafts) {
          if (draft.status === "succeeded") {
            draft.video = await directStudioVideoInfo(draft.vid);
          }
        }
      }
      return task;
    }
    if (path === STUDIO_TASK_PATH) {
      const task = normalizeStudioTask(result, body.taskId);
      if (task.status === "succeeded") {
        for (const draft of task.drafts) {
          if (draft.status === "succeeded") {
            draft.video = await directStudioVideoInfo(draft.vid);
          }
        }
      }
      return task;
    }
    if (path === STUDIO_PERMISSIONS_PATH) {
      return normalizeStudioPermissions(result);
    }
    if (path === STUDIO_GENERATING_COUNT_PATH) {
      return normalizeStudioGeneratingCount(result);
    }
    if (path === STUDIO_MAX_COUNT_PATH) {
      return normalizeStudioMaxCount(result);
    }
    if (path === STUDIO_LEDGER_PATH) {
      return normalizeStudioLedger(result);
    }
    if (path === STUDIO_HISTORY_PATH) {
      return normalizeStudioHistory(
        result,
        body.pageOffset,
        body.pageLimit
      );
    }
    if (path === STUDIO_TASK_DETAIL_PATH) {
      const draft = normalizeStudioTaskDetail(result, body.draftId);
      if (draft.status === "succeeded") {
        draft.video = await directStudioVideoInfo(draft.vid);
      }
      return draft;
    }
    if (path === ONE_FILTERS_PATH) {
      return normalizeOneFilters(result);
    }
    if (path === ONE_SUGGEST_PATH) {
      return normalizeOneSuggestions(result);
    }
    if (path === ONE_SEARCH_PATH) {
      return normalizeOneSearch(result, body);
    }
    throw new Error("invalid_request");
  }

  function renderedHashtagID() {
    for (const anchor of Array.from(
      document.querySelectorAll("a[href]")
    ).slice(0, 1000)) {
      let parsed;
      try {
        parsed = new URL(anchor.href);
      } catch {
        continue;
      }
      const match = parsed.origin === "https://ads.tiktok.com"
        ? parsed.pathname.match(
          /^\/creative\/creativeCenter\/trends\/hashtag\/([1-9][0-9]{0,31})$/
        )
        : null;
      if (match) {
        return match[1];
      }
    }
    return "";
  }

  function isTopAdsV2Page() {
    return (
      location.pathname === TOP_ADS_V2_PAGE_PATH ||
      /^\/business\/creativecenter\/topads\/[1-9][0-9]{0,31}\/pc\/en$/.test(
        location.pathname
      )
    );
  }

  function isTrendingVideoPage() {
    return [
      TRENDING_VIDEO_ROOT_PATH,
      TRENDING_VIDEO_PAGE_PATH,
      TRENDING_VIDEO_LEGACY_PAGE_PATH
    ].includes(location.pathname);
  }

  async function sessionAccessProbe(scope) {
    if (scope === "one") {
      try {
        await invokeRequest(ONE_FILTERS_PATH, {});
        return true;
      } catch (error) {
        if (errorCode(error) === "not_logged_in") {
          return false;
        }
        throw error;
      }
    }
    if (scope === "studio") {
      try {
        await invokeRequest(STUDIO_CREDITS_PATH, {});
        return true;
      } catch (error) {
        const code = errorCode(error);
        if (code === "not_logged_in") {
          return false;
        }
        throw error;
      }
    }
    if (scope === "top_ads") {
      try {
        if (isTopAdsV2Page()) {
          await invokeRequest(TOP_ADS_V2_FILTERS_PATH, {});
        } else {
          const sourceModule = location.pathname === TOP_ADS_INSIGHT_PATH ? 1 : 2;
          await invokeRequest(TOP_ADS_FILTERS_PATH, { sourceModule });
        }
        return true;
      } catch (error) {
        const code = errorCode(error);
        if (code === "not_logged_in") {
          return false;
        }
        throw error;
      }
    }
    if (isTrendingVideoPage()) {
      try {
        await invokeRequest(TRENDING_VIDEO_OVERVIEW_PATH, {});
        return true;
      } catch (error) {
        if (errorCode(error) === "not_logged_in") {
          return false;
        }
        throw error;
      }
    }
    let hashtagID = renderedHashtagID();
    if (!hashtagID) {
      const list = await invokeRequest(LIST_PATH, {
        timeRange: 7,
        countryCode: "US",
        page: 1,
        limit: 1
      });
      hashtagID = String(
        list.items[0] && list.items[0].hashtagID || ""
      );
    }
    if (!HASHTAG_ID.test(hashtagID)) {
      throw new Error("invalid_response");
    }
    try {
      await invokeRequest(DETAIL_PATH, {
        hashtagID,
        timeRange: 7,
        countryCode: "US"
      });
      return true;
    } catch (error) {
      if (errorCode(error) === "not_logged_in") {
        return false;
      }
      throw error;
    }
  }

  function sessionResult({
    loggedIn,
    requestReady,
    verification,
    profileRequired = false,
    probeRequired = false
  }) {
    return response({
      ok: true,
      payload: {
        fingerprint: fingerprint(),
        logged_in: loggedIn,
        request_ready: requestReady,
        verification_required: verification,
        profile_required: profileRequired,
        probe_required: probeRequired
      }
    });
  }

  function validRequestPage(path, body) {
    if ([ADS_KEYWORD_IDEAS_PATH, ADS_KEYWORD_SUMMARY_PATH].includes(path)) {
      return adsManagerAccountPage();
    }
    if (
      [
        TOP_ADS_V2_FILTERS_PATH,
        TOP_ADS_V2_LIST_PATH,
        TOP_ADS_SUGGEST_PATH,
        TOP_ADS_V2_DETAIL_PATH,
        TOP_ADS_V2_RECOMMEND_PATH,
        TOP_ADS_KEYFRAME_PATH,
        TOP_ADS_PERCENTILE_PATH,
        TOP_ADS_V2_ANALYSIS_PATH
      ].includes(path)
    ) {
      return isTopAdsV2Page();
    }
    if ([ONE_FILTERS_PATH, ONE_SUGGEST_PATH, ONE_SEARCH_PATH].includes(path)) {
      return location.pathname === ONE_PAGE_PATH;
    }
    if (
      [
        STUDIO_CREDITS_PATH,
        STUDIO_GENERATE_PATH,
        STUDIO_UPLOAD_IMAGE_PATH,
        STUDIO_I2V_GENERATE_PATH,
        STUDIO_TASK_PATH,
        STUDIO_PERMISSIONS_PATH,
        STUDIO_GENERATING_COUNT_PATH,
        STUDIO_MAX_COUNT_PATH,
        STUDIO_LEDGER_PATH,
        STUDIO_HISTORY_PATH,
        STUDIO_TASK_DETAIL_PATH,
        STUDIO_VIDEO_INFO_PATH
      ].includes(path)
    ) {
      if (location.pathname === STUDIO_PAGE_PATH) {
        return true;
      }
      return (
        location.pathname === STUDIO_T2V_PAGE_PATH &&
        [...new URLSearchParams(location.search || "").entries()].length === 1 &&
        new URLSearchParams(location.search || "").get("subApp") ===
          STUDIO_T2V_SUB_APP
      );
    }
    if (path === TOP_ADS_FILTERS_PATH) {
      return body.sourceModule === 1
        ? location.pathname === TOP_ADS_INSIGHT_PATH
        : location.pathname === TOP_ADS_LIBRARY_PATH;
    }
    if (path === TOP_ADS_SEARCH_PATH) {
      return location.pathname === TOP_ADS_LIBRARY_PATH;
    }
    if (
      [
        TRENDING_VIDEO_OVERVIEW_PATH,
        TRENDING_VIDEO_LIST_PATH
      ].includes(path)
    ) {
      return isTrendingVideoPage();
    }
    return true;
  }

  if (!isRecord(input) || typeof input.kind !== "string") {
    return response({ ok: false, error: "invalid_request" });
  }
  if (input.kind === "session") {
    const verification = verificationRequired();
    const profileRequired =
      ["top_ads", "studio"].includes(input.scope) &&
      profileCompletionRequired();
    if (verification || profileRequired) {
      return sessionResult({
        loggedIn: profileRequired && !verification,
        requestReady: false,
        verification,
        profileRequired: profileRequired && !verification
      });
    }
    if (input.scope === "ads_manager") {
      const requestReady = Boolean(
        adsManagerAccountPage() &&
        cookieValue("csrftoken") &&
        typeof window.fetch === "function"
      );
      return sessionResult({
        loggedIn: requestReady,
        requestReady,
        verification: false,
        profileRequired: false
      });
    }
    const account = routerAccountState();
    const anonymous = anonymousLoginCue();
    const loggedIn =
      account.loaded &&
      account.loggedIn &&
      !anonymous;
    const transportReady = Boolean(
      (
        input.scope === "top_ads"
          ? (
              isTopAdsV2Page()
                ? topAdsRadarTransportModule()
                : topAdsTransportModule()
            )
          : ["studio", "one"].includes(input.scope)
            ? null
            : transportModule()
      ) || typeof window.fetch === "function"
    );
    return sessionResult({
      loggedIn,
      requestReady: loggedIn && transportReady,
      verification,
      profileRequired: false,
      probeRequired:
        input.scope === "top_ads" &&
        isTopAdsV2Page()
          ? !verification && transportReady
          : !verification &&
            !anonymous &&
            !account.loaded &&
            transportReady
    });
  }
  if (input.kind === "session_probe") {
    const verification = verificationRequired();
    const profileRequired =
      ["top_ads", "studio"].includes(input.scope) &&
      profileCompletionRequired();
    if (verification || profileRequired) {
      return sessionResult({
        loggedIn: profileRequired && !verification,
        requestReady: false,
        verification,
        profileRequired: profileRequired && !verification
      });
    }
    if (input.scope === "ads_manager") {
      const requestReady = Boolean(
        adsManagerAccountPage() &&
        cookieValue("csrftoken") &&
        typeof window.fetch === "function"
      );
      return sessionResult({
        loggedIn: requestReady,
        requestReady,
        verification: false,
        profileRequired: false
      });
    }
    const publicTopAds =
      input.scope === "top_ads" &&
      isTopAdsV2Page();
    if (anonymousLoginCue() && !publicTopAds) {
      return sessionResult({
        loggedIn: false,
        requestReady: false,
        verification: false,
        profileRequired: false
      });
    }
    try {
      const loggedIn = await sessionAccessProbe(input.scope);
      return sessionResult({
        loggedIn: publicTopAds ? false : loggedIn,
        requestReady: loggedIn,
        verification: false,
        profileRequired: false
      });
    } catch (error) {
      const code = errorCode(error);
      if (code === "verification_required") {
        return sessionResult({
          loggedIn: false,
          requestReady: false,
          verification: true,
          profileRequired: false
        });
      }
      if (code === "profile_required") {
        return sessionResult({
          loggedIn: true,
          requestReady: false,
          verification: false,
          profileRequired: true
        });
      }
      return response({ ok: false, error: code });
    }
  }
  if (
    input.kind !== "request" ||
    ![
      LIST_PATH,
      DETAIL_PATH,
      TRENDING_VIDEO_OVERVIEW_PATH,
      TRENDING_VIDEO_LIST_PATH,
      TOP_ADS_FILTERS_PATH,
      TOP_ADS_SEARCH_PATH,
      TOP_ADS_V2_FILTERS_PATH,
      TOP_ADS_V2_LIST_PATH,
      TOP_ADS_SUGGEST_PATH,
      TOP_ADS_V2_DETAIL_PATH,
      TOP_ADS_V2_RECOMMEND_PATH,
      TOP_ADS_KEYFRAME_PATH,
      TOP_ADS_PERCENTILE_PATH,
      TOP_ADS_V2_ANALYSIS_PATH,
      STUDIO_CREDITS_PATH,
      STUDIO_GENERATE_PATH,
      STUDIO_UPLOAD_IMAGE_PATH,
      STUDIO_I2V_GENERATE_PATH,
      STUDIO_TASK_PATH,
      STUDIO_PERMISSIONS_PATH,
      STUDIO_GENERATING_COUNT_PATH,
      STUDIO_MAX_COUNT_PATH,
      STUDIO_LEDGER_PATH,
      STUDIO_HISTORY_PATH,
      STUDIO_TASK_DETAIL_PATH,
      STUDIO_VIDEO_INFO_PATH,
      ONE_FILTERS_PATH,
      ONE_SUGGEST_PATH,
      ONE_SEARCH_PATH,
      ADS_KEYWORD_IDEAS_PATH,
      ADS_KEYWORD_SUMMARY_PATH
    ].includes(input.path)
  ) {
    return response({ ok: false, error: "invalid_request" });
  }
  const body = parseEntries(input.path, input.entries);
  if (!body) {
    return response({ ok: false, error: "invalid_request" });
  }
  if (verificationRequired()) {
    return response({ ok: false, error: "verification_required" });
  }
  if (
    ![ONE_FILTERS_PATH, ONE_SUGGEST_PATH, ONE_SEARCH_PATH].includes(input.path) &&
    profileCompletionRequired()
  ) {
    return response({ ok: false, error: "profile_required" });
  }
  if (!validRequestPage(input.path, body)) {
    return response({ ok: false, error: "invalid_request" });
  }
  const account = routerAccountState();
  const publicTopAdsRequest = [
    TOP_ADS_V2_FILTERS_PATH,
    TOP_ADS_V2_LIST_PATH,
    TOP_ADS_SUGGEST_PATH,
    TOP_ADS_V2_DETAIL_PATH,
    TOP_ADS_V2_RECOMMEND_PATH,
    TOP_ADS_KEYFRAME_PATH,
    TOP_ADS_PERCENTILE_PATH,
    TOP_ADS_V2_ANALYSIS_PATH
  ].includes(input.path);
  if (
    (!publicTopAdsRequest && anonymousLoginCue()) ||
    (!publicTopAdsRequest && account.loaded && !account.loggedIn) ||
    (!account.loaded && input.session_verified !== true)
  ) {
    return response({ ok: false, error: "not_logged_in" });
  }
  try {
    const payload = sanitize(await invokeRequest(input.path, body));
    return response(
      isRecord(payload)
        ? { ok: true, payload }
        : { ok: false, error: "invalid_response" }
    );
  } catch (error) {
    const code = String(error && error.message) === "transport_modules_changed"
      ? "transport_modules_changed"
      : errorCode(error);
    return response({ ok: false, error: code });
  }
}
