import assert from "node:assert/strict";
import test from "node:test";

import { TwitterSessionAdapter } from "./adapters/twitter/adapter.js";
import {
  TWITTER_FOLLOWERS_PATH,
  TWITTER_FOLLOWING_PATH,
  TWITTER_HOME_FEED_PATH,
  TWITTER_HOME_URL,
  TWITTER_SEARCH_POSTS_PATH,
  TWITTER_USER_PATH,
  TWITTER_USER_TWEETS_PATH,
  sameTwitterRequestContext,
  validTwitterRequest
} from "./adapters/twitter/contract.js";
import {
  invokeTwitterPageRuntime
} from "./adapters/twitter/page_runtime.js";
import { sanitizeBrowserPayload } from "./core/sanitize.js";

const FIXTURE_BEARER_TOKEN =
  "AAAAAAAAAAAAAAAAAAAA_FIXTURE_BEARER_TOKEN_" +
  "1234567890_ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const FIXTURE_TRANSACTION_ID =
  "FIXTURE_TRANSACTION_ID_1234567890_ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const FEATURES_TABLE_KEY = Symbol.for(
  "browser-session-bridge.twitter.features.v1"
);
const USER_GRAPHQL_FEATURES = {
  hidden_profile_likes_enabled: false
};
const USER_FEATURES_TABLE = {
  UserByScreenName: USER_GRAPHQL_FEATURES,
  UserByRestId: USER_GRAPHQL_FEATURES,
  UserTweets: USER_GRAPHQL_FEATURES,
  Followers: USER_GRAPHQL_FEATURES,
  Following: USER_GRAPHQL_FEATURES
};

function homeRequest(overrides = {}) {
  return {
    path: TWITTER_HOME_FEED_PATH,
    entries: [["count", "20"]],
    referer: "https://x.com/home",
    request_interval_ms: 3000,
    ...overrides
  };
}

function searchRequest(overrides = {}) {
  return {
    path: TWITTER_SEARCH_POSTS_PATH,
    entries: [
      ["query", "social listening"],
      ["count", "20"],
      ["product", "Latest"]
    ],
    referer:
      "https://x.com/search?q=social+listening&src=typed_query&f=live",
    request_interval_ms: 3000,
    ...overrides
  };
}

function userRequest(overrides = {}) {
  return {
    path: TWITTER_USER_PATH,
    entries: [["screen_name", "researcher"]],
    referer: "https://x.com/home",
    request_interval_ms: 3000,
    ...overrides
  };
}

function userListRequest(path, overrides = {}) {
  return {
    path,
    entries: [["user_id", "12345"], ["count", "20"]],
    referer: "https://x.com/home",
    request_interval_ms: 3000,
    ...overrides
  };
}

async function runtimeFixture(input, {
  href,
  resources = [],
  scripts = [],
  preloads = [],
  cachedBearer = FIXTURE_BEARER_TOKEN,
  cachedTransactionModuleId = 991160,
  transactionCalls = [],
  webpackModules = {},
  webpackPublicPath = "",
  webpackChunkFile = null,
  featuresByOperation = USER_FEATURES_TABLE,
  fetchImpl = async () => {
    throw new Error("unexpected_fetch");
  },
  cookie = "ct0=LOCAL_CSRF"
}) {
  const operationCacheKey = Symbol.for(
    "browser-session-bridge.twitter.operations.v2"
  );
  const operationCacheDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    operationCacheKey
  );
  const featuresDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    FEATURES_TABLE_KEY
  );
  delete globalThis[operationCacheKey];
  delete globalThis[FEATURES_TABLE_KEY];
  const names = [
    "window",
    "document",
    "location",
    "navigator",
    "performance",
    "fetch",
    "webpackChunk_twitter_responsive_web"
  ];
  const previous = new Map(names.map((name) => [
    name,
    Object.getOwnPropertyDescriptor(globalThis, name)
  ]));
  const locationValue = new URL(href);
  const webpackChunks = [];
  webpackChunks.push = (chunk) => {
    const runtime = (moduleId) => ({
      kc: async (host, path, method) => {
        transactionCalls.push({ moduleId, host, path, method });
        return FIXTURE_TRANSACTION_ID;
      }
    });
    runtime.m = webpackModules;
    if (webpackPublicPath) {
      runtime.p = webpackPublicPath;
    }
    if (typeof webpackChunkFile === "function") {
      runtime.u = webpackChunkFile;
    }
    chunk[2](runtime);
    return 1;
  };
  const values = {
    window: {
      getComputedStyle: () => ({
        display: "block",
        visibility: "visible",
        opacity: "1"
      })
    },
    document: {
      cookie,
      scripts: scripts.map((src) => ({ src })),
      querySelector: () => null,
      querySelectorAll: (selector) => {
        if (!String(selector || "").includes("preload")) {
          return [];
        }
        return preloads.map((src) => ({
          href: src,
          getAttribute: (name) => (name === "href" ? src : null)
        }));
      }
    },
    location: locationValue,
    navigator: {
      language: "en-US",
      cookieEnabled: true
    },
    performance: {
      getEntriesByType: () => resources.map((name) => ({ name }))
    },
    fetch: fetchImpl,
    webpackChunk_twitter_responsive_web: webpackChunks
  };
  for (const [name, value] of Object.entries(values)) {
    Object.defineProperty(globalThis, name, {
      configurable: true,
      writable: true,
      value
    });
  }
  if (cachedBearer || cachedTransactionModuleId) {
    const cache = {};
    if (cachedBearer) {
      cache.bearerToken = cachedBearer;
    }
    if (cachedTransactionModuleId) {
      cache.transactionModuleId = cachedTransactionModuleId;
    }
    Object.defineProperty(globalThis, operationCacheKey, {
      configurable: true,
      value: cache
    });
  }
  if (featuresByOperation) {
    Object.defineProperty(globalThis, FEATURES_TABLE_KEY, {
      configurable: true,
      value: featuresByOperation
    });
  }
  try {
    return await invokeTwitterPageRuntime(input);
  } finally {
    delete globalThis[operationCacheKey];
    delete globalThis[FEATURES_TABLE_KEY];
    if (operationCacheDescriptor) {
      Object.defineProperty(
        globalThis,
        operationCacheKey,
        operationCacheDescriptor
      );
    }
    if (featuresDescriptor) {
      Object.defineProperty(
        globalThis,
        FEATURES_TABLE_KEY,
        featuresDescriptor
      );
    }
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

function upstream(url, data = { timeline: {} }) {
  return {
    ok: true,
    status: 200,
    url,
    headers: {
      get: (name) => ({
        "x-rate-limit-limit": "50",
        "x-rate-limit-remaining": "49",
        "x-rate-limit-reset": "1785259000"
      })[name] || null
    },
    json: async () => ({ data })
  };
}

function scriptUpstream(source, contentLength = null) {
  return {
    ok: true,
    status: 200,
    headers: {
      get: (name) =>
        name === "content-length" && contentLength !== null
          ? String(contentLength)
          : null
    },
    text: async () => source
  };
}

function failedUpstream(url, status) {
  return {
    ok: false,
    status,
    url,
    headers: { get: () => null }
  };
}

test("Twitter 合同只接受白名单推荐流和搜索请求", () => {
  assert.equal(validTwitterRequest(homeRequest(), "home"), true);
  assert.equal(validTwitterRequest(searchRequest(), "search"), true);
  assert.equal(
    validTwitterRequest(
      searchRequest({ entries: [["query", "social listening"], ["count", "0"], ["product", "Top"]] }),
      "search"
    ),
    false
  );
  assert.equal(
    validTwitterRequest(
      searchRequest({ referer: "https://example.com/search?q=social+listening" }),
      "search"
    ),
    false
  );
  assert.equal(
    validTwitterRequest(
      searchRequest({ entries: [...searchRequest().entries, ["token", "secret"]] }),
      "search"
    ),
    false
  );
});

test("Twitter 请求上下文按推荐流和搜索词区分", () => {
  assert.equal(
    sameTwitterRequestContext(
      "https://www.x.com/home",
      "https://x.com/home",
      "home"
    ),
    true
  );
  assert.equal(
    sameTwitterRequestContext(
      "https://x.com/search?q=one&src=typed_query",
      "https://x.com/search?q=two&src=typed_query",
      "search"
    ),
    false
  );
});

test("共享清洗器保留 X 时间线深层作者并移除凭据字段", () => {
  const author = {
    rest_id: "1325102346792218629",
    core: { name: "研究者", screen_name: "researcher" },
    relationship_counts: { followers: 3053, following: 1685 },
    authorization: "Bearer SECRET"
  };
  let nested = { user_results: { result: author } };
  for (let depth = 0; depth < 16; depth += 1) {
    nested = { value: nested };
  }
  const sanitized = sanitizeBrowserPayload(nested);
  let current = sanitized;
  for (let depth = 0; depth < 16; depth += 1) {
    current = current.value;
  }
  assert.equal(
    current.user_results.result.core.screen_name,
    "researcher"
  );
  assert.equal(
    current.user_results.result.relationship_counts.followers,
    3053
  );
  assert.equal(
    "authorization" in current.user_results.result,
    false
  );
});

test("页面运行时先探测登录态且不发送请求", async () => {
  const result = await runtimeFixture(
    { kind: "session" },
    { href: "https://x.com/home" }
  );
  assert.equal(result.ok, true);
  assert.equal(result.payload.logged_in, true);
  assert.equal(result.payload.fingerprint.pathname, "/home");
  assert.equal("ct0" in result.payload.fingerprint, false);
});

test("页面运行时复用动态 SearchTimeline 操作 ID", async () => {
  const calls = [];
  const operation =
    "https://x.com/i/api/graphql/BGd0T_j7oVwlW5U79tO_0A/" +
    "SearchTimeline?features=%7B%22fixture%22%3Atrue%7D";
  const result = await runtimeFixture(
    {
      kind: "request",
      session_verified: true,
      path: TWITTER_SEARCH_POSTS_PATH,
      entries: [
        ["query", "social listening"],
        ["count", "10"],
        ["product", "Latest"],
        ["cursor", "NEXT"]
      ]
    },
    {
      href:
        "https://x.com/search?q=social+listening&src=typed_query&f=live",
      resources: [operation],
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return upstream(url, { search_by_raw_query: {} });
      }
    }
  );
  assert.equal(result.ok, true);
  assert.equal(result.payload.operation, "SearchTimeline");
  assert.equal(calls.length, 1);
  const target = new URL(calls[0].url);
  const variables = JSON.parse(target.searchParams.get("variables"));
  assert.equal(variables.rawQuery, "social listening");
  assert.equal(variables.product, "Latest");
  assert.equal(variables.cursor, "NEXT");
  assert.deepEqual(
    JSON.parse(target.searchParams.get("features")),
    { fixture: true }
  );
  assert.equal(calls[0].options.credentials, "include");
  assert.equal(
    calls[0].options.headers["x-csrf-token"],
    "LOCAL_CSRF"
  );
  assert.equal(
    calls[0].options.headers["x-client-transaction-id"],
    FIXTURE_TRANSACTION_ID
  );
});

test("页面运行时用当前 HomeTimeline 操作 ID 发起 POST", async () => {
  const calls = [];
  const operation =
    "https://x.com/i/api/graphql/3b9_7tltt0hJRef-xm_3sw/HomeTimeline";
  const result = await runtimeFixture(
    {
      kind: "request",
      session_verified: true,
      path: TWITTER_HOME_FEED_PATH,
      entries: [["count", "20"]]
    },
    {
      href: "https://x.com/home",
      resources: [operation],
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return upstream(url, { home: {} });
      }
    }
  );
  assert.equal(result.ok, true);
  assert.equal(calls[0].options.method, "POST");
  const body = JSON.parse(calls[0].options.body);
  assert.equal(body.queryId, "3b9_7tltt0hJRef-xm_3sw");
  assert.equal(body.variables.count, 20);
  assert.equal(body.variables.requestContext, "launch");
});

test("页面运行时从 webpack 已加载模块发现 HomeTimeline 操作 ID", async () => {
  const calls = [];
  const webpackModules = {
    436870(module) {
      module.exports = {
        queryId: "WEBPACK_HOME_123",
        operationName: "HomeTimeline"
      };
    }
  };
  const result = await runtimeFixture(
    {
      kind: "request",
      session_verified: true,
      path: TWITTER_HOME_FEED_PATH,
      entries: [["count", "5"]]
    },
    {
      href: "https://x.com/home",
      webpackModules,
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return upstream(url, { home: {} });
      }
    }
  );
  assert.equal(result.ok, true);
  assert.equal(calls.length, 1);
  assert.equal(
    new URL(calls[0].url).pathname,
    "/i/api/graphql/WEBPACK_HOME_123/HomeTimeline"
  );
  assert.equal(calls[0].options.method, "POST");
});

test("页面运行时从已加载脚本发现 SearchTimeline 操作 ID", async () => {
  const calls = [];
  const transactionCalls = [];
  const mainScript =
    "https://abs.twimg.com/responsive-web/client-web/main.fixture.js";
  const dynamicBearer =
    "AAAAAAAAAAAAAAAAAAAA_DYNAMIC_BEARER_TOKEN_" +
    "1234567890_ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  const source =
    `const auth=\"Bearer ${dynamicBearer}\";` +
    "},765432(e,t,r){\"use strict\";let i;" +
    "r.d(t,{Ay:()=>l,_E:()=>s,kc:()=>a});" +
    "const flag=\"rweb_client_transaction_id_enabled\";" +
    "100(e){e.exports={queryId:\"SCRIPT_QUERY_123\"," +
    "operationName:\"SearchTimeline\",operationType:\"query\"}}";
  const result = await runtimeFixture(
    {
      kind: "request",
      session_verified: true,
      path: TWITTER_SEARCH_POSTS_PATH,
      entries: [
        ["query", "social listening"],
        ["count", "5"],
        ["product", "Latest"]
      ]
    },
    {
      href:
        "https://x.com/search?q=social+listening&src=typed_query&f=live",
      cachedBearer: "",
      cachedTransactionModuleId: null,
      transactionCalls,
      scripts: [
        "https://example.com/ignored.js",
        mainScript
      ],
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        if (url === mainScript) {
          return scriptUpstream(source);
        }
        return upstream(url, { search_by_raw_query: {} });
      }
    }
  );
  assert.equal(result.ok, true);
  assert.equal(result.payload.operation, "SearchTimeline");
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, mainScript);
  assert.equal(calls[0].options.credentials, "omit");
  assert.equal(
    calls[1].options.headers.authorization,
    `Bearer ${dynamicBearer}`
  );
  assert.equal(
    calls[1].options.headers["content-type"],
    "application/json"
  );
  assert.deepEqual(transactionCalls, [{
    moduleId: 765432,
    host: "x.com",
    path: "/i/api/graphql/SCRIPT_QUERY_123/SearchTimeline",
    method: "GET"
  }]);
  assert.equal(
    new URL(calls[1].url).pathname,
    "/i/api/graphql/SCRIPT_QUERY_123/SearchTimeline"
  );
  assert.equal(JSON.stringify(result).includes(source), false);
  assert.equal(JSON.stringify(result).includes(dynamicBearer), false);
  assert.equal(JSON.stringify(result).includes("LOCAL_CSRF"), false);
});

test("页面运行时不把 operationName 后相邻模块的 queryId 误判为当前操作", async () => {
  const decoy =
    "operationName:\"SearchTimeline\",operationType:\"enum\"}," +
    "200(e){e.exports={queryId:\"WRONG_QUERY_123\"," +
    "operationName:\"OtherTimeline\"}}";
  const valid =
    "300(e){e.exports={queryId:\"RIGHT_QUERY_123\"," +
    "operationName:\"SearchTimeline\"}}";
  const calls = [];
  const result = await runtimeFixture(
    {
      kind: "request",
      session_verified: true,
      path: TWITTER_SEARCH_POSTS_PATH,
      entries: [
        ["query", "social listening"],
        ["count", "5"],
        ["product", "Latest"]
      ]
    },
    {
      href:
        "https://x.com/search?q=social+listening&src=typed_query&f=live",
      scripts: [
        "https://abs.twimg.com/responsive-web/client-web/bundle.SearchTimeline.js",
        "https://abs.twimg.com/responsive-web/client-web/main.fixture.js"
      ],
      fetchImpl: async (url) => {
        calls.push(url);
        if (url.endsWith("bundle.SearchTimeline.js")) {
          return scriptUpstream(decoy);
        }
        if (url.endsWith("main.fixture.js")) {
          return scriptUpstream(valid);
        }
        return upstream(url, { search_by_raw_query: {} });
      }
    }
  );
  assert.equal(result.ok, true);
  assert.deepEqual(
    calls.slice(0, 2).map((url) => new URL(url).pathname),
    [
      "/responsive-web/client-web/bundle.SearchTimeline.js",
      "/responsive-web/client-web/main.fixture.js"
    ]
  );
  assert.equal(
    new URL(calls.at(-1)).pathname,
    "/i/api/graphql/RIGHT_QUERY_123/SearchTimeline"
  );
});

test("页面运行时把失效 operation ID 分类为可刷新运行时", async () => {
  const operation =
    "https://x.com/i/api/graphql/STALE_QUERY_123/SearchTimeline";
  const result = await runtimeFixture(
    {
      kind: "request",
      session_verified: true,
      path: TWITTER_SEARCH_POSTS_PATH,
      entries: [
        ["query", "social listening"],
        ["count", "5"],
        ["product", "Latest"]
      ]
    },
    {
      href:
        "https://x.com/search?q=social+listening&src=typed_query&f=live",
      resources: [operation],
      fetchImpl: async (url) => failedUpstream(url, 404)
    }
  );
  assert.deepEqual(result, {
    ok: false,
    error: "runtime_unavailable"
  });
});

test("页面运行时跳过超限脚本并发现 HomeTimeline 操作 ID", async () => {
  const calls = [];
  const oversized =
    "https://abs.twimg.com/responsive-web/client-web/bundle.HomeTimeline.big.js";
  const homeScript =
    "https://abs.twimg.com/responsive-web/client-web/main.fixture.js";
  const result = await runtimeFixture(
    {
      kind: "request",
      session_verified: true,
      path: TWITTER_HOME_FEED_PATH,
      entries: [["count", "5"]]
    },
    {
      href: "https://x.com/home",
      scripts: [oversized, homeScript],
      fetchImpl: async (url) => {
        calls.push(url);
        if (url === oversized) {
          return scriptUpstream(
            "不应读取",
            2 * 1024 * 1024
          );
        }
        if (url === homeScript) {
          return scriptUpstream(
            "queryId:'HOME_QUERY_123',operationName:'HomeTimeline'"
          );
        }
        return upstream(url, { home: {} });
      }
    }
  );
  assert.equal(result.ok, true);
  assert.deepEqual(calls.slice(0, 2), [oversized, homeScript]);
  assert.equal(
    new URL(calls.at(-1)).pathname,
    "/i/api/graphql/HOME_QUERY_123/HomeTimeline"
  );
});

test("会话探测缺页时不自行创建标签页", async () => {
  let created = 0;
  const chromeApi = {
    tabs: {
      onRemoved: { addListener: () => undefined },
      query: async () => [],
      create: async () => {
        created += 1;
        return { id: 1, url: TWITTER_HOME_URL };
      }
    }
  };
  const adapter = new TwitterSessionAdapter({ chromeApi, scope: "home" });
  const result = await adapter.routeSession();
  assert.deepEqual(result, { error: "tab_unavailable" });
  assert.equal(created, 0);
});

test("Twitter home 作用域接受用户图 path 且拒绝非法 entries/referer", () => {
  assert.equal(validTwitterRequest(userRequest(), "home"), true);
  assert.equal(
    validTwitterRequest(
      userRequest({ entries: [["user_id", "12345"]] }),
      "home"
    ),
    true
  );
  assert.equal(
    validTwitterRequest(
      userRequest({ entries: [["screen_name", "me"]] }),
      "home"
    ),
    true
  );
  assert.equal(
    validTwitterRequest(
      userListRequest(TWITTER_USER_TWEETS_PATH),
      "home"
    ),
    true
  );
  assert.equal(
    validTwitterRequest(userListRequest(TWITTER_FOLLOWERS_PATH), "home"),
    true
  );
  assert.equal(
    validTwitterRequest(
      userListRequest(TWITTER_FOLLOWING_PATH, {
        entries: [["screen_name", "me"], ["count", "20"], ["cursor", "NEXT"]]
      }),
      "home"
    ),
    true
  );
  assert.equal(
    validTwitterRequest(
      userListRequest(TWITTER_FOLLOWERS_PATH, {
        entries: [["screen_name", "alice"], ["count", "20"]]
      }),
      "home"
    ),
    false
  );
  assert.equal(
    validTwitterRequest(
      userListRequest(TWITTER_USER_TWEETS_PATH, {
        entries: [["screen_name", "alice"], ["count", "10"]]
      }),
      "home"
    ),
    false
  );
  assert.equal(
    validTwitterRequest(
      userRequest({ referer: "https://x.com/researcher" }),
      "home"
    ),
    false
  );
  assert.equal(
    validTwitterRequest(
      userListRequest(TWITTER_FOLLOWERS_PATH, {
        referer: "https://x.com/researcher/followers"
      }),
      "home"
    ),
    false
  );
  assert.equal(validTwitterRequest(searchRequest(), "search"), true);
  assert.equal(validTwitterRequest(userRequest(), "search"), false);
  assert.equal(validTwitterRequest(searchRequest(), "home"), false);
  assert.equal(
    validTwitterRequest(
      userRequest({
        entries: [["screen_name", "researcher"], ["count", "20"]]
      }),
      "home"
    ),
    false
  );
});

function webpackOperation(queryId, operationName) {
  return {
    436871: new Function(
      "module",
      `module.exports={queryId:"${queryId}",operationName:"${operationName}"};`
    )
  };
}

test("页面运行时用独立 features 请求用户图 GraphQL", async () => {
  const cases = [
    {
      operationName: "UserByScreenName",
      path: TWITTER_USER_PATH,
      entries: [["screen_name", "researcher"]],
      queryId: "USER_SCREEN_123",
      expected: { screen_name: "researcher" }
    },
    {
      operationName: "UserByRestId",
      path: TWITTER_USER_PATH,
      entries: [["user_id", "12345"]],
      queryId: "USER_RESTID_123",
      expected: { userId: "12345" }
    },
    {
      operationName: "UserTweets",
      path: TWITTER_USER_TWEETS_PATH,
      entries: [["user_id", "12345"], ["count", "10"]],
      queryId: "USER_TWEETS_12",
      expected: {
        userId: "12345",
        count: 10,
        includePromotedContent: true,
        withQuickPromoteEligibilityTweetFields: true,
        withVoice: true,
        withV2Timeline: true
      }
    },
    {
      operationName: "Followers",
      path: TWITTER_FOLLOWERS_PATH,
      entries: [["user_id", "12345"], ["count", "20"]],
      queryId: "FOLLOWERS_1234",
      expected: {
        userId: "12345",
        count: 20,
        includePromotedContent: false
      }
    },
    {
      operationName: "Following",
      path: TWITTER_FOLLOWING_PATH,
      entries: [
        ["user_id", "12345"],
        ["count", "20"],
        ["cursor", "NEXT"]
      ],
      queryId: "FOLLOWING_1234",
      expected: {
        userId: "12345",
        count: 20,
        includePromotedContent: false,
        cursor: "NEXT"
      }
    }
  ];
  for (const item of cases) {
    const calls = [];
    const result = await runtimeFixture(
      {
        kind: "request",
        session_verified: true,
        path: item.path,
        entries: item.entries
      },
      {
        href: "https://x.com/home",
        webpackModules: webpackOperation(item.queryId, item.operationName),
        fetchImpl: async (url, options) => {
          calls.push({ url, options });
          return upstream(url, {
            user: { result: { __typename: "User", rest_id: "12345" } }
          });
        }
      }
    );
    assert.equal(result.ok, true, item.operationName);
    assert.equal(result.payload.operation, item.operationName);
    assert.equal(calls.length, 1, item.operationName);
    const list = ["UserTweets", "Followers", "Following"].includes(
      item.operationName
    );
    assert.equal(calls[0].options.method, list ? "POST" : "GET");
    assert.equal(calls[0].options.credentials, "include");
    assert.equal(calls[0].options.headers["x-csrf-token"], "LOCAL_CSRF");
    const target = new URL(calls[0].url);
    assert.equal(
      target.pathname,
      `/i/api/graphql/${item.queryId}/${item.operationName}`
    );
    if (list) {
      const body = JSON.parse(calls[0].options.body);
      assert.deepEqual(body.variables, item.expected);
      assert.deepEqual(body.features, USER_GRAPHQL_FEATURES);
      assert.equal(body.queryId, item.queryId);
    } else {
      assert.deepEqual(
        JSON.parse(target.searchParams.get("variables")),
        item.expected
      );
      const features = JSON.parse(target.searchParams.get("features"));
      assert.deepEqual(features, USER_GRAPHQL_FEATURES);
      assert.equal("rweb_video_screen_enabled" in features, false);
      assert.equal(calls[0].options.body, undefined);
    }
  }
});

test("缺 FEATURES_BY_OPERATION 时不打网", async () => {
  let fetches = 0;
  const result = await runtimeFixture(
    {
      kind: "request",
      session_verified: true,
      path: TWITTER_USER_PATH,
      entries: [["screen_name", "researcher"]]
    },
    {
      href: "https://x.com/home",
      featuresByOperation: {
        HomeTimeline: { fixture: true },
        SearchTimeline: { fixture: true }
      },
      webpackModules: webpackOperation(
        "USER_SCREEN_123",
        "UserByScreenName"
      ),
      fetchImpl: async () => {
        fetches += 1;
        throw new Error("unexpected_fetch");
      }
    }
  );
  assert.deepEqual(result, { ok: false, error: "runtime_unavailable" });
  assert.equal(fetches, 0);
});

test("用户图 payload 经清洗后不含凭据", async () => {
  const result = await runtimeFixture(
    {
      kind: "request",
      session_verified: true,
      path: TWITTER_USER_PATH,
      entries: [["screen_name", "researcher"]]
    },
    {
      href: "https://x.com/home",
      webpackModules: webpackOperation(
        "USER_SCREEN_123",
        "UserByScreenName"
      ),
      fetchImpl: async (url) => upstream(url, {
        user: {
          result: {
            rest_id: "12345",
            authorization: "Bearer SECRET",
            cookie: "twid=u%3D12345"
          }
        }
      })
    }
  );
  const sanitized = sanitizeBrowserPayload(result.payload);
  const text = JSON.stringify(sanitized);
  assert.equal(result.ok, true);
  assert.equal(sanitized.data.user.result.rest_id, "12345");
  assert.equal("authorization" in sanitized.data.user.result, false);
  assert.equal("cookie" in sanitized.data.user.result, false);
  assert.equal(text.includes("ct0"), false);
  assert.equal(text.includes("twid"), false);
  assert.equal(text.includes("LOCAL_CSRF"), false);
  assert.equal(text.includes(FIXTURE_BEARER_TOKEN), false);
  assert.equal(/Bearer /i.test(text), false);
});

test("me 从 twid 解析 rest_id 且 payload 不含 twid", async () => {
  const cookie = "ct0=LOCAL_CSRF; twid=u%3D12345";
  const cases = [
    {
      path: TWITTER_USER_PATH,
      entries: [["screen_name", "me"]],
      operationName: "UserByRestId",
      queryId: "USER_RESTID_123",
      expected: { userId: "12345" }
    },
    {
      path: TWITTER_FOLLOWERS_PATH,
      entries: [["screen_name", "me"], ["count", "20"]],
      operationName: "Followers",
      queryId: "FOLLOWERS_1234",
      expected: {
        userId: "12345",
        count: 20,
        includePromotedContent: false
      }
    }
  ];
  for (const item of cases) {
    const calls = [];
    const result = await runtimeFixture(
      {
        kind: "request",
        session_verified: true,
        path: item.path,
        entries: item.entries
      },
      {
        href: "https://x.com/home",
        cookie,
        webpackModules: webpackOperation(item.queryId, item.operationName),
        fetchImpl: async (url, options) => {
          calls.push({ url, options });
          return upstream(url, { user: { result: { rest_id: "12345" } } });
        }
      }
    );
    assert.equal(result.ok, true, item.operationName);
    const target = new URL(calls[0].url);
    assert.equal(
      target.pathname,
      `/i/api/graphql/${item.queryId}/${item.operationName}`
    );
    const variables = item.operationName === "Followers"
      ? JSON.parse(calls[0].options.body).variables
      : JSON.parse(target.searchParams.get("variables"));
    assert.deepEqual(variables, item.expected);
    const raw = JSON.stringify(result);
    const sanitized = JSON.stringify(sanitizeBrowserPayload(result.payload));
    assert.equal(raw.includes("twid"), false);
    assert.equal(sanitized.includes("twid"), false);
    assert.equal(raw.includes("u%3D"), false);
  }
});

test("HTTP 200 的 UserUnavailable 仍成功返回 data", async () => {
  const result = await runtimeFixture(
    {
      kind: "request",
      session_verified: true,
      path: TWITTER_USER_PATH,
      entries: [["screen_name", "missinguser"]]
    },
    {
      href: "https://x.com/home",
      webpackModules: webpackOperation(
        "USER_SCREEN_123",
        "UserByScreenName"
      ),
      fetchImpl: async (url) => upstream(url, {
        user: { result: { __typename: "UserUnavailable" } }
      })
    }
  );
  assert.equal(result.ok, true);
  assert.equal(
    result.payload.data.user.result.__typename,
    "UserUnavailable"
  );
});

test("页面运行时从 preload 未加载 chunk 发现 UserByScreenName", async () => {
  const chunk =
    "https://abs.twimg.com/responsive-web/client-web/bundle.UserByScreenName.abc.js";
  const calls = [];
  const result = await runtimeFixture(
    {
      kind: "request",
      session_verified: true,
      path: TWITTER_USER_PATH,
      entries: [["screen_name", "researcher"]]
    },
    {
      href: "https://x.com/home",
      scripts: [
        "https://abs.twimg.com/responsive-web/client-web/main.fixture.js"
      ],
      preloads: [chunk],
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        if (url === chunk) {
          assert.equal(options.credentials, "omit");
          return scriptUpstream(
            'queryId:"PRELOAD_Q_123",operationName:"UserByScreenName"'
          );
        }
        if (String(url).endsWith("main.fixture.js")) {
          return scriptUpstream("no matching operation");
        }
        return upstream(url, { user: { result: { rest_id: "12345" } } });
      }
    }
  );
  assert.equal(result.ok, true);
  assert.equal(
    new URL(calls.at(-1).url).pathname,
    "/i/api/graphql/PRELOAD_Q_123/UserByScreenName"
  );
  assert.equal(
    calls.some((item) => item.url === chunk && item.options.credentials === "omit"),
    true
  );
});

test("页面运行时从 webpack.u 未加载 chunk 发现 Followers", async () => {
  const chunk =
    "https://abs.twimg.com/responsive-web/client-web/43210.Followers.js";
  function webpackChunkFile(e) {
    return `${e}.${({ 43210: "Followers" })[e]}.js`;
  }
  const calls = [];
  const result = await runtimeFixture(
    {
      kind: "request",
      session_verified: true,
      path: TWITTER_FOLLOWERS_PATH,
      entries: [["user_id", "12345"], ["count", "20"]]
    },
    {
      href: "https://x.com/home",
      webpackPublicPath:
        "https://abs.twimg.com/responsive-web/client-web/",
      webpackChunkFile,
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        if (url === chunk) {
          assert.equal(options.credentials, "omit");
          return scriptUpstream(
            'queryId:"WEBPACK_U_1234",operationName:"Followers"'
          );
        }
        return upstream(url, { user: { result: { rest_id: "12345" } } });
      }
    }
  );
  assert.equal(result.ok, true);
  assert.equal(
    new URL(calls.at(-1).url).pathname,
    "/i/api/graphql/WEBPACK_U_1234/Followers"
  );
  assert.equal(calls[0].url, chunk);
  assert.equal(calls[0].options.credentials, "omit");
});

test("用户图 HTTP 404 清除 operation 缓存", async () => {
  const result = await runtimeFixture(
    {
      kind: "request",
      session_verified: true,
      path: TWITTER_USER_PATH,
      entries: [["screen_name", "researcher"]]
    },
    {
      href: "https://x.com/home",
      resources: [
        "https://x.com/i/api/graphql/STALE_USER_123/UserByScreenName"
      ],
      fetchImpl: async (url) => failedUpstream(url, 404)
    }
  );
  assert.deepEqual(result, { ok: false, error: "runtime_unavailable" });
});
