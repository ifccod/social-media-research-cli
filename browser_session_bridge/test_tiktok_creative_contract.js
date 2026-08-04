import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  TikTokCreativeSessionAdapter
} from "./adapters/tiktok_creative/adapter.js";
import {
  invokeTikTokCreativePageRuntime
} from "./adapters/tiktok_creative/page_runtime.js";
import { SerialRequestPolicy } from "./core/serial_request_policy.js";
import {
  TIKTOK_ADS_KEYWORD_IDEAS_PATH,
  TIKTOK_ADS_KEYWORD_PLANNER_URL,
  TIKTOK_ADS_KEYWORD_SUMMARY_PATH,
  TIKTOK_CREATIVE_HASHTAG_DETAIL_PATH,
  TIKTOK_CREATIVE_HASHTAG_LIST_PATH,
  TIKTOK_CREATIVE_HASHTAG_URL,
  TIKTOK_CREATIVE_ORIGIN,
  TIKTOK_CREATIVE_SIGNUP_PATH,
  TIKTOK_CREATIVE_TRENDING_VIDEO_OVERVIEW_PATH,
  TIKTOK_CREATIVE_TRENDING_VIDEO_LIST_PATH,
  TIKTOK_CREATIVE_TRENDING_VIDEO_URL,
  TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH,
  TIKTOK_CREATIVE_TOP_ADS_INSIGHT_URL,
  TIKTOK_CREATIVE_TOP_ADS_KEYFRAME_PATH,
  TIKTOK_CREATIVE_TOP_ADS_SUGGEST_PATH,
  TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH,
  TIKTOK_CREATIVE_TOP_ADS_URL,
  TIKTOK_CREATIVE_TOP_ADS_V2_DETAIL_PATH,
  TIKTOK_CREATIVE_TOP_ADS_V2_FILTERS_PATH,
  TIKTOK_CREATIVE_TOP_ADS_V2_LIST_PATH,
  TIKTOK_CREATIVE_TOP_ADS_V2_URL,
  isTikTokAdsManagerHomeUrl,
  validTikTokCreativeHashtagDetailReferer,
  validTikTokCreativeEntries,
  validTikTokCreativeReferer,
  validTikTokCreativeRequest,
  validTikTokAdsKeywordPlannerReferer
} from "./adapters/tiktok_creative/contract.js";

const LIST_ENTRIES = [
  ["timeRange", "7"],
  ["countryCode", "US"],
  ["industryID", "23000000000"],
  ["page", "2"],
  ["limit", "20"]
];
const DETAIL_ENTRIES = [
  ["hashtagID", "7383227119714238469"],
  ["timeRange", "90"],
  ["countryCode", "US"]
];
const TRENDING_VIDEO_ENTRIES = [
  ["periodDimension", "5"],
  ["periodEndTimestamp", "1784764800"],
  ["orderByMetric", "1"],
  ["countryCode", "US"],
  ["contentLabelIDs", "11002,11003"],
  ["page", "2"],
  ["limit", "20"]
];
const TOP_ADS_FILTER_LIBRARY_ENTRIES = [["sourceModule", "2"]];
const TOP_ADS_FILTER_INSIGHT_ENTRIES = [["sourceModule", "1"]];
const TOP_ADS_SEARCH_ENTRIES = [
  ["sourceModule", "2"],
  ["industryLabelList", "12000000000,12000000001"],
  ["countryCodeList", "US,GB"],
  ["timeRange", "30"],
  ["searchWord", "running shoes"],
  ["objectiveList", "1,4"],
  ["adFormat", "1"],
  ["likeCntFilter", "1"],
  ["orderField", "1"],
  ["page", "1"],
  ["limit", "20"]
];
const TOP_ADS_MINIMAL_SEARCH_ENTRIES = [
  ["sourceModule", "2"],
  ["timeRange", "30"],
  ["orderField", "1"],
  ["page", "1"],
  ["limit", "20"]
];

function request(path, entries, overrides = {}) {
  return {
    path,
    entries,
    referer: TIKTOK_CREATIVE_HASHTAG_URL,
    request_interval_ms: 3000,
    ...overrides
  };
}

function topAdsRequest(path, entries, referer = TIKTOK_CREATIVE_TOP_ADS_URL) {
  return {
    path,
    entries,
    referer,
    request_interval_ms: 3000
  };
}

function trendingVideoRequest(entries = TRENDING_VIDEO_ENTRIES) {
  return {
    path: TIKTOK_CREATIVE_TRENDING_VIDEO_LIST_PATH,
    entries,
    referer: TIKTOK_CREATIVE_TRENDING_VIDEO_URL,
    request_interval_ms: 3000
  };
}

function trendingVideoOverviewRequest(entries = []) {
  return {
    path: TIKTOK_CREATIVE_TRENDING_VIDEO_OVERVIEW_PATH,
    entries,
    referer: TIKTOK_CREATIVE_TRENDING_VIDEO_URL,
    request_interval_ms: 3000
  };
}

async function invokeTikTokCreativeRuntimeFixture(input, {
  href,
  fetchImpl,
  nextRequire = null,
  webpackChunkclient = null,
  webpackChunkserver = null,
  verificationVisible = false,
  cookie = ""
}) {
  const names = [
    "window",
    "document",
    "Element",
    "location",
    "navigator",
    "screen",
    "fetch"
  ];
  const previous = new Map(names.map((name) => [
    name,
    Object.getOwnPropertyDescriptor(globalThis, name)
  ]));
  const locationValue = new URL(href);
  class FixtureElement {
    getBoundingClientRect() {
      return { width: 320, height: 180 };
    }
  }
  const verificationElement = new FixtureElement();
  const windowValue = {
    fetch: fetchImpl,
    __next_require__: nextRequire,
    webpackChunkclient,
    webpackChunkserver,
    getComputedStyle: () => ({
      display: "block",
      visibility: "visible",
      opacity: "1"
    }),
    devicePixelRatio: 1,
    innerWidth: 1280,
    innerHeight: 720,
    outerWidth: 1280,
    outerHeight: 800
  };
  const values = {
    window: windowValue,
    document: {
      cookie,
      getElementById: () => null,
      querySelectorAll: (selector) =>
        verificationVisible && selector === "#captcha_container"
          ? [verificationElement]
          : []
    },
    Element: FixtureElement,
    location: locationValue,
    navigator: {
      userAgent: "fixture",
      language: "en-US",
      languages: ["en-US"],
      platform: "fixture",
      vendor: "fixture",
      cookieEnabled: true,
      onLine: true
    },
    screen: {
      width: 1280,
      height: 720,
      availWidth: 1280,
      availHeight: 700,
      colorDepth: 24,
      pixelDepth: 24
    },
    fetch: fetchImpl
  };
  for (const [name, value] of Object.entries(values)) {
    Object.defineProperty(globalThis, name, {
      configurable: true,
      writable: true,
      value
    });
  }
  try {
    return await invokeTikTokCreativePageRuntime(input);
  } finally {
    for (const name of names) {
      const descriptor = previous.get(name);
      if (descriptor) {
        Object.defineProperty(globalThis, name, descriptor);
      } else {
        delete globalThis[name];
      }
    }
  }
}

test("TikTok Creative contract pins paths, values, and referer", () => {
  assert.equal(
    validTikTokCreativeEntries(
      TIKTOK_CREATIVE_HASHTAG_LIST_PATH,
      LIST_ENTRIES
    ),
    true
  );
  assert.equal(
    validTikTokCreativeEntries(
      TIKTOK_CREATIVE_HASHTAG_DETAIL_PATH,
      DETAIL_ENTRIES
    ),
    true
  );
  assert.equal(validTikTokCreativeReferer(TIKTOK_CREATIVE_HASHTAG_URL), true);
  assert.equal(
    validTikTokCreativeReferer(TIKTOK_CREATIVE_TRENDING_VIDEO_URL),
    true
  );
  assert.equal(
    validTikTokCreativeReferer(
      `${TIKTOK_CREATIVE_ORIGIN}/creative/creativeCenter/trends`
    ),
    true
  );
  assert.equal(
    validTikTokCreativeReferer(
      `${TIKTOK_CREATIVE_ORIGIN}/creative/creativeCenter/trends/video` +
        "?region=US&period=30"
    ),
    true
  );
  assert.equal(
    validTikTokCreativeRequest(
      request(TIKTOK_CREATIVE_HASHTAG_LIST_PATH, LIST_ENTRIES)
    ),
    true
  );
  assert.equal(
    validTikTokCreativeRequest(
      request(TIKTOK_CREATIVE_HASHTAG_DETAIL_PATH, DETAIL_ENTRIES)
    ),
    true
  );
  assert.equal(validTikTokCreativeEntries(
    TIKTOK_CREATIVE_TRENDING_VIDEO_LIST_PATH,
    TRENDING_VIDEO_ENTRIES
  ), true);
  assert.equal(
    validTikTokCreativeEntries(
      TIKTOK_CREATIVE_TRENDING_VIDEO_OVERVIEW_PATH,
      []
    ),
    true
  );
  assert.equal(validTikTokCreativeRequest(trendingVideoRequest()), true);
  assert.equal(validTikTokCreativeRequest(trendingVideoOverviewRequest()), true);

  const invalid = [
    request("/CreativeOne/KnowledgeAPI/Other", LIST_ENTRIES),
    request(TIKTOK_CREATIVE_HASHTAG_LIST_PATH, [
      ...LIST_ENTRIES,
      ["token", "TOKEN"]
    ]),
    request(TIKTOK_CREATIVE_HASHTAG_LIST_PATH, [
      ...LIST_ENTRIES,
      ["page", "3"]
    ]),
    request(
      TIKTOK_CREATIVE_HASHTAG_LIST_PATH,
      LIST_ENTRIES.map((entry) =>
        entry[0] === "countryCode" ? ["countryCode", "usa"] : entry
      )
    ),
    request(
      TIKTOK_CREATIVE_HASHTAG_DETAIL_PATH,
      DETAIL_ENTRIES.map((entry) =>
        entry[0] === "hashtagID" ? ["hashtagID", "0"] : entry
      )
    ),
    request(TIKTOK_CREATIVE_HASHTAG_LIST_PATH, LIST_ENTRIES, {
      referer: `${TIKTOK_CREATIVE_HASHTAG_URL}&token=TOKEN`
    }),
    request(TIKTOK_CREATIVE_HASHTAG_LIST_PATH, LIST_ENTRIES, {
      request_interval_ms: 10001
    }),
    trendingVideoRequest(TRENDING_VIDEO_ENTRIES.map((entry) =>
      entry[0] === "limit" ? ["limit", "21"] : entry
    )),
    trendingVideoRequest(TRENDING_VIDEO_ENTRIES.map((entry) =>
      entry[0] === "contentLabelIDs" ? ["contentLabelIDs", "0"] : entry
    )),
    trendingVideoOverviewRequest([["countryCode", "US"]]),
    {
      ...request(TIKTOK_CREATIVE_HASHTAG_LIST_PATH, LIST_ENTRIES),
      extra: true
    }
  ];
  for (const value of invalid) {
    assert.equal(validTikTokCreativeRequest(value), false);
  }
});

test("TikTok Top Ads contract binds source module to its exact page", () => {
  assert.equal(
    validTikTokCreativeEntries(
      TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH,
      TOP_ADS_FILTER_LIBRARY_ENTRIES
    ),
    true
  );
  assert.equal(
    validTikTokCreativeEntries(
      TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH,
      TOP_ADS_FILTER_INSIGHT_ENTRIES
    ),
    true
  );
  assert.equal(
    validTikTokCreativeEntries(
      TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH,
      TOP_ADS_SEARCH_ENTRIES
    ),
    true
  );
  assert.equal(
    validTikTokCreativeEntries(
      TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH,
      TOP_ADS_MINIMAL_SEARCH_ENTRIES
    ),
    true
  );
  assert.equal(
    validTikTokCreativeRequest(
      topAdsRequest(
        TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH,
        TOP_ADS_FILTER_LIBRARY_ENTRIES
      )
    ),
    true
  );
  assert.equal(
    validTikTokCreativeRequest(
      topAdsRequest(
        TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH,
        TOP_ADS_FILTER_INSIGHT_ENTRIES,
        TIKTOK_CREATIVE_TOP_ADS_INSIGHT_URL
      )
    ),
    true
  );
  assert.equal(
    validTikTokCreativeRequest(
      topAdsRequest(
        TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH,
        TOP_ADS_SEARCH_ENTRIES
      )
    ),
    true
  );

  const mismatches = [
    topAdsRequest(
      TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH,
      TOP_ADS_FILTER_LIBRARY_ENTRIES,
      TIKTOK_CREATIVE_TOP_ADS_INSIGHT_URL
    ),
    topAdsRequest(
      TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH,
      TOP_ADS_FILTER_INSIGHT_ENTRIES
    ),
    topAdsRequest(
      TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH,
      TOP_ADS_SEARCH_ENTRIES,
      TIKTOK_CREATIVE_TOP_ADS_INSIGHT_URL
    ),
    topAdsRequest(
      TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH,
      [["sourceModule", "3"]]
    ),
    topAdsRequest(
      TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH,
      TOP_ADS_SEARCH_ENTRIES.map((entry) =>
        entry[0] === "countryCodeList"
          ? ["countryCodeList", "US,US"]
          : entry
      )
    ),
    topAdsRequest(
      TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH,
      TOP_ADS_SEARCH_ENTRIES.map((entry) =>
        entry[0] === "objectiveList"
          ? ["objectiveList", "1,1"]
          : entry
      )
    )
  ];
  for (const value of mismatches) {
    assert.equal(validTikTokCreativeRequest(value), false);
  }
});

test("TikTok Top Ads v2 contract accepts the observed radar requests", () => {
  assert.equal(
    validTikTokCreativeReferer(
      `${TIKTOK_CREATIVE_TOP_ADS_V2_URL}?period=30&region=US`
    ),
    true
  );
  assert.equal(
    validTikTokCreativeReferer(
      `${TIKTOK_CREATIVE_TOP_ADS_V2_URL}?period=365&region=USA`
    ),
    false
  );
  const listEntries = [
    ["period", "30"],
    ["orderBy", "for_you"],
    ["countryCode", "US"],
    ["page", "1"],
    ["limit", "20"],
    ["industry", "14103000000"],
    ["keyword", "coffee"],
    ["objective", "3"],
    ["duration", "0-15"],
    ["like", "100-1000"],
    ["patternLabel", "10100100000"],
    ["adFormat", "spark"],
    ["adLanguage", "en"]
  ];
  const valid = [
    topAdsRequest(TIKTOK_CREATIVE_TOP_ADS_V2_FILTERS_PATH, [], TIKTOK_CREATIVE_TOP_ADS_V2_URL),
    topAdsRequest(TIKTOK_CREATIVE_TOP_ADS_V2_LIST_PATH, listEntries, TIKTOK_CREATIVE_TOP_ADS_V2_URL),
    topAdsRequest(TIKTOK_CREATIVE_TOP_ADS_SUGGEST_PATH, [
      ["query", "coffee"],
      ["count", "5"],
      ["scenario", "2"],
      ["countryCode", "US"]
    ], TIKTOK_CREATIVE_TOP_ADS_V2_URL),
    topAdsRequest(TIKTOK_CREATIVE_TOP_ADS_V2_DETAIL_PATH, [
      ["materialId", "7650516707254976533"]
    ], TIKTOK_CREATIVE_TOP_ADS_V2_URL),
    topAdsRequest(TIKTOK_CREATIVE_TOP_ADS_KEYFRAME_PATH, [
      ["materialId", "7650516707254976533"],
      ["metric", "retain_ctr"]
    ], TIKTOK_CREATIVE_TOP_ADS_V2_URL)
  ];
  for (const value of valid) {
    assert.equal(validTikTokCreativeRequest(value), true);
  }
  const invalid = [
    topAdsRequest(TIKTOK_CREATIVE_TOP_ADS_V2_LIST_PATH, listEntries.map(
      (entry) => entry[0] === "countryCode" ? ["countryCode", "USA"] : entry
    ), TIKTOK_CREATIVE_TOP_ADS_V2_URL),
    topAdsRequest(TIKTOK_CREATIVE_TOP_ADS_SUGGEST_PATH, [
      ["query", ""],
      ["count", "5"],
      ["scenario", "2"],
      ["countryCode", "US"]
    ], TIKTOK_CREATIVE_TOP_ADS_V2_URL),
    topAdsRequest(TIKTOK_CREATIVE_TOP_ADS_KEYFRAME_PATH, [
      ["materialId", "7650516707254976533"],
      ["metric", "unknown"]
    ], TIKTOK_CREATIVE_TOP_ADS_V2_URL)
  ];
  for (const value of invalid) {
    assert.equal(validTikTokCreativeRequest(value), false);
  }
});

test("TikTok Ads Keyword Planner validates and signs the observed request chain", async () => {
  const referer = `${TIKTOK_ADS_KEYWORD_PLANNER_URL}?aadvid=7012345678901234567`;
  const entries = [
    ["keywords", "[\"wireless charger\"]"],
    ["startTime", "1751299200"],
    ["endTime", "1782835199"],
    ["brandOption", "0"],
    ["sortField", "1"],
    ["sortOrder", "1"],
    ["countryId", "6252001"],
    ["languageCode", "en"],
    ["languageName", "English"]
  ];
  assert.equal(
    validTikTokCreativeEntries(TIKTOK_ADS_KEYWORD_IDEAS_PATH, entries),
    true
  );
  assert.equal(validTikTokAdsKeywordPlannerReferer(referer), true);
  assert.equal(
    isTikTokAdsManagerHomeUrl("https://ads.tiktok.com/i18n/home"),
    true
  );
  assert.equal(
    isTikTokAdsManagerHomeUrl(
      "https://ads.tiktok.com/i18n/home?aadvid=7012345678901234567"
    ),
    false
  );
  assert.equal(
    validTikTokCreativeRequest({
      path: TIKTOK_ADS_KEYWORD_IDEAS_PATH,
      entries,
      referer,
      request_interval_ms: 0
    }),
    true
  );
  assert.equal(
    validTikTokCreativeEntries(TIKTOK_ADS_KEYWORD_IDEAS_PATH, [
      ...entries.slice(0, 1),
      ["startTime", "1782835199"],
      ["endTime", "1751299200"],
      ...entries.slice(3)
    ]),
    false
  );

  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options, body: JSON.parse(options.body) });
    if (url.includes("check_nogo_list")) {
      return {
        ok: true,
        json: async () => ({
          code: 0,
          msg: "success",
          data: {
            keywordsInNoGoList: { "wireless charger": false },
            BaseResp: null
          }
        })
      };
    }
    if (url.includes("check_get_word_ids")) {
      return {
        ok: true,
        json: async () => ({
          code: 0,
          msg: "success",
          data: {
            keywords: [{
              keyword: "wireless charger",
              keywordId: "29107367",
              invalidCode: null
            }]
          }
        })
      };
    }
    return {
      ok: true,
      json: async () => ({
        code: 0,
        msg: "success",
        data: {
          keywordIdeaInfoList: [{
            keyword: "wireless charger",
            searchVol: { volumeMax: 5000, volumeMin: 1000 },
            threeMonthChange: -0.4864279526422177,
            yoyChange: -0.6368184602818052,
            trend: null,
            competition: 3,
            estimatedCpc: {
              estimatedCpcLow: "0.230000",
              estimatedCpcHigh: "0.300000"
            },
            brandOption: 2,
            sourceType: 1,
            matchType: 3,
            language: "en",
            countryId: null
          }],
          totalSearchVol: { volumeMax: 500000, volumeMin: 250000 },
          totalBudgetEstimate: { volumeMax: 11, volumeMin: 5 },
          BaseResp: null
        }
      })
    };
  };
  const result = await invokeTikTokCreativeRuntimeFixture({
    kind: "request",
    path: TIKTOK_ADS_KEYWORD_IDEAS_PATH,
    entries,
    session_verified: true
  }, {
    href: referer,
    fetchImpl,
    cookie: "csrftoken=csrf-fixture"
  });

  assert.equal(result.ok, true);
  assert.equal(result.payload.keywordIdeaInfoList.length, 1);
  assert.equal(result.payload.keywordIdeaInfoList[0].competition, 3);
  assert.equal(calls.length, 3);
  assert.deepEqual(
    calls.map((call) => new URL(call.url, referer).pathname),
    [
      "/api/v4/i18n/search_ads/search_keyword/check_nogo_list/",
      "/api/v4/i18n/search_ads/search_keyword/check_get_word_ids/",
      TIKTOK_ADS_KEYWORD_IDEAS_PATH
    ]
  );
  assert.equal(calls[0].options.headers["x-csrftoken"], "csrf-fixture");
  assert.deepEqual(calls[0].body, {
    keywords: ["wireless charger"],
    regions: [],
    aadvid: "7012345678901234567"
  });
  assert.deepEqual(calls[2].body.inputKeywords, [
    { keyword: "wireless charger" }
  ]);
  assert.equal(calls[2].body.aadvid, "7012345678901234567");

  const accountPageResult = await invokeTikTokCreativeRuntimeFixture({
    kind: "request",
    path: TIKTOK_ADS_KEYWORD_IDEAS_PATH,
    entries,
    session_verified: true
  }, {
    href: (
      "https://ads.tiktok.com/i18n/nb_creation/create/objectives" +
      "?aadvid=7012345678901234567"
    ),
    fetchImpl,
    cookie: "csrftoken=csrf-fixture"
  });
  assert.equal(accountPageResult.ok, true);
  assert.equal(calls.length, 6);

  assert.equal(
    validTikTokCreativeEntries(TIKTOK_ADS_KEYWORD_SUMMARY_PATH, [
      [
        "words",
        "[{\"keyword\":\"wireless charger\",\"matchType\":3,\"sourceType\":1}]"
      ],
      ["countryName", "US"]
    ]),
    true
  );
  const readySession = await invokeTikTokCreativeRuntimeFixture({
    kind: "session",
    scope: "ads_manager"
  }, {
    href: referer,
    fetchImpl,
    cookie: "csrftoken=csrf-fixture"
  });
  const accountRequired = await invokeTikTokCreativeRuntimeFixture({
    kind: "session",
    scope: "ads_manager"
  }, {
    href: TIKTOK_ADS_KEYWORD_PLANNER_URL,
    fetchImpl,
    cookie: "csrftoken=csrf-fixture"
  });
  assert.equal(readySession.payload.request_ready, true);
  assert.equal(accountRequired.payload.request_ready, false);
  const accountPageSession = await invokeTikTokCreativeRuntimeFixture({
    kind: "session",
    scope: "ads_manager"
  }, {
    href: (
      "https://ads.tiktok.com/i18n/nb_creation/create/objectives" +
      "?aadvid=7012345678901234567"
    ),
    fetchImpl,
    cookie: "csrftoken=csrf-fixture"
  });
  assert.equal(accountPageSession.payload.request_ready, true);
});

test("TikTok Top Ads v2 runtime discovers the signed page transport", async () => {
  const calls = [];
  const transport = {
    U2: async (path, body) => {
      calls.push({ path, body });
      if (path === TIKTOK_CREATIVE_TOP_ADS_V2_FILTERS_PATH) {
        const option = (id) => ({ id, label: `label_${id}`, value: `value_${id}` });
        return {
          code: 0,
          data: {
            adLanguage: [option("en")],
            country: [option("US")],
            industry: [option("14103000000")],
            objective: [option("3")],
            patternLabel: [option("10100100000")],
            period: [option("30")]
          }
        };
      }
      return {
        code: 0,
        data: {
          materials: [{
            id: "7650516707254976533",
            adTitle: "Hook",
            brandName: "Brand",
            cost: 1,
            ctr: 0.5,
            like: 10,
            industryKey: "label_14103000000",
            objectiveKey: "campaign_objective_conversion",
            videoInfo: {
              vid: "v100",
              duration: 1557.039,
              width: 720,
              height: 1280,
              cover: "https://cdn.example/cover.jpg",
              videoUrl: { "720P": "https://cdn.example/video.mp4" }
            }
          }],
          pagination: {
            page: 1,
            size: 1,
            totalCount: 1,
            hasMore: false
          }
        }
      };
    },
    v_: async () => ({ code: 0, data: {} })
  };
  const factory = function signedTransportFactory() {
    return "cc-user-id __tea_cache_tokens_3874 maxiosGlobalConfig";
  };
  const nextRequire = () => transport;
  nextRequire.m = { 731864: factory };
  const fetchImpl = async () => {
    throw new Error("原生 fetch 不应承载 Top Ads 页面签名请求");
  };

  const filters = await invokeTikTokCreativeRuntimeFixture({
    kind: "request",
    path: TIKTOK_CREATIVE_TOP_ADS_V2_FILTERS_PATH,
    entries: [],
    session_verified: true
  }, {
    href: TIKTOK_CREATIVE_TOP_ADS_V2_URL,
    fetchImpl,
    nextRequire
  });
  const list = await invokeTikTokCreativeRuntimeFixture({
    kind: "request",
    path: TIKTOK_CREATIVE_TOP_ADS_V2_LIST_PATH,
    entries: [
      ["period", "30"],
      ["orderBy", "for_you"],
      ["countryCode", "US"],
      ["page", "1"],
      ["limit", "1"]
    ],
    session_verified: true
  }, {
    href: TIKTOK_CREATIVE_TOP_ADS_V2_URL,
    fetchImpl,
    nextRequire
  });

  assert.equal(filters.ok, true);
  assert.equal(filters.payload.country[0].id, "US");
  assert.equal(list.ok, true);
  assert.equal(list.payload.materials[0].id, "7650516707254976533");
  assert.equal(list.payload.materials[0].videoInfo.duration, 1557.039);
  assert.deepEqual(calls[1], {
    path: TIKTOK_CREATIVE_TOP_ADS_V2_LIST_PATH,
    body: {
      period: 30,
      orderBy: "for_you",
      countryCode: "US",
      page: 1,
      limit: 1
    }
  });
});

test("TikTok Top Ads v2 public page becomes request ready after a probe", async () => {
  const transport = {
    U2: async () => {
      const option = (id) => ({ id, label: `label_${id}`, value: `value_${id}` });
      return {
        code: 0,
        data: {
          adLanguage: [option("en")],
          country: [option("US")],
          industry: [option("14103000000")],
          objective: [option("3")],
          patternLabel: [option("10100100000")],
          period: [option("30")]
        }
      };
    },
    v_: async () => ({ code: 0, data: {} })
  };
  const factory = function signedTransportFactory() {
    return "cc-user-id __tea_cache_tokens_3874 maxiosGlobalConfig";
  };
  const nextRequire = () => transport;
  nextRequire.m = { 731864: factory };
  const result = await invokeTikTokCreativeRuntimeFixture({
    kind: "session_probe",
    scope: "top_ads"
  }, {
    href: TIKTOK_CREATIVE_TOP_ADS_V2_URL,
    fetchImpl: async () => {
      throw new Error("fetch fallback must not run");
    },
    nextRequire
  });

  assert.equal(result.ok, true);
  assert.equal(result.payload.logged_in, false);
  assert.equal(result.payload.request_ready, true);
});

test("TikTok Creative runtime uses observed module and strips mock interests", () => {
  const source = readFileSync(
    new URL("./adapters/tiktok_creative/page_runtime.js", import.meta.url),
    "utf8"
  );
  assert.match(source, /const HASHTAG_MODULE_ID = 28474;/);
  assert.match(source, /const TOP_ADS_MODULE_ID = 90444;/);
  assert.match(source, /window\.webpackChunkclient/);
  assert.match(source, /topAdsTransportModule/);
  assert.match(source, /module\.U5/);
  assert.match(source, /module\.N6/);
  assert.match(source, /module\.hP\(body\)/);
  assert.match(source, /module\.in\(body\)/);
  assert.match(source, /normalizeListResult/);
  assert.match(source, /normalizeDetailResult/);
  assert.match(source, /sessionAccessProbe/);
  assert.match(source, /normalizeTopAdsFilters/);
  assert.match(source, /normalizeTopAdsSearch/);
  assert.match(
    source,
    /const method = isFilters \|\| isOneFilters \|\| isOneSuggest \|\| isStudioGet\s*\?\s*"GET"\s*:\s*"POST";/
  );
  assert.match(source, /TOP_ADS_SEARCH_PATH/);
  assert.match(source, /profileCompletionRequired/);
  assert.match(source, /name === "relatedInterests"/);
  assert.match(source, /__MODERN_ROUTER_DATA__/);
  assert.match(source, /credentials:\s*"include"/);
  assert.doesNotMatch(source, /chrome\.cookies/);
});

test("TikTok Creative runtime pages trending videos on its exact page context", async () => {
  const calls = [];
  const result = await invokeTikTokCreativeRuntimeFixture({
    kind: "request",
    path: TIKTOK_CREATIVE_TRENDING_VIDEO_LIST_PATH,
    entries: TRENDING_VIDEO_ENTRIES,
    session_verified: true
  }, {
    href: TIKTOK_CREATIVE_TRENDING_VIDEO_URL,
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return {
        ok: true,
        text: async () => JSON.stringify({
          entityInfos: [{
            itemInfo: {
              itemID: "7656166869774109983",
              authorID: "7506219246691926062",
              creatorID: "168541398546182144",
              title: "Fixture video",
              coverURL: "https://cdn.example/cover.jpg",
              videoURL: "https://cdn.example/video.mp4",
              createTime: 1782590275,
              contentType: 1,
              token: "DROP"
            },
            itemAuthorInfo: {
              handlerName: "fixture.creator",
              nickName: "Fixture Creator",
              avatarURI: "https://cdn.example/avatar.jpg",
              bio: "Fixture bio",
              token: "DROP"
            },
            itemAuthorMetrics: { followers: 55097934 },
            itemMetrics: {
              videoViews: 139898979,
              organicVideoViews: 137104452,
              engagementRate: 0.11,
              sixSecondsVTR: 0.56,
              token: "DROP"
            }
          }],
          pagination: {
            page: 2,
            limit: 20,
            totalCount: 41,
            hasMore: true
          }
        })
          .replace('"7656166869774109983"', "7656166869774109983")
          .replace('"7506219246691926062"', "7506219246691926062")
          .replace('"168541398546182144"', "168541398546182144")
      };
    }
  });

  assert.equal(calls.length, 1);
  assert.equal(
    calls[0].url,
    "/CreativeOne/Report/CreativeCenterGetTopContentsList?" +
      "periodDimension=5&periodEndTimestamp=1784764800&orderByMetric=1&" +
      "countryCode=US&contentLabelIDs=11002%2C11003&organicOnly=false&" +
      "limit=20&page=2"
  );
  assert.equal(calls[0].options.method, "GET");
  assert.equal(calls[0].options.credentials, "include");
  assert.deepEqual(result, {
    ok: true,
    payload: {
      entityInfos: [{
        itemInfo: {
          itemID: "7656166869774109983",
          authorID: "7506219246691926062",
          creatorID: "168541398546182144",
          title: "Fixture video",
          coverURL: "https://cdn.example/cover.jpg",
          videoURL: "https://cdn.example/video.mp4",
          createTime: 1782590275,
          contentType: 1
        },
        itemAuthorInfo: {
          handlerName: "fixture.creator",
          nickName: "Fixture Creator",
          avatarURI: "https://cdn.example/avatar.jpg",
          bio: "Fixture bio"
        },
        itemAuthorMetrics: { followers: 55097934 },
        itemMetrics: {
          videoViews: 139898979,
          organicVideoViews: 137104452,
          engagementRate: 0.11,
          sixSecondsVTR: 0.56
        }
      }],
      pagination: { page: 2, limit: 20, totalCount: 41, hasMore: true }
    }
  });
});

test("TikTok Creative runtime reads the trending overview on its exact page", async () => {
  const calls = [];
  const result = await invokeTikTokCreativeRuntimeFixture({
    kind: "request",
    path: TIKTOK_CREATIVE_TRENDING_VIDEO_OVERVIEW_PATH,
    entries: [],
    session_verified: true
  }, {
    href: TIKTOK_CREATIVE_TRENDING_VIDEO_URL,
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return {
        ok: true,
        json: async () => ({
          BaseResp: { StatusCode: 0, StatusMessage: "" },
          lastDailyEndTimestamp: 1784764800
        })
      };
    }
  });

  assert.deepEqual(result, {
    ok: true,
    payload: { lastDailyEndTimestamp: 1784764800 }
  });
  assert.deepEqual(calls, [{
    url: "/CreativeOne/Report/GetTopContentsOverview",
    options: {
      method: "GET",
      credentials: "include",
      headers: { accept: "application/json, text/plain, */*" }
    }
  }]);
});

test("TikTok Creative trending video runtime rejects a mismatched page", async () => {
  const result = await invokeTikTokCreativeRuntimeFixture({
    kind: "request",
    path: TIKTOK_CREATIVE_TRENDING_VIDEO_LIST_PATH,
    entries: TRENDING_VIDEO_ENTRIES,
    session_verified: true
  }, {
    href: TIKTOK_CREATIVE_HASHTAG_URL,
    fetchImpl: async () => {
      throw new Error("must not fetch");
    }
  });

  assert.deepEqual(result, { ok: false, error: "invalid_request" });
});

test("TikTok Top Ads runtime prefers webpackChunkclient module 90444", async () => {
  const moduleIDs = [];
  const moduleCalls = [];
  const topAdsModule = {
    hP: async (body) => {
      moduleCalls.push({ method: "hP", body });
      return {
        BaseResp: { StatusCode: 0, StatusMessage: "" },
        industryLabelTree: [],
        countryCodeList: ["US"],
        objectiveList: [1]
      };
    },
    in: async (body) => {
      moduleCalls.push({ method: "in", body });
      return {
        BaseResp: { StatusCode: 0, StatusMessage: "" },
        itemList: [],
        pagination: {
          page: 1,
          size: 20,
          total: 0,
          hasMore: false
        }
      };
    }
  };
  const webpackChunkclient = [];
  webpackChunkclient.push = (chunk) => {
    chunk[2]((moduleID) => {
      moduleIDs.push(moduleID);
      return moduleID === 90444 ? topAdsModule : null;
    });
    return 1;
  };
  const fetchImpl = async () => {
    throw new Error("fetch fallback must not run when module 90444 exists");
  };

  const filters = await invokeTikTokCreativeRuntimeFixture({
    kind: "request",
    path: TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH,
    entries: TOP_ADS_FILTER_LIBRARY_ENTRIES,
    session_verified: true
  }, {
    href: TIKTOK_CREATIVE_TOP_ADS_URL,
    fetchImpl,
    webpackChunkclient
  });
  const search = await invokeTikTokCreativeRuntimeFixture({
    kind: "request",
    path: TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH,
    entries: TOP_ADS_MINIMAL_SEARCH_ENTRIES,
    session_verified: true
  }, {
    href: TIKTOK_CREATIVE_TOP_ADS_URL,
    fetchImpl,
    webpackChunkclient
  });

  assert.deepEqual(moduleIDs, [90444, 90444]);
  assert.deepEqual(moduleCalls, [
    { method: "hP", body: { sourceModule: 2 } },
    {
      method: "in",
      body: {
        timeRange: 30,
        orderField: 1,
        page: "1",
        limit: "20",
        sourceModule: 2,
        sellingPointList: [],
        excludeMid: false,
        excludeKA: false
      }
    }
  ]);
  assert.deepEqual(filters, {
    ok: true,
    payload: {
      industryLabelTree: [],
      countryCodeList: ["US"],
      objectiveList: [1]
    }
  });
  assert.deepEqual(search, {
    ok: true,
    payload: {
      itemList: [],
      pagination: {
        page: 1,
        size: 20,
        hasMore: false,
        total: 0
      }
    }
  });
});

test("TikTok Creative runtime session probe recovers after verification clears", async () => {
  let probeCalls = 0;
  const fetchImpl = async () => {
    probeCalls += 1;
    return {
      ok: true,
      json: async () => ({
        BaseResp: { StatusCode: 0, StatusMessage: "" },
        industryLabelTree: [],
        countryCodeList: ["US"],
        objectiveList: [1]
      })
    };
  };
  const input = { kind: "session_probe", scope: "top_ads" };

  const verification = await invokeTikTokCreativeRuntimeFixture(input, {
    href: TIKTOK_CREATIVE_TOP_ADS_URL,
    fetchImpl,
    verificationVisible: true
  });
  const ready = await invokeTikTokCreativeRuntimeFixture(input, {
    href: TIKTOK_CREATIVE_TOP_ADS_URL,
    fetchImpl
  });

  assert.equal(verification.ok, true);
  assert.equal(verification.payload.verification_required, true);
  assert.equal(verification.payload.logged_in, false);
  assert.equal(verification.payload.request_ready, false);
  assert.equal(ready.ok, true);
  assert.equal(ready.payload.verification_required, false);
  assert.equal(ready.payload.logged_in, true);
  assert.equal(ready.payload.request_ready, true);
  assert.equal(probeCalls, 1);
});

test("TikTok Top Ads Library Filters projects its nested labelled tree", async () => {
  const calls = [];
  const result = await invokeTikTokCreativeRuntimeFixture({
    kind: "request",
    path: TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH,
    entries: TOP_ADS_FILTER_LIBRARY_ENTRIES,
    session_verified: true
  }, {
    href: TIKTOK_CREATIVE_TOP_ADS_URL,
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return {
        ok: true,
        json: async () => ({
          BaseResp: { StatusCode: 0, StatusMessage: "" },
          industryLabelTree: [{
            value: "12000000000",
            label: "Consumer goods",
            extra: "drop",
            children: [{
              industryLabelID: "12000000001",
              industryLabelName: "Beauty and personal care",
              parentID: "12000000000",
              extra: "drop"
            }]
          }],
          countryCodeList: ["US", "GB"],
          objectiveList: [1, 4, 16],
          token: "BROWSER_ONLY"
        })
      };
    }
  });

  assert.deepEqual(calls, [{
    url: `${TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH}?sourceModule=2`,
    options: {
      method: "GET",
      credentials: "include",
      headers: { accept: "application/json, text/plain, */*" }
    }
  }]);
  assert.deepEqual(result, {
    ok: true,
    payload: {
      industryLabelTree: [
        {
          value: "12000000000",
          label: "Consumer goods",
          children: [{
            industryLabelID: "12000000001",
            industryLabelName: "Beauty and personal care",
            parentID: "12000000000"
          }]
        }
      ],
      countryCodeList: ["US", "GB"],
      objectiveList: [1, 4, 16]
    }
  });
  assert.equal(JSON.stringify(result).includes("BROWSER_ONLY"), false);
});

test("TikTok Top Ads Insight Filters projects scalar industries independently", async () => {
  const result = await invokeTikTokCreativeRuntimeFixture({
    kind: "request",
    path: TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH,
    entries: TOP_ADS_FILTER_INSIGHT_ENTRIES,
    session_verified: true
  }, {
    href: TIKTOK_CREATIVE_TOP_ADS_INSIGHT_URL,
    fetchImpl: async (url, options) => {
      assert.equal(
        url,
        `${TIKTOK_CREATIVE_TOP_ADS_FILTERS_PATH}?sourceModule=1`
      );
      assert.equal(options.method, "GET");
      return {
        ok: true,
        json: async () => ({
          BaseResp: { StatusCode: 0, StatusMessage: "" },
          industryLabel: [1000000000000001, "1000000000000002"],
          countryCodeList: ["US", "JP"],
          objectiveList: "DROP",
          industryLabelTree: "DROP"
        })
      };
    }
  });

  assert.deepEqual(result, {
    ok: true,
    payload: {
      industryLabel: ["1000000000000001", "1000000000000002"],
      countryCodeList: ["US", "JP"]
    }
  });
});

test("TikTok Top Ads runtime posts SearchMaterial and strictly projects a page", async () => {
  const calls = [];
  const result = await invokeTikTokCreativeRuntimeFixture({
    kind: "request",
    path: TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH,
    entries: TOP_ADS_SEARCH_ENTRIES,
    session_verified: true
  }, {
    href: TIKTOK_CREATIVE_TOP_ADS_URL,
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return {
        ok: true,
        json: async () => ({
          BaseResp: { StatusCode: 0, StatusMessage: "" },
          itemList: [{
            materialID: "7654723953340235783",
            videoInfo: {
              video_url: {
                "360p": "https://cdn.example/360.mp4",
                "720p": "https://cdn.example/720.mp4"
              },
              coverAvif: "https://cdn.example/cover.avif",
              cover: "https://cdn.example/cover.jpg",
              token: "DROP"
            },
            videoView: 1000,
            clickRate: 0.1,
            ctrRank: "0.9",
            engagementRate: 0.25,
            videoView6sRank: "0.8",
            sellingPointList: ["Hook", "Product demo"],
            authorization: "DROP"
          }],
          pagination: {
            page: "1",
            size: "20",
            hasMore: false,
            total: "1"
          }
        })
      };
    }
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH);
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.credentials, "include");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    timeRange: 30,
    orderField: 1,
    page: "1",
    limit: "20",
    sourceModule: 2,
    sellingPointList: [],
    excludeMid: false,
    excludeKA: false,
    industryLabelList: ["12000000000", "12000000001"],
    countryCodeList: ["US", "GB"],
    searchWord: "running shoes",
    objectiveList: [1, 4],
    adFormat: 1,
    likeCntFilter: 1
  });
  assert.deepEqual(result, {
    ok: true,
    payload: {
      itemList: [{
        materialID: "7654723953340235783",
        videoInfo: {
          video_url: { "720p": "https://cdn.example/720.mp4" },
          coverAvif: "https://cdn.example/cover.avif",
          cover: "https://cdn.example/cover.jpg"
        },
        videoView: 1000,
        clickRate: 0.1,
        ctrRank: "0.9",
        engagementRate: 0.25,
        videoView6sRank: "0.8",
        sellingPointList: ["Hook", "Product demo"]
      }],
      pagination: {
        page: 1,
        size: 20,
        hasMore: false,
        total: 1
      }
    }
  });
  assert.equal(JSON.stringify(result).includes("DROP"), false);
});

test("TikTok Top Ads SearchMaterial omits unset filters and agrees on totals", async () => {
  let body;
  const result = await invokeTikTokCreativeRuntimeFixture({
    kind: "request",
    path: TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH,
    entries: TOP_ADS_MINIMAL_SEARCH_ENTRIES,
    session_verified: true
  }, {
    href: TIKTOK_CREATIVE_TOP_ADS_URL,
    fetchImpl: async (_url, options) => {
      body = JSON.parse(options.body);
      return {
        ok: true,
        json: async () => ({
          BaseResp: { StatusCode: 0, StatusMessage: "" },
          itemList: [],
          pagination: {
            page: 1,
            size: 20,
            total: 0,
            totalCount: 0,
            hasMore: false
          }
        })
      };
    }
  });

  assert.deepEqual(body, {
    timeRange: 30,
    orderField: 1,
    page: "1",
    limit: "20",
    sourceModule: 2,
    sellingPointList: [],
    excludeMid: false,
    excludeKA: false
  });
  assert.equal(Object.hasOwn(body, "countryCodeList"), false);
  assert.equal(Object.hasOwn(body, "objectiveList"), false);
  assert.deepEqual(result.payload.pagination, {
    page: 1,
    size: 20,
    hasMore: false,
    total: 0,
    totalCount: 0
  });
});

test("TikTok Top Ads SearchMaterial enforces canonical pagination across pages", async (t) => {
  const material = (id, coverAvif = "") => ({
    materialID: id,
    videoInfo: {
      video_url: { "720p": `https://cdn.example/${id}.mp4` },
      cover: `https://cdn.example/${id}.jpg`,
      coverAvif
    },
    videoView: 1,
    clickRate: 0,
    ctrRank: 0,
    engagementRate: 0,
    videoView6sRank: 0,
    sellingPointList: []
  });
  const items = [material("1"), material("2")];
  const entriesForPage = (page) => TOP_ADS_MINIMAL_SEARCH_ENTRIES.map(
    (entry) => entry[0] === "page" ? ["page", String(page)] : entry
  );
  const invoke = async ({ page, total, totalCount, hasMore, omitTotal = false }) =>
    invokeTikTokCreativeRuntimeFixture({
      kind: "request",
      path: TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH,
      entries: entriesForPage(page),
      session_verified: true
    }, {
      href: TIKTOK_CREATIVE_TOP_ADS_URL,
      fetchImpl: async () => {
        const pagination = { page, size: 20, hasMore };
        if (!omitTotal) {
          pagination.total = total;
        }
        if (totalCount !== undefined) {
          pagination.totalCount = totalCount;
        }
        return {
          ok: true,
          json: async () => ({ itemList: items, pagination })
        };
      }
    });

  const pageTwo = await invoke({ page: 2, total: 42, hasMore: true });
  assert.deepEqual(pageTwo.payload.pagination, {
    page: 2,
    size: 20,
    hasMore: true,
    total: 42
  });
  assert.equal(pageTwo.payload.itemList[0].videoInfo.coverAvif, undefined);

  const lastPage = await invoke({ page: 3, total: 42, hasMore: false });
  assert.deepEqual(lastPage.payload.pagination, {
    page: 3,
    size: 20,
    hasMore: false,
    total: 42
  });

  for (const fixture of [
    { name: "missing total", page: 1, totalCount: 42, hasMore: true, omitTotal: true },
    { name: "total below consumed", page: 2, total: 21, hasMore: false },
    { name: "more rows but hasMore false", page: 2, total: 42, hasMore: false },
    { name: "fully consumed but hasMore true", page: 3, total: 42, hasMore: true },
    { name: "totalCount mismatch", page: 2, total: 42, totalCount: 41, hasMore: true }
  ]) {
    await t.test(fixture.name, async () => {
      assert.deepEqual(await invoke(fixture), {
        ok: false,
        error: "invalid_response"
      });
    });
  }
});

test("TikTok Creative adapter invokes MAIN world and sanitizes payload", async () => {
  const tab = {
    id: 17,
    windowId: 1,
    status: "complete",
    url: TIKTOK_CREATIVE_HASHTAG_URL
  };
  const injections = [];
  let requestedInterval = null;
  const chromeApi = {
    tabs: {
      query: async () => [tab],
      get: async () => tab,
      update: async (_tabID, changes) => ({ ...tab, ...changes }),
      create: async (changes) => ({ ...tab, ...changes }),
      onRemoved: { addListener: () => undefined },
      onUpdated: {
        addListener: () => undefined,
        removeListener: () => undefined
      }
    },
    windows: { update: async () => undefined },
    scripting: {
      executeScript: async (input) => {
        injections.push(input);
        if (input.args[0].kind === "session") {
          return [{
            result: {
              ok: true,
              payload: {
                fingerprint: { cookie_enabled: true },
                logged_in: true,
                request_ready: true,
                verification_required: false,
                probe_required: false
              }
            }
          }];
        }
        return [{
          result: {
            ok: true,
            payload: {
              items: [{ hashtagID: "1", hashtagName: "fixture" }],
              pagination: { page: 1, totalCount: 1, hasMore: false },
              cookie: "COOKIE",
              nested: { authorization: "TOKEN", retained: true }
            }
          }
        }];
      }
    }
  };
  const requestPolicy = {
    runWithInterval: async (_signal, interval, operation) => {
      requestedInterval = interval;
      return operation(async () => undefined);
    }
  };
  const adapter = new TikTokCreativeSessionAdapter({
    chromeApi,
    requestPolicy
  });
  const result = await adapter.routeRequest(
    request(TIKTOK_CREATIVE_HASHTAG_LIST_PATH, LIST_ENTRIES)
  );

  assert.equal(requestedInterval, 3000);
  assert.equal(injections.length, 2);
  const injection = injections[1];
  assert.equal(injection.target.tabId, tab.id);
  assert.equal(injection.world, "MAIN");
  assert.equal(injection.injectImmediately, true);
  assert.deepEqual(injection.args[0], {
    kind: "request",
    path: TIKTOK_CREATIVE_HASHTAG_LIST_PATH,
    entries: LIST_ENTRIES,
    session_verified: true
  });
  assert.equal(result.payload.cookie, undefined);
  assert.deepEqual(result.payload.nested, { retained: true });
});

test("TikTok Creative session probe does not create a missing tab", async () => {
  let creates = 0;
  const chromeApi = {
    tabs: {
      query: async () => [],
      get: async () => null,
      update: async () => {
        throw new Error("unexpected_update");
      },
      create: async () => {
        creates += 1;
        throw new Error("unexpected_create");
      },
      onRemoved: { addListener: () => undefined },
      onUpdated: {
        addListener: () => undefined,
        removeListener: () => undefined
      }
    },
    windows: { update: async () => undefined },
    scripting: {
      executeScript: async () => {
        throw new Error("unexpected_injection");
      }
    }
  };
  const adapter = new TikTokCreativeSessionAdapter({ chromeApi });

  assert.deepEqual(await adapter.routeSession(), {
    error: "tab_unavailable"
  });
  assert.equal(creates, 0);
});

test("TikTok Creative returns runtime_unavailable for a loading tab without waiting", async () => {
  const tab = {
    id: 40,
    status: "loading",
    url: TIKTOK_CREATIVE_HASHTAG_URL
  };
  let injections = 0;
  const chromeApi = {
    tabs: {
      query: async () => [tab],
      get: async () => tab,
      onRemoved: { addListener: () => undefined }
    },
    scripting: {
      executeScript: async () => {
        injections += 1;
        return [];
      }
    }
  };
  const adapter = new TikTokCreativeSessionAdapter({ chromeApi });

  assert.deepEqual(await adapter.routeSession(), {
    error: "runtime_unavailable"
  });
  assert.equal(injections, 0);
});

test("TikTok Creative request does not create a missing tab", async () => {
  let creates = 0;
  const chromeApi = {
    tabs: {
      query: async () => [],
      get: async () => null,
      update: async () => {
        throw new Error("unexpected_update");
      },
      create: async () => {
        creates += 1;
        throw new Error("unexpected_create");
      },
      onRemoved: { addListener: () => undefined },
      onUpdated: {
        addListener: () => undefined,
        removeListener: () => undefined
      }
    },
    windows: { update: async () => undefined },
    scripting: {
      executeScript: async () => {
        throw new Error("unexpected_injection");
      }
    }
  };
  const requestPolicy = {
    runWithInterval: async (_signal, _interval, operation) =>
      operation(async () => undefined)
  };
  const adapter = new TikTokCreativeSessionAdapter({
    chromeApi,
    requestPolicy
  });

  assert.deepEqual(
    await adapter.routeRequest(
      request(TIKTOK_CREATIVE_HASHTAG_LIST_PATH, LIST_ENTRIES)
    ),
    { error: "tab_unavailable" }
  );
  assert.equal(creates, 0);
});

test("TikTok Creative keeps a trending video request on its exact page", async () => {
  const tab = {
    id: 45,
    windowId: 1,
    active: true,
    status: "complete",
    url: TIKTOK_CREATIVE_HASHTAG_URL
  };
  const injected = [];
  const chromeApi = {
    tabs: {
      query: async () => [tab],
      get: async () => tab,
      onRemoved: { addListener: () => undefined },
      onUpdated: { addListener: () => undefined }
    },
    scripting: {
      executeScript: async (input) => {
        injected.push(input.target.tabId);
        throw new Error("unexpected_injection");
      }
    }
  };
  const requestPolicy = {
    runWithInterval: async (_signal, _interval, operation) =>
      operation(async () => undefined)
  };
  const adapter = new TikTokCreativeSessionAdapter({
    chromeApi,
    requestPolicy
  });

  assert.deepEqual(
    await adapter.routeRequest(trendingVideoRequest()),
    { error: "tab_unavailable" }
  );
  assert.deepEqual(injected, []);
});

test("TikTok Creative reuses a loaded hashtag detail page", async () => {
  const detailURL =
    `${TIKTOK_CREATIVE_ORIGIN}/creative/creativeCenter/trends/hashtag/` +
    "1657263259226117" +
    "?region=US&period=7&from_creative=login" +
    "&aioChannel=SEO&aioScene=AIOEntrance&aioCode=685cefab91818007";
  const tab = {
    id: 44,
    windowId: 1,
    active: true,
    status: "complete",
    url: detailURL
  };
  const updates = [];
  const kinds = [];
  const chromeApi = {
    tabs: {
      query: async () => [tab],
      get: async () => tab,
      update: async (_tabID, changes) => {
        updates.push(changes);
        return { ...tab, ...changes };
      },
      create: async () => {
        throw new Error("unexpected_create");
      },
      onRemoved: { addListener: () => undefined },
      onUpdated: {
        addListener: () => undefined,
        removeListener: () => undefined
      }
    },
    windows: { update: async () => undefined },
    scripting: {
      executeScript: async (input) => {
        kinds.push(input.args[0].kind);
        return [{
          result: {
            ok: true,
            payload: input.args[0].kind === "request"
              ? { hashtagID: "1657263259226117" }
              : {
                  fingerprint: {},
                  logged_in: true,
                  request_ready: true,
                  verification_required: false,
                  probe_required: false
                }
          }
        }];
      }
    }
  };
  const requestPolicy = {
    runWithInterval: async (_signal, _interval, operation) =>
      operation(async () => undefined)
  };
  const adapter = new TikTokCreativeSessionAdapter({
    chromeApi,
    requestPolicy
  });

  assert.equal(validTikTokCreativeHashtagDetailReferer(detailURL), true);
  assert.equal((await adapter.routeSession()).payload.request_ready, true);
  assert.deepEqual(
    await adapter.routeRequest(
      request(TIKTOK_CREATIVE_HASHTAG_DETAIL_PATH, [
        ["hashtagID", "1657263259226117"],
        ["timeRange", "7"],
        ["countryCode", "US"]
      ])
    ),
    { payload: { hashtagID: "1657263259226117" } }
  );
  assert.deepEqual(updates, []);
  assert.deepEqual(kinds, ["session", "request"]);
});

test("TikTok Ads Manager reports an existing advertiser account context", async () => {
  const advertiserID = "7559533685016674320";
  let tab = {
    id: 43,
    windowId: 1,
    active: false,
    status: "complete",
    url: (
      "https://ads.tiktok.com/i18n/nb_creation/create/objectives" +
      `?aadvid=${advertiserID}`
    )
  };
  const updates = [];
  const injectedTabs = [];
  const chromeApi = {
    tabs: {
      query: async () => [tab],
      get: async () => tab,
      update: async (_tabID, changes) => {
        updates.push(changes);
        tab = { ...tab, ...changes };
        return tab;
      },
      create: async () => {
        throw new Error("unexpected_create");
      },
      onRemoved: { addListener: () => undefined },
      onUpdated: {
        addListener: () => undefined,
        removeListener: () => undefined
      }
    },
    windows: { update: async () => undefined },
    scripting: {
      executeScript: async (input) => {
        injectedTabs.push(input.target.tabId);
        return [{
          result: {
            ok: true,
            payload: {
              fingerprint: { cookie_enabled: true },
              logged_in: true,
              request_ready: true,
              verification_required: false,
              profile_required: false,
              probe_required: false
            }
          }
        }];
      }
    }
  };
  const adapter = new TikTokCreativeSessionAdapter({
    chromeApi,
    scope: "ads_manager"
  });

  assert.deepEqual(await adapter.routeSession(), {
    payload: {
      fingerprint: { cookie_enabled: true },
      logged_in: true,
      request_ready: true,
      verification_required: false,
      profile_required: false
    }
  });
  assert.deepEqual(updates, []);
  assert.deepEqual(injectedTabs, [tab.id]);
});

test("TikTok Ads Manager keeps its advertiser tab selection deterministic", async () => {
  const advertiserID = "7559533685016674320";
  const staleTab = {
    id: 43,
    windowId: 1,
    active: true,
    status: "complete",
    url: (
      "https://ads.tiktok.com/i18n/nb_creation/create/objectives" +
      `?aadvid=${advertiserID}`
    )
  };
  const plannerTab = {
    id: 45,
    windowId: 1,
    active: false,
    status: "complete",
    url: `${TIKTOK_ADS_KEYWORD_PLANNER_URL}?aadvid=${advertiserID}`
  };
  let tabs = [staleTab];
  const injectedTabs = [];
  const chromeApi = {
    tabs: {
      query: async () => tabs,
      get: async (tabID) => tabs.find((tab) => tab.id === tabID) || null,
      onRemoved: { addListener: () => undefined },
      onUpdated: {
        addListener: () => undefined,
        removeListener: () => undefined
      }
    },
    scripting: {
      executeScript: async (input) => {
        injectedTabs.push(input.target.tabId);
        return [{
          result: {
            ok: true,
            payload: {
              fingerprint: { cookie_enabled: true },
              logged_in: true,
              request_ready: true,
              verification_required: false,
              profile_required: false,
              probe_required: false
            }
          }
        }];
      }
    }
  };
  const adapter = new TikTokCreativeSessionAdapter({
    chromeApi,
    scope: "ads_manager"
  });

  assert.equal((await adapter.routeSession()).payload.request_ready, true);

  tabs = [staleTab, plannerTab];
  assert.equal((await adapter.routeSession()).payload.request_ready, true);
  assert.deepEqual(injectedTabs, [staleTab.id]);
});

test("TikTok Ads Manager distinguishes its account selection landing page", async () => {
  const tab = {
    id: 44,
    windowId: 1,
    active: true,
    status: "complete",
    url: "https://ads.tiktok.com/i18n/home"
  };
  const chromeApi = {
    tabs: {
      query: async () => [tab],
      get: async () => tab,
      onRemoved: { addListener: () => undefined },
      onUpdated: { addListener: () => undefined }
    },
    scripting: {
      executeScript: async () => {
        throw new Error("unexpected_injection");
      }
    }
  };
  const adapter = new TikTokCreativeSessionAdapter({
    chromeApi,
    scope: "ads_manager"
  });
  const referer =
    `${TIKTOK_ADS_KEYWORD_PLANNER_URL}?aadvid=7012345678901234567`;

  assert.deepEqual(await adapter.routeSession(), {
    error: "advertiser_account_required"
  });
  assert.deepEqual(await adapter.routeRequest({
    path: TIKTOK_ADS_KEYWORD_SUMMARY_PATH,
    entries: [
      [
        "words",
        "[{\"keyword\":\"wireless charger\",\"matchType\":3,\"sourceType\":1}]"
      ],
      ["countryName", "US"]
    ],
    referer,
    request_interval_ms: 0
  }), {
    error: "advertiser_account_required"
  });
});

test("TikTok Creative adapter rejects anonymous preview before request", async () => {
  const tab = {
    id: 18,
    windowId: 1,
    status: "complete",
    url: TIKTOK_CREATIVE_HASHTAG_URL
  };
  const kinds = [];
  const chromeApi = {
    tabs: {
      query: async () => [tab],
      get: async () => tab,
      update: async (_tabID, changes) => ({ ...tab, ...changes }),
      create: async (changes) => ({ ...tab, ...changes }),
      onRemoved: { addListener: () => undefined },
      onUpdated: {
        addListener: () => undefined,
        removeListener: () => undefined
      }
    },
    windows: { update: async () => undefined },
    scripting: {
      executeScript: async (input) => {
        kinds.push(input.args[0].kind);
        return [{
          result: {
            ok: true,
            payload: {
              fingerprint: { cookie_enabled: true },
              logged_in: false,
              request_ready: false,
              verification_required: false,
              probe_required: false
            }
          }
        }];
      }
    }
  };
  const requestPolicy = {
    runWithInterval: async (_signal, _interval, operation) =>
      operation(async () => undefined)
  };
  const adapter = new TikTokCreativeSessionAdapter({
    chromeApi,
    requestPolicy
  });
  const result = await adapter.routeRequest(
    request(TIKTOK_CREATIVE_HASHTAG_LIST_PATH, LIST_ENTRIES)
  );

  assert.deepEqual(result, { error: "not_logged_in" });
  assert.deepEqual(kinds, ["session"]);
});

test("TikTok Creative adapter probes missing router state once per cache", async () => {
  const tab = {
    id: 19,
    windowId: 1,
    status: "complete",
    url: TIKTOK_CREATIVE_HASHTAG_URL
  };
  const kinds = [];
  let platformRequestStarts = 0;
  let now = 1000;
  const chromeApi = {
    tabs: {
      query: async () => [tab],
      get: async () => tab,
      update: async (_tabID, changes) => ({ ...tab, ...changes }),
      create: async (changes) => ({ ...tab, ...changes }),
      onRemoved: { addListener: () => undefined },
      onUpdated: {
        addListener: () => undefined,
        removeListener: () => undefined
      }
    },
    windows: { update: async () => undefined },
    scripting: {
      executeScript: async (input) => {
        const kind = input.args[0].kind;
        kinds.push(kind);
        if (kind === "session") {
          return [{
            result: {
              ok: true,
              payload: {
                fingerprint: { cookie_enabled: true },
                logged_in: false,
                request_ready: false,
                verification_required: false,
                probe_required: true
              }
            }
          }];
        }
        return [{
          result: {
            ok: true,
            payload: {
              fingerprint: { cookie_enabled: true },
              logged_in: true,
              request_ready: true,
              verification_required: false,
              probe_required: false
            }
          }
        }];
      }
    }
  };
  const requestPolicy = {
    runWithInterval: async (_signal, _interval, operation) =>
      operation(async () => {
        platformRequestStarts += 1;
      })
  };
  const adapter = new TikTokCreativeSessionAdapter({
    chromeApi,
    requestPolicy,
    now: () => now
  });

  const first = await adapter.routeSession();
  now += 299999;
  const cached = await adapter.routeSession();

  assert.equal(first.payload.request_ready, true);
  assert.deepEqual(cached, first);
  assert.equal(platformRequestStarts, 1);
  assert.deepEqual(kinds, ["session", "session_probe"]);

  now += 2;
  await adapter.routeSession();
  assert.equal(platformRequestStarts, 2);
  assert.deepEqual(
    kinds,
    ["session", "session_probe", "session", "session_probe"]
  );
});

test("TikTok Creative ready cache is cleared when its tab starts navigating", async () => {
  const tab = {
    id: 191,
    windowId: 1,
    status: "complete",
    url: TIKTOK_CREATIVE_HASHTAG_URL
  };
  let onUpdated = null;
  const kinds = [];
  const chromeApi = {
    tabs: {
      query: async () => [tab],
      get: async () => tab,
      onRemoved: { addListener: () => undefined },
      onUpdated: {
        addListener: (listener) => {
          onUpdated = listener;
        }
      }
    },
    scripting: {
      executeScript: async (input) => {
        kinds.push(input.args[0].kind);
        return [{
          result: {
            ok: true,
            payload: {
              fingerprint: { cookie_enabled: true },
              logged_in: true,
              request_ready: true,
              verification_required: false,
              profile_required: false,
              probe_required: false
            }
          }
        }];
      }
    }
  };
  const requestPolicy = {
    runWithInterval: async (_signal, _interval, operation) =>
      operation(async () => undefined)
  };
  const adapter = new TikTokCreativeSessionAdapter({
    chromeApi,
    requestPolicy
  });
  adapter.registerLifecycle();

  await adapter.routeSession();
  await adapter.routeSession();
  onUpdated(tab.id, { status: "loading" });
  await adapter.routeSession();

  assert.deepEqual(kinds, ["session", "session"]);
});

test("TikTok Creative login loss forces the next session probe", async () => {
  let tab = {
    id: 20,
    windowId: 1,
    status: "complete",
    url: TIKTOK_CREATIVE_HASHTAG_URL
  };
  const kinds = [];
  let platformRequestStarts = 0;
  const sessionPayload = (loggedIn, verification = false) => ({
    fingerprint: { cookie_enabled: true },
    logged_in: loggedIn,
    request_ready: loggedIn && !verification,
    verification_required: verification,
    probe_required: false
  });
  const chromeApi = {
    tabs: {
      query: async () => [tab],
      get: async () => tab,
      update: async (_tabID, changes) => {
        tab = { ...tab, ...changes };
        return tab;
      },
      create: async (changes) => {
        tab = { ...tab, ...changes };
        return tab;
      },
      onRemoved: { addListener: () => undefined },
      onUpdated: {
        addListener: () => undefined,
        removeListener: () => undefined
      }
    },
    windows: { update: async () => undefined },
    scripting: {
      executeScript: async (input) => {
        const kind = input.args[0].kind;
        kinds.push(kind);
        if (kind === "request") {
          return [{ result: { ok: false, error: "not_logged_in" } }];
        }
        if (kind === "session_probe") {
          return [{
            result: {
              ok: true,
              payload: sessionPayload(false)
            }
          }];
        }
        return [{
          result: {
            ok: true,
            payload: sessionPayload(true)
          }
        }];
      }
    }
  };
  const requestPolicy = {
    runWithInterval: async (_signal, _interval, operation) =>
      operation(async () => {
        platformRequestStarts += 1;
      })
  };
  const adapter = new TikTokCreativeSessionAdapter({
    chromeApi,
    requestPolicy
  });

  const requestResult = await adapter.routeRequest(
    request(TIKTOK_CREATIVE_HASHTAG_LIST_PATH, LIST_ENTRIES)
  );
  const session = await adapter.routeSession();
  const cached = await adapter.routeSession();

  assert.deepEqual(requestResult, { error: "not_logged_in" });
  assert.equal(session.payload.logged_in, false);
  assert.equal(session.payload.request_ready, false);
  assert.deepEqual(cached, session);
  assert.equal(platformRequestStarts, 2);
  assert.deepEqual(
    kinds,
    ["session", "request", "session", "session_probe"]
  );
});

test("TikTok Creative verification keeps a forced probe across repeated session checks", async () => {
  let tab = {
    id: 21,
    windowId: 1,
    status: "complete",
    url: TIKTOK_CREATIVE_HASHTAG_URL
  };
  const kinds = [];
  let probeCount = 0;
  const chromeApi = {
    tabs: {
      query: async () => [tab],
      get: async () => tab,
      update: async (_tabID, changes) => {
        tab = { ...tab, ...changes };
        return tab;
      },
      create: async (changes) => {
        tab = { ...tab, ...changes };
        return tab;
      },
      onRemoved: { addListener: () => undefined },
      onUpdated: {
        addListener: () => undefined,
        removeListener: () => undefined
      }
    },
    windows: { update: async () => undefined },
    scripting: {
      executeScript: async (input) => {
        const kind = input.args[0].kind;
        kinds.push(kind);
        const verification =
          kind === "session_probe" && probeCount++ === 0;
        return [{
          result: {
            ok: true,
            payload: {
              fingerprint: { cookie_enabled: true },
              logged_in: !verification,
              request_ready: !verification,
              verification_required: verification,
              probe_required: false
            }
          }
        }];
      }
    }
  };
  const requestPolicy = {
    runWithInterval: async (_signal, _interval, operation) =>
      operation(async () => undefined)
  };
  const adapter = new TikTokCreativeSessionAdapter({
    chromeApi,
    requestPolicy
  });
  adapter.forceSessionProbe = true;

  const verification = await adapter.routeSession();
  const authorized = await adapter.routeSession();

  assert.equal(verification.payload.verification_required, true);
  assert.equal(authorized.payload.request_ready, true);
  assert.equal(adapter.forceSessionProbe, false);
  assert.deepEqual(
    kinds,
    ["session", "session_probe", "session", "session_probe"]
  );
});

test("TikTok Creative session recovers its own risk latch without polluting Top Ads", async () => {
  let now = 1000;
  let hashtagVerified = false;
  const tabs = new Map([
    [51, {
      id: 51,
      windowId: 1,
      active: true,
      status: "complete",
      url: TIKTOK_CREATIVE_HASHTAG_URL
    }],
    [52, {
      id: 52,
      windowId: 1,
      active: false,
      status: "complete",
      url: TIKTOK_CREATIVE_TOP_ADS_URL
    }]
  ]);
  const kinds = [];
  const chromeApi = {
    tabs: {
      query: async () => [...tabs.values()],
      get: async (tabID) => tabs.get(tabID),
      update: async (tabID, changes) => {
        const tab = { ...tabs.get(tabID), ...changes };
        tabs.set(tabID, tab);
        return tab;
      },
      create: async () => {
        throw new Error("unexpected_create");
      },
      onRemoved: { addListener: () => undefined },
      onUpdated: {
        addListener: () => undefined,
        removeListener: () => undefined
      }
    },
    windows: { update: async () => undefined },
    scripting: {
      executeScript: async (input) => {
        const kind = input.args[0].kind;
        const tabID = input.target.tabId;
        kinds.push(`${tabID}:${kind}`);
        if (kind === "request") {
          return [{ result: { ok: true, payload: { items: [] } } }];
        }
        const ready = tabID === 52 || hashtagVerified;
        return [{
          result: {
            ok: true,
            payload: {
              fingerprint: { cookie_enabled: true },
              logged_in: ready,
              request_ready: ready,
              verification_required: !ready,
              profile_required: false,
              probe_required: false
            }
          }
        }];
      }
    }
  };
  const requestPolicy = new SerialRequestPolicy({
    now: () => now,
    delay: async (milliseconds) => {
      now += milliseconds;
    }
  });
  const hashtag = new TikTokCreativeSessionAdapter({
    chromeApi,
    requestPolicy,
    now: () => now,
    scope: "hashtag"
  });
  const topAds = new TikTokCreativeSessionAdapter({
    chromeApi,
    requestPolicy,
    now: () => now,
    scope: "top_ads"
  });

  assert.deepEqual(
    await hashtag.routeRequest(
      request(TIKTOK_CREATIVE_HASHTAG_LIST_PATH, LIST_ENTRIES)
    ),
    { error: "verification_required" }
  );
  assert.equal(hashtag.trippedError, "verification_required");
  assert.equal(topAds.trippedError, "");
  assert.equal(requestPolicy.trippedError, "");

  const topAdsSession = await topAds.routeSession();
  assert.equal(topAdsSession.payload.request_ready, true);

  hashtagVerified = true;
  now += 2501;
  const recovered = await hashtag.routeSession();
  assert.equal(recovered.payload.request_ready, true);
  assert.equal(hashtag.trippedError, "");

  const requestResult = await hashtag.routeRequest(
    request(TIKTOK_CREATIVE_HASHTAG_LIST_PATH, LIST_ENTRIES)
  );
  assert.deepEqual(requestResult, { payload: { items: [] } });
  assert.deepEqual(kinds, [
    "51:session",
    "52:session",
    "51:session",
    "51:request"
  ]);
});

test("TikTok Top Ads session probes the requested Library context", async () => {
  const tabs = new Map([
    [61, {
      id: 61,
      windowId: 1,
      active: true,
      status: "complete",
      url: TIKTOK_CREATIVE_TOP_ADS_V2_URL
    }],
    [62, {
      id: 62,
      windowId: 1,
      active: false,
      status: "complete",
      url: TIKTOK_CREATIVE_TOP_ADS_URL
    }]
  ]);
  const injections = [];
  const chromeApi = {
    tabs: {
      query: async () => [...tabs.values()],
      get: async (tabID) => tabs.get(tabID),
      onRemoved: { addListener: () => undefined },
      onUpdated: { addListener: () => undefined }
    },
    scripting: {
      executeScript: async (input) => {
        injections.push(input.target.tabId);
        return [{
          result: {
            ok: true,
            payload: {
              fingerprint: { tab_marker: input.target.tabId },
              logged_in: true,
              request_ready: true,
              verification_required: false,
              profile_required: false,
              probe_required: false
            }
          }
        }];
      }
    }
  };
  const adapter = new TikTokCreativeSessionAdapter({
    chromeApi,
    scope: "top_ads"
  });

  const session = await adapter.routeSession({
    referer: TIKTOK_CREATIVE_TOP_ADS_URL
  });

  assert.equal(session.payload.fingerprint.tab_marker, 62);
  assert.deepEqual(injections, [62]);
});

test("TikTok Creative cancellation preserves a forced session probe", async () => {
  const tab = {
    id: 22,
    windowId: 1,
    status: "complete",
    url: TIKTOK_CREATIVE_HASHTAG_URL
  };
  const controller = new AbortController();
  const kinds = [];
  let cancelFirstProbe = true;
  const chromeApi = {
    tabs: {
      query: async () => [tab],
      get: async () => tab,
      update: async (_tabID, changes) => ({ ...tab, ...changes }),
      create: async (changes) => ({ ...tab, ...changes }),
      onRemoved: { addListener: () => undefined },
      onUpdated: {
        addListener: () => undefined,
        removeListener: () => undefined
      }
    },
    windows: { update: async () => undefined },
    scripting: {
      executeScript: async (input) => {
        const kind = input.args[0].kind;
        kinds.push(kind);
        if (kind === "session_probe" && cancelFirstProbe) {
          cancelFirstProbe = false;
          controller.abort();
        }
        return [{
          result: {
            ok: true,
            payload: {
              fingerprint: { cookie_enabled: true },
              logged_in: kind !== "session_probe",
              request_ready: kind !== "session_probe",
              verification_required: false,
              probe_required: false
            }
          }
        }];
      }
    }
  };
  const requestPolicy = {
    runWithInterval: async (_signal, _interval, operation) =>
      operation(async () => undefined)
  };
  const adapter = new TikTokCreativeSessionAdapter({
    chromeApi,
    requestPolicy
  });
  adapter.forceSessionProbe = true;

  const cancelled = await adapter.routeSession({
    signal: controller.signal
  });
  const retried = await adapter.routeSession();

  assert.deepEqual(cancelled, { error: "runtime_unavailable" });
  assert.equal(retried.payload.logged_in, false);
  assert.equal(adapter.forceSessionProbe, false);
  assert.deepEqual(
    kinds,
    ["session", "session_probe", "session", "session_probe"]
  );
});

test("TikTok Top Ads requires an existing page matching the request context", async () => {
  let tab = {
    id: 31,
    windowId: 1,
    active: true,
    status: "complete",
    url: TIKTOK_CREATIVE_TOP_ADS_INSIGHT_URL
  };
  const updates = [];
  const chromeApi = {
    tabs: {
      query: async () => [tab],
      get: async () => tab,
      update: async (_tabID, changes) => {
        updates.push(changes);
        tab = {
          ...tab,
          ...changes,
          url: changes.url === TIKTOK_CREATIVE_TOP_ADS_URL
            ? `${TIKTOK_CREATIVE_ORIGIN}${TIKTOK_CREATIVE_SIGNUP_PATH}` +
              "?redirect=top_ads"
            : changes.url || tab.url,
          status: "complete"
        };
        return tab;
      },
      create: async () => {
        throw new Error("unexpected_create");
      },
      onRemoved: { addListener: () => undefined },
      onUpdated: {
        addListener: () => undefined,
        removeListener: () => undefined
      }
    },
    windows: { update: async () => undefined },
    scripting: {
      executeScript: async () => {
        throw new Error("unexpected_injection");
      }
    }
  };
  const requestPolicy = {
    runWithInterval: async (_signal, _interval, operation) =>
      operation(async () => undefined)
  };
  const adapter = new TikTokCreativeSessionAdapter({
    chromeApi,
    requestPolicy,
    scope: "top_ads"
  });

  const result = await adapter.routeRequest(
    topAdsRequest(
      TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH,
      TOP_ADS_SEARCH_ENTRIES
    )
  );

  assert.deepEqual(result, { error: "tab_unavailable" });
  assert.deepEqual(updates, []);
});

test("TikTok Top Ads keeps login, verification, and profile states distinct", async () => {
  const states = [
    {
      expected: "not_logged_in",
      payload: {
        logged_in: false,
        request_ready: false,
        verification_required: false,
        profile_required: false
      }
    },
    {
      expected: "verification_required",
      payload: {
        logged_in: false,
        request_ready: false,
        verification_required: true,
        profile_required: false
      }
    },
    {
      expected: "profile_required",
      payload: {
        logged_in: true,
        request_ready: false,
        verification_required: false,
        profile_required: true
      }
    }
  ];
  for (const fixture of states) {
    const tab = {
      id: 33,
      windowId: 1,
      active: true,
      status: "complete",
      url: TIKTOK_CREATIVE_TOP_ADS_URL
    };
    const chromeApi = {
      tabs: {
        query: async () => [tab],
        get: async () => tab,
        update: async (_tabID, changes) => ({ ...tab, ...changes }),
        create: async (changes) => ({ ...tab, ...changes }),
        onRemoved: { addListener: () => undefined },
        onUpdated: {
          addListener: () => undefined,
          removeListener: () => undefined
        }
      },
      windows: { update: async () => undefined },
      scripting: {
        executeScript: async () => [{
          result: {
            ok: true,
            payload: {
              fingerprint: { cookie_enabled: true },
              probe_required: false,
              ...fixture.payload
            }
          }
        }]
      }
    };
    const requestPolicy = {
      runWithInterval: async (_signal, _interval, operation) =>
        operation(async () => undefined)
    };
    const adapter = new TikTokCreativeSessionAdapter({
      chromeApi,
      requestPolicy,
      scope: "top_ads"
    });

    assert.deepEqual(
      await adapter.routeRequest(
        topAdsRequest(
          TIKTOK_CREATIVE_TOP_ADS_SEARCH_PATH,
          TOP_ADS_SEARCH_ENTRIES
        )
      ),
      { error: fixture.expected }
    );
  }
});

test("TikTok Creative scopes share policy but keep session caches isolated", async () => {
  const tabs = new Map([
    [41, {
      id: 41,
      windowId: 1,
      active: true,
      status: "complete",
      url: TIKTOK_CREATIVE_HASHTAG_URL
    }],
    [42, {
      id: 42,
      windowId: 1,
      active: false,
      status: "complete",
      url: TIKTOK_CREATIVE_TOP_ADS_URL
    }]
  ]);
  const injections = [];
  const chromeApi = {
    tabs: {
      query: async () => [...tabs.values()],
      get: async (tabID) => tabs.get(tabID),
      update: async (tabID, changes) => {
        const tab = { ...tabs.get(tabID), ...changes };
        tabs.set(tabID, tab);
        return tab;
      },
      create: async () => {
        throw new Error("unexpected_create");
      },
      onRemoved: { addListener: () => undefined },
      onUpdated: {
        addListener: () => undefined,
        removeListener: () => undefined
      }
    },
    windows: { update: async () => undefined },
    scripting: {
      executeScript: async (input) => {
        injections.push(input);
        return [{
          result: {
            ok: true,
            payload: {
              fingerprint: {
                cookie_enabled: true,
                tab_marker: input.target.tabId
              },
              logged_in: true,
              request_ready: true,
              verification_required: false,
              profile_required: false,
              probe_required: false
            }
          }
        }];
      }
    }
  };
  const sharedPolicy = {
    runWithInterval: async (_signal, _interval, operation) =>
      operation(async () => undefined)
  };
  const hashtag = new TikTokCreativeSessionAdapter({
    chromeApi,
    requestPolicy: sharedPolicy,
    scope: "hashtag"
  });
  const topAds = new TikTokCreativeSessionAdapter({
    chromeApi,
    requestPolicy: sharedPolicy,
    scope: "top_ads"
  });

  const hashtagFirst = await hashtag.routeSession();
  const topAdsFirst = await topAds.routeSession();
  const hashtagCached = await hashtag.routeSession();
  const topAdsCached = await topAds.routeSession();

  assert.equal(hashtag.requestPolicy, topAds.requestPolicy);
  assert.equal(hashtagFirst.payload.fingerprint.tab_marker, 41);
  assert.equal(topAdsFirst.payload.fingerprint.tab_marker, 42);
  assert.deepEqual(hashtagCached, hashtagFirst);
  assert.deepEqual(topAdsCached, topAdsFirst);
  assert.notEqual(hashtag.sessionCache, topAds.sessionCache);
  assert.deepEqual(
    injections.map((input) => input.target.tabId),
    [41, 42]
  );
});

test("TikTok Top Ads cache is invalidated when one tab enters signup", async () => {
  let tab = {
    id: 43,
    windowId: 1,
    active: true,
    status: "complete",
    url: TIKTOK_CREATIVE_TOP_ADS_URL
  };
  const kinds = [];
  const chromeApi = {
    tabs: {
      query: async () => [tab],
      get: async () => tab,
      update: async (_tabID, changes) => {
        tab = { ...tab, ...changes };
        return tab;
      },
      create: async () => {
        throw new Error("unexpected_create");
      },
      onRemoved: { addListener: () => undefined },
      onUpdated: {
        addListener: () => undefined,
        removeListener: () => undefined
      }
    },
    windows: { update: async () => undefined },
    scripting: {
      executeScript: async (input) => {
        kinds.push(input.args[0].kind);
        const profileRequired =
          tab.url.startsWith(
            `${TIKTOK_CREATIVE_ORIGIN}${TIKTOK_CREATIVE_SIGNUP_PATH}`
          );
        return [{
          result: {
            ok: true,
            payload: {
              fingerprint: { cookie_enabled: true },
              logged_in: true,
              request_ready: !profileRequired,
              verification_required: false,
              profile_required: profileRequired,
              probe_required: false
            }
          }
        }];
      }
    }
  };
  const requestPolicy = {
    runWithInterval: async (_signal, _interval, operation) =>
      operation(async () => undefined)
  };
  const adapter = new TikTokCreativeSessionAdapter({
    chromeApi,
    requestPolicy,
    scope: "top_ads"
  });

  const ready = await adapter.routeSession();
  tab = {
    ...tab,
    url: `${TIKTOK_CREATIVE_ORIGIN}${TIKTOK_CREATIVE_SIGNUP_PATH}`
  };
  const profile = await adapter.routeSession();

  assert.equal(ready.payload.request_ready, true);
  assert.equal(profile.payload.profile_required, true);
  assert.deepEqual(kinds, ["session", "session"]);
});

test("service worker registers TikTok commercial scopes with one request policy", () => {
  const source = readFileSync(
    new URL("./service_worker_v2.js", import.meta.url),
    "utf8"
  );
  assert.match(
    source,
    /const tiktokCreativeRequestPolicy = new SerialRequestPolicy\(\);/
  );
  assert.match(source, /scope:\s*"hashtag"/);
  assert.match(source, /scope:\s*"top_ads"/);
  assert.match(source, /scope:\s*"studio"/);
  assert.match(source, /scope:\s*"one"/);
  assert.match(source, /scope:\s*"ads_manager"/);
  assert.match(source, /tiktok_creative_topads:\s*\{/);
  assert.match(source, /tiktok_creative_studio:\s*\{/);
  assert.match(source, /tiktok_one:\s*\{/);
  assert.match(source, /tiktok_ads_manager:\s*\{/);
  assert.equal(
    (source.match(/requestPolicy:\s*tiktokCreativeRequestPolicy/g) || [])
      .length,
    5
  );
});
