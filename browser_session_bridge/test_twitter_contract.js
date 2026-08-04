import assert from "node:assert/strict";
import test from "node:test";

import { TwitterSessionAdapter } from "./adapters/twitter/adapter.js";
import {
  TWITTER_HOME_FEED_PATH,
  TWITTER_HOME_URL,
  TWITTER_SEARCH_POSTS_PATH,
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

async function runtimeFixture(input, {
  href,
  resources = [],
  scripts = [],
  cachedBearer = FIXTURE_BEARER_TOKEN,
  cachedTransactionModuleId = 991160,
  transactionCalls = [],
  webpackModules = {},
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
  delete globalThis[operationCacheKey];
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
      querySelectorAll: () => []
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
  try {
    return await invokeTwitterPageRuntime(input);
  } finally {
    delete globalThis[operationCacheKey];
    if (operationCacheDescriptor) {
      Object.defineProperty(
        globalThis,
        operationCacheKey,
        operationCacheDescriptor
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
