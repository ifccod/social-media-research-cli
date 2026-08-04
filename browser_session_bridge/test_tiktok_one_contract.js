import assert from "node:assert/strict";
import test from "node:test";

import {
  TIKTOK_ONE_CREATOR_FILTERS_PATH,
  TIKTOK_ONE_CREATOR_SEARCH_PATH,
  TIKTOK_ONE_CREATOR_SUGGEST_PATH,
  TIKTOK_ONE_CREATOR_URL,
  isTikTokCreativeScopeTabUrl,
  validTikTokCreativeEntries,
  validTikTokCreativeRequest,
  validTikTokOneCreatorReferer
} from "./adapters/tiktok_creative/contract.js";
import {
  invokeTikTokCreativePageRuntime
} from "./adapters/tiktok_creative/page_runtime.js";

function oneRequest(path, entries) {
  return {
    path,
    entries,
    referer: TIKTOK_ONE_CREATOR_URL,
    request_interval_ms: 3000
  };
}

async function withOnePage(fetchImpl, callback) {
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
  class FixtureElement {
    getBoundingClientRect() {
      return { width: 320, height: 180 };
    }
  }
  const values = {
    window: {
      fetch: fetchImpl,
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
    },
    document: {
      cookie: "csrftoken=one-fixture-csrf",
      getElementById: () => null,
      querySelectorAll: () => []
    },
    Element: FixtureElement,
    location: new URL(TIKTOK_ONE_CREATOR_URL),
    navigator: {
      userAgent: "fixture",
      language: "zh-CN",
      languages: ["zh-CN"],
      platform: "MacIntel",
      vendor: "Google Inc.",
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
  try {
    for (const [name, value] of Object.entries(values)) {
      Object.defineProperty(globalThis, name, {
        configurable: true,
        writable: true,
        value
      });
    }
    return await callback();
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

function creatorFixture(id = "7074051131063664645") {
  return {
    aioCreatorID: id,
    ttUID: "6841953820793881606",
    creatorTTInfo: {
      avatarURL: "https://p16.example.test/avatar.jpeg",
      bio: "coffee creator",
      handleName: "coffee_creator",
      nickName: "Coffee Creator",
      storeRegion: "BR",
      isBannedInTT: false,
      riskInfo: {
        disciplineInfoList: [],
        riskEventInfoList: []
      }
    },
    statisticData: {
      overallPerformance: {
        followerCount: 1421277,
        medianViews: 30869,
        engagementRate: 0.236
      }
    },
    creatorValueStat: {
      commercialScore: 60,
      collaborationScore: 76,
      broadcastingScore: 100,
      comprehensiveScore: 80.8
    },
    esData: {
      price: {
        currency: "USD",
        recommendRate100k: "273357641",
        startingRate100k: "10000000",
        storeRegionCurrency: "BRL",
        storeRegionStartingRate100k: "55560000"
      }
    },
    contentLabels: [
      { labelID: "11007004", labelLevel: 2, labelType: 2 }
    ],
    recentItems: [
      {
        itemID: "7657034880374656263",
        title: "coffee",
        createTime: "1782792375",
        views: "193821",
        heart: 46215,
        comment: 107,
        share: 5713,
        coverURL: "https://p16.example.test/cover.jpeg",
        videoURL: "https://v77.example.test/video.mp4"
      }
    ],
    riskInfo: {
      disciplineInfoList: [],
      riskEventInfoList: []
    }
  };
}

test("TikTok One 合同固定达人广场页面、页长和筛选参数", () => {
  assert.equal(validTikTokOneCreatorReferer(TIKTOK_ONE_CREATOR_URL), true);
  assert.equal(
    validTikTokOneCreatorReferer(
      `${TIKTOK_ONE_CREATOR_URL}&from_creative=login`
    ),
    true
  );
  assert.equal(
    validTikTokOneCreatorReferer(
      `${TIKTOK_ONE_CREATOR_URL}&from_creative=unknown`
    ),
    false
  );
  assert.equal(isTikTokCreativeScopeTabUrl(TIKTOK_ONE_CREATOR_URL, "one"), true);
  assert.equal(
    validTikTokOneCreatorReferer(
      "https://ads.tiktok.com/creative/creator/explore?region=row"
    ),
    false
  );
  const entries = [
    ["page", "1"],
    ["limit", "24"],
    ["query", "coffee"],
    ["sortField", "5"],
    ["sortType", "2"],
    ["countryCodeList", "US,BR"],
    ["languageList", "en,pt"],
    ["minFansCnt", "10000"],
    ["maxFansCnt", "1000000"],
    ["minEngagementRate", "0.01"],
    ["maxEngagementRate", "0.5"]
  ];
  assert.equal(
    validTikTokCreativeEntries(TIKTOK_ONE_CREATOR_SEARCH_PATH, entries),
    true
  );
  assert.equal(
    validTikTokCreativeRequest(
      oneRequest(TIKTOK_ONE_CREATOR_SEARCH_PATH, entries)
    ),
    true
  );
  assert.equal(
    validTikTokCreativeEntries(
      TIKTOK_ONE_CREATOR_SEARCH_PATH,
      entries.map((entry) =>
        entry[0] === "limit" ? ["limit", "10"] : entry
      )
    ),
    false
  );
});

test("TikTok One 筛选和联想请求使用 GET 且不携带 Studio 来源头", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    const body = String(url).includes("QueryPartnerSearchSuggestWords")
      ? {
        baseResp: { StatusCode: 0, StatusMessage: "" },
        suggestedWords: [
          { suggestedWord: "coffeetiktok" },
          { suggestedWord: "coffeeaddict" }
        ]
      }
      : {
        baseResp: { StatusCode: 0, StatusMessage: "" },
        allDataVDCRegions: [1, 2, 3],
        defaultDataVDCRegion: 1,
        languages: ["en", "pt"],
        personaList: [1, 2]
      };
    return { ok: true, status: 200, json: async () => body };
  };
  const filters = await withOnePage(fetchImpl, () =>
    invokeTikTokCreativePageRuntime({
      kind: "request",
      path: TIKTOK_ONE_CREATOR_FILTERS_PATH,
      entries: [],
      session_verified: true
    })
  );
  const suggestions = await withOnePage(fetchImpl, () =>
    invokeTikTokCreativePageRuntime({
      kind: "request",
      path: TIKTOK_ONE_CREATOR_SUGGEST_PATH,
      entries: [["query", "coffee"]],
      session_verified: true
    })
  );
  assert.equal(filters.ok, true, JSON.stringify({ filters, calls }));
  assert.deepEqual(suggestions.payload.suggestedWords, [
    "coffeetiktok",
    "coffeeaddict"
  ]);
  assert.equal(calls[0].options.method, "GET");
  assert.equal(calls[1].options.method, "GET");
  assert.equal(calls[0].options.credentials, "include");
  assert.equal(calls[0].options.headers["agw-js-conv"], "str");
  assert.equal(calls[0].options.headers["x-csrftoken"], "one-fixture-csrf");
  assert.equal(calls[0].options.headers["x-creative-source"], undefined);
  assert.equal(JSON.stringify(filters).includes("one-fixture-csrf"), false);
});

test("TikTok One 达人搜索使用固定 POST 合同并返回商业字段", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      status: 200,
      json: async () => ({
        baseResp: { StatusCode: 0, StatusMessage: "" },
        creators: [creatorFixture()],
        pagination: {
          page: 1,
          limit: 24,
          totalCount: 3086,
          hasMore: true
        },
        hasMoreMatchCreators: true,
        hasMoreRecommendedCreators: false
      })
    };
  };
  const result = await withOnePage(fetchImpl, () =>
    invokeTikTokCreativePageRuntime({
      kind: "request",
      path: TIKTOK_ONE_CREATOR_SEARCH_PATH,
      entries: [
        ["page", "1"],
        ["limit", "24"],
        ["query", "coffee"],
        ["sortField", "5"],
        ["sortType", "2"]
      ],
      session_verified: true
    })
  );
  assert.equal(result.ok, true, JSON.stringify({ result, calls }));
  assert.equal(result.payload.creators[0].handle, "coffee_creator");
  assert.equal(result.payload.creators[0].metrics.followers, 1421277);
  assert.equal(
    result.payload.creators[0].rates.regional_starting.amount_100k,
    "55560000"
  );
  assert.equal(result.payload.creators[0].recent_videos[0].views, "193821");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    page: 1,
    limit: 24,
    query: "coffee",
    filterParam: {
      contentLabels: [],
      potentialIndustryLabels: [],
      creatorPriceFilter: { currency: "USD" },
      languages: [],
      audienceMaxDistriCountry: "",
      audienceMaxDistriAge: "",
      storeCountryCodeList: [],
      subRegions: [],
      audienceMaxDistrPersonaList: [],
      creatorValueList: [],
      recommendationTypeList: []
    },
    sortParam: { sortType: 2, sortField: 5 },
    dataVDCRegion: 1,
    searchType: 6
  });
});
