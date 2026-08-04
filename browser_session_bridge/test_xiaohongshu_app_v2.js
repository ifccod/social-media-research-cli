import assert from "node:assert/strict";
import test from "node:test";

import {
  XiaohongshuAppV2SessionAdapter
} from "./adapters/xiaohongshu_app_v2/adapter.js";
import {
  XIAOHONGSHU_APP_V2_CREATOR_HOT_INSPIRATION_PATH,
  XIAOHONGSHU_APP_V2_CREATOR_INSPIRATION_PATH,
  XIAOHONGSHU_APP_V2_PRODUCT_DETAIL_PATH,
  XIAOHONGSHU_APP_V2_PRODUCT_RECOMMENDATIONS_PATH,
  XIAOHONGSHU_APP_V2_PRODUCT_REVIEWS_PATH,
  XIAOHONGSHU_APP_V2_PRODUCT_REVIEW_OVERVIEW_PATH,
  XIAOHONGSHU_APP_V2_SEARCH_GROUPS_PATH,
  XIAOHONGSHU_APP_V2_SEARCH_IMAGES_PATH,
  XIAOHONGSHU_APP_V2_SEARCH_PRODUCTS_PATH,
  XIAOHONGSHU_APP_V2_TOPIC_FEED_PATH,
  XIAOHONGSHU_APP_V2_TOPIC_INFO_PATH,
  validXiaohongshuAppV2Request
} from "./adapters/xiaohongshu_app_v2/contract.js";
import {
  invokeXiaohongshuAppV2PageRuntime
} from "./adapters/xiaohongshu_app_v2/page_runtime.js";

const SKU_ID = "669ddd44e05f3700011067ed";
const PAGE_ID = "5c1cc866febed9000184b7c1";
const NOTE_ID = "6a5e0730000000000503b173";
const SEARCH_REFERER = "https://www.xiaohongshu.com/search_result";
const CHAT_REFERER = "https://www.xiaohongshu.com/chat";
const EXPLORE_REFERER = "https://www.xiaohongshu.com/explore";

const CASES = Object.freeze([
  {
    path: XIAOHONGSHU_APP_V2_SEARCH_IMAGES_PATH,
    referer: SEARCH_REFERER,
    entries: [
      ["keyword", "壁纸"],
      ["page", "1"],
      ["search_id", ""],
      ["search_session_id", ""],
      ["word_request_id", ""],
      ["source", "explore_feed"]
    ]
  },
  {
    path: XIAOHONGSHU_APP_V2_SEARCH_PRODUCTS_PATH,
    referer: SEARCH_REFERER,
    entries: [
      ["keyword", "手机壳"],
      ["page", "1"],
      ["search_id", ""],
      ["source", "explore_feed"]
    ]
  },
  {
    path: XIAOHONGSHU_APP_V2_SEARCH_GROUPS_PATH,
    referer: CHAT_REFERER,
    entries: [
      ["keyword", "上海"],
      ["page_no", "0"],
      ["search_id", ""],
      ["source", "unifiedSearchGroup"],
      ["is_recommend", "0"]
    ]
  },
  {
    path: XIAOHONGSHU_APP_V2_PRODUCT_DETAIL_PATH,
    referer: EXPLORE_REFERER,
    entries: [
      ["sku_id", SKU_ID],
      ["source", "mall_search"],
      ["pre_page", "mall_search"]
    ]
  },
  {
    path: XIAOHONGSHU_APP_V2_PRODUCT_REVIEW_OVERVIEW_PATH,
    referer: EXPLORE_REFERER,
    entries: [["sku_id", SKU_ID], ["tab", "2"]]
  },
  {
    path: XIAOHONGSHU_APP_V2_PRODUCT_REVIEWS_PATH,
    referer: EXPLORE_REFERER,
    entries: [
      ["sku_id", SKU_ID],
      ["page", "0"],
      ["sort_strategy_type", "0"],
      ["share_pics_only", "0"],
      ["from_page", "score_page"]
    ]
  },
  {
    path: XIAOHONGSHU_APP_V2_PRODUCT_RECOMMENDATIONS_PATH,
    referer: EXPLORE_REFERER,
    entries: [
      ["sku_id", SKU_ID],
      ["cursor_score", ""],
      ["region", "US"]
    ]
  },
  {
    path: XIAOHONGSHU_APP_V2_TOPIC_INFO_PATH,
    referer: SEARCH_REFERER,
    entries: [
      ["page_id", PAGE_ID],
      ["source", "normal"],
      ["note_id", NOTE_ID]
    ]
  },
  {
    path: XIAOHONGSHU_APP_V2_TOPIC_FEED_PATH,
    referer: SEARCH_REFERER,
    entries: [
      ["page_id", PAGE_ID],
      ["sort", "trend"],
      ["cursor_score", ""],
      ["last_note_id", ""],
      ["last_note_ct", ""],
      ["session_id", ""],
      ["first_load_time", ""],
      ["source", "normal"]
    ]
  },
  {
    path: XIAOHONGSHU_APP_V2_CREATOR_INSPIRATION_PATH,
    referer: EXPLORE_REFERER,
    entries: [
      ["cursor", ""],
      ["tab", "0"],
      ["source", "creator_center"]
    ]
  },
  {
    path: XIAOHONGSHU_APP_V2_CREATOR_HOT_INSPIRATION_PATH,
    referer: EXPLORE_REFERER,
    entries: [["cursor", ""]]
  }
]);

function operationMethod(fixture) {
  return fixture.path === XIAOHONGSHU_APP_V2_SEARCH_IMAGES_PATH
    ? "POST"
    : "GET";
}

class MockEvent {
  constructor() {
    this.listeners = new Set();
  }

  addListener(listener) {
    this.listeners.add(listener);
  }

  removeListener(listener) {
    this.listeners.delete(listener);
  }
}

function createWebpackRuntime(onRequest) {
  const factories = {
    search(module) {
      function getAiSearchNotesV2(body, options = {}) {
        const transportKey = "WEB_AI_SEARCH_NOTES_V2";
        const path = transportKey === "WEB_AI_SEARCH_NOTES_V2"
          ? "/api/sns/web/v2/search/notes"
          : "";
        return onRequest(path, body, options);
      }
      module.exports = { i1: getAiSearchNotesV2 };
    },
    groups(module) {
      class GroupAPI {
        constructor() {
          this.searchGroup = this.searchGroup.bind(this);
        }

        searchGroup(params, options = {}) {
          const path = "/api/im/v1/group/square/search";
          return onRequest(path, params, options);
        }
      }
      class SocialService {
        static getInstance() {
          return SocialService.instance;
        }
      }
      SocialService.instance = { sdk: new GroupAPI() };
      module.exports = { V: SocialService };
    }
  };
  const cache = {};
  function runtimeRequire(moduleID) {
    if (!cache[moduleID]) {
      const module = { exports: {} };
      factories[moduleID](module, module.exports, runtimeRequire);
      cache[moduleID] = module.exports;
    }
    return cache[moduleID];
  }
  runtimeRequire.m = factories;

  const chunks = [];
  chunks.push = (chunk) => {
    const runtime = chunk[2];
    if (typeof runtime === "function") {
      runtime(runtimeRequire);
    }
    return Array.prototype.push.call(chunks, chunk);
  };
  return chunks;
}

function installPageFixture(onRequest) {
  const names = ["document", "navigator", "screen", "window"];
  const previous = Object.fromEntries(
    names.map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)])
  );
  const document = {
    cookie: "web_session=LOCAL_ONLY; a1=LOCAL_ONLY",
    querySelectorAll() {
      return [];
    }
  };
  const navigator = {
    connection: {},
    cookieEnabled: true,
    hardwareConcurrency: 8,
    language: "zh-CN",
    languages: ["zh-CN", "en"],
    onLine: true,
    platform: "MacIntel",
    userAgent: "Fixture Chrome",
    vendor: "Google Inc."
  };
  const screen = {
    availHeight: 900,
    availWidth: 1440,
    colorDepth: 24,
    height: 900,
    pixelDepth: 24,
    width: 1440
  };
  const window = {
    __INITIAL_STATE__: { user: { loggedIn: true } },
    devicePixelRatio: 2,
    document,
    getComputedStyle() {
      return { display: "none", opacity: "0", visibility: "hidden" };
    },
    innerHeight: 800,
    innerWidth: 1200,
    location: { href: SEARCH_REFERER },
    navigator,
    outerHeight: 900,
    outerWidth: 1440,
    screen,
    webpackChunkxhs_pc_web: createWebpackRuntime(onRequest)
  };
  for (const [name, value] of Object.entries({
    document,
    navigator,
    screen,
    window
  })) {
    Object.defineProperty(globalThis, name, {
      configurable: true,
      value
    });
  }
  return {
    window,
    restore() {
      for (const [name, descriptor] of Object.entries(previous)) {
        if (descriptor) {
          Object.defineProperty(globalThis, name, descriptor);
        } else {
          delete globalThis[name];
        }
      }
    }
  };
}

test("App V2 contract fixes all 11 operation methods, fields, and referers", () => {
  assert.equal(CASES.length, 11);
  for (const fixture of CASES) {
    const request = {
      method: operationMethod(fixture),
      path: fixture.path,
      entries: fixture.entries,
      referer: fixture.referer
    };
    assert.equal(validXiaohongshuAppV2Request(request), true, fixture.path);
    assert.equal(validXiaohongshuAppV2Request({
      ...request,
      method: request.method === "POST" ? "GET" : "POST"
    }), false, fixture.path);
    assert.equal(validXiaohongshuAppV2Request({
      ...request,
      entries: [...fixture.entries, ["unknown", "1"]]
    }), false, fixture.path);
    assert.equal(validXiaohongshuAppV2Request({
      ...request,
      headers: { authorization: "LOCAL_ONLY" }
    }), false, fixture.path);
    assert.equal(validXiaohongshuAppV2Request({
      ...request,
      referer: `${fixture.referer}?xsec_token=LOCAL_ONLY`
    }), false, fixture.path);
  }
});

test("App V2 contract rejects invalid defaults and identifiers", () => {
  const images = CASES.find(
    (fixture) => fixture.path === XIAOHONGSHU_APP_V2_SEARCH_IMAGES_PATH
  );
  assert.equal(validXiaohongshuAppV2Request({
    method: operationMethod(images),
    path: images.path,
    entries: images.entries.map((entry) =>
      entry[0] === "source" ? ["source", "mall_search"] : entry
    ),
    referer: images.referer
  }), false);

  const detail = CASES.find(
    (fixture) => fixture.path === XIAOHONGSHU_APP_V2_PRODUCT_DETAIL_PATH
  );
  assert.equal(validXiaohongshuAppV2Request({
    method: "GET",
    path: detail.path,
    entries: detail.entries.map((entry) =>
      entry[0] === "sku_id" ? ["sku_id", "not-a-sku"] : entry
    ),
    referer: detail.referer
  }), false);
});

test("App V2 runtime discovers the confirmed image and group Web wrappers", async () => {
  const calls = [];
  const fixture = installPageFixture((path, parameters, options) => {
    calls.push({ path, parameters, options });
    return {
      items: [
        {
          modelType: "note",
          noteCard: { noteId: NOTE_ID }
        },
        {
          modelType: "hot_query",
          hotQuery: { items: [] }
        }
      ],
      hasMore: true,
      searchId: "response-search",
      authorization: "LOCAL_ONLY",
      xsecToken: "LOCAL_ONLY"
    };
  });
  try {
    const session = await invokeXiaohongshuAppV2PageRuntime({
      kind: "session"
    });
    assert.equal(session.ok, true);
    assert.equal(session.payload.logged_in, true);
    assert.equal(session.payload.request_ready, true);

    const images = CASES.find(
      (item) => item.path === XIAOHONGSHU_APP_V2_SEARCH_IMAGES_PATH
    );
    assert.deepEqual(await invokeXiaohongshuAppV2PageRuntime({
      kind: "request",
      operation_id: "app_v2_images_fixture",
      method: operationMethod(images),
      path: images.path,
      entries: images.entries
    }), {
      ok: true,
      payload: {
        items: [
          {
            modelType: "note",
            noteCard: { noteId: NOTE_ID }
          },
          {
            modelType: "hot_query",
            hotQuery: { items: [] }
          }
        ],
        hasMore: true,
        searchId: "response-search"
      }
    });
    assert.equal(calls[0].path, "/api/sns/web/v2/search/notes");
    assert.deepEqual({
      extFlags: calls[0].parameters.extFlags,
      filters: calls[0].parameters.filters,
      geo: calls[0].parameters.geo,
      imageFormats: calls[0].parameters.imageFormats,
      keyword: calls[0].parameters.keyword,
      noteType: calls[0].parameters.noteType,
      page: calls[0].parameters.page,
      pageSize: calls[0].parameters.pageSize,
      sort: calls[0].parameters.sort
    }, {
      extFlags: [],
      filters: [],
      geo: "",
      imageFormats: ["jpg", "webp", "avif"],
      keyword: "壁纸",
      noteType: 2,
      page: 1,
      pageSize: 20,
      sort: "general"
    });
    assert.match(calls[0].parameters.searchId, /^[0-9a-z]+$/);
    assert.equal(calls[0].parameters.sessionId, "");
    assert.equal(
      Object.prototype.hasOwnProperty.call(calls[0].parameters, "source"),
      false
    );
    assert.equal(
      Object.prototype.hasOwnProperty.call(calls[0].parameters, "wordRequestId"),
      false
    );
    assert.equal(calls[0].options.signal instanceof AbortSignal, true);

    fixture.window.location.href = CHAT_REFERER;
    const groups = CASES.find(
      (item) => item.path === XIAOHONGSHU_APP_V2_SEARCH_GROUPS_PATH
    );
    const groupResult = await invokeXiaohongshuAppV2PageRuntime({
      kind: "request",
      operation_id: "app_v2_groups_fixture",
      method: "GET",
      path: groups.path,
      entries: groups.entries
    });
    assert.equal(groupResult.ok, true);
    assert.equal(calls[1].path, "/api/im/v1/group/square/search");
    assert.deepEqual(calls[1].parameters, {
      keyword: "上海",
      pageNo: 0,
      searchId: "",
      source: "unifiedSearchGroup",
      isRecommend: 0
    });
  } finally {
    fixture.restore();
  }
});

test("App V2 runtime classifies bounded nested transport risk signals", async (t) => {
  const images = CASES.find(
    (item) => item.path === XIAOHONGSHU_APP_V2_SEARCH_IMAGES_PATH
  );
  const cases = [
    {
      name: "nested rate limit overrides outer forbidden",
      expected: "rate_limited",
      error() {
        const error = new Error("HTTPServerError");
        error.code = "ERR_BAD_RESPONSE";
        error.status = 403;
        error.response = {
          data: { statusCode: "429", msg: "SECRET_RATE_LIMIT_DETAIL" }
        };
        return error;
      }
    },
    {
      name: "nested forbidden business code",
      expected: "forbidden",
      error() {
        const error = new Error("HTTPServerError");
        error.response = { data: { data: { error_code: -10000 } } };
        return error;
      }
    },
    {
      name: "nested verification status overrides outer forbidden",
      expected: "verification_required",
      error() {
        const error = new Error("HTTPServerError");
        error.status = 403;
        error.cause = {
          response: {
            data: { status: 471, message: "SECRET_CHALLENGE" }
          }
        };
        return error;
      }
    },
    {
      name: "unknown server error",
      expected: "request_failed",
      error() {
        return new Error("HTTPServerError SECRET_UNKNOWN_DETAIL");
      }
    }
  ];

  for (const fixture of cases) {
    await t.test(fixture.name, async () => {
      const page = installPageFixture(() => {
        throw fixture.error();
      });
      try {
        const result = await invokeXiaohongshuAppV2PageRuntime({
          kind: "request",
          operation_id: "app_v2_nested_error_fixture",
          method: operationMethod(images),
          path: images.path,
          entries: images.entries
        });
        assert.deepEqual(result, { ok: false, error: fixture.expected });
        assert.equal(JSON.stringify(result).includes("SECRET_"), false);
      } finally {
        page.restore();
      }
    });
  }
});

test("App V2 runtime classifies resolved group business risk responses", async (t) => {
  const groups = CASES.find(
    (item) => item.path === XIAOHONGSHU_APP_V2_SEARCH_GROUPS_PATH
  );
  const cases = [
    { name: "rate limit", response: { code: 429, msg: "请求频繁" }, expected: "rate_limited" },
    { name: "forbidden", response: { code: -10000, msg: "denied" }, expected: "forbidden" },
    { name: "login expired", response: { code: 104, msg: "未登录" }, expected: "not_logged_in" },
    {
      name: "verification",
      response: { code: 300012, msg: "请完成安全验证" },
      expected: "verification_required"
    }
  ];

  for (const [index, item] of cases.entries()) {
    await t.test(item.name, async () => {
      const page = installPageFixture(() => item.response);
      page.window.location.href = CHAT_REFERER;
      try {
        assert.deepEqual(await invokeXiaohongshuAppV2PageRuntime({
          kind: "request",
          operation_id: `app_v2_group_business_risk_${index}`,
          method: "GET",
          path: groups.path,
          entries: groups.entries
        }), {
          ok: false,
          error: item.expected
        });
      } finally {
        page.restore();
      }
    });
  }
});

test("App V2 runtime reports every unconfirmed Web equivalent explicitly", async () => {
  const fixture = installPageFixture(() => {
    throw new Error("unexpected_wrapper_call");
  });
  try {
    const confirmed = new Set([
      XIAOHONGSHU_APP_V2_SEARCH_IMAGES_PATH,
      XIAOHONGSHU_APP_V2_SEARCH_GROUPS_PATH
    ]);
    for (const [index, item] of CASES.entries()) {
      if (confirmed.has(item.path)) {
        continue;
      }
      fixture.window.location.href = item.referer;
      assert.deepEqual(await invokeXiaohongshuAppV2PageRuntime({
        kind: "request",
        operation_id: `app_v2_unavailable_${index}`,
        method: operationMethod(item),
        path: item.path,
        entries: item.entries
      }), {
        ok: false,
        error: "runtime_unavailable"
      }, item.path);
    }
  } finally {
    fixture.restore();
  }
});

test("App V2 adapter keeps its platform route and applies final sanitization", async () => {
  const tab = {
    id: 31,
    status: "complete",
    url: SEARCH_REFERER,
    windowId: 1
  };
  const chromeApi = {
    tabs: {
      onRemoved: new MockEvent(),
      onUpdated: new MockEvent(),
      async query() {
        return [tab];
      },
      async get() {
        return tab;
      },
      async update(_tabID, changes) {
        Object.assign(tab, changes);
        return tab;
      }
    },
    windows: {
      async update() {}
    },
    scripting: {
      async executeScript(details) {
        assert.equal(details.world, "MAIN");
        assert.equal(details.args[0].path, XIAOHONGSHU_APP_V2_SEARCH_IMAGES_PATH);
        return [{
          result: {
            ok: true,
            payload: {
              items: [],
              authorization: "LOCAL_ONLY",
              search_session_id: "LOCAL_ONLY"
            }
          }
        }];
      }
    }
  };
  const adapter = new XiaohongshuAppV2SessionAdapter({ chromeApi });
  adapter.registerLifecycle();
  const images = CASES.find(
    (item) => item.path === XIAOHONGSHU_APP_V2_SEARCH_IMAGES_PATH
  );
  assert.deepEqual(await adapter.routeRequest({
    method: operationMethod(images),
    path: images.path,
    entries: images.entries,
    referer: images.referer
  }, {
    requestId: "adapter_app_v2_fixture"
  }), {
    payload: { items: [] }
  });
});

test("App V2 adapter rejects a missing request context without creating a tab", async () => {
  const noteURL =
    `https://www.xiaohongshu.com/explore/${NOTE_ID}?xsec_token=LOCAL_ONLY`;
  const noteTab = {
    id: 41,
    status: "complete",
    url: noteURL,
    windowId: 1
  };
  let creates = 0;
  const chromeApi = {
    tabs: {
      async query() {
        return [noteTab];
      },
      async create() {
        creates += 1;
        throw new Error("不应新建标签页");
      },
      async get(tabID) {
        return tabID === noteTab.id ? noteTab : null;
      },
      async update() {
        throw new Error("existing tab must not be replaced");
      }
    }
  };
  const requestPolicy = {
    async run(_signal, callback) {
      return callback(async () => {});
    }
  };
  const adapter = new XiaohongshuAppV2SessionAdapter({
    chromeApi,
    requestPolicy
  });
  adapter.runInPage = async () => {
    throw new Error("不应执行页面请求");
  };
  const images = CASES.find(
    (item) => item.path === XIAOHONGSHU_APP_V2_SEARCH_IMAGES_PATH
  );

  assert.deepEqual(await adapter.routeRequest({
    method: operationMethod(images),
    path: images.path,
    entries: images.entries,
    referer: images.referer
  }), { error: "tab_unavailable" });
  assert.equal(creates, 0);
  assert.equal(noteTab.url, noteURL);
});

test("App V2 adapter latches verification responses while session probes stay available", async () => {
  const adapter = new XiaohongshuAppV2SessionAdapter({ chromeApi: {} });
  let requestExecutions = 0;
  let sessionExecutions = 0;
  adapter.pickTab = async () => ({
    id: 32,
    status: "complete",
    url: SEARCH_REFERER
  });
  adapter.runInPage = async (_tabID, input) => {
    if (input.kind === "session") {
      sessionExecutions += 1;
      return {
        ok: true,
        payload: {
          fingerprint: { cookie_enabled: true },
          logged_in: true,
          request_ready: true,
          verification_required: true
        }
      };
    }
    requestExecutions += 1;
    return { ok: false, error: "verification_required" };
  };
  const images = CASES.find(
    (item) => item.path === XIAOHONGSHU_APP_V2_SEARCH_IMAGES_PATH
  );
  const message = {
    method: operationMethod(images),
    path: images.path,
    entries: images.entries,
    referer: images.referer
  };

  assert.deepEqual(await adapter.routeRequest(message), {
    error: "verification_required"
  });
  assert.deepEqual(await adapter.routeRequest(message), {
    error: "verification_required"
  });
  assert.equal(requestExecutions, 1);
  assert.deepEqual(await adapter.routeSession(), {
    payload: {
      fingerprint: { cookie_enabled: true },
      logged_in: true,
      request_ready: true,
      verification_required: true
    }
  });
  assert.equal(sessionExecutions, 1);
});
