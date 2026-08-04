import assert from "node:assert/strict";
import test from "node:test";

import {
  XiaohongshuPgySessionAdapter
} from "./adapters/xiaohongshu_pgy/adapter.js";
import {
  XIAOHONGSHU_PGY_BLOGGER_DETAIL_PATH,
  XIAOHONGSHU_PGY_BLOGGER_LIST_PATH,
  XIAOHONGSHU_PGY_BLOGGER_NOTES_PATH,
  XIAOHONGSHU_PGY_GOOD_CASE_CLASSES_PATH,
  XIAOHONGSHU_PGY_GOOD_LIVES_PATH,
  XIAOHONGSHU_PGY_GOOD_NOTES_PATH,
  XIAOHONGSHU_PGY_INDUSTRIES_PATH,
  XIAOHONGSHU_PGY_LOGIN_URL,
  XIAOHONGSHU_PGY_TOP_BLOGGERS_PATH,
  sameXiaohongshuPgyRequestContext,
  validXiaohongshuPgyRequest
} from "./adapters/xiaohongshu_pgy/contract.js";
import {
  invokeXiaohongshuPgyPageRuntime
} from "./adapters/xiaohongshu_pgy/page_runtime.js";
import {
  DEFAULT_MINIMUM_START_INTERVAL_MS,
  SerialRequestPolicy
} from "./core/serial_request_policy.js";

const USER_ID = "5c668b3e0000000012021605";

function installPageFixture({
  onBloggerDetail = null,
  onBloggerList = null,
  onBloggerTrack = null,
  onUserInfo = null
} = {}) {
  const previous = {
    document: globalThis.document,
    navigator: globalThis.navigator,
    screen: globalThis.screen,
    window: globalThis.window
  };
  const wrapperCalls = [];

  const factories = {
    fixture(module) {
      class FixtureAPI {
        async getUserInfo() {
          wrapperCalls.push("user_info");
          if (typeof onUserInfo === "function") {
            return onUserInfo();
          }
          return {
            userId: USER_ID,
            endpoint: "/api/solar/user/info"
          };
        }

        async getBloggerDetail(userID) {
          wrapperCalls.push("blogger_detail");
          if (typeof onBloggerDetail === "function") {
            return onBloggerDetail(userID);
          }
          return {
            userId: userID,
            endpoint: "/api/solar/cooperator/user/blogger"
          };
        }

        async getBloggerNotes(body) {
          wrapperCalls.push("blogger_notes");
          return {
            ...body,
            endpoint: "/api/solar/kol/data_v2/notes_detail"
          };
        }

        async getBloggerTrackID(body) {
          wrapperCalls.push("blogger_track");
          if (typeof onBloggerTrack === "function") {
            return onBloggerTrack(body);
          }
          return {
            trackId: `track-${body.pageNum}`,
            endpoint: "/api/solar/cooperator/blogger/track"
          };
        }

        async getBloggerList(body) {
          wrapperCalls.push("blogger_list");
          if (typeof onBloggerList === "function") {
            return onBloggerList(body);
          }
          return {
            brandUserId: body.brandUserId,
            pageNum: body.pageNum,
            pageSize: body.pageSize,
            trackId: body.trackId,
            endpoint: "/api/solar/cooperator/blogger/v2"
          };
        }

        async getGoodCaseClass() {
          wrapperCalls.push("good_case_classes");
          return {
            data: ["美妆个护"],
            endpoint: "/api/solar/index/class_info"
          };
        }

        async getGoodCase(body) {
          wrapperCalls.push("good_notes");
          return {
            ...body,
            pageNum: 1,
            pageSize: 6,
            endpoint: "/api/solar/index/high_grade_note"
          };
        }

        async getLiveGoodCase(body) {
          wrapperCalls.push("good_lives");
          return {
            ...body,
            pageNum: 1,
            pageSize: 6,
            endpoint: "/api/solar/index/high_grade_live"
          };
        }

        async getBloggerRank(body) {
          wrapperCalls.push("top_bloggers");
          return {
            ...body,
            pageNumber: 1,
            pageSize: 3,
            endpoint: "/api/solar/index/top_kols"
          };
        }

        async getIndustries() {
          wrapperCalls.push("industries");
          return {
            data: ["食品饮料"],
            endpoint: "/api/solar/index/get_industry_data"
          };
        }
      }
      module.exports = { api: new FixtureAPI() };
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

  const document = {
    cookie: "",
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
    document,
    innerHeight: 800,
    innerWidth: 1200,
    location: { href: XIAOHONGSHU_PGY_LOGIN_URL },
    navigator,
    outerHeight: 900,
    outerWidth: 1440,
    screen,
    webpackChunkpgy_pc: chunks,
    __INITIAL_STATE__: {
      user: {
        isLogin: true,
        userId: USER_ID
      }
    },
    devicePixelRatio: 2,
    getComputedStyle() {
      return { display: "none", opacity: "0", visibility: "hidden" };
    }
  };

  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: document
  });
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: navigator
  });
  Object.defineProperty(globalThis, "screen", {
    configurable: true,
    value: screen
  });
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: window
  });

  const restore = () => {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) {
        delete globalThis[name];
      } else {
        Object.defineProperty(globalThis, name, {
          configurable: true,
          value
        });
      }
    }
  };
  restore.wrapperCalls = wrapperCalls;
  return restore;
}

test("PGY contract keeps the operation, method, parameters, and origin fixed", () => {
  assert.equal(validXiaohongshuPgyRequest({
    method: "GET",
    path: XIAOHONGSHU_PGY_BLOGGER_DETAIL_PATH,
    entries: [["user_id", USER_ID]],
    referer: XIAOHONGSHU_PGY_LOGIN_URL
  }), true);
  assert.equal(validXiaohongshuPgyRequest({
    method: "POST",
    path: XIAOHONGSHU_PGY_BLOGGER_DETAIL_PATH,
    entries: [["user_id", USER_ID]],
    referer: XIAOHONGSHU_PGY_LOGIN_URL
  }), false);
  assert.equal(validXiaohongshuPgyRequest({
    path: XIAOHONGSHU_PGY_BLOGGER_DETAIL_PATH,
    entries: [["user_id", USER_ID]],
    referer: XIAOHONGSHU_PGY_LOGIN_URL
  }), false);
  assert.equal(validXiaohongshuPgyRequest({
    method: "GET",
    path: XIAOHONGSHU_PGY_BLOGGER_DETAIL_PATH,
    entries: [["user_id", USER_ID]],
    referer: XIAOHONGSHU_PGY_LOGIN_URL,
    headers: { authorization: "BROWSER_ONLY" }
  }), false);
  assert.equal(validXiaohongshuPgyRequest({
    method: "GET",
    path: XIAOHONGSHU_PGY_BLOGGER_DETAIL_PATH,
    entries: [["user_id", USER_ID], ["unknown", "1"]],
    referer: XIAOHONGSHU_PGY_LOGIN_URL
  }), false);
  assert.equal(validXiaohongshuPgyRequest({
    method: "GET",
    path: XIAOHONGSHU_PGY_BLOGGER_DETAIL_PATH,
    entries: [["user_id", USER_ID]],
    referer: "https://www.xiaohongshu.com/explore"
  }), false);
  assert.equal(sameXiaohongshuPgyRequestContext(
    "https://pgy.xiaohongshu.com/solar/pre-trade/blogger",
    XIAOHONGSHU_PGY_LOGIN_URL
  ), true);
});

test("PGY runtime finds and binds a singleton prototype wrapper", async () => {
  const restore = installPageFixture();
  try {
    assert.deepEqual(await invokeXiaohongshuPgyPageRuntime({
      kind: "session"
    }), {
      ok: true,
      payload: {
        fingerprint: {
          user_agent: "Fixture Chrome",
          ua_ch: null,
          language: "zh-CN",
          languages: ["zh-CN", "en"],
          platform: "MacIntel",
          vendor: "Google Inc.",
          cookie_enabled: true,
          online: true,
          hardware_concurrency: 8,
          device_memory: null,
          screen: {
            width: 1440,
            height: 900,
            avail_width: 1440,
            avail_height: 900,
            color_depth: 24,
            pixel_depth: 24,
            device_pixel_ratio: 2
          },
          viewport: {
            width: 1200,
            height: 800,
            outer_width: 1440,
            outer_height: 900
          },
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          connection: {
            effective_type: "",
            round_trip_time: null,
            downlink: null,
            save_data: false
          }
        },
        logged_in: true,
        request_ready: true,
        verification_required: false
      }
    });
    assert.deepEqual(restore.wrapperCalls, []);

    assert.deepEqual(await invokeXiaohongshuPgyPageRuntime({
      kind: "request",
      operation_id: "pgy_blogger_detail_fixture",
      method: "GET",
      path: XIAOHONGSHU_PGY_BLOGGER_DETAIL_PATH,
      entries: [["user_id", USER_ID]]
    }), {
      ok: true,
      payload: {
        userId: USER_ID,
        endpoint: "/api/solar/cooperator/user/blogger"
      }
    });
    assert.deepEqual(restore.wrapperCalls, ["blogger_detail"]);
  } finally {
    restore();
  }
});

test("PGY runtime calls the observed commercial homepage wrappers", async () => {
  const restore = installPageFixture();
  try {
    const fixtures = [
      {
        operation_id: "pgy_good_case_classes_fixture",
        path: XIAOHONGSHU_PGY_GOOD_CASE_CLASSES_PATH,
        entries: [],
        expected: {
          data: ["美妆个护"],
          endpoint: "/api/solar/index/class_info"
        }
      },
      {
        operation_id: "pgy_good_notes_fixture",
        path: XIAOHONGSHU_PGY_GOOD_NOTES_PATH,
        entries: [["category", "美妆个护"]],
        expected: {
          secondClass: "美妆个护",
          pageNum: 1,
          pageSize: 6,
          endpoint: "/api/solar/index/high_grade_note"
        }
      },
      {
        operation_id: "pgy_good_lives_fixture",
        path: XIAOHONGSHU_PGY_GOOD_LIVES_PATH,
        entries: [["category", "潮流运动"]],
        expected: {
          secondClass: "潮流运动",
          pageNum: 1,
          pageSize: 6,
          endpoint: "/api/solar/index/high_grade_live"
        }
      },
      {
        operation_id: "pgy_top_bloggers_fixture",
        path: XIAOHONGSHU_PGY_TOP_BLOGGERS_PATH,
        entries: [["rank_type", "6"]],
        expected: {
          rankType: 6,
          pageNumber: 1,
          pageSize: 3,
          endpoint: "/api/solar/index/top_kols"
        }
      },
      {
        operation_id: "pgy_industries_fixture",
        path: XIAOHONGSHU_PGY_INDUSTRIES_PATH,
        entries: [],
        expected: {
          data: ["食品饮料"],
          endpoint: "/api/solar/index/get_industry_data"
        }
      }
    ];

    for (const fixture of fixtures) {
      assert.deepEqual(await invokeXiaohongshuPgyPageRuntime({
        kind: "request",
        operation_id: fixture.operation_id,
        method: "GET",
        path: fixture.path,
        entries: fixture.entries
      }), {
        ok: true,
        payload: fixture.expected
      });
    }
    assert.deepEqual(restore.wrapperCalls, [
      "good_case_classes",
      "good_notes",
      "good_lives",
      "top_bloggers",
      "industries"
    ]);
  } finally {
    restore();
  }
});

test("PGY runtime classifies bounded nested transport risk signals", async (t) => {
  const cases = [
    {
      name: "nested rate limit overrides outer forbidden",
      expected: "rate_limited",
      error() {
        const error = new Error("HTTPServerError");
        error.code = "ERR_BAD_RESPONSE";
        error.status = 403;
        error.response = {
          data: { status: 429, msg: "SECRET_RATE_LIMIT_DETAIL" }
        };
        return error;
      }
    },
    {
      name: "nested forbidden business code",
      expected: "forbidden",
      error() {
        const error = new Error("HTTPServerError");
        error.data = { data: { businessCode: -10000 } };
        return error;
      }
    },
    {
      name: "nested verification status overrides outer forbidden",
      expected: "verification_required",
      error() {
        const error = new Error("HTTPServerError");
        error.status = 403;
        error.response = {
          data: { statusCode: 471, error_message: "SECRET_CHALLENGE" }
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
      const restore = installPageFixture({
        onBloggerDetail() {
          throw fixture.error();
        }
      });
      try {
        const result = await invokeXiaohongshuPgyPageRuntime({
          kind: "request",
          operation_id: "pgy_nested_error_fixture",
          method: "GET",
          path: XIAOHONGSHU_PGY_BLOGGER_DETAIL_PATH,
          entries: [["user_id", USER_ID]]
        });
        assert.deepEqual(result, { ok: false, error: fixture.expected });
        assert.equal(JSON.stringify(result).includes("SECRET_"), false);
      } finally {
        restore();
      }
    });
  }
});

test("PGY runtime classifies resolved business risk responses", async (t) => {
  const cases = [
    {
      name: "rate limit",
      response: { code: 429, msg: "请求频繁" },
      expected: "rate_limited"
    },
    {
      name: "forbidden",
      response: { code: -10000, msg: "denied" },
      expected: "forbidden"
    },
    {
      name: "verification",
      response: { code: 300012, msg: "请完成安全验证" },
      expected: "verification_required"
    }
  ];

  for (const [index, fixture] of cases.entries()) {
    await t.test(fixture.name, async () => {
      const restore = installPageFixture({
        onBloggerDetail() {
          return fixture.response;
        }
      });
      try {
        assert.deepEqual(await invokeXiaohongshuPgyPageRuntime({
          kind: "request",
          operation_id: `pgy_resolved_risk_${index}`,
          method: "GET",
          path: XIAOHONGSHU_PGY_BLOGGER_DETAIL_PATH,
          entries: [["user_id", USER_ID]]
        }), {
          ok: false,
          error: fixture.expected
        });
      } finally {
        restore();
      }
    });
  }
});

test("PGY blogger list uses local brand identity and one wrapper per stage", async () => {
  const restore = installPageFixture();
  try {
    const trackResult = await invokeXiaohongshuPgyPageRuntime({
      kind: "request",
      operation_id: "pgy_blogger_list_fixture",
      method: "POST",
      path: XIAOHONGSHU_PGY_BLOGGER_LIST_PATH,
      stage: "track",
      entries: [
        ["page_num", "2"],
        ["page_size", "25"],
        ["fans_number_lower", "10000"],
        ["fans_number_upper", "1000000"]
      ]
    });
    assert.deepEqual(trackResult, {
      ok: true,
      payload: {
        brand_user_id: USER_ID,
        track_id: "track-2"
      }
    });
    assert.deepEqual(restore.wrapperCalls, ["blogger_track"]);

    assert.deepEqual(await invokeXiaohongshuPgyPageRuntime({
      kind: "request",
      operation_id: "pgy_blogger_list_fixture",
      method: "POST",
      path: XIAOHONGSHU_PGY_BLOGGER_LIST_PATH,
      stage: "list",
      brand_user_id: trackResult.payload.brand_user_id,
      track_id: trackResult.payload.track_id,
      entries: [
        ["page_num", "2"],
        ["page_size", "25"],
        ["fans_number_lower", "10000"],
        ["fans_number_upper", "1000000"]
      ]
    }), {
      ok: true,
      payload: {
        brandUserId: USER_ID,
        pageNum: 2,
        pageSize: 25,
        trackId: "track-2",
        endpoint: "/api/solar/cooperator/blogger/v2"
      }
    });
    assert.deepEqual(restore.wrapperCalls, ["blogger_track", "blogger_list"]);

    assert.deepEqual(await invokeXiaohongshuPgyPageRuntime({
      kind: "request",
      operation_id: "pgy_blogger_list_unsplit_fixture",
      method: "POST",
      path: XIAOHONGSHU_PGY_BLOGGER_LIST_PATH,
      entries: []
    }), {
      ok: false,
      error: "invalid_request"
    });
  } finally {
    restore();
  }
});

test("PGY blogger list starts track and list through the shared serial policy", async () => {
  let clock = 1000;
  const delays = [];
  const starts = [];
  const requestPolicy = new SerialRequestPolicy({
    now: () => clock,
    delay: async (milliseconds) => {
      delays.push(milliseconds);
      clock += milliseconds;
    }
  });
  const adapter = new XiaohongshuPgySessionAdapter({
    chromeApi: {},
    requestPolicy
  });
  adapter.pickTab = async () => ({
    id: 42,
    status: "complete",
    url: XIAOHONGSHU_PGY_LOGIN_URL
  });
  adapter.runInPage = async (_tabID, input) => {
    starts.push({ stage: input.stage, at: clock });
    if (input.stage === "track") {
      return {
        ok: true,
        payload: {
          brand_user_id: USER_ID,
          track_id: "track-fixture"
        }
      };
    }
    return {
      ok: true,
      payload: {
        brandUserId: input.brand_user_id,
        trackId: input.track_id
      }
    };
  };

  assert.deepEqual(await adapter.routeRequest({
    method: "POST",
    path: XIAOHONGSHU_PGY_BLOGGER_LIST_PATH,
    entries: [["brand_user_id", USER_ID]],
    referer: XIAOHONGSHU_PGY_LOGIN_URL
  }), {
    payload: {
      brandUserId: USER_ID,
      trackId: "track-fixture"
    }
  });
  assert.deepEqual(delays, [DEFAULT_MINIMUM_START_INTERVAL_MS]);
  assert.deepEqual(starts, [
    { stage: "track", at: 1000 },
    {
      stage: "list",
      at: 1000 + DEFAULT_MINIMUM_START_INTERVAL_MS
    }
  ]);
});

test("PGY blogger list stage errors keep bounded risk classification", async () => {
  const restore = installPageFixture({
    onBloggerTrack() {
      const error = new Error("HTTPServerError");
      error.status = 403;
      error.response = {
        data: {
          status: 429,
          msg: "SECRET_TRACK_RATE_LIMIT"
        }
      };
      throw error;
    }
  });
  try {
    const result = await invokeXiaohongshuPgyPageRuntime({
      kind: "request",
      operation_id: "pgy_blogger_track_error_fixture",
      method: "POST",
      path: XIAOHONGSHU_PGY_BLOGGER_LIST_PATH,
      stage: "track",
      entries: [["brand_user_id", USER_ID]]
    });
    assert.deepEqual(result, { ok: false, error: "rate_limited" });
    assert.equal(JSON.stringify(result).includes("SECRET_"), false);
    assert.deepEqual(restore.wrapperCalls, ["blogger_track"]);
  } finally {
    restore();
  }
});

test("PGY blogger notes uses the OpenAPI order type default", async () => {
  const restore = installPageFixture();
  try {
    assert.deepEqual(await invokeXiaohongshuPgyPageRuntime({
      kind: "request",
      operation_id: "pgy_blogger_notes_default_fixture",
      method: "GET",
      path: XIAOHONGSHU_PGY_BLOGGER_NOTES_PATH,
      entries: [["user_id", USER_ID]]
    }), {
      ok: true,
      payload: {
        userId: USER_ID,
        advertiseSwitch: 1,
        orderType: 1,
        pageNumber: 1,
        pageSize: 20,
        noteType: 0,
        endpoint: "/api/solar/kol/data_v2/notes_detail"
      }
    });
  } finally {
    restore();
  }
});

test("PGY list-stage risk latches while session probes stay available", async () => {
  const adapter = new XiaohongshuPgySessionAdapter({
    chromeApi: {},
    requestPolicy: new SerialRequestPolicy({ minimumStartIntervalMs: 0 })
  });
  let requestExecutions = 0;
  let sessionExecutions = 0;
  adapter.pickTab = async () => ({
    id: 41,
    status: "complete",
    url: XIAOHONGSHU_PGY_LOGIN_URL
  });
  adapter.pgyTabs = async () => [{
    id: 41,
    status: "complete",
    url: XIAOHONGSHU_PGY_LOGIN_URL,
    windowId: 7
  }];
  adapter.runInPage = async (_tabID, input) => {
    if (input.kind === "session") {
      sessionExecutions += 1;
      return {
        ok: true,
        payload: {
          fingerprint: { cookie_enabled: true },
          logged_in: true,
          request_ready: true,
          verification_required: false
        }
      };
    }
    requestExecutions += 1;
    if (input.stage === "track") {
      return {
        ok: true,
        payload: {
          brand_user_id: USER_ID,
          track_id: "track-before-forbidden"
        }
      };
    }
    return { ok: false, error: "forbidden" };
  };
  const message = {
    method: "POST",
    path: XIAOHONGSHU_PGY_BLOGGER_LIST_PATH,
    entries: [["brand_user_id", USER_ID]],
    referer: XIAOHONGSHU_PGY_LOGIN_URL
  };

  assert.deepEqual(await adapter.routeRequest(message), {
    error: "forbidden"
  });
  assert.deepEqual(await adapter.routeRequest(message), {
    error: "forbidden"
  });
  assert.equal(requestExecutions, 2);
  assert.deepEqual(await adapter.routeSession(), {
    payload: {
      fingerprint: { cookie_enabled: true },
      logged_in: true,
      request_ready: true,
      verification_required: false
    }
  });
  assert.equal(sessionExecutions, 1);
});
