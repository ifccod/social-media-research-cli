const COUNTRY_CODE = /^[A-Z]{2}$/;
const DECIMAL_ID = /^[1-9][0-9]{0,31}$/;
const POSITIVE_INTEGER = /^[1-9][0-9]*$/;
const INTEGER = /^(?:0|[1-9][0-9]*)$/;
const PARAMETER_NAME = /^[A-Za-z][A-Za-z0-9_]{0,79}$/;
const ADS_KEYWORD_COUNTRIES = new Map([
  ["AE", "290557"],
  ["AU", "2077456"],
  ["BR", "3469034"],
  ["CA", "6251999"],
  ["DE", "2921044"],
  ["ES", "2510769"],
  ["FR", "3017382"],
  ["GB", "2635167"],
  ["ID", "1643084"],
  ["IT", "3175395"],
  ["MX", "3996063"],
  ["MY", "1733045"],
  ["PH", "1694008"],
  ["SA", "102358"],
  ["TH", "1605651"],
  ["US", "6252001"],
  ["VN", "1562822"]
]);

export const TIKTOK_CREATIVE_ORIGIN = "https://ads.tiktok.com";
export const TIKTOK_CREATIVE_HASHTAG_PATH =
  "/creative/creativeCenter/trends/hashtag";
export const TIKTOK_CREATIVE_HASHTAG_URL =
  `${TIKTOK_CREATIVE_ORIGIN}${TIKTOK_CREATIVE_HASHTAG_PATH}` +
  "?region=US&period=7";
// 旧的 popular/video 页面在 2026-07-31 已跳转到新版 Trends 路由。
// 根页和 video 子页都可承载同一份 Top Contents 请求。
export const TIKTOK_CREATIVE_TRENDS_PATH = "/creative/creativeCenter/trends";
export const TIKTOK_CREATIVE_TRENDING_VIDEO_PATH =
  `${TIKTOK_CREATIVE_TRENDS_PATH}/video`;
export const TIKTOK_CREATIVE_TRENDING_VIDEO_LEGACY_PATH =
  "/business/creativecenter/inspiration/popular/video/pc/en";
export const TIKTOK_CREATIVE_TRENDING_VIDEO_URL =
  `${TIKTOK_CREATIVE_ORIGIN}${TIKTOK_CREATIVE_TRENDING_VIDEO_PATH}`;
export const TIKTOK_CREATIVE_LOGIN_URL =
  `${TIKTOK_CREATIVE_ORIGIN}/creative/login?redirect=` +
  encodeURIComponent(TIKTOK_CREATIVE_HASHTAG_URL);
export const TIKTOK_CREATIVE_TOP_ADS_PATH =
  "/creative/inspiration/top-ads/library";
export const TIKTOK_CREATIVE_TOP_ADS_URL =
  `${TIKTOK_CREATIVE_ORIGIN}${TIKTOK_CREATIVE_TOP_ADS_PATH}`;
export const TIKTOK_CREATIVE_TOP_ADS_INSIGHT_PATH =
  "/creative/inspiration/top-ads/insight";
export const TIKTOK_CREATIVE_TOP_ADS_INSIGHT_URL =
  `${TIKTOK_CREATIVE_ORIGIN}${TIKTOK_CREATIVE_TOP_ADS_INSIGHT_PATH}`;
export const TIKTOK_CREATIVE_TOP_ADS_V2_PATH =
  "/business/creativecenter/inspiration/topads/pc/en";
export const TIKTOK_CREATIVE_TOP_ADS_V2_URL =
  `${TIKTOK_CREATIVE_ORIGIN}${TIKTOK_CREATIVE_TOP_ADS_V2_PATH}`;
export const TIKTOK_CREATIVE_TOP_ADS_LOGIN_URL =
  `${TIKTOK_CREATIVE_ORIGIN}/creative/login?redirect=` +
  encodeURIComponent(TIKTOK_CREATIVE_TOP_ADS_URL);
export const TIKTOK_CREATIVE_STUDIO_PATH =
  "/creative/creativestudio/create";
export const TIKTOK_CREATIVE_STUDIO_T2V_PATH =
  "/creative/creativestudio/image-to-video";
export const TIKTOK_CREATIVE_STUDIO_URL =
  `${TIKTOK_CREATIVE_ORIGIN}${TIKTOK_CREATIVE_STUDIO_PATH}` +
  "?from_creative=signup&region=row";
export const TIKTOK_CREATIVE_STUDIO_LOGIN_URL =
  `${TIKTOK_CREATIVE_ORIGIN}/creative/login?redirect=` +
  encodeURIComponent(TIKTOK_CREATIVE_STUDIO_URL);
export const TIKTOK_ONE_CREATOR_PATH =
  "/creative/forpartners/creator/explore";
export const TIKTOK_ONE_CREATOR_URL =
  `${TIKTOK_CREATIVE_ORIGIN}${TIKTOK_ONE_CREATOR_PATH}?region=row`;
export const TIKTOK_ONE_CREATOR_LOGIN_URL =
  `${TIKTOK_CREATIVE_ORIGIN}/creative/login?redirect=` +
  encodeURIComponent(TIKTOK_ONE_CREATOR_URL);
export const TIKTOK_ADS_KEYWORD_PLANNER_PATH =
  "/i18n/search_ads_center/keyword-planner/creation";
export const TIKTOK_ADS_KEYWORD_PLANNER_URL =
  `${TIKTOK_CREATIVE_ORIGIN}${TIKTOK_ADS_KEYWORD_PLANNER_PATH}`;
export const TIKTOK_ADS_KEYWORD_PLANNER_LOGIN_URL =
  TIKTOK_ADS_KEYWORD_PLANNER_URL;
export const TIKTOK_ADS_MANAGER_HOME_PATH = "/i18n/home";
export const TIKTOK_CREATIVE_LOGIN_PATH = "/creative/login";
export const TIKTOK_CREATIVE_SIGNUP_PATH = "/creative/signup";
export const TIKTOK_CREATIVE_TAB_PATTERNS = [
  `${TIKTOK_CREATIVE_ORIGIN}/*`
];
export const TIKTOK_CREATIVE_HASHTAG_LIST_PATH =
  "/CreativeOne/KnowledgeAPI/GetHashtagList";
export const TIKTOK_CREATIVE_HASHTAG_DETAIL_PATH =
  "/CreativeOne/KnowledgeAPI/GetHashtagDetail";
export const TIKTOK_CREATIVE_TRENDING_VIDEO_OVERVIEW_PATH =
  "/CreativeOne/Report/GetTopContentsOverview";
export const TIKTOK_CREATIVE_TRENDING_VIDEO_LIST_PATH =
  "/CreativeOne/Report/CreativeCenterGetTopContentsList";
export const TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH =
  "/CreativeOne/TopAds/Filters";
export const TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH =
  "/CreativeOne/TopAds/SearchMaterial";
export const TIKTOK_CREATIVE_TOP_ADS_V2_FILTERS_PATH =
  "/creative_radar_api/v1/top_ads/v2/filters";
export const TIKTOK_CREATIVE_TOP_ADS_V2_LIST_PATH =
  "/creative_radar_api/v1/top_ads/v2/list";
export const TIKTOK_CREATIVE_TOP_ADS_SUGGEST_PATH =
  "/creative_radar_api/v1/top_ads/query_suggestion";
export const TIKTOK_CREATIVE_TOP_ADS_V2_DETAIL_PATH =
  "/creative_radar_api/v1/top_ads/v2/detail";
export const TIKTOK_CREATIVE_TOP_ADS_V2_RECOMMEND_PATH =
  "/creative_radar_api/v1/top_ads/v2/recommend";
export const TIKTOK_CREATIVE_TOP_ADS_KEYFRAME_PATH =
  "/creative_radar_api/v1/top_ads/keyframe";
export const TIKTOK_CREATIVE_TOP_ADS_PERCENTILE_PATH =
  "/creative_radar_api/v1/top_ads/percentile";
export const TIKTOK_CREATIVE_TOP_ADS_V2_ANALYSIS_PATH =
  "/creative_radar_api/v1/top_ads/v2/detail_analysis";
export const TIKTOK_CREATIVE_STUDIO_CREDITS_PATH =
  "/CreativeOne/SymphonyPlatform/QueryCreditAccount";
export const TIKTOK_CREATIVE_STUDIO_GENERATE_PATH =
  "/creative_bff_i18n/api/cue/t2v/create_generate_task";
export const TIKTOK_CREATIVE_STUDIO_UPLOAD_IMAGE_PATH =
  "/creative_bff_i18n/api/cue/upload/local-image";
export const TIKTOK_CREATIVE_STUDIO_I2V_GENERATE_PATH =
  "/creative_bff_i18n/api/cue/i2v/create_generate_task";
export const TIKTOK_CREATIVE_STUDIO_TASK_PATH =
  "/creative_bff_i18n/api/cue/generate-task/check";
export const TIKTOK_CREATIVE_STUDIO_PERMISSIONS_PATH =
  "/creative_bff_i18n/api/cue/get_miniapp_permission_with_allowlist";
export const TIKTOK_CREATIVE_STUDIO_GENERATING_COUNT_PATH =
  "/creative_bff_i18n/api/cue/generating-task-count";
export const TIKTOK_CREATIVE_STUDIO_MAX_COUNT_PATH =
  "/creative_bff_i18n/api/cue/get_generate_max_count";
export const TIKTOK_CREATIVE_STUDIO_LEDGER_PATH =
  "/CreativeOne/SymphonyPlatform/QueryCreditLedgerEntries";
export const TIKTOK_CREATIVE_STUDIO_HISTORY_PATH =
  "/creative_bff_i18n/api/cue/history/tasks";
export const TIKTOK_CREATIVE_STUDIO_TASK_DETAIL_PATH =
  "/creative_bff_i18n/api/cue/history/task/detail";
export const TIKTOK_CREATIVE_STUDIO_VIDEO_INFO_PATH =
  "/creative_bff_i18n/api/cue/video_info";
export const TIKTOK_ONE_CREATOR_FILTERS_PATH =
  "/CreativeOne/MatchMaking/QueryPartnerSearchFilterOption";
export const TIKTOK_ONE_CREATOR_SUGGEST_PATH =
  "/CreativeOne/MatchMaking/QueryPartnerSearchSuggestWords";
export const TIKTOK_ONE_CREATOR_SEARCH_PATH =
  "/CreativeOne/MatchMaking/QueryPartnerCreatorSquare";
export const TIKTOK_ADS_KEYWORD_IDEAS_PATH =
  "/api/v4/i18n/search_ads/search_keyword/mget_keyword_ideas/";
export const TIKTOK_ADS_KEYWORD_SUMMARY_PATH =
  "/api/v4/i18n/search_ads/search_keyword/keyword_plan_summary/";
export const TIKTOK_CREATIVE_HASHTAG_PATHS = new Set([
  TIKTOK_CREATIVE_HASHTAG_LIST_PATH,
  TIKTOK_CREATIVE_HASHTAG_DETAIL_PATH
]);
export const TIKTOK_CREATIVE_TRENDING_VIDEO_PATHS = new Set([
  TIKTOK_CREATIVE_TRENDING_VIDEO_OVERVIEW_PATH,
  TIKTOK_CREATIVE_TRENDING_VIDEO_LIST_PATH
]);
export const TIKTOK_CREATIVE_TOP_ADS_PATHS = new Set([
  TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH,
  TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH,
  TIKTOK_CREATIVE_TOP_ADS_V2_FILTERS_PATH,
  TIKTOK_CREATIVE_TOP_ADS_V2_LIST_PATH,
  TIKTOK_CREATIVE_TOP_ADS_SUGGEST_PATH,
  TIKTOK_CREATIVE_TOP_ADS_V2_DETAIL_PATH,
  TIKTOK_CREATIVE_TOP_ADS_V2_RECOMMEND_PATH,
  TIKTOK_CREATIVE_TOP_ADS_KEYFRAME_PATH,
  TIKTOK_CREATIVE_TOP_ADS_PERCENTILE_PATH,
  TIKTOK_CREATIVE_TOP_ADS_V2_ANALYSIS_PATH
]);
export const TIKTOK_CREATIVE_STUDIO_PATHS = new Set([
  TIKTOK_CREATIVE_STUDIO_CREDITS_PATH,
  TIKTOK_CREATIVE_STUDIO_GENERATE_PATH,
  TIKTOK_CREATIVE_STUDIO_UPLOAD_IMAGE_PATH,
  TIKTOK_CREATIVE_STUDIO_I2V_GENERATE_PATH,
  TIKTOK_CREATIVE_STUDIO_TASK_PATH,
  TIKTOK_CREATIVE_STUDIO_PERMISSIONS_PATH,
  TIKTOK_CREATIVE_STUDIO_GENERATING_COUNT_PATH,
  TIKTOK_CREATIVE_STUDIO_MAX_COUNT_PATH,
  TIKTOK_CREATIVE_STUDIO_LEDGER_PATH,
  TIKTOK_CREATIVE_STUDIO_HISTORY_PATH,
  TIKTOK_CREATIVE_STUDIO_TASK_DETAIL_PATH,
  TIKTOK_CREATIVE_STUDIO_VIDEO_INFO_PATH
]);
export const TIKTOK_ONE_CREATOR_PATHS = new Set([
  TIKTOK_ONE_CREATOR_FILTERS_PATH,
  TIKTOK_ONE_CREATOR_SUGGEST_PATH,
  TIKTOK_ONE_CREATOR_SEARCH_PATH
]);
export const TIKTOK_ADS_KEYWORD_PATHS = new Set([
  TIKTOK_ADS_KEYWORD_IDEAS_PATH,
  TIKTOK_ADS_KEYWORD_SUMMARY_PATH
]);
export const TIKTOK_CREATIVE_ERROR_CODES = new Set([
  "invalid_request",
  "runtime_unavailable",
  "transport_modules_changed",
  "request_failed",
  "forbidden",
  "timeout",
  "tab_unavailable",
  "invalid_response",
  "response_too_large",
  "verification_required",
  "not_logged_in",
  "profile_required",
  "rate_limited",
  "advertiser_account_required",
  "csrf_or_signature_expired",
  "keyword_not_allowed",
  "keyword_invalid"
]);

const CONTRACTS = Object.freeze({
  [TIKTOK_CREATIVE_HASHTAG_LIST_PATH]: {
    required: new Set(["timeRange", "countryCode", "page", "limit"]),
    optional: new Set(["industryID"])
  },
  [TIKTOK_CREATIVE_HASHTAG_DETAIL_PATH]: {
    required: new Set(["hashtagID", "timeRange", "countryCode"]),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_TRENDING_VIDEO_OVERVIEW_PATH]: {
    required: new Set(),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_TRENDING_VIDEO_LIST_PATH]: {
    required: new Set([
      "periodDimension",
      "periodEndTimestamp",
      "orderByMetric",
      "countryCode",
      "contentLabelIDs",
      "page",
      "limit"
    ]),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH]: {
    required: new Set(["sourceModule"]),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH]: {
    required: new Set([
      "timeRange",
      "orderField",
      "page",
      "limit",
      "sourceModule"
    ]),
    optional: new Set([
      "industryLabelList",
      "countryCodeList",
      "searchWord",
      "objectiveList",
      "adFormat",
      "likeCntFilter"
    ])
  },
  [TIKTOK_CREATIVE_TOP_ADS_V2_FILTERS_PATH]: {
    required: new Set(),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_TOP_ADS_V2_LIST_PATH]: {
    required: new Set(["period", "orderBy", "countryCode", "page", "limit"]),
    optional: new Set([
      "industry",
      "keyword",
      "objective",
      "duration",
      "like",
      "patternLabel",
      "adFormat",
      "adLanguage"
    ])
  },
  [TIKTOK_CREATIVE_TOP_ADS_SUGGEST_PATH]: {
    required: new Set(["query", "count", "scenario", "countryCode"]),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_TOP_ADS_V2_DETAIL_PATH]: {
    required: new Set(["materialId"]),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_TOP_ADS_V2_RECOMMEND_PATH]: {
    required: new Set(["materialId", "industry", "countryCode"]),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_TOP_ADS_KEYFRAME_PATH]: {
    required: new Set(["materialId", "metric"]),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_TOP_ADS_PERCENTILE_PATH]: {
    required: new Set(["materialId", "metric", "periodType"]),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_TOP_ADS_V2_ANALYSIS_PATH]: {
    required: new Set(["materialId"]),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_STUDIO_CREDITS_PATH]: {
    required: new Set(),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_STUDIO_GENERATE_PATH]: {
    required: new Set(["prompt", "duration"]),
    optional: new Set(["enhancePrompt"])
  },
  [TIKTOK_CREATIVE_STUDIO_UPLOAD_IMAGE_PATH]: {
    required: new Set(["name", "mimeType", "dataBase64"]),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_STUDIO_I2V_GENERATE_PATH]: {
    required: new Set(["prompt", "duration", "firstFrameUrl"]),
    optional: new Set(["lastFrameUrl"])
  },
  [TIKTOK_CREATIVE_STUDIO_TASK_PATH]: {
    required: new Set(["taskId"]),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_STUDIO_PERMISSIONS_PATH]: {
    required: new Set(),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_STUDIO_GENERATING_COUNT_PATH]: {
    required: new Set(),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_STUDIO_MAX_COUNT_PATH]: {
    required: new Set(),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_STUDIO_LEDGER_PATH]: {
    required: new Set(["pageSize"]),
    optional: new Set(["cursor"])
  },
  [TIKTOK_CREATIVE_STUDIO_HISTORY_PATH]: {
    required: new Set(["offset", "limit"]),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_STUDIO_TASK_DETAIL_PATH]: {
    required: new Set(["draftId"]),
    optional: new Set()
  },
  [TIKTOK_CREATIVE_STUDIO_VIDEO_INFO_PATH]: {
    required: new Set(["vid"]),
    optional: new Set()
  },
  [TIKTOK_ONE_CREATOR_FILTERS_PATH]: {
    required: new Set(),
    optional: new Set()
  },
  [TIKTOK_ONE_CREATOR_SUGGEST_PATH]: {
    required: new Set(["query"]),
    optional: new Set()
  },
  [TIKTOK_ONE_CREATOR_SEARCH_PATH]: {
    required: new Set([
      "page",
      "limit",
      "query",
      "sortField",
      "sortType"
    ]),
    optional: new Set([
      "countryCodeList",
      "languageList",
      "minFansCnt",
      "maxFansCnt",
      "minMedianViews",
      "maxMedianViews",
      "minEngagementRate",
      "maxEngagementRate"
    ])
  },
  [TIKTOK_ADS_KEYWORD_IDEAS_PATH]: {
    required: new Set([
      "keywords",
      "startTime",
      "endTime",
      "brandOption",
      "sortField",
      "sortOrder",
      "countryId",
      "languageCode",
      "languageName"
    ]),
    optional: new Set()
  },
  [TIKTOK_ADS_KEYWORD_SUMMARY_PATH]: {
    required: new Set(["words", "countryName"]),
    optional: new Set()
  }
});

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasControlCharacters(value) {
  return /[\r\n\0]/.test(value);
}

function validStudioImageUrl(value) {
  if (
    typeof value !== "string" ||
    value.length < 1 ||
    value.length > 2048 ||
    hasControlCharacters(value)
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

function parsePositiveInteger(value, maximum) {
  if (typeof value !== "string" || !POSITIVE_INTEGER.test(value)) {
    return null;
  }
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed <= maximum ? parsed : null;
}

function entriesMap(path, value) {
  const contract = CONTRACTS[path];
  if (!contract || !Array.isArray(value)) {
    return null;
  }
  const minimum = contract.required.size;
  const maximum = minimum + contract.optional.size;
  if (value.length < minimum || value.length > maximum) {
    return null;
  }
  const values = new Map();
  for (const entry of value) {
    const largeStudioImage = (
      path === TIKTOK_CREATIVE_STUDIO_UPLOAD_IMAGE_PATH &&
      Array.isArray(entry) &&
      entry.length === 2 &&
      entry[0] === "dataBase64" &&
      typeof entry[1] === "string" &&
      entry[1].length <= 7 * 1024 * 1024 &&
      /^[A-Za-z0-9+/]+={0,2}$/.test(entry[1])
    );
    if (
      !Array.isArray(entry) ||
      entry.length !== 2 ||
      typeof entry[0] !== "string" ||
      typeof entry[1] !== "string" ||
      !PARAMETER_NAME.test(entry[0]) ||
      (!contract.required.has(entry[0]) && !contract.optional.has(entry[0])) ||
      values.has(entry[0]) ||
      (entry[1].length > 4096 && !largeStudioImage) ||
      hasControlCharacters(entry[1])
    ) {
      return null;
    }
    values.set(entry[0], entry[1]);
  }
  for (const name of contract.required) {
    if (!values.has(name)) {
      return null;
    }
  }
  return values;
}

function validCommonValues(values) {
  return (
    COUNTRY_CODE.test(values.get("countryCode") || "") &&
    ["7", "30", "90"].includes(values.get("timeRange"))
  );
}

function validDecimalCSV(value, maximumItems = 20) {
  if (typeof value !== "string" || value === "") {
    return false;
  }
  const items = value.split(",");
  if (items.length < 1 || items.length > maximumItems) {
    return false;
  }
  const seen = new Set();
  for (const item of items) {
    if (
      !DECIMAL_ID.test(item) ||
      !Number.isSafeInteger(Number(item)) ||
      seen.has(item)
    ) {
      return false;
    }
    seen.add(item);
  }
  return true;
}

function validCountryCSV(value, maximumItems = 249) {
  if (typeof value !== "string" || value === "") {
    return false;
  }
  const items = value.split(",");
  if (items.length < 1 || items.length > maximumItems) {
    return false;
  }
  const seen = new Set();
  return items.every((item) => {
    if (!COUNTRY_CODE.test(item) || seen.has(item)) {
      return false;
    }
    seen.add(item);
    return true;
  });
}

function validEnumCSV(value, allowed, maximumItems = 20) {
  if (typeof value !== "string" || value === "") {
    return false;
  }
  const items = value.split(",");
  if (items.length < 1 || items.length > maximumItems) {
    return false;
  }
  const seen = new Set();
  return items.every((item) => {
    if (!allowed.has(item) || seen.has(item)) {
      return false;
    }
    seen.add(item);
    return true;
  });
}

function validLanguageCSV(value, maximumItems = 20) {
  if (typeof value !== "string" || value === "") {
    return false;
  }
  const items = value.split(",");
  const seen = new Set();
  return (
    items.length <= maximumItems &&
    items.every((item) => {
      if (!/^[A-Za-z]{2,8}(?:-[A-Za-z]{2,8})?$/.test(item) || seen.has(item)) {
        return false;
      }
      seen.add(item);
      return true;
    })
  );
}

function parsedJSON(value) {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function validAdsKeywords(value, maximum) {
  const keywords = parsedJSON(value);
  if (!Array.isArray(keywords) || keywords.length < 1 || keywords.length > maximum) {
    return null;
  }
  const seen = new Set();
  return keywords.every((keyword) => {
    if (
      typeof keyword !== "string" ||
      keyword.trim() === "" ||
      keyword.length > 80 ||
      hasControlCharacters(keyword) ||
      seen.has(keyword)
    ) {
      return false;
    }
    seen.add(keyword);
    return true;
  }) ? keywords : null;
}

export function validTikTokCreativeEntries(path, value) {
  const values = entriesMap(path, value);
  if (!values) {
    return false;
  }
  if (path === TIKTOK_ADS_KEYWORD_IDEAS_PATH) {
    const keywords = validAdsKeywords(values.get("keywords"), 10);
    const startTime = values.get("startTime");
    const endTime = values.get("endTime");
    if (
      !keywords ||
      !POSITIVE_INTEGER.test(startTime || "") ||
      !POSITIVE_INTEGER.test(endTime || "") ||
      Number(startTime) >= Number(endTime) ||
      Number(endTime) - Number(startTime) > 370 * 24 * 60 * 60 ||
      Number(endTime) > 4_102_444_800 ||
      !["0", "1", "2"].includes(values.get("brandOption")) ||
      !["0", "1", "2", "3", "4", "5", "6"].includes(values.get("sortField")) ||
      !["0", "1", "2"].includes(values.get("sortOrder")) ||
      values.get("languageCode") !== "en" ||
      values.get("languageName") !== "English"
    ) {
      return false;
    }
    return [...ADS_KEYWORD_COUNTRIES.values()].includes(values.get("countryId"));
  }
  if (path === TIKTOK_ADS_KEYWORD_SUMMARY_PATH) {
    const words = parsedJSON(values.get("words"));
    const countryName = values.get("countryName");
    if (
      !Array.isArray(words) ||
      words.length < 1 ||
      words.length > 20 ||
      !ADS_KEYWORD_COUNTRIES.has(countryName)
    ) {
      return false;
    }
    const seen = new Set();
    return words.every((word) => {
      if (
        !isRecord(word) ||
        Object.keys(word).length !== 3 ||
        typeof word.keyword !== "string" ||
        word.keyword.trim() === "" ||
        word.keyword.length > 80 ||
        hasControlCharacters(word.keyword) ||
        seen.has(word.keyword) ||
        ![1, 2, 3].includes(word.matchType) ||
        !Number.isSafeInteger(word.sourceType) ||
        word.sourceType < 1 ||
        word.sourceType > 20
      ) {
        return false;
      }
      seen.add(word.keyword);
      return true;
    });
  }
  if (path === TIKTOK_CREATIVE_TOP_ADS_V2_FILTERS_PATH) {
    return true;
  }
  if (path === TIKTOK_CREATIVE_TOP_ADS_V2_LIST_PATH) {
    if (
      !["7", "30", "180"].includes(values.get("period")) ||
      !["for_you", "impression", "ctr", "like"].includes(
        values.get("orderBy")
      ) ||
      !validCountryCSV(values.get("countryCode"), 50) ||
      parsePositiveInteger(values.get("page"), 1000) === null ||
      parsePositiveInteger(values.get("limit"), 20) === null
    ) {
      return false;
    }
    for (const name of ["industry", "objective", "patternLabel"]) {
      if (values.has(name) && !validDecimalCSV(values.get(name), 50)) {
        return false;
      }
    }
    if (
      values.has("keyword") &&
      (
        values.get("keyword").trim() === "" ||
        values.get("keyword").length > 256
      )
    ) {
      return false;
    }
    if (
      values.has("duration") &&
      !["0-15", "15-30", "30-60", "60-999"].includes(values.get("duration"))
    ) {
      return false;
    }
    if (
      values.has("like") &&
      !["0-100", "100-1000", "1000-10000", "10000-999999999"].includes(
        values.get("like")
      )
    ) {
      return false;
    }
    if (
      values.has("adFormat") &&
      !["spark", "non_spark"].includes(values.get("adFormat"))
    ) {
      return false;
    }
    return (
      !values.has("adLanguage") ||
      validLanguageCSV(values.get("adLanguage"), 20)
    );
  }
  if (path === TIKTOK_CREATIVE_TOP_ADS_SUGGEST_PATH) {
    const query = values.get("query") || "";
    const scenario = values.get("scenario");
    return (
      query.length <= 256 &&
      !hasControlCharacters(query) &&
      parsePositiveInteger(values.get("count"), 50) !== null &&
      ["1", "2"].includes(scenario) &&
      (
        (scenario === "1" && query === "") ||
        (scenario === "2" && query.trim() !== "")
      ) &&
      COUNTRY_CODE.test(values.get("countryCode") || "")
    );
  }
  if (
    [
      TIKTOK_CREATIVE_TOP_ADS_V2_DETAIL_PATH,
      TIKTOK_CREATIVE_TOP_ADS_V2_ANALYSIS_PATH
    ].includes(path)
  ) {
    return DECIMAL_ID.test(values.get("materialId") || "");
  }
  if (path === TIKTOK_CREATIVE_TOP_ADS_V2_RECOMMEND_PATH) {
    return (
      DECIMAL_ID.test(values.get("materialId") || "") &&
      DECIMAL_ID.test(values.get("industry") || "") &&
      COUNTRY_CODE.test(values.get("countryCode") || "")
    );
  }
  if (path === TIKTOK_CREATIVE_TOP_ADS_KEYFRAME_PATH) {
    return (
      DECIMAL_ID.test(values.get("materialId") || "") &&
      new Set([
        "retain_ctr",
        "retain_cvr",
        "click_cnt",
        "convert_cnt",
        "play_retain_cnt"
      ]).has(values.get("metric"))
    );
  }
  if (path === TIKTOK_CREATIVE_TOP_ADS_PERCENTILE_PATH) {
    return (
      DECIMAL_ID.test(values.get("materialId") || "") &&
      values.get("metric") === "ctr_percentile" &&
      ["7", "30", "180"].includes(values.get("periodType"))
    );
  }
  if (path === TIKTOK_CREATIVE_STUDIO_CREDITS_PATH) {
    return true;
  }
  if (path === TIKTOK_CREATIVE_STUDIO_GENERATE_PATH) {
    const prompt = values.get("prompt") || "";
    const duration = values.get("duration") || "";
    return (
      prompt.trim() !== "" &&
      prompt.length <= 5000 &&
      INTEGER.test(duration) &&
      Number(duration) >= 4 &&
      Number(duration) <= 15 &&
      (
        !values.has("enhancePrompt") ||
        ["0", "1"].includes(values.get("enhancePrompt"))
      )
    );
  }
  if (path === TIKTOK_CREATIVE_STUDIO_UPLOAD_IMAGE_PATH) {
    const name = values.get("name") || "";
    const mimeType = values.get("mimeType") || "";
    const dataBase64 = values.get("dataBase64") || "";
    return (
      name.length >= 1 &&
      name.length <= 255 &&
      !/[\\/\r\n\0]/.test(name) &&
      ["image/png", "image/jpeg", "image/webp"].includes(mimeType) &&
      dataBase64.length >= 4 &&
      dataBase64.length <= 7 * 1024 * 1024 &&
      /^[A-Za-z0-9+/]+={0,2}$/.test(dataBase64)
    );
  }
  if (path === TIKTOK_CREATIVE_STUDIO_I2V_GENERATE_PATH) {
    const prompt = values.get("prompt") || "";
    const duration = values.get("duration") || "";
    return (
      prompt.trim() !== "" &&
      prompt.length <= 5000 &&
      INTEGER.test(duration) &&
      Number(duration) >= 4 &&
      Number(duration) <= 15 &&
      validStudioImageUrl(values.get("firstFrameUrl")) &&
      (
        !values.has("lastFrameUrl") ||
        validStudioImageUrl(values.get("lastFrameUrl"))
      )
    );
  }
  if (path === TIKTOK_CREATIVE_STUDIO_TASK_PATH) {
    return DECIMAL_ID.test(values.get("taskId") || "");
  }
  if (
    [
      TIKTOK_CREATIVE_STUDIO_PERMISSIONS_PATH,
      TIKTOK_CREATIVE_STUDIO_GENERATING_COUNT_PATH,
      TIKTOK_CREATIVE_STUDIO_MAX_COUNT_PATH
    ].includes(path)
  ) {
    return true;
  }
  if (path === TIKTOK_CREATIVE_STUDIO_LEDGER_PATH) {
    const cursor = values.get("cursor");
    return (
      parsePositiveInteger(values.get("pageSize"), 100) !== null &&
      (
        cursor === undefined ||
        (
          cursor.trim() !== "" &&
          cursor.length <= 1024 &&
          !hasControlCharacters(cursor)
        )
      )
    );
  }
  if (path === TIKTOK_CREATIVE_STUDIO_HISTORY_PATH) {
    return (
      INTEGER.test(values.get("offset") || "") &&
      Number(values.get("offset")) <= 100000 &&
      parsePositiveInteger(values.get("limit"), 100) !== null
    );
  }
  if (path === TIKTOK_CREATIVE_STUDIO_TASK_DETAIL_PATH) {
    return DECIMAL_ID.test(values.get("draftId") || "");
  }
  if (path === TIKTOK_CREATIVE_STUDIO_VIDEO_INFO_PATH) {
    return /^[A-Za-z0-9_-]{1,256}$/.test(values.get("vid") || "");
  }
  if (path === TIKTOK_ONE_CREATOR_FILTERS_PATH) {
    return true;
  }
  if (path === TIKTOK_ONE_CREATOR_SUGGEST_PATH) {
    const query = values.get("query") || "";
    return query.trim() !== "" && query.length <= 256;
  }
  if (path === TIKTOK_ONE_CREATOR_SEARCH_PATH) {
    if (
      parsePositiveInteger(values.get("page"), 1000) === null ||
      values.get("limit") !== "24" ||
      (values.get("query") || "").length > 256 ||
      !["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"].includes(
        values.get("sortField")
      ) ||
      !["1", "2"].includes(values.get("sortType"))
    ) {
      return false;
    }
    if (
      values.has("countryCodeList") &&
      !validCountryCSV(values.get("countryCodeList"), 50)
    ) {
      return false;
    }
    if (
      values.has("languageList") &&
      !validLanguageCSV(values.get("languageList"))
    ) {
      return false;
    }
    for (const name of [
      "minFansCnt",
      "maxFansCnt",
      "minMedianViews",
      "maxMedianViews"
    ]) {
      if (
        values.has(name) &&
        (
          !INTEGER.test(values.get(name)) ||
          Number(values.get(name)) > 1_000_000_000
        )
      ) {
        return false;
      }
    }
    for (const name of ["minEngagementRate", "maxEngagementRate"]) {
      if (
        values.has(name) &&
        (
          !/^(?:0(?:\.[0-9]{1,6})?|1(?:\.0{1,6})?)$/.test(values.get(name)) ||
          Number(values.get(name)) > 1
        )
      ) {
        return false;
      }
    }
    const pairs = [
      ["minFansCnt", "maxFansCnt"],
      ["minMedianViews", "maxMedianViews"],
      ["minEngagementRate", "maxEngagementRate"]
    ];
    return pairs.every(([minimum, maximum]) =>
      !values.has(minimum) ||
      !values.has(maximum) ||
      Number(values.get(minimum)) <= Number(values.get(maximum))
    );
  }
  if (path === TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH) {
    return ["1", "2"].includes(values.get("sourceModule"));
  }
  if (path === TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH) {
    if (
      !["7", "30", "180"].includes(values.get("timeRange")) ||
      !["1", "2", "3", "4"].includes(values.get("orderField")) ||
      parsePositiveInteger(values.get("page"), 1000) === null ||
      parsePositiveInteger(values.get("limit"), 20) === null ||
      values.get("sourceModule") !== "2"
    ) {
      return false;
    }
    if (
      values.has("countryCodeList") &&
      !validCountryCSV(values.get("countryCodeList"))
    ) {
      return false;
    }
    if (
      values.has("industryLabelList") &&
      !validDecimalCSV(values.get("industryLabelList"))
    ) {
      return false;
    }
    if (
      values.has("searchWord") &&
      (
        values.get("searchWord").trim() === "" ||
        values.get("searchWord").length > 256
      )
    ) {
      return false;
    }
    if (
      values.has("objectiveList") &&
      !validEnumCSV(
        values.get("objectiveList"),
        new Set(["1", "2", "3", "4", "5", "6", "8", "9", "14", "15", "16"])
      )
    ) {
      return false;
    }
    if (
      values.has("adFormat") &&
      !["1", "2", "3", "4", "99", "100"].includes(values.get("adFormat"))
    ) {
      return false;
    }
    return (
      !values.has("likeCntFilter") ||
      ["1", "2", "3", "4", "5"].includes(values.get("likeCntFilter"))
    );
  }
  if (path === TIKTOK_CREATIVE_TRENDING_VIDEO_OVERVIEW_PATH) {
    return true;
  }
  if (path === TIKTOK_CREATIVE_TRENDING_VIDEO_LIST_PATH) {
    if (
      !["3", "5"].includes(values.get("periodDimension")) ||
      parsePositiveInteger(values.get("periodEndTimestamp"), 4_102_444_800) === null ||
      !["1", "2", "3"].includes(values.get("orderByMetric")) ||
      !COUNTRY_CODE.test(values.get("countryCode") || "") ||
      parsePositiveInteger(values.get("page"), 1000) === null ||
      parsePositiveInteger(values.get("limit"), 20) === null
    ) {
      return false;
    }
    const labels = values.get("contentLabelIDs");
    return labels === "" || validDecimalCSV(labels);
  }
  if (!validCommonValues(values)) {
    return false;
  }
  if (path === TIKTOK_CREATIVE_HASHTAG_LIST_PATH) {
    if (
      parsePositiveInteger(values.get("page"), 1000) === null ||
      parsePositiveInteger(values.get("limit"), 100) === null
    ) {
      return false;
    }
    return (
      !values.has("industryID") ||
      (
        DECIMAL_ID.test(values.get("industryID")) &&
        Number.isSafeInteger(Number(values.get("industryID")))
      )
    );
  }
  return (
    path === TIKTOK_CREATIVE_HASHTAG_DETAIL_PATH &&
    DECIMAL_ID.test(values.get("hashtagID") || "")
  );
}

function parsedTikTokCreativeReferer(value) {
  if (typeof value !== "string" || value.length > 4096) {
    return null;
  }
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    return null;
  }
  if (
    parsed.origin !== TIKTOK_CREATIVE_ORIGIN ||
    parsed.username ||
    parsed.password ||
    parsed.hash ||
    (parsed.port && parsed.port !== "443")
  ) {
    return null;
  }
  return parsed;
}

export function validTikTokCreativeHashtagReferer(value) {
  const parsed = parsedTikTokCreativeReferer(value);
  if (!parsed || parsed.pathname !== TIKTOK_CREATIVE_HASHTAG_PATH) {
    return false;
  }
  return validTikTokCreativeHashtagQuery(parsed);
}

export function validTikTokCreativeHashtagDetailReferer(value) {
  const parsed = parsedTikTokCreativeReferer(value);
  if (
    !parsed ||
    !/^\/creative\/creativeCenter\/trends\/hashtag\/[1-9][0-9]{0,31}$/.test(
      parsed.pathname
    )
  ) {
    return false;
  }
  return validTikTokCreativeHashtagQuery(parsed);
}

export function validTikTokCreativeTrendingVideoReferer(value) {
  const parsed = parsedTikTokCreativeReferer(value);
  if (
    !parsed ||
    ![
      TIKTOK_CREATIVE_TRENDS_PATH,
      TIKTOK_CREATIVE_TRENDING_VIDEO_PATH,
      TIKTOK_CREATIVE_TRENDING_VIDEO_LEGACY_PATH
    ].includes(parsed.pathname)
  ) {
    return false;
  }
  const parameters = [...parsed.searchParams.entries()];
  return (
    parameters.every(([name]) => ["region", "period"].includes(name)) &&
    new Set(parameters.map(([name]) => name)).size === parameters.length &&
    (parsed.searchParams.get("region") === null ||
      COUNTRY_CODE.test(parsed.searchParams.get("region") || "")) &&
    (parsed.searchParams.get("period") === null ||
      ["7", "30", "90"].includes(parsed.searchParams.get("period") || ""))
  );
}

function validTikTokCreativeHashtagQuery(parsed) {
  const parameters = [...parsed.searchParams.entries()];
  if (
    parameters.some(([name]) =>
      ![
        "region",
        "period",
        "from_creative",
        "aioChannel",
        "aioScene",
        "aioCode"
      ].includes(name)
    ) ||
    new Set(parameters.map(([name]) => name)).size !== parameters.length
  ) {
    return false;
  }
  const region = parsed.searchParams.get("region");
  const period = parsed.searchParams.get("period");
  const source = parsed.searchParams.get("from_creative");
  const aio = [
    parsed.searchParams.get("aioChannel"),
    parsed.searchParams.get("aioScene"),
    parsed.searchParams.get("aioCode")
  ];
  const validAio = aio.every((value) => value === null) || (
    aio[0] === "SEO" &&
    aio[1] === "AIOEntrance" &&
    /^[a-f0-9]{16}$/.test(aio[2] || "")
  );
  return (
    (region === null || COUNTRY_CODE.test(region)) &&
    (period === null || ["7", "30", "90"].includes(period)) &&
    (source === null || source === "login") &&
    validAio
  );
}

export function validTikTokCreativeTopAdsReferer(value) {
  const parsed = parsedTikTokCreativeReferer(value);
  return Boolean(
    (
      parsed &&
      [
        TIKTOK_CREATIVE_TOP_ADS_PATH,
        TIKTOK_CREATIVE_TOP_ADS_INSIGHT_PATH
      ].includes(parsed.pathname) &&
      [...parsed.searchParams].length === 0
    ) ||
    validTikTokCreativeTopAdsV2Referer(value)
  );
}

export function validTikTokCreativeTopAdsV2Referer(value) {
  const parsed = parsedTikTokCreativeReferer(value);
  if (!parsed) {
    return false;
  }
  if (parsed.pathname === TIKTOK_CREATIVE_TOP_ADS_V2_PATH) {
    const parameters = [...parsed.searchParams.entries()];
    if (
      parameters.some(([name]) => !["period", "region"].includes(name)) ||
      new Set(parameters.map(([name]) => name)).size !== parameters.length
    ) {
      return false;
    }
    const period = parsed.searchParams.get("period");
    const region = parsed.searchParams.get("region");
    return (
      (period === null || ["7", "30", "180"].includes(period)) &&
      (region === null || COUNTRY_CODE.test(region))
    );
  }
  return Boolean(
    /^\/business\/creativecenter\/topads\/[1-9][0-9]{0,31}\/pc\/en$/.test(
      parsed.pathname
    ) &&
    [...parsed.searchParams].every(([name]) =>
      ["countryCode", "period", "from"].includes(name)
    )
  );
}

export function validTikTokCreativeTopAdsLibraryReferer(value) {
  const parsed = parsedTikTokCreativeReferer(value);
  return Boolean(
    parsed &&
    parsed.pathname === TIKTOK_CREATIVE_TOP_ADS_PATH &&
    [...parsed.searchParams].length === 0
  );
}

export function validTikTokCreativeTopAdsInsightReferer(value) {
  const parsed = parsedTikTokCreativeReferer(value);
  return Boolean(
    parsed &&
    parsed.pathname === TIKTOK_CREATIVE_TOP_ADS_INSIGHT_PATH &&
    [...parsed.searchParams].length === 0
  );
}

export function validTikTokCreativeStudioReferer(value) {
  const parsed = parsedTikTokCreativeReferer(value);
  if (!parsed) {
    return false;
  }
  if (parsed.pathname === TIKTOK_CREATIVE_STUDIO_T2V_PATH) {
    const parameters = [...parsed.searchParams.entries()];
    return (
      parameters.length === 1 &&
      parameters[0][0] === "subApp" &&
      parameters[0][1] === "CreativeStudio/MiniApp/TextToVideo"
    );
  }
  if (parsed.pathname !== TIKTOK_CREATIVE_STUDIO_PATH) {
    return false;
  }
  const parameters = [...parsed.searchParams.entries()];
  if (
    parameters.some(([name]) => !["from_creative", "region"].includes(name)) ||
    new Set(parameters.map(([name]) => name)).size !== parameters.length
  ) {
    return false;
  }
  const source = parsed.searchParams.get("from_creative");
  const region = parsed.searchParams.get("region");
  return (
    (source === null || ["login", "signup", "sign_up"].includes(source)) &&
    (region === null || region === "row")
  );
}

export function validTikTokOneCreatorReferer(value) {
  const parsed = parsedTikTokCreativeReferer(value);
  if (!parsed || parsed.pathname !== TIKTOK_ONE_CREATOR_PATH) {
    return false;
  }
  const parameters = [...parsed.searchParams.entries()];
  if (
    parameters.some(([name]) => !["region", "from_creative"].includes(name)) ||
    new Set(parameters.map(([name]) => name)).size !== parameters.length
  ) {
    return false;
  }
  const region = parsed.searchParams.get("region");
  const source = parsed.searchParams.get("from_creative");
  return (
    (region === null || region === "row") &&
    (source === null || source === "login")
  );
}

export function validTikTokAdsKeywordPlannerReferer(value) {
  const parsed = parsedTikTokCreativeReferer(value);
  if (
    !parsed ||
    parsed.pathname !== TIKTOK_ADS_KEYWORD_PLANNER_PATH
  ) {
    return false;
  }
  const parameters = [...parsed.searchParams.entries()];
  return (
    parameters.length <= 1 &&
    parameters.every(([name, item]) =>
      name === "aadvid" && DECIMAL_ID.test(item)
    )
  );
}

export function isTikTokAdsManagerHomeUrl(value) {
  const parsed = parsedTikTokCreativeReferer(value);
  return Boolean(
    parsed &&
    parsed.pathname === TIKTOK_ADS_MANAGER_HOME_PATH &&
    [...parsed.searchParams].length === 0
  );
}

export function validTikTokCreativeReferer(value) {
  return (
    validTikTokCreativeHashtagReferer(value) ||
    validTikTokCreativeTrendingVideoReferer(value) ||
    validTikTokCreativeTopAdsReferer(value) ||
    validTikTokCreativeStudioReferer(value) ||
    validTikTokOneCreatorReferer(value) ||
    validTikTokAdsKeywordPlannerReferer(value)
  );
}

export function isTikTokCreativeLoginUrl(value) {
  const parsed = parsedTikTokCreativeReferer(value);
  return Boolean(
    parsed &&
    parsed.pathname === TIKTOK_CREATIVE_LOGIN_PATH
  );
}

export function isTikTokCreativeProfileUrl(value) {
  const parsed = parsedTikTokCreativeReferer(value);
  return Boolean(
    parsed &&
    parsed.pathname === TIKTOK_CREATIVE_SIGNUP_PATH
  );
}

export function isTikTokCreativeTabUrl(value) {
  return (
    validTikTokCreativeReferer(value) ||
    isTikTokAdsManagerHomeUrl(value) ||
    isTikTokCreativeLoginUrl(value) ||
    isTikTokCreativeProfileUrl(value)
  );
}

export function isTikTokCreativeScopeTabUrl(value, scope = "hashtag") {
  if (scope === "ads_manager") {
    return (
      validTikTokAdsKeywordPlannerReferer(value) ||
      isTikTokAdsManagerHomeUrl(value) ||
      isTikTokCreativeScopeLoginUrl(value, scope)
    );
  }
  if (scope === "one") {
    return (
      validTikTokOneCreatorReferer(value) ||
      isTikTokCreativeScopeLoginUrl(value, scope)
    );
  }
  if (scope === "studio") {
    return (
      validTikTokCreativeStudioReferer(value) ||
      isTikTokCreativeScopeLoginUrl(value, scope) ||
      isTikTokCreativeProfileUrl(value)
    );
  }
  if (scope === "top_ads") {
    return (
      validTikTokCreativeTopAdsReferer(value) ||
      validTikTokCreativeTopAdsV2Referer(value) ||
      isTikTokCreativeScopeLoginUrl(value, scope) ||
      isTikTokCreativeProfileUrl(value)
    );
  }
  return (
    validTikTokCreativeHashtagReferer(value) ||
    validTikTokCreativeHashtagDetailReferer(value) ||
    validTikTokCreativeTrendingVideoReferer(value) ||
    isTikTokCreativeScopeLoginUrl(value, scope)
  );
}

export function isTikTokCreativeScopeLoginUrl(value, scope = "hashtag") {
  const parsed = parsedTikTokCreativeReferer(value);
  if (!parsed) {
    return false;
  }
  if (scope === "ads_manager") {
    return /^\/i18n\/login\/?$/.test(parsed.pathname);
  }
  if (parsed.pathname !== TIKTOK_CREATIVE_LOGIN_PATH) {
    return false;
  }
  const redirect = parsed.searchParams.get("redirect");
  if (redirect === null || redirect === "") {
    return true;
  }
  return scope === "top_ads"
    ? validTikTokCreativeTopAdsReferer(redirect)
    : scope === "studio"
      ? validTikTokCreativeStudioReferer(redirect)
        : scope === "one"
          ? validTikTokOneCreatorReferer(redirect)
        : (
            validTikTokCreativeHashtagReferer(redirect) ||
            validTikTokCreativeTrendingVideoReferer(redirect)
          );
}

export function sameTikTokCreativeRequestContext(current, referer) {
  return (
    (
      (
        validTikTokCreativeHashtagReferer(current) ||
        validTikTokCreativeHashtagDetailReferer(current)
      ) &&
      validTikTokCreativeHashtagReferer(referer)
    ) ||
    (
      validTikTokCreativeTrendingVideoReferer(current) &&
      validTikTokCreativeTrendingVideoReferer(referer)
    ) ||
    (
      validTikTokCreativeTopAdsLibraryReferer(current) &&
      validTikTokCreativeTopAdsLibraryReferer(referer)
    ) ||
    (
      validTikTokCreativeTopAdsInsightReferer(current) &&
      validTikTokCreativeTopAdsInsightReferer(referer)
    ) ||
    (
      validTikTokCreativeTopAdsV2Referer(current) &&
      validTikTokCreativeTopAdsV2Referer(referer)
    ) ||
    (
      validTikTokCreativeStudioReferer(current) &&
      validTikTokCreativeStudioReferer(referer)
    ) ||
    (
      validTikTokOneCreatorReferer(current) &&
      validTikTokOneCreatorReferer(referer)
    ) ||
    (
      validTikTokAdsKeywordPlannerReferer(current) &&
      validTikTokAdsKeywordPlannerReferer(referer)
    )
  );
}

function validTikTokCreativeRequestReferer(path, entries, referer) {
  if (TIKTOK_ADS_KEYWORD_PATHS.has(path)) {
    return validTikTokAdsKeywordPlannerReferer(referer);
  }
  if (TIKTOK_ONE_CREATOR_PATHS.has(path)) {
    return validTikTokOneCreatorReferer(referer);
  }
  if (TIKTOK_CREATIVE_STUDIO_PATHS.has(path)) {
    return validTikTokCreativeStudioReferer(referer);
  }
  if (TIKTOK_CREATIVE_TRENDING_VIDEO_PATHS.has(path)) {
    return validTikTokCreativeTrendingVideoReferer(referer);
  }
  if (TIKTOK_CREATIVE_HASHTAG_PATHS.has(path)) {
    return validTikTokCreativeHashtagReferer(referer);
  }
  if (
    [
      TIKTOK_CREATIVE_TOP_ADS_V2_FILTERS_PATH,
      TIKTOK_CREATIVE_TOP_ADS_V2_LIST_PATH,
      TIKTOK_CREATIVE_TOP_ADS_SUGGEST_PATH,
      TIKTOK_CREATIVE_TOP_ADS_V2_DETAIL_PATH,
      TIKTOK_CREATIVE_TOP_ADS_V2_RECOMMEND_PATH,
      TIKTOK_CREATIVE_TOP_ADS_KEYFRAME_PATH,
      TIKTOK_CREATIVE_TOP_ADS_PERCENTILE_PATH,
      TIKTOK_CREATIVE_TOP_ADS_V2_ANALYSIS_PATH
    ].includes(path)
  ) {
    return validTikTokCreativeTopAdsV2Referer(referer);
  }
  if (path === TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH) {
    return validTikTokCreativeTopAdsLibraryReferer(referer);
  }
  if (path !== TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH) {
    return false;
  }
  const sourceModule = entries.find((entry) =>
    Array.isArray(entry) && entry[0] === "sourceModule"
  );
  return Boolean(
    sourceModule &&
    (
      (
        sourceModule[1] === "1" &&
        validTikTokCreativeTopAdsInsightReferer(referer)
      ) ||
      (
        sourceModule[1] === "2" &&
        validTikTokCreativeTopAdsLibraryReferer(referer)
      )
    )
  );
}

export function validTikTokCreativeRequest(message, allowedPaths = null) {
  return Boolean(
    isRecord(message) &&
    Object.keys(message).every((name) =>
      ["path", "entries", "referer", "request_interval_ms"].includes(name)
    ) &&
    Object.prototype.hasOwnProperty.call(CONTRACTS, message.path) &&
    (
      allowedPaths === null ||
      (allowedPaths instanceof Set && allowedPaths.has(message.path))
    ) &&
    validTikTokCreativeEntries(message.path, message.entries) &&
    validTikTokCreativeRequestReferer(
      message.path,
      message.entries,
      message.referer
    ) &&
    (
      message.request_interval_ms === undefined ||
      (
        Number.isInteger(message.request_interval_ms) &&
        message.request_interval_ms >= 0 &&
        message.request_interval_ms <= 10000
      )
    )
  );
}
