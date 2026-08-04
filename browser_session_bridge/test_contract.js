import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import test from "node:test";

import { DouyinSessionAdapter } from "./adapters/douyin/adapter.js";
import {
  validDouyinReferer,
  validDouyinRequest
} from "./adapters/douyin/contract.js";
import { invokeDouyinPageRuntime } from "./adapters/douyin/page_runtime.js";
import { XiaohongshuSessionAdapter } from "./adapters/xiaohongshu/adapter.js";
import {
  XIAOHONGSHU_COLLECTED_NOTES_PATH,
  XIAOHONGSHU_COMMENT_PATH,
  XIAOHONGSHU_FEED_PATH,
  XIAOHONGSHU_HOMEFEED_CATEGORY_PATH,
  XIAOHONGSHU_HOMEFEED_PATH,
  XIAOHONGSHU_SEARCH_HOTLIST_PATH,
  XIAOHONGSHU_SEARCH_NOTES_PATH,
  XIAOHONGSHU_SEARCH_RECOMMEND_PATH,
  XIAOHONGSHU_SEARCH_USERS_PATH,
  XIAOHONGSHU_SUB_COMMENT_PATH,
  XIAOHONGSHU_USER_INFO_PATH,
  XIAOHONGSHU_USER_POSTED_PATH,
  sameXiaohongshuRequestContext,
  validXiaohongshuRequest
} from "./adapters/xiaohongshu/contract.js";
import { invokeXiaohongshuPageRuntime } from "./adapters/xiaohongshu/page_runtime.js";
import {
  BROWSER_INSTANCE_SUPERSEDED_CLOSE_CODE,
  LocalSessionBridgeClient
} from "./core/local_bridge_v2.js";
import {
  FAST_DISCOVERY_DOCUMENT_PATH,
  FAST_DISCOVERY_INTERVAL_MS,
  FAST_DISCOVERY_PROBE_TYPE,
  createFastDiscoveryController
} from "./core/fast_discovery.js";
import {
  BRIDGE_PROTOCOL_VERSION,
  generateBrowserInstanceId,
  normalizeLoopbackBridgeUrl,
  validBrowserInstanceId
} from "./core/protocol.js";
import {
  BRIDGE_RECONNECT_ALARM,
  BRIDGE_RECONNECT_PERIOD_MINUTES,
  installReconnectAlarm
} from "./core/reconnect_alarm.js";
import {
  DEFAULT_MINIMUM_START_INTERVAL_MS,
  SerialRequestPolicy
} from "./core/serial_request_policy.js";

test("manifest pins cache-busting entry points and wire protocol v4", () => {
  const manifest = JSON.parse(
    readFileSync(new URL("./manifest.json", import.meta.url), "utf8")
  );
  const worker = readFileSync(
    new URL(`./${manifest.background.service_worker}`, import.meta.url),
    "utf8"
  );
  const popup = readFileSync(
    new URL(`./${manifest.action.default_popup}`, import.meta.url),
    "utf8"
  );

  assert.equal(manifest.version, "1.0.1");
  assert.equal(manifest.background.service_worker, "service_worker_v2.js");
  assert.match(worker, /core\/local_bridge_v2\.js/);
  assert.match(popup, /popup_v2\.js/);
  assert.equal(BRIDGE_PROTOCOL_VERSION, 4);
});

test("platform adapters cannot mutate tabs or poll page readiness", () => {
  const adaptersURL = new URL("./adapters/", import.meta.url);
  for (const entry of readdirSync(adaptersURL, { withFileTypes: true })) {
    if (!entry.isDirectory()) {
      continue;
    }
    const adapterURL = new URL(`${entry.name}/adapter.js`, adaptersURL);
    let source;
    try {
      source = readFileSync(adapterURL, "utf8");
    } catch (error) {
      if (error && error.code === "ENOENT") {
        continue;
      }
      throw error;
    }
    for (const forbidden of [
      ".tabs.create",
      ".tabs.update",
      ".tabs.reload",
      "routeOpenLogin",
      "waitForTab"
    ]) {
      assert.equal(source.includes(forbidden), false, `${entry.name}: ${forbidden}`);
    }
    const runtimeURL = new URL(`${entry.name}/page_runtime.js`, adaptersURL);
    let runtimeSource;
    try {
      runtimeSource = readFileSync(runtimeURL, "utf8");
    } catch (error) {
      if (error && error.code === "ENOENT") {
        continue;
      }
      throw error;
    }
    for (const forbidden of ["DISCOVERY_ATTEMPTS", "waitForOperation"]) {
      assert.equal(
        runtimeSource.includes(forbidden),
        false,
        `${entry.name}/page_runtime.js: ${forbidden}`
      );
    }
    if (entry.name === "linkedin") {
      assert.equal(runtimeSource.includes("setTimeout"), false, "linkedin 页面快照不得等待");
    }
  }
});

test("browser instance IDs use strict 128-bit lowercase hexadecimal format", () => {
  const first = generateBrowserInstanceId();
  const second = generateBrowserInstanceId();

  assert.equal(validBrowserInstanceId(first), true);
  assert.equal(validBrowserInstanceId(second), true);
  assert.notEqual(first, second);
  assert.equal(validBrowserInstanceId(first.toUpperCase()), false);
  assert.equal(validBrowserInstanceId("01234567-89ab-cdef-0123-456789abcdef"), false);
  assert.equal(validBrowserInstanceId("f".repeat(31)), false);
});

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

  emit(...args) {
    for (const listener of [...this.listeners]) {
      listener(...args);
    }
  }
}

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    this.listeners = new Map();
    this.sent = [];
    MockWebSocket.instances.push(this);
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  emit(type, value = {}) {
    if (type === "open") {
      this.readyState = MockWebSocket.OPEN;
    }
    for (const listener of this.listeners.get(type) || []) {
      listener(value);
    }
  }

  send(source) {
    if (this.readyState !== MockWebSocket.OPEN) {
      throw new Error("socket is not open");
    }
    this.sent.push(JSON.parse(source));
  }

  close() {
    this.readyState = MockWebSocket.CLOSING;
  }
}

function createStorage(initial = {}) {
  const values = { ...initial };
  return {
    values,
    async get(keys) {
      return Object.fromEntries(keys.map((key) => [key, values[key]]));
    },
    async set(next) {
      Object.assign(values, next);
    },
    async remove(keys) {
      for (const key of Array.isArray(keys) ? keys : [keys]) {
        delete values[key];
      }
    }
  };
}

function createBridgeChrome(initial = {}) {
  const local = createStorage(initial);
  return { storage: { local } };
}

function createAlarmChrome() {
  const created = [];
  return {
    created,
    runtime: {
      onInstalled: new MockEvent(),
      onStartup: new MockEvent()
    },
    alarms: {
      onAlarm: new MockEvent(),
      create(name, details) {
        created.push({ name, details });
      }
    }
  };
}

function createFastDiscoveryChrome() {
  const createCalls = [];
  let documentOpen = false;
  const chromeApi = {
    runtime: {
      id: "bridgeextension",
      getURL(path) {
        return `chrome-extension://bridgeextension/${path}`;
      }
    },
    offscreen: {
      async hasDocument() {
        return documentOpen;
      },
      async createDocument(options) {
        createCalls.push(options);
        documentOpen = true;
      }
    }
  };
  return { chromeApi, createCalls };
}

function createAdapterChrome(initialTab, pageResult) {
  const removed = new MockEvent();
  const updated = new MockEvent();
  const calls = [];
  const tabs = initialTab ? [initialTab] : [];
  let nextTabID = 100;
  return {
    calls,
    tabs: {
      onRemoved: removed,
      onUpdated: updated,
      async query() {
        return [...tabs];
      },
      async get(tabId) {
        return tabs.find((tab) => tabId === tab.id) || null;
      },
      async update(tabId, changes) {
        calls.push({ type: "tabs.update", tabId, changes });
        const tab = tabs.find((item) => tabId === item.id);
        if (!tab) {
          return null;
        }
        Object.assign(tab, changes);
        return tab;
      },
      async create(changes) {
        calls.push({ type: "tabs.create", changes });
        const tab = {
          id: nextTabID,
          status: "complete",
          windowId: 1,
          ...changes
        };
        nextTabID += 1;
        tabs.push(tab);
        return tab;
      }
    },
    windows: {
      async update(windowId, changes) {
        calls.push({ type: "windows.update", windowId, changes });
      }
    },
    scripting: {
      async executeScript(details) {
        calls.push({ type: "executeScript", details });
        const result = typeof pageResult === "function"
          ? await pageResult(details)
          : pageResult;
        return [{ result }];
      }
    }
  };
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function waitFor(predicate, timeout = 1000) {
  const deadline = Date.now() + timeout;
  while (!predicate()) {
    if (Date.now() >= deadline) {
      throw new Error("fixture_timeout");
    }
    await delay(1);
  }
}

function createXiaohongshuWebpackRuntime(onRequest, {
  comments = true,
  userPosted = false,
  searchNotes = false,
  searchTrending = false,
  feed = false,
  userInfo = false,
  collectedNotes = false
} = {}) {
  const fixturePaths = {
    WEB_AI_SEARCH_NOTES_V2: "/api/sns/web/v2/search/notes",
    WEB_AI_SEARCH_QUERY_TRENDING: "/api/sns/web/v1/search/trending/query"
  };
  const moduleFactories = {
    ...(comments ? { fixture_api(module) {
      function getCommentPage(options = {}) {
        const path = "/api/sns/web/v2/comment/page";
        return onRequest(path, options);
      }
      function getSubCommentPage(options = {}) {
        const path = "/api/sns/web/v2/comment/sub/page";
        return onRequest(path, options);
      }
      Object.defineProperties(module.exports, {
        arbitraryCommentExport: {
          enumerable: true,
          get() {
            return getCommentPage;
          }
        },
        arbitrarySubCommentExport: {
          enumerable: true,
          get() {
            return getSubCommentPage;
          }
        }
      });
    } } : {}),
    ...(userPosted ? { fixture_user_posted(module) {
      function getUserPosted(options = {}) {
        const path = "/api/sns/web/v1/user_posted";
        return onRequest(path, options);
      }
      module.exports.arbitraryUserPostedExport = getUserPosted;
    } } : {}),
    ...(searchNotes ? { fixture_search_notes(module) {
      function getAiSearchNotesV2(body, options = {}) {
        const transportKey = "WEB_AI_SEARCH_NOTES_V2";
        return onRequest(fixturePaths[transportKey], body, options);
      }
      module.exports.arbitrarySearchNotesExport = getAiSearchNotesV2;
    } } : {}),
    ...(searchTrending ? { fixture_search_trending(module) {
      function getAiSearchQueryTrending(input = {}) {
        const transportKey = "WEB_AI_SEARCH_QUERY_TRENDING";
        return onRequest(fixturePaths[transportKey], input);
      }
      module.exports.arbitrarySearchTrendingExport = getAiSearchQueryTrending;
    } } : {}),
    ...(feed ? { fixture_feed(module) {
      function postFeed(body, options = {}) {
        const path = "/api/sns/web/v1/feed";
        return onRequest(path, body, options);
      }
      module.exports.arbitraryFeedExport = postFeed;
    } } : {}),
    ...(userInfo ? { fixture_user_info(module) {
      function getUserInfo(options = {}) {
        const path = "/api/sns/web/v1/user/otherinfo";
        return onRequest(path, options);
      }
      module.exports.arbitraryUserInfoExport = getUserInfo;
    } } : {}),
    ...(collectedNotes ? { fixture_collected_notes(module) {
      function getCollectedNotes(options = {}) {
        const path = "/api/sns/web/v2/note/collect/page";
        return onRequest(path, options);
      }
      module.exports.arbitraryCollectedNotesExport = getCollectedNotes;
    } } : {})
  };
  const moduleCache = {};
  function webpackRequire(moduleID) {
    if (moduleCache[moduleID]) {
      return moduleCache[moduleID].exports;
    }
    const factory = webpackRequire.m[moduleID];
    if (typeof factory !== "function") {
      throw new Error(`fixture module ${String(moduleID)} is unavailable`);
    }
    const module = { exports: {} };
    moduleCache[moduleID] = module;
    factory(module, module.exports, webpackRequire);
    return module.exports;
  }
  webpackRequire.m = moduleFactories;

  const chunks = [];
  chunks.push = function pushWebpackChunk(chunk) {
    const modules = chunk[1] || {};
    Object.assign(webpackRequire.m, modules);
    return typeof chunk[2] === "function" ? chunk[2](webpackRequire) : undefined;
  };
  return chunks;
}

async function captureDouyinSessionState({
  store,
  initialState,
  renderData,
  avatarLinks = [],
  verificationVisible = false
} = {}) {
  const names = ["window", "navigator", "screen"];
  const previous = Object.fromEntries(
    names.map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)])
  );
  const images = avatarLinks.map((href) => ({
    closest(selector) {
      assert.equal(selector, "a[href]");
      return {
        getAttribute(name) {
          assert.equal(name, "href");
          return href;
        }
      };
    }
  }));
  const verificationFrame = {
    getBoundingClientRect() {
      return { width: 380, height: 348 };
    }
  };
  const verificationContainer = {
    getBoundingClientRect() {
      return { width: 1280, height: 720 };
    },
    querySelectorAll(selector) {
      assert.equal(selector, "iframe");
      return [verificationFrame];
    }
  };
  const windowValue = {
    __STORE__: store,
    INITIAL_STATE: initialState,
    document: {
      querySelector(selector) {
        assert.equal(selector, 'script#RENDER_DATA[type="application/json"]');
        return renderData === undefined ? null : { textContent: renderData };
      },
      querySelectorAll(selector) {
        assert.equal(
          selector,
          'a[href] [data-e2e="live-avatar"][role="listitem"] img'
        );
        return images;
      },
      getElementById(id) {
        assert.equal(id, "captcha_container");
        return verificationVisible ? verificationContainer : null;
      }
    },
    getComputedStyle() {
      return { display: "block", visibility: "visible", opacity: "1" };
    },
    location: { origin: "https://www.douyin.com" },
    innerWidth: 1280,
    innerHeight: 720,
    outerWidth: 1280,
    outerHeight: 720,
    devicePixelRatio: 2
  };
  const navigatorValue = {
    userAgent: "fixture-agent",
    language: "zh-CN",
    languages: ["zh-CN"],
    platform: "MacIntel",
    vendor: "Google Inc.",
    cookieEnabled: true,
    onLine: true,
    hardwareConcurrency: 8,
    deviceMemory: 8
  };
  const screenValue = {
    width: 1280,
    height: 720,
    availWidth: 1280,
    availHeight: 680,
    colorDepth: 24,
    pixelDepth: 24
  };

  Object.defineProperties(globalThis, {
    window: { configurable: true, value: windowValue },
    navigator: { configurable: true, value: navigatorValue },
    screen: { configurable: true, value: screenValue }
  });
  try {
    const result = await invokeDouyinPageRuntime({ kind: "session" });
    assert.equal(result.ok, true);
    return result.payload;
  } finally {
    for (const name of names) {
      const descriptor = previous[name];
      if (descriptor) {
        Object.defineProperty(globalThis, name, descriptor);
      } else {
        delete globalThis[name];
      }
    }
  }
}

async function captureDouyinLoginState(options = {}) {
  return (await captureDouyinSessionState(options)).logged_in;
}

async function invokeXiaohongshuFixture(input, {
  initialState,
  cookie = "",
  verificationVisible = false,
  signedInNavigation = false,
  href = "https://www.xiaohongshu.com/explore/0123456789abcdef01234567",
  webpackRuntime = null
} = {}) {
  const names = ["window", "navigator", "screen"];
  const previous = Object.fromEntries(
    names.map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)])
  );
  const verificationFrame = {
    getBoundingClientRect() {
      return { width: 380, height: 348 };
    }
  };
  const navigationElement = (text = "") => ({
    textContent: text,
    getAttribute(name) {
      return name === "aria-label" ? text : null;
    },
    getBoundingClientRect() {
      return { width: 40, height: 40 };
    }
  });
  const windowValue = {
    __INITIAL_STATE__: initialState,
    document: {
      cookie,
      querySelectorAll(selector) {
        switch (selector) {
        case 'iframe[src*="captcha"], [id*="captcha"] iframe, [class*="captcha"] iframe':
          return verificationVisible ? [verificationFrame] : [];
        case 'a[href^="/user/profile/"]':
          return signedInNavigation ? [navigationElement("我")] : [];
        case 'a[href^="/notification"]':
        case 'a[href^="/chat"]':
          return signedInNavigation ? [navigationElement()] : [];
        default:
          assert.fail(`unexpected selector ${selector}`);
        }
      }
    },
    getComputedStyle() {
      return { display: "block", visibility: "visible", opacity: "1" };
    },
    location: {
      origin: "https://www.xiaohongshu.com",
      href
    },
    innerWidth: 1280,
    innerHeight: 720,
    outerWidth: 1280,
    outerHeight: 720,
    devicePixelRatio: 2
  };
  if (webpackRuntime) {
    windowValue.webpackChunkxhs_pc_web = webpackRuntime;
  }
  const navigatorValue = {
    userAgent: "fixture-agent",
    language: "zh-CN",
    languages: ["zh-CN"],
    platform: "MacIntel",
    vendor: "Google Inc.",
    cookieEnabled: true,
    onLine: true,
    hardwareConcurrency: 8,
    deviceMemory: 8
  };
  const screenValue = {
    width: 1280,
    height: 720,
    availWidth: 1280,
    availHeight: 680,
    colorDepth: 24,
    pixelDepth: 24
  };

  Object.defineProperties(globalThis, {
    window: { configurable: true, value: windowValue },
    navigator: { configurable: true, value: navigatorValue },
    screen: { configurable: true, value: screenValue }
  });
  try {
    return await invokeXiaohongshuPageRuntime(input);
  } finally {
    for (const name of names) {
      const descriptor = previous[name];
      if (descriptor) {
        Object.defineProperty(globalThis, name, descriptor);
      } else {
        delete globalThis[name];
      }
    }
  }
}

test("loopback protocol only accepts the broker's IPv4 URL", () => {
  assert.equal(normalizeLoopbackBridgeUrl("ws://127.0.0.1:18765"), "ws://127.0.0.1:18765");
  assert.equal(normalizeLoopbackBridgeUrl("ws://localhost:18765"), null);
  assert.equal(normalizeLoopbackBridgeUrl("wss://127.0.0.1:18765"), null);
});

test("Douyin user requests accept the real MS4wLjAB sec_uid referer prefix", () => {
  const secUserID = `MS4wLjAB${"a".repeat(40)}`;
  const referer = `https://www.douyin.com/user/${secUserID}`;
  assert.equal(validDouyinReferer("/aweme/v1/web/aweme/post/", referer), true);
  assert.equal(
    validDouyinReferer(
      "/aweme/v1/web/aweme/post/",
      `https://www.douyin.com/user/MS4w.LjAB${"a".repeat(40)}`
    ),
    false
  );
  assert.equal(validDouyinRequest({
    path: "/aweme/v1/web/aweme/post/",
    entries: [["sec_user_id", secUserID], ["max_cursor", "0"], ["count", "20"]],
    referer
  }), true);
});

test("Douyin discovery requests use fixed hashtag, music, mix, and series contracts", () => {
  const hashtagID = "1788527695713283";
  const musicID = "7637698197799930678";
  const mixID = "7346613166719109130";
  const seriesID = "7661857744487450667";
  const seriesAuthor = "MS4wLjABBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB";
  const cases = [
    {
      path: "/aweme/v1/web/challenge/detail/",
      entries: [["ch_id", hashtagID], ["query_type", "0"]],
      referer: `https://www.douyin.com/hashtag/${hashtagID}`
    },
    {
      path: "/aweme/v1/web/challenge/aweme/",
      entries: [
        ["ch_id", hashtagID],
        ["hashtag_name", "外道之歌"],
        ["query_type", "0"],
        ["sort_type", "0"],
        ["offset", "0"],
        ["cursor", "0"],
        ["count", "20"]
      ],
      referer: `https://www.douyin.com/hashtag/${hashtagID}`
    },
    {
      path: "/aweme/v1/web/music/detail/",
      entries: [["music_id", musicID], ["scene", "1"]],
      referer: `https://www.douyin.com/music/${musicID}`
    },
    {
      path: "/aweme/v1/web/music/aweme/",
      entries: [["music_id", musicID], ["cursor", "0"], ["count", "10"]],
      referer: `https://www.douyin.com/music/${musicID}`
    },
    {
      path: "/aweme/v1/web/mix/detail/",
      entries: [["mix_id", mixID], ["req_from", "channel_pc_web"]],
      referer: `https://www.douyin.com/collection/${mixID}/1`
    },
    {
      path: "/aweme/v1/web/mix/aweme/",
      entries: [["mix_id", mixID], ["cursor", "0"], ["count", "12"]],
      referer: `https://www.douyin.com/collection/${mixID}`
    },
    {
      path: "/aweme/v1/web/series/detail/",
      entries: [["series_id", seriesID], ["req_from", "channel_pc_web"]],
      referer: `https://www.douyin.com/series?series_id=${seriesID}`
    },
    {
      path: "/aweme/v1/web/series/list/",
      entries: [
        ["sec_user_id", seriesAuthor],
        ["req_from", "channel_pc_web"],
        ["cursor", "0"],
        ["count", "12"]
      ],
      referer: `https://www.douyin.com/user/${seriesAuthor}`
    },
    {
      path: "/aweme/v1/web/series/aweme/",
      entries: [
        ["series_id", seriesID],
        ["pull_type", "2"],
        ["cursor", "0"],
        ["count", "12"]
      ],
      referer: `https://www.douyin.com/series?series_id=${seriesID}`
    }
  ];

  for (const request of cases) {
    assert.equal(validDouyinRequest(request), true, request.path);
    assert.equal(validDouyinReferer(request.path, request.referer), true, request.path);
    assert.equal(validDouyinRequest({
      ...request,
      entries: [...request.entries, ["unknown_parameter", "1"]]
    }), false, `${request.path} rejects unknown parameters`);
    assert.equal(validDouyinRequest({
      ...request,
      referer: `${request.referer}?redirect=https%3A%2F%2Fexample.test`
    }), false, `${request.path} rejects unexpected referer query`);
  }

  assert.equal(validDouyinRequest({
    ...cases[0],
    referer: `https://www.douyin.com/music/${hashtagID}`
  }), false);
  assert.equal(validDouyinRequest({
    ...cases[2],
    referer: `https://www.douyin.com/hashtag/${musicID}`
  }), false);
  assert.equal(validDouyinRequest({
    ...cases[4],
    referer: `https://www.douyin.com/collection/${mixID}1/1`
  }), false);
  assert.equal(validDouyinRequest({
    ...cases[5],
    entries: [["mix_id", `${mixID}1`], ["cursor", "0"], ["count", "12"]]
  }), false);
  assert.equal(validDouyinRequest({
    ...cases[6],
    entries: [["series_id", `${seriesID}1`], ["req_from", "channel_pc_web"]]
  }), false);
  assert.equal(validDouyinRequest({
    ...cases[7],
    entries: [
      ["sec_user_id", `${seriesAuthor}x`],
      ["req_from", "channel_pc_web"],
      ["cursor", "0"],
      ["count", "12"]
    ]
  }), false);
  assert.equal(validDouyinRequest({
    ...cases[8],
    referer: `https://www.douyin.com/series?series_id=${seriesID}#episode`
  }), false);
});

test("Xiaohongshu contract accepts fixed comment operations with xsec only in referer", () => {
  const noteID = "0123456789abcdef01234567";
  const rootCommentID = "89abcdef0123456701234567";
  const referer = `https://www.xiaohongshu.com/explore/${noteID}`;
  const comments = {
    method: "GET",
    path: XIAOHONGSHU_COMMENT_PATH,
    entries: [
      ["note_id", noteID],
      ["cursor", ""],
      ["top_comment_id", ""],
      ["image_formats", "jpg,webp,avif"]
    ],
    referer,
    request_interval_ms: 3000
  };
  const replies = {
    method: "GET",
    path: XIAOHONGSHU_SUB_COMMENT_PATH,
    entries: [
      ["note_id", noteID],
      ["root_comment_id", rootCommentID],
      ["num", "10"],
      ["cursor", ""],
      ["top_comment_id", ""],
      ["image_formats", "jpg,webp,avif"]
    ],
    referer
  };

  assert.equal(validXiaohongshuRequest(comments), true);
  assert.equal(validXiaohongshuRequest(replies), true);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    request_interval_ms: -1
  }), false);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    request_interval_ms: 10001
  }), false);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    request_interval_ms: 1.5
  }), false);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    path: "/api/sns/web/v2/comment/page/extra"
  }), false);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    entries: [...comments.entries, ["xsec_token", "SECRET"]]
  }), false);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    entries: [...comments.entries, ["X-S", "SECRET"]]
  }), false);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    referer: `${referer}?xsec_token=SECRET_TOKEN%3D&xsec_source=pc_feed`
  }), true);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    referer: `${referer}?xsec_token=SECRET_TOKEN%3D&xsec_source=`
  }), true);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    referer: `${referer}?xsec_token=SECRET_TOKEN&redirect=https%3A%2F%2Fevil.test`
  }), false);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    referer: `${referer}?xsec_token=ONE&xsec_token=TWO`
  }), false);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    referer: `${referer}?xsec_token=SECRET_TOKEN&xsec_source=&xsec_source=pc_feed`
  }), false);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    referer: `${referer}?xsec_token=&xsec_source=`
  }), false);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    referer: `${referer}?xsec_source=`
  }), false);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    referer: `${referer}?xsec_token=BAD%20TOKEN`
  }), false);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    referer: `${referer}?xsec_token=${"a".repeat(513)}`
  }), false);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    referer: `https://user:password@www.xiaohongshu.com/explore/${noteID}`
  }), false);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    referer: `${referer}#xsec_token=SECRET_TOKEN`
  }), false);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    referer: "https://edith.xiaohongshu.com/api/sns/web/v2/comment/page"
  }), false);
  assert.equal(validXiaohongshuRequest({
    ...comments,
    referer: "https://www.xiaohongshu.com/explore/ffffffffffffffffffffffff"
  }), false);
  assert.equal(sameXiaohongshuRequestContext(
    `${referer}?xsec_token=BROWSER_ONLY`,
    referer
  ), true);
  assert.equal(sameXiaohongshuRequestContext(
    referer,
    `${referer}?xsec_token=REQUESTED&xsec_source=pc_feed`
  ), false);
  assert.equal(sameXiaohongshuRequestContext(
    `${referer}?xsec_token=REQUESTED&xsec_source=pc_feed`,
    `${referer}?xsec_token=REQUESTED&xsec_source=pc_feed`
  ), true);
  assert.equal(sameXiaohongshuRequestContext(
    `${referer}?xsec_token=REQUESTED&xsec_source=`,
    `${referer}?xsec_token=REQUESTED&xsec_source=`
  ), true);
  assert.equal(sameXiaohongshuRequestContext(
    `${referer}?xsec_token=REQUESTED&xsec_source=pc_feed`,
    `${referer}?xsec_token=REQUESTED&xsec_source=`
  ), true);
  assert.equal(sameXiaohongshuRequestContext(
    `${referer}?xsec_token=REQUESTED`,
    `${referer}?xsec_token=REQUESTED&xsec_source=`
  ), false);
  assert.equal(sameXiaohongshuRequestContext(
    `${referer}?xsec_token=OTHER&xsec_source=pc_feed`,
    `${referer}?xsec_token=REQUESTED&xsec_source=`
  ), false);
  assert.equal(sameXiaohongshuRequestContext(
    `${referer}?xsec_token=OTHER&xsec_source=pc_feed`,
    `${referer}?xsec_token=REQUESTED&xsec_source=pc_feed`
  ), false);
});

test("Xiaohongshu contract binds catalog operations to fixed methods and page contexts", () => {
  const noteID = "0123456789abcdef01234567";
  const userID = "89abcdef0123456701234567";
  const searchID = "search_fixture_123";
  assert.equal(XIAOHONGSHU_SEARCH_NOTES_PATH, "/api/sns/web/v2/search/notes");
  assert.equal(
    XIAOHONGSHU_SEARCH_HOTLIST_PATH,
    "/api/sns/web/v1/search/trending/query"
  );
  const cases = [
    ["GET", XIAOHONGSHU_USER_POSTED_PATH, [["user_id", userID]], `/user/profile/${userID}`],
    ["POST", XIAOHONGSHU_SEARCH_NOTES_PATH, [
      ["keyword", "typing"], ["page", "1"], ["page_size", "20"],
      ["search_id", searchID], ["sort", "general"], ["note_type", "0"]
    ], "/search_result"],
    ["POST", XIAOHONGSHU_FEED_PATH, [["note_id", noteID]], `/explore/${noteID}`],
    ["POST", XIAOHONGSHU_HOMEFEED_PATH, [
      ["num", "20"], ["need_filter_image", "true"]
    ], "/explore"],
    ["GET", XIAOHONGSHU_HOMEFEED_CATEGORY_PATH, [], "/explore"],
    ["GET", XIAOHONGSHU_SEARCH_HOTLIST_PATH, [], "/search_result"],
    ["GET", XIAOHONGSHU_SEARCH_RECOMMEND_PATH, [["keyword", "type"]], "/search_result"],
    ["POST", XIAOHONGSHU_SEARCH_USERS_PATH, [
      ["keyword", "type"], ["page", "1"], ["page_size", "20"], ["search_id", searchID]
    ], "/search_result"],
    ["GET", XIAOHONGSHU_USER_INFO_PATH, [["user_id", userID]], `/user/profile/${userID}`],
    ["GET", XIAOHONGSHU_COLLECTED_NOTES_PATH, [
      ["user_id", userID], ["num", "30"]
    ], `/user/profile/${userID}`]
  ];

  for (const [method, path, entries, pathname] of cases) {
    const request = {
      method,
      path,
      entries,
      referer: `https://www.xiaohongshu.com${pathname}`
    };
    assert.equal(validXiaohongshuRequest(request), true, path);
    assert.equal(validXiaohongshuRequest({
      ...request,
      method: method === "GET" ? "POST" : "GET"
    }), false, `${path} method`);
    assert.equal(validXiaohongshuRequest({
      ...request,
      body: {}
    }), false, `${path} body`);
  }

  assert.equal(validXiaohongshuRequest({
    method: "GET",
    path: XIAOHONGSHU_USER_INFO_PATH,
    entries: [["user_id", userID]],
    referer: `https://www.xiaohongshu.com/user/profile/${userID}` +
      "?xsec_token=PROFILE_TOKEN&xsec_source=pc_profile"
  }), true);
  assert.equal(validXiaohongshuRequest({
    method: "POST",
    path: XIAOHONGSHU_SEARCH_NOTES_PATH,
    entries: [
      ["keyword", "typing"], ["page", "1"], ["page_size", "20"],
      ["search_id", searchID]
    ],
    referer: "https://www.xiaohongshu.com/search_result?xsec_token=FORBIDDEN"
  }), false);
});

test("Xiaohongshu runtime reports login state without returning Cookie or xsec data", async () => {
  const result = await invokeXiaohongshuFixture(
    { kind: "session" },
    { cookie: "a1=DEVICE; web_session=BROWSER_ONLY_SESSION; xsec_token=NEVER_RETURN" }
  );
  assert.equal(result.ok, true);
  assert.equal(result.payload.logged_in, true);
  assert.equal(result.payload.request_ready, true);
  assert.equal(result.payload.verification_required, false);
  const encoded = JSON.stringify(result);
  assert.equal(encoded.includes("BROWSER_ONLY_SESSION"), false);
  assert.equal(encoded.includes("NEVER_RETURN"), false);

  const explicitLogout = await invokeXiaohongshuFixture(
    { kind: "session" },
    {
      initialState: { user: { loggedIn: false } },
      cookie: "web_session=STALE_SESSION"
    }
  );
  assert.equal(explicitLogout.payload.logged_in, false);
  assert.equal(explicitLogout.payload.request_ready, false);

  const visitor = await invokeXiaohongshuFixture(
    { kind: "session" },
    { cookie: "a1=BROWSER_ONLY_VISITOR_IDENTITY" }
  );
  assert.equal(visitor.payload.logged_in, false);
  assert.equal(visitor.payload.request_ready, true);

  const navigationLogin = await invokeXiaohongshuFixture(
    { kind: "session" },
    {
      initialState: { user: { loggedIn: false } },
      cookie: "a1=BROWSER_ONLY_VISITOR_IDENTITY",
      signedInNavigation: true
    }
  );
  assert.equal(navigationLogin.payload.logged_in, true);
  assert.equal(navigationLogin.payload.request_ready, true);
});

test("Xiaohongshu runtime discovers the page GET wrapper and strips browser secrets", async () => {
  const noteID = "0123456789abcdef01234567";
  const xsecToken = "BROWSER_ONLY_XSEC";
  const calls = [];
  const webpackRuntime = createXiaohongshuWebpackRuntime((path, options) => {
    calls.push({ path, options });
    return {
      success: true,
      cursor: "NEXT_CURSOR",
      next_cursor: "NORMAL_NEXT_CURSOR",
      comments: [{
        id: "comment-1",
        content: "fixture",
        cookie: "BROWSER_COOKIE",
        authorization: "Bearer BROWSER_AUTH"
      }],
      xsec_token: xsecToken,
      "X-S": "BROWSER_XS",
      "X-T": "BROWSER_XT",
      request_url: `${path}?xsec_token=${xsecToken}`,
      debug_message: `server echoed ${xsecToken}`,
      headers: {
        Authorization: "Bearer BROWSER_AUTH",
        cookie: "BROWSER_COOKIE"
      }
    };
  });
  const input = {
    kind: "request",
    operation_id: "xiaohongshu_runtime_fixture",
    method: "GET",
    path: XIAOHONGSHU_COMMENT_PATH,
    entries: [
      ["note_id", noteID],
      ["cursor", ""],
      ["top_comment_id", ""],
      ["image_formats", "jpg,webp,avif"]
    ]
  };
  const result = await invokeXiaohongshuFixture(input, {
    cookie: "a1=BROWSER_ONLY_VISITOR",
    href: `https://www.xiaohongshu.com/explore/${noteID}?xsec_token=${xsecToken}`,
    webpackRuntime
  });

  assert.equal(result.ok, true);
  assert.equal(result.payload.cursor, "NEXT_CURSOR");
  assert.equal(result.payload.next_cursor, "NORMAL_NEXT_CURSOR");
  assert.equal(Object.hasOwn(result.payload, "debug_message"), false);
  assert.deepEqual(result.payload.comments, [{ id: "comment-1", content: "fixture" }]);
  assert.equal(
    result.payload.request_url,
    "/api/sns/web/v2/comment/page"
  );
  const encoded = JSON.stringify(result);
  for (const secret of [
    xsecToken,
    "BROWSER_XS",
    "BROWSER_XT",
    "BROWSER_AUTH",
    "BROWSER_COOKIE",
    "BROWSER_ONLY_VISITOR"
  ]) {
    assert.equal(encoded.includes(secret), false);
  }
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, XIAOHONGSHU_COMMENT_PATH);
  assert.deepEqual(calls[0].options.params, {
    noteId: noteID,
    cursor: "",
    topCommentId: "",
    imageFormats: "jpg,webp,avif",
    xsecToken
  });
  assert.equal(calls[0].options.signal instanceof AbortSignal, true);
  assert.equal(calls[0].options.signal.aborted, false);
  assert.equal(calls[0].options.timeout, 15000);
  assert.equal(JSON.stringify(input).includes(xsecToken), false);
});

test("Xiaohongshu runtime maps typed GET and POST requests to independent page wrappers", async () => {
  const userID = "89abcdef0123456701234567";
  const getCalls = [];
  const getRuntime = createXiaohongshuWebpackRuntime((...args) => {
    getCalls.push(args);
    return { success: true, notes: [] };
  }, { comments: false, userPosted: true });
  const getResult = await invokeXiaohongshuFixture({
    kind: "request",
    operation_id: "xiaohongshu_user_posted_fixture",
    method: "GET",
    path: XIAOHONGSHU_USER_POSTED_PATH,
    entries: [
      ["user_id", userID],
      ["cursor", ""],
      ["num", "30"],
      ["image_formats", "jpg,webp,avif"]
    ]
  }, {
    cookie: "a1=BROWSER_ONLY_VISITOR",
    href: `https://www.xiaohongshu.com/user/profile/${userID}` +
      "?xsec_token=BROWSER_XSEC&xsec_source=pc_profile",
    webpackRuntime: getRuntime
  });
  assert.equal(getResult.ok, true);
  assert.equal(getCalls.length, 1);
  assert.deepEqual(getCalls[0][1].params, {
    userId: userID,
    cursor: "",
    num: 30,
    imageFormats: "jpg,webp,avif",
    xsecToken: "BROWSER_XSEC",
    xsecSource: "pc_profile"
  });

  const postCalls = [];
  const postRuntime = createXiaohongshuWebpackRuntime((...args) => {
    postCalls.push(args);
    return { success: true, items: [] };
  }, { comments: false, searchNotes: true });
  const postResult = await invokeXiaohongshuFixture({
    kind: "request",
    operation_id: "xiaohongshu_search_notes_fixture",
    method: "POST",
    path: XIAOHONGSHU_SEARCH_NOTES_PATH,
    entries: [
      ["keyword", "python typing"],
      ["page", "2"],
      ["page_size", "20"],
      ["search_id", "search_fixture_123"],
      ["sort", "time_descending"],
      ["note_type", "1"]
    ]
  }, {
    cookie: "a1=BROWSER_ONLY_VISITOR",
    href: "https://www.xiaohongshu.com/search_result",
    webpackRuntime: postRuntime
  });
  assert.equal(postResult.ok, true);
  assert.equal(postCalls.length, 1);
  assert.deepEqual(postCalls[0][1], {
    extFlags: [],
    filters: [],
    geo: "",
    imageFormats: ["jpg", "webp", "avif"],
    keyword: "python typing",
    page: 2,
    pageSize: 20,
    searchId: "search_fixture_123",
    sessionId: "",
    sort: "time_descending",
    noteType: 1
  });
  assert.equal(postCalls[0][2].signal instanceof AbortSignal, true);
  assert.equal(postCalls[0][2].timeout, 15000);
});

test("Xiaohongshu runtime executes a bare note request without borrowing another tab xsec", async () => {
  const noteID = "0123456789abcdef01234567";
  const otherNoteID = "89abcdef0123456701234567";
  const tabSecret = "UNRELATED_TAB_XSEC=";
  const calls = [];
  const webpackRuntime = createXiaohongshuWebpackRuntime((...args) => {
    calls.push(args);
    return {
      success: true,
      items: [{ id: noteID }],
      echo: `server echoed ${tabSecret}`,
      xsecToken: tabSecret
    };
  }, { comments: false, feed: true });

  const result = await invokeXiaohongshuFixture({
    kind: "request",
    operation_id: "xiaohongshu_session_note_fixture",
    method: "POST",
    path: XIAOHONGSHU_FEED_PATH,
    entries: [["note_id", noteID], ["image_formats", "jpg,webp,avif"]],
    context_mode: "session"
  }, {
    cookie: "a1=BROWSER_ONLY_VISITOR; web_session=BROWSER_ONLY_SESSION",
    href: `https://www.xiaohongshu.com/explore/${otherNoteID}` +
      `?xsec_token=${encodeURIComponent(tabSecret)}&xsec_source=pc_feed`,
    webpackRuntime
  });

  assert.deepEqual(result, {
    ok: true,
    payload: { success: true, items: [{ id: noteID }] }
  });
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0][1], {
    sourceNoteId: noteID,
    imageFormats: ["jpg", "webp", "avif"]
  });
  assert.equal(JSON.stringify(result).includes(tabSecret), false);
});

test("Xiaohongshu runtime maps hot-list to the current query-trending wrapper", async () => {
  const calls = [];
  const webpackRuntime = createXiaohongshuWebpackRuntime((...args) => {
    calls.push(args);
    return {
      success: true,
      queries: [{
        title: "今日热门",
        searchWord: "今日热门",
        displayType: "hot"
      }],
      hintWord: {
        title: "搜索小红书",
        type: "default",
        hintWordRequestId: "hint-fixture"
      },
      wordRequestId: "word-fixture"
    };
  }, { comments: false, searchTrending: true });

  const result = await invokeXiaohongshuFixture({
    kind: "request",
    operation_id: "xiaohongshu_search_trending_fixture",
    method: "GET",
    path: XIAOHONGSHU_SEARCH_HOTLIST_PATH,
    entries: []
  }, {
    cookie: "a1=BROWSER_ONLY_VISITOR; web_session=BROWSER_ONLY_SESSION",
    href: "https://www.xiaohongshu.com/search_result",
    initialState: { user: { loggedIn: true } },
    webpackRuntime
  });

  assert.equal(result.ok, true);
  assert.deepEqual(result.payload.queries, [{
    title: "今日热门",
    searchWord: "今日热门",
    displayType: "hot"
  }]);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], XIAOHONGSHU_SEARCH_HOTLIST_PATH);
  assert.deepEqual(calls[0][1].params, {
    source: "search",
    searchType: "trend",
    lastQuery: "",
    lastQueryTime: 0,
    wordRequestSituation: "FIRST_ENTER",
    hintWord: "",
    hintWordType: "",
    hintWordRequestId: ""
  });
  assert.equal(calls[0][1].signal instanceof AbortSignal, true);
  assert.equal(calls[0][1].timeout, 15000);
});

test("Xiaohongshu runtime consumes URL xsec for note and profile browser operations", async () => {
  const noteID = "0123456789abcdef01234567";
  const rootCommentID = "89abcdef0123456701234567";
  const userID = "fedcba987654321001234567";
  const xsecToken = "RUNTIME_XSEC_TOKEN=";
  const noteSource = "";
  const profileSource = "pc_profile";
  const calls = [];
  const webpackRuntime = createXiaohongshuWebpackRuntime((...args) => {
    calls.push(args);
    return { success: true, data: { items: [] } };
  }, {
    comments: true,
    userPosted: true,
    feed: true,
    userInfo: true,
    collectedNotes: true
  });
  const noteHref = `https://www.xiaohongshu.com/explore/${noteID}` +
    `?xsec_token=${encodeURIComponent(xsecToken)}&xsec_source=${noteSource}`;
  const profileHref = `https://www.xiaohongshu.com/user/profile/${userID}` +
    `?xsec_token=${encodeURIComponent(xsecToken)}&xsec_source=${profileSource}`;
  const requests = [
    {
      operation_id: "xhs_xsec_comments",
      method: "GET",
      path: XIAOHONGSHU_COMMENT_PATH,
      entries: [["note_id", noteID], ["cursor", ""]],
      href: noteHref
    },
    {
      operation_id: "xhs_xsec_replies",
      method: "GET",
      path: XIAOHONGSHU_SUB_COMMENT_PATH,
      entries: [
        ["note_id", noteID],
        ["root_comment_id", rootCommentID],
        ["num", "10"],
        ["cursor", ""]
      ],
      href: noteHref
    },
    {
      operation_id: "xhs_xsec_note_api",
      method: "POST",
      path: XIAOHONGSHU_FEED_PATH,
      entries: [["note_id", noteID], ["image_formats", "jpg,webp,avif"]],
      href: noteHref
    },
    {
      operation_id: "xhs_xsec_user_posts",
      method: "GET",
      path: XIAOHONGSHU_USER_POSTED_PATH,
      entries: [["user_id", userID], ["cursor", ""], ["num", "20"]],
      href: profileHref
    },
    {
      operation_id: "xhs_xsec_favorites",
      method: "GET",
      path: XIAOHONGSHU_COLLECTED_NOTES_PATH,
      entries: [["user_id", userID], ["cursor", ""], ["num", "20"]],
      href: profileHref
    },
    {
      operation_id: "xhs_xsec_profile_api",
      method: "GET",
      path: XIAOHONGSHU_USER_INFO_PATH,
      entries: [["user_id", userID]],
      href: profileHref
    }
  ];

  for (const request of requests) {
    const result = await invokeXiaohongshuFixture({
      kind: "request",
      operation_id: request.operation_id,
      method: request.method,
      path: request.path,
      entries: request.entries
    }, {
      cookie: "a1=BROWSER_ONLY_VISITOR; web_session=BROWSER_ONLY_SESSION",
      href: request.href,
      webpackRuntime
    });
    assert.equal(result.ok, true, request.path);
    assert.equal(JSON.stringify(result).includes(xsecToken), false, request.path);
  }

  const byPath = new Map(calls.map((call) => [call[0], call]));
  assert.equal(byPath.get(XIAOHONGSHU_COMMENT_PATH)[1].params.xsecToken, xsecToken);
  assert.equal(byPath.get(XIAOHONGSHU_SUB_COMMENT_PATH)[1].params.xsecToken, xsecToken);
  assert.equal(byPath.get(XIAOHONGSHU_FEED_PATH)[1].xsecToken, xsecToken);
  assert.equal(byPath.get(XIAOHONGSHU_FEED_PATH)[1].xsecSource, noteSource);
  for (const path of [
    XIAOHONGSHU_USER_POSTED_PATH,
    XIAOHONGSHU_COLLECTED_NOTES_PATH,
    XIAOHONGSHU_USER_INFO_PATH
  ]) {
    assert.equal(byPath.get(path)[1].params.xsecToken, xsecToken, path);
    assert.equal(byPath.get(path)[1].params.xsecSource, profileSource, path);
  }
});

test("Xiaohongshu runtime rejects credential, fragment, and non-xsec URL state", async () => {
  const noteID = "0123456789abcdef01234567";
  let calls = 0;
  const webpackRuntime = createXiaohongshuWebpackRuntime(() => {
    calls += 1;
    return { success: true, comments: [] };
  });
  const secret = "MALICIOUS_XSEC_TOKEN";
  const hrefs = [
    `https://www.xiaohongshu.com/explore/${noteID}?xsec_token=${secret}&redirect=evil`,
    `https://www.xiaohongshu.com/explore/${noteID}?xsec_token=${secret}&xsec_token=OTHER`,
    `https://www.xiaohongshu.com/explore/${noteID}?xsec_token=${secret}` +
      "&xsec_source=&xsec_source=pc_feed",
    `https://www.xiaohongshu.com/explore/${noteID}?xsec_token=&xsec_source=`,
    `https://www.xiaohongshu.com/explore/${noteID}?xsec_source=`,
    `https://www.xiaohongshu.com/explore/${noteID}?xsec_token=BAD%20TOKEN`,
    `https://www.xiaohongshu.com/explore/${noteID}?xsec_token=${"a".repeat(513)}`,
    `https://user:${secret}@www.xiaohongshu.com/explore/${noteID}`,
    `https://www.xiaohongshu.com/explore/${noteID}#xsec_token=${secret}`
  ];
  for (let index = 0; index < hrefs.length; index += 1) {
    const result = await invokeXiaohongshuFixture({
      kind: "request",
      operation_id: `xhs_invalid_url_${index}`,
      method: "GET",
      path: XIAOHONGSHU_COMMENT_PATH,
      entries: [["note_id", noteID]]
    }, {
      cookie: "a1=BROWSER_ONLY_VISITOR",
      href: hrefs[index],
      webpackRuntime
    });
    assert.deepEqual(result, { ok: false, error: "invalid_request" });
    assert.equal(JSON.stringify(result).includes(secret), false);
  }
  assert.equal(calls, 0);
});

test("Xiaohongshu runtime rejects oversized sanitized responses", async () => {
  const noteID = "0123456789abcdef01234567";
  const webpackRuntime = createXiaohongshuWebpackRuntime(() => ({
    comments: Array.from({ length: 7000 }, () => "x".repeat(1000))
  }));
  const result = await invokeXiaohongshuFixture({
    kind: "request",
    operation_id: "xiaohongshu_oversized_fixture",
    method: "GET",
    path: XIAOHONGSHU_COMMENT_PATH,
    entries: [["note_id", noteID]]
  }, {
    cookie: "a1=BROWSER_ONLY_VISITOR",
    href: `https://www.xiaohongshu.com/explore/${noteID}`,
    webpackRuntime
  });
  assert.deepEqual(result, { ok: false, error: "response_too_large" });
});

test("Xiaohongshu runtime binds a request to the current note URL", async () => {
  const noteID = "0123456789abcdef01234567";
  let callCount = 0;
  const webpackRuntime = createXiaohongshuWebpackRuntime(() => {
    callCount += 1;
    return { comments: [] };
  });
  const result = await invokeXiaohongshuFixture({
    kind: "request",
    operation_id: "xiaohongshu_context_fixture",
    method: "GET",
    path: XIAOHONGSHU_COMMENT_PATH,
    entries: [["note_id", noteID], ["cursor", ""]]
  }, {
    cookie: "a1=BROWSER_ONLY_VISITOR",
    href: "https://www.xiaohongshu.com/explore/ffffffffffffffffffffffff?xsec_token=LOCAL",
    webpackRuntime
  });

  assert.deepEqual(result, { ok: false, error: "invalid_request" });
  assert.equal(callCount, 0);
});

test("Xiaohongshu runtime cancellation aborts the in-page GET wrapper", async () => {
  const noteID = "0123456789abcdef01234567";
  let transportSignal = null;
  let transportAborted = false;
  const webpackRuntime = createXiaohongshuWebpackRuntime((_path, options) => {
    transportSignal = options.signal;
    return new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => {
        transportAborted = true;
        const error = new Error("fixture transport cancelled");
        error.name = "AbortError";
        reject(error);
      }, { once: true });
    });
  });
  const operationID = "xiaohongshu_cancel_fixture";
  const pending = invokeXiaohongshuFixture({
    kind: "request",
    operation_id: operationID,
    method: "GET",
    path: XIAOHONGSHU_COMMENT_PATH,
    entries: [["note_id", noteID], ["cursor", ""]]
  }, {
    cookie: "a1=BROWSER_ONLY_VISITOR",
    href: `https://www.xiaohongshu.com/explore/${noteID}?xsec_token=LOCAL`,
    webpackRuntime
  });

  await waitFor(() => transportSignal instanceof AbortSignal);
  assert.deepEqual(await invokeXiaohongshuPageRuntime({
    kind: "cancel",
    operation_id: operationID
  }), {
    ok: true,
    payload: { cancelled: true }
  });
  assert.deepEqual(await pending, { ok: false, error: "request_failed" });
  assert.equal(transportSignal.aborted, true);
  assert.equal(transportAborted, true);
});

test("Xiaohongshu runtime reports identity, verification, and missing runtime states", async () => {
  const noteID = "0123456789abcdef01234567";
  const input = {
    kind: "request",
    operation_id: "xiaohongshu_runtime_missing_fixture",
    method: "GET",
    path: XIAOHONGSHU_COMMENT_PATH,
    entries: [["note_id", noteID], ["cursor", ""]]
  };
  assert.deepEqual(await invokeXiaohongshuFixture(input), {
    ok: false,
    error: "not_logged_in"
  });
  assert.deepEqual(await invokeXiaohongshuFixture(input, {
    cookie: "a1=BROWSER_ONLY"
  }), {
    ok: false,
    error: "runtime_unavailable"
  });
  assert.deepEqual(await invokeXiaohongshuFixture(input, {
    cookie: "a1=BROWSER_ONLY",
    verificationVisible: true
  }), {
    ok: false,
    error: "verification_required"
  });
});

test("Xiaohongshu runtime classifies bounded nested transport risk signals", async (t) => {
  const noteID = "0123456789abcdef01234567";
  const input = {
    kind: "request",
    operation_id: "xiaohongshu_nested_error_fixture",
    method: "GET",
    path: XIAOHONGSHU_COMMENT_PATH,
    entries: [["note_id", noteID], ["cursor", ""]]
  };
  const cases = [
    {
      name: "nested rate limit overrides outer forbidden",
      expected: "rate_limited",
      error() {
        const error = new Error("HTTPServerError");
        error.code = "ERR_BAD_RESPONSE";
        error.status = 403;
        error.response = {
          data: {
            status: 429,
            msg: "SECRET_RATE_LIMIT_DETAIL"
          }
        };
        return error;
      }
    },
    {
      name: "nested business code",
      expected: "forbidden",
      error() {
        const error = new Error("HTTPServerError");
        error.response = { data: { data: { code: -10000 } } };
        return error;
      }
    },
    {
      name: "nested verification status overrides outer forbidden",
      expected: "verification_required",
      error() {
        const error = new Error("HTTPServerError");
        error.status = 403;
        error.data = {
          statusCode: 471,
          error_message: "SECRET_CHALLENGE"
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
      const webpackRuntime = createXiaohongshuWebpackRuntime(() => {
        throw fixture.error();
      });
      const result = await invokeXiaohongshuFixture(input, {
        cookie: "a1=BROWSER_ONLY_VISITOR",
        href: `https://www.xiaohongshu.com/explore/${noteID}?xsec_token=LOCAL`,
        webpackRuntime
      });
      assert.deepEqual(result, { ok: false, error: fixture.expected });
      assert.equal(JSON.stringify(result).includes("SECRET_"), false);
    });
  }
});

test("Xiaohongshu runtime classifies resolved business risk responses", async (t) => {
  const noteID = "0123456789abcdef01234567";
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
      const webpackRuntime = createXiaohongshuWebpackRuntime(
        () => fixture.response
      );
      assert.deepEqual(await invokeXiaohongshuFixture({
        kind: "request",
        operation_id: `xiaohongshu_resolved_risk_${index}`,
        method: "GET",
        path: XIAOHONGSHU_COMMENT_PATH,
        entries: [["note_id", noteID], ["cursor", ""]]
      }, {
        cookie: "a1=BROWSER_ONLY_VISITOR",
        href: `https://www.xiaohongshu.com/explore/${noteID}?xsec_token=LOCAL`,
        webpackRuntime
      }), {
        ok: false,
        error: fixture.expected
      });
    });
  }
});

test("persistent reconnect alarm wakes an idle MV3 worker when the daemon appears", () => {
  const chromeApi = createAlarmChrome();
  let wakeCount = 0;
  const bridge = {
    ensureConnection() {
      wakeCount += 1;
      return Promise.resolve();
    }
  };

  installReconnectAlarm({ chromeApi, bridge });
  assert.deepEqual(chromeApi.created, [{
    name: BRIDGE_RECONNECT_ALARM,
    details: { periodInMinutes: BRIDGE_RECONNECT_PERIOD_MINUTES }
  }]);
  assert.equal(wakeCount, 1);

  chromeApi.alarms.onAlarm.emit({ name: "unrelated" });
  assert.equal(wakeCount, 1);
  chromeApi.alarms.onAlarm.emit({ name: BRIDGE_RECONNECT_ALARM });
  assert.equal(wakeCount, 2);

  chromeApi.runtime.onStartup.emit();
  assert.equal(wakeCount, 3);
  assert.equal(chromeApi.created.length, 2);
});

test("offscreen discovery wakes the bridge every five seconds after worker idle", async () => {
  const fixture = createFastDiscoveryChrome();
  const controller = createFastDiscoveryController({ chromeApi: fixture.chromeApi });

  const results = await Promise.all([controller.ensureDocument(), controller.ensureDocument()]);
  assert.deepEqual(results, [true, true]);
  assert.deepEqual(fixture.createCalls, [{
    url: FAST_DISCOVERY_DOCUMENT_PATH,
    reasons: ["WORKERS"],
    justification: "Wake the local browser-session bridge every five seconds."
  }]);
  await controller.ensureDocument();
  assert.equal(fixture.createCalls.length, 1);
  assert.equal(FAST_DISCOVERY_INTERVAL_MS, 5000);
  assert.equal(controller.isProbe(
    { type: FAST_DISCOVERY_PROBE_TYPE },
    { id: "bridgeextension", url: "chrome-extension://bridgeextension/offscreen.html" }
  ), true);
  assert.equal(controller.isProbe(
    { type: FAST_DISCOVERY_PROBE_TYPE },
    { id: "bridgeextension", url: "chrome-extension://bridgeextension/ui/popup.html" }
  ), false);
});

test("Douyin runtime uses explicit account state and a scoped signed-in avatar", async () => {
  assert.equal(await captureDouyinLoginState({
    renderData: encodeURIComponent(JSON.stringify({
      app: { user: { isLogin: true } }
    }))
  }), true);

  assert.equal(await captureDouyinLoginState({
    renderData: encodeURIComponent(JSON.stringify({
      app: { user: { isLogin: false } }
    })),
    store: {
      userStore: {
        userInfo: {
          isLogin: true,
          info: { uid: "STALE_USER" }
        }
      }
    },
    avatarLinks: ["/user/self?enter_method=top_bar"]
  }), false);

  assert.equal(await captureDouyinLoginState({
    renderData: "%malformed",
    store: {
      userStore: {
        userInfo: {
          isLogin: true,
          info: { uid: "CURRENT_USER" }
        }
      }
    }
  }), true);

  assert.equal(await captureDouyinLoginState({
    store: {
      userStore: {
        userInfo: {
          isLogin: false,
          info: { uid: "CACHED_USER" }
        }
      }
    },
    avatarLinks: ["/user/self?enter_method=top_bar"]
  }), false);

  assert.equal(await captureDouyinLoginState({
    store: {
      userStore: {
        userInfo: {
          info: { id_str: "CURRENT_USER" }
        }
      }
    }
  }), true);

  assert.equal(await captureDouyinLoginState({
    initialState: {
      userStore: {
        isLogin: 1
      }
    }
  }), true);

  assert.equal(await captureDouyinLoginState({
    avatarLinks: ["/user/self?enter_method=top_bar"]
  }), true);

  // 仅有通用个人链接、作者直播头像或设备身份，不足以证明浏览器账户已登录。
  assert.equal(await captureDouyinLoginState(), false);
  assert.equal(await captureDouyinLoginState({
    avatarLinks: ["/user/MS4wLjABAuthor?enter_method=video"]
  }), false);
  assert.equal(await captureDouyinLoginState({
    store: {
      userStore: {
        odin: { id: "DEVICE_ID" }
      }
    }
  }), false);
});

test("Douyin runtime reports visible verification state in session probes", async () => {
  const clear = await captureDouyinSessionState({
    renderData: encodeURIComponent(JSON.stringify({
      app: { user: { isLogin: true } }
    }))
  });
  assert.equal(clear.logged_in, true);
  assert.equal(clear.verification_required, false);

  const challenged = await captureDouyinSessionState({
    renderData: encodeURIComponent(JSON.stringify({
      app: { user: { isLogin: true } }
    })),
    verificationVisible: true
  });
  assert.equal(challenged.logged_in, true);
  assert.equal(challenged.verification_required, true);
});

test("Douyin runtime stops a pending transport when verification appears", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  let verificationVisible = false;
  let requestCalls = 0;
  let cancelCalls = 0;
  const frame = {
    getBoundingClientRect() {
      return { width: 380, height: 348 };
    }
  };
  const container = {
    getBoundingClientRect() {
      return { width: 1280, height: 720 };
    },
    querySelectorAll(selector) {
      assert.equal(selector, "iframe");
      return [frame];
    }
  };
  const modules = {
    30995: {
      COMMON_SEARCH_PARAMS: {
        device_platform: "webapp",
        aid: "6383",
        channel: "channel_pc_web"
      }
    },
    911429: {
      U2(path, parameters, options, baseURL, context, transportOptions, cancelRef) {
        requestCalls += 1;
        assert.equal(path, "/aweme/v1/web/comment/list/reply/");
        assert.equal(parameters.comment_id, "7372484719365098811");
        assert.deepEqual(options, {});
        assert.equal(baseURL, undefined);
        assert.equal(context, null);
        assert.equal(transportOptions, undefined);
        cancelRef.current = () => {
          cancelCalls += 1;
        };
        return new Promise(() => {});
      }
    }
  };
  const chunks = [];
  chunks.push = (entry) => {
    entry[2]((moduleID) => modules[moduleID]);
    return Array.prototype.push.call(chunks, entry);
  };
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      webpackChunkdouyin_web: chunks,
      document: {
        getElementById(id) {
          assert.equal(id, "captcha_container");
          return verificationVisible ? container : null;
        }
      },
      getComputedStyle() {
        return { display: "block", visibility: "visible", opacity: "1" };
      }
    }
  });

  try {
    const request = invokeDouyinPageRuntime({
      kind: "request",
      operation_id: "verification_fixture",
      path: "/aweme/v1/web/comment/list/reply/",
      entries: [
        ["item_id", "7372484719365098803"],
        ["comment_id", "7372484719365098811"],
        ["whale_cut_token", ""],
        ["cut_version", "1"],
        ["cursor", "0"],
        ["count", "2"],
        ["item_type", "0"]
      ]
    });
    setTimeout(() => {
      verificationVisible = true;
    }, 20);
    const result = await request;
    assert.deepEqual(result, { ok: false, error: "verification_required" });
    assert.equal(requestCalls, 1);
    assert.equal(cancelCalls, 1);
  } finally {
    if (previousWindow) {
      Object.defineProperty(globalThis, "window", previousWindow);
    } else {
      delete globalThis.window;
    }
  }
});

test("Douyin search page runtime uses its independent modules and JSONP global", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  let requestCalls = 0;
  const modules = {
    437154: {
      COMMON_SEARCH_PARAMS: {
        device_platform: "webapp",
        aid: 6383,
        channel: "channel_pc_web"
      }
    },
    706726: {
      U2(path, parameters, options, baseURL, context, transportOptions, cancelRef) {
        requestCalls += 1;
        assert.equal(path, "/aweme/v1/web/search/item/");
        assert.deepEqual(parameters, {
          device_platform: "webapp",
          aid: 6383,
          channel: "channel_pc_web",
          keyword: "Codex",
          search_channel: "aweme_video_web",
          search_source: "normal_search",
          query_correct_type: "1",
          is_filter_search: "0",
          from_group_id: "",
          offset: "0",
          count: "2",
          sort_type: "0",
          publish_time: "0",
          search_id: ""
        });
        assert.deepEqual(options, {});
        assert.equal(baseURL, undefined);
        assert.equal(context, null);
        assert.equal(transportOptions, undefined);
        assert.deepEqual(cancelRef, { current: null });
        return Promise.resolve({
          status_code: 0,
          data: [{ aweme_info: { aweme_id: "7372484719365098803" } }],
          cursor: 2,
          has_more: 0,
          search_id: "search_fixture"
        });
      }
    }
  };
  const chunks = [];
  chunks.push = (entry) => {
    entry[2]((moduleID) => modules[moduleID]);
    return Array.prototype.push.call(chunks, entry);
  };
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      webpackChunkdouyin_search: chunks,
      document: {
        getElementById(id) {
          assert.equal(id, "captcha_container");
          return null;
        }
      }
    }
  });

  try {
    const result = await invokeDouyinPageRuntime({
      kind: "request",
      operation_id: "search_runtime_fixture",
      path: "/aweme/v1/web/search/item/",
      entries: [
        ["keyword", "Codex"],
        ["search_channel", "aweme_video_web"],
        ["search_source", "normal_search"],
        ["query_correct_type", "1"],
        ["is_filter_search", "0"],
        ["from_group_id", ""],
        ["offset", "0"],
        ["count", "2"],
        ["sort_type", "0"],
        ["publish_time", "0"],
        ["search_id", ""]
      ]
    });
    assert.deepEqual(result, {
      ok: true,
      payload: {
        status_code: 0,
        data: [{ aweme_info: { aweme_id: "7372484719365098803" } }],
        cursor: 2,
        has_more: 0,
        search_id: "search_fixture"
      }
    });
    assert.equal(requestCalls, 1);
  } finally {
    if (previousWindow) {
      Object.defineProperty(globalThis, "window", previousWindow);
    } else {
      delete globalThis.window;
    }
  }
});

test("Douyin web runtime dispatches fixed hashtag, music, mix, and series request contracts", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const calls = [];
  const modules = {
    30995: {
      COMMON_SEARCH_PARAMS: {
        device_platform: "webapp",
        aid: "6383",
        channel: "channel_pc_web"
      }
    },
    911429: {
      U2(path, parameters, options, baseURL, context, transportOptions, cancelRef) {
        calls.push({ path, parameters });
        assert.deepEqual(options, {});
        assert.equal(baseURL, undefined);
        assert.equal(context, null);
        assert.equal(transportOptions, undefined);
        assert.deepEqual(cancelRef, { current: null });
        return Promise.resolve({
          data: {
            status_code: 0,
            fixture_path: path
          }
        });
      }
    }
  };
  const chunks = [];
  chunks.push = (entry) => {
    entry[2]((moduleID) => modules[moduleID]);
    return Array.prototype.push.call(chunks, entry);
  };
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      webpackChunkdouyin_web: chunks,
      document: {
        getElementById(id) {
          assert.equal(id, "captcha_container");
          return null;
        }
      }
    }
  });

  const cases = [
    {
      operation_id: "hashtag_detail_fixture",
      path: "/aweme/v1/web/challenge/detail/",
      entries: [["ch_id", "1788527695713283"], ["query_type", "0"]]
    },
    {
      operation_id: "hashtag_videos_fixture",
      path: "/aweme/v1/web/challenge/aweme/",
      entries: [
        ["ch_id", "1788527695713283"],
        ["hashtag_name", "外道之歌"],
        ["query_type", "0"],
        ["sort_type", "0"],
        ["offset", "20"],
        ["cursor", "20"],
        ["count", "20"]
      ]
    },
    {
      operation_id: "music_detail_fixture",
      path: "/aweme/v1/web/music/detail/",
      entries: [["music_id", "7637698197799930678"], ["scene", "1"]]
    },
    {
      operation_id: "music_videos_fixture",
      path: "/aweme/v1/web/music/aweme/",
      entries: [["music_id", "7637698197799930678"], ["cursor", "10"], ["count", "10"]]
    },
    {
      operation_id: "mix_detail_fixture",
      path: "/aweme/v1/web/mix/detail/",
      entries: [["mix_id", "7346613166719109130"], ["req_from", "channel_pc_web"]]
    },
    {
      operation_id: "mix_videos_fixture",
      path: "/aweme/v1/web/mix/aweme/",
      entries: [["mix_id", "7346613166719109130"], ["cursor", "12"], ["count", "12"]]
    },
    {
      operation_id: "series_detail_fixture",
      path: "/aweme/v1/web/series/detail/",
      entries: [["series_id", "7661857744487450667"], ["req_from", "channel_pc_web"]]
    },
    {
      operation_id: "series_list_fixture",
      path: "/aweme/v1/web/series/list/",
      entries: [
        ["sec_user_id", "MS4wLjABBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"],
        ["req_from", "channel_pc_web"],
        ["cursor", "12"],
        ["count", "12"]
      ]
    },
    {
      operation_id: "series_episodes_fixture",
      path: "/aweme/v1/web/series/aweme/",
      entries: [
        ["series_id", "7661857744487450667"],
        ["pull_type", "2"],
        ["cursor", "12"],
        ["count", "12"]
      ]
    }
  ];

  try {
    assert.deepEqual(await invokeDouyinPageRuntime({
      kind: "request",
      operation_id: "invalid_discovery_fixture",
      path: cases[0].path,
      entries: [...cases[0].entries, ["unexpected", "1"]]
    }), {
      ok: false,
      error: "invalid_request"
    });
    assert.equal(calls.length, 0);

    for (const request of cases) {
      assert.deepEqual(await invokeDouyinPageRuntime({
        kind: "request",
        ...request
      }), {
        ok: true,
        payload: {
          status_code: 0,
          fixture_path: request.path
        }
      });
    }
    assert.deepEqual(
      calls.map(({ path, parameters }) => ({
        path,
        parameters: Object.fromEntries(
          Object.entries(parameters).filter(([name]) => (
            name !== "device_platform" && name !== "aid" && name !== "channel"
          ))
        )
      })),
      cases.map(({ path, entries }) => ({
        path,
        parameters: Object.fromEntries(entries)
      }))
    );
    for (const call of calls) {
      assert.equal(call.parameters.device_platform, "webapp");
      assert.equal(call.parameters.aid, "6383");
      assert.equal(call.parameters.channel, "channel_pc_web");
    }
  } finally {
    if (previousWindow) {
      Object.defineProperty(globalThis, "window", previousWindow);
    } else {
      delete globalThis.window;
    }
  }
});

test("Douyin runtime cancellation stops transport and polling before a retry", async () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  let requestCalls = 0;
  let cancelCalls = 0;
  let activeTransports = 0;
  let cancelRefReady = false;
  let verificationChecks = 0;
  const modules = {
    30995: {
      COMMON_SEARCH_PARAMS: {
        device_platform: "webapp",
        aid: "6383",
        channel: "channel_pc_web"
      }
    },
    911429: {
      async U2(_path, _parameters, _options, _baseURL, _context, _transportOptions, cancelRef) {
        requestCalls += 1;
        if (requestCalls === 1) {
          activeTransports += 1;
          await delay(30);
          cancelRef.current = () => {
            cancelCalls += 1;
            activeTransports -= 1;
          };
          cancelRefReady = true;
          return new Promise(() => {});
        }
        assert.equal(activeTransports, 0);
        return Promise.resolve({ data: { status_code: 0, comments: [] } });
      }
    }
  };
  const chunks = [];
  chunks.push = (entry) => {
    entry[2]((moduleID) => modules[moduleID]);
    return Array.prototype.push.call(chunks, entry);
  };
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      webpackChunkdouyin_web: chunks,
      document: {
        getElementById(id) {
          assert.equal(id, "captcha_container");
          verificationChecks += 1;
          return null;
        }
      }
    }
  });

  const requestInput = {
    kind: "request",
    operation_id: "rpc_cancel_fixture",
    path: "/aweme/v1/web/comment/list/reply/",
    entries: [
      ["item_id", "7372484719365098803"],
      ["comment_id", "7372484719365098811"],
      ["whale_cut_token", ""],
      ["cut_version", "1"],
      ["cursor", "0"],
      ["count", "2"],
      ["item_type", "0"]
    ]
  };

  try {
    assert.deepEqual(await invokeDouyinPageRuntime({
      kind: "cancel",
      operation_id: "rpc_prestart_fixture"
    }), {
      ok: true,
      payload: { cancelled: false }
    });
    assert.deepEqual(await invokeDouyinPageRuntime({
      ...requestInput,
      operation_id: "rpc_prestart_fixture"
    }), {
      ok: false,
      error: "request_failed"
    });
    assert.equal(requestCalls, 0);

    const pendingRequest = invokeDouyinPageRuntime(requestInput);
    await waitFor(() => requestCalls === 1);
    assert.equal(requestCalls, 1);
    assert.equal(cancelRefReady, false);
    const cancelled = await invokeDouyinPageRuntime({
      kind: "cancel",
      operation_id: requestInput.operation_id
    });
    assert.deepEqual(cancelled, { ok: true, payload: { cancelled: true } });
    assert.equal(cancelRefReady, true);
    assert.deepEqual(await pendingRequest, { ok: false, error: "request_failed" });
    assert.equal(cancelCalls, 1);
    assert.equal(activeTransports, 0);

    const checksAfterCancellation = verificationChecks;
    await delay(125);
    assert.equal(verificationChecks, checksAfterCancellation);

    const retry = await invokeDouyinPageRuntime({
      ...requestInput,
      operation_id: "rpc_retry_fixture"
    });
    assert.deepEqual(retry, {
      ok: true,
      payload: { status_code: 0, comments: [] }
    });
    assert.equal(requestCalls, 2);
  } finally {
    if (previousWindow) {
      Object.defineProperty(globalThis, "window", previousWindow);
    } else {
      delete globalThis.window;
    }
  }
});

test("Xiaohongshu adapter preserves request readiness in session probes", () => {
  const adapter = new XiaohongshuSessionAdapter({ chromeApi: {} });
  const payload = adapter.sessionPayload({
    fingerprint: { cookie_enabled: true, language: "zh-CN" },
    logged_in: false,
    request_ready: true,
    verification_required: false
  });
  assert.deepEqual(payload, {
    fingerprint: { cookie_enabled: true, language: "zh-CN" },
    logged_in: false,
    request_ready: true,
    verification_required: false
  });
});

test("Xiaohongshu adapter preserves a matching live note tab and keeps xsec out of RPC args", async () => {
  const noteID = "0123456789abcdef01234567";
  const tab = {
    id: 18,
    active: true,
    status: "complete",
    windowId: 3,
    url: `https://www.xiaohongshu.com/explore/${noteID}?xsec_token=BROWSER_ONLY`
  };
  const chromeApi = createAdapterChrome(tab, {
    ok: false,
    error: "runtime_unavailable"
  });
  const adapter = new XiaohongshuSessionAdapter({ chromeApi });
  const result = await adapter.routeRequest({
    method: "GET",
    path: XIAOHONGSHU_COMMENT_PATH,
    entries: [
      ["note_id", noteID],
      ["cursor", ""],
      ["top_comment_id", ""],
      ["image_formats", "jpg,webp,avif"]
    ],
    referer: `https://www.xiaohongshu.com/explore/${noteID}`
  }, { requestId: "xhs_adapter_fixture" });

  assert.deepEqual(result, { error: "runtime_unavailable" });
  assert.equal(chromeApi.calls.some((call) => call.type === "tabs.update"), false);
  const execution = chromeApi.calls.find((call) => call.type === "executeScript");
  assert.ok(execution);
  assert.equal(JSON.stringify(execution.details.args).includes("BROWSER_ONLY"), false);
  assert.deepEqual(execution.details.args[0], {
    kind: "request",
    operation_id: "xhs_adapter_fixture",
    method: "GET",
    path: XIAOHONGSHU_COMMENT_PATH,
    entries: [
      ["note_id", noteID],
      ["cursor", ""],
      ["top_comment_id", ""],
      ["image_formats", "jpg,webp,avif"]
    ],
    context_mode: "session"
  });
});

test("Xiaohongshu adapter runs a bare note API request in an existing session tab", async () => {
  const noteID = "0123456789abcdef01234567";
  const otherNoteID = "89abcdef0123456701234567";
  const tabSecret = "OTHER_NOTE_XSEC=";
  const tab = {
    id: 20,
    active: true,
    status: "complete",
    windowId: 3,
    url: `https://www.xiaohongshu.com/explore/${otherNoteID}` +
      `?xsec_token=${encodeURIComponent(tabSecret)}&xsec_source=pc_feed`
  };
  const chromeApi = createAdapterChrome(tab, {
    ok: true,
    payload: { items: [{ id: noteID }] }
  });
  const adapter = new XiaohongshuSessionAdapter({ chromeApi });
  const result = await adapter.routeRequest({
    method: "POST",
    path: XIAOHONGSHU_FEED_PATH,
    entries: [["note_id", noteID], ["image_formats", "jpg,webp,avif"]],
    referer: `https://www.xiaohongshu.com/explore/${noteID}`
  }, { requestId: "xhs_adapter_bare_note_fixture" });

  assert.deepEqual(result, { payload: { items: [{ id: noteID }] } });
  assert.equal(chromeApi.calls.some((call) => call.type === "tabs.update"), false);
  const execution = chromeApi.calls.find((call) => call.type === "executeScript");
  assert.ok(execution);
  assert.deepEqual(execution.details.args[0], {
    kind: "request",
    operation_id: "xhs_adapter_bare_note_fixture",
    method: "POST",
    path: XIAOHONGSHU_FEED_PATH,
    entries: [["note_id", noteID], ["image_formats", "jpg,webp,avif"]],
    context_mode: "session"
  });
  assert.equal(JSON.stringify(execution.details.args).includes(tabSecret), false);
});

test("Xiaohongshu adapter uses a matching xsec tab and scrubs it before returning", async () => {
  const noteID = "0123456789abcdef01234567";
  const xsecToken = "REQUESTED_XSEC_TOKEN=";
  const xsecSource = "pc_feed";
  const referer = `https://www.xiaohongshu.com/explore/${noteID}` +
    `?xsec_token=${encodeURIComponent(xsecToken)}&xsec_source=${xsecSource}`;
  const tab = {
    id: 19,
    active: true,
    status: "complete",
    windowId: 3,
    url: referer
  };
  const chromeApi = createAdapterChrome(tab, {
    ok: true,
    payload: {
      items: [{ id: "safe" }],
      echo: `server echoed ${xsecToken}`,
      source_echo: `source=${xsecSource}`,
      request_url: referer,
      nested: { xsec_token: xsecToken }
    }
  });
  const adapter = new XiaohongshuSessionAdapter({ chromeApi });
  const result = await adapter.routeRequest({
    method: "GET",
    path: XIAOHONGSHU_COMMENT_PATH,
    entries: [["note_id", noteID], ["cursor", ""]],
    referer
  }, { requestId: "xhs_adapter_xsec_fixture" });

  assert.equal(chromeApi.calls.some((call) => call.type === "tabs.update"), false);
  const execution = chromeApi.calls.find((call) => call.type === "executeScript");
  assert.ok(execution);
  assert.equal(execution.details.args[0].context_mode, "strict");
  assert.equal(JSON.stringify(execution.details.args).includes(xsecToken), false);
  assert.equal(JSON.stringify(execution.details.args).includes(xsecSource), false);
  assert.deepEqual(result.payload.items, [{ id: "safe" }]);
  assert.equal(Object.hasOwn(result.payload, "request_url"), false);
  const encoded = JSON.stringify(result);
  assert.equal(encoded.includes(xsecToken), false);
  assert.equal(encoded.includes(xsecSource), false);
  assert.equal(encoded.includes("xsec_token"), false);
});

test("Xiaohongshu adapter rejects a mismatched xsec page without tab mutation", async () => {
  const noteID = "0123456789abcdef01234567";
  const referer = `https://www.xiaohongshu.com/explore/${noteID}` +
    "?xsec_token=REQUESTED_XSEC_TOKEN%3D&xsec_source=pc_feed";
  const chromeApi = createAdapterChrome({
    id: 23,
    active: true,
    status: "complete",
    windowId: 3,
    url: `https://www.xiaohongshu.com/explore/${noteID}`
  }, { ok: true, payload: {} });
  const adapter = new XiaohongshuSessionAdapter({ chromeApi });

  assert.deepEqual(await adapter.routeRequest({
    method: "GET",
    path: XIAOHONGSHU_COMMENT_PATH,
    entries: [["note_id", noteID], ["cursor", ""]],
    referer
  }), { error: "tab_unavailable" });
  assert.deepEqual(chromeApi.calls, []);
});

test("Xiaohongshu adapter serializes and spaces request injections", async () => {
  const noteID = "0123456789abcdef01234567";
  const tab = {
    id: 21,
    active: true,
    status: "complete",
    windowId: 3,
    url: `https://www.xiaohongshu.com/explore/${noteID}`
  };
  let clock = 2000;
  const delays = [];
  const starts = [];
  let releaseFirst;
  const firstPending = new Promise((resolve) => {
    releaseFirst = resolve;
  });
  let requestCount = 0;
  const chromeApi = createAdapterChrome(tab, async (details) => {
    const input = details.args[0];
    if (input.kind !== "request") {
      return { ok: false, error: "invalid_request" };
    }
    requestCount += 1;
    starts.push(clock);
    if (requestCount === 1) {
      await firstPending;
    }
    return { ok: true, payload: { request: requestCount } };
  });
  const requestPolicy = new SerialRequestPolicy({
    now: () => clock,
    delay: async (milliseconds) => {
      delays.push(milliseconds);
      clock += milliseconds;
    }
  });
  const adapter = new XiaohongshuSessionAdapter({
    chromeApi,
    requestPolicy
  });
  const message = {
    method: "GET",
    path: XIAOHONGSHU_COMMENT_PATH,
    entries: [["note_id", noteID], ["cursor", ""]],
    referer: `https://www.xiaohongshu.com/explore/${noteID}`
  };

  const first = adapter.routeRequest(message, { requestId: "xhs_serial_first" });
  const second = adapter.routeRequest(message, { requestId: "xhs_serial_second" });
  await waitFor(() => starts.length === 1);
  assert.deepEqual(starts, [2000]);
  releaseFirst();
  assert.deepEqual(await Promise.all([first, second]), [
    { payload: { request: 1 } },
    { payload: { request: 2 } }
  ]);
  assert.deepEqual(delays, [DEFAULT_MINIMUM_START_INTERVAL_MS]);
  assert.deepEqual(starts, [2000, 2000 + DEFAULT_MINIMUM_START_INTERVAL_MS]);
});

test("Xiaohongshu adapter latches risk errors without blocking session probes", async () => {
  const noteID = "0123456789abcdef01234567";
  const tab = {
    id: 22,
    active: true,
    status: "complete",
    windowId: 3,
    url: `https://www.xiaohongshu.com/explore/${noteID}`
  };
  let requestExecutions = 0;
  let sessionExecutions = 0;
  const chromeApi = createAdapterChrome(tab, async (details) => {
    if (details.args[0].kind === "session") {
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
    return { ok: false, error: "rate_limited" };
  });
  const adapter = new XiaohongshuSessionAdapter({ chromeApi });
  const message = {
    method: "GET",
    path: XIAOHONGSHU_COMMENT_PATH,
    entries: [["note_id", noteID], ["cursor", ""]],
    referer: `https://www.xiaohongshu.com/explore/${noteID}`
  };

  assert.deepEqual(await adapter.routeRequest(message), {
    error: "rate_limited"
  });
  assert.deepEqual(await adapter.routeRequest(message), {
    error: "rate_limited"
  });
  assert.equal(requestExecutions, 1);
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

test("local bridge persists and reuses its browser instance ID across worker restarts", async () => {
  const previousWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket;
  MockWebSocket.instances.length = 0;

  const chromeApi = createBridgeChrome({ bridgeAuthToken: "t".repeat(40) });
  const first = new LocalSessionBridgeClient({ chromeApi });
  let restarted = null;

  try {
    await first.initialize();
    const browserInstanceId = chromeApi.storage.local.values.browserInstanceId;
    assert.equal(validBrowserInstanceId(browserInstanceId), true);
    assert.equal(first.statusSnapshot().browser_instance_id, browserInstanceId);

    first.disconnectSocket();
    restarted = new LocalSessionBridgeClient({ chromeApi });
    await restarted.initialize();
    assert.equal(restarted.statusSnapshot().browser_instance_id, browserInstanceId);
    assert.equal(chromeApi.storage.local.values.browserInstanceId, browserInstanceId);

    const socket = MockWebSocket.instances.at(-1);
    socket.emit("open");
    assert.deepEqual(socket.sent.at(-1), {
      type: "hello",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: browserInstanceId,
      token: "t".repeat(40)
    });
    await restarted.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: browserInstanceId
    }));
    restarted.sendHello();
    assert.deepEqual(socket.sent.at(-1), {
      type: "hello",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: browserInstanceId,
      token: "t".repeat(40)
    });
  } finally {
    first.clearHeartbeat();
    first.clearReconnect();
    first.disconnectSocket();
    restarted?.clearHeartbeat();
    restarted?.clearReconnect();
    restarted?.disconnectSocket();
    globalThis.WebSocket = previousWebSocket;
  }
});

test("local bridge creates distinct browser instance IDs for separate profiles", async () => {
  const previousWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket;
  MockWebSocket.instances.length = 0;

  const firstChrome = createBridgeChrome();
  const secondChrome = createBridgeChrome();
  const malformedChrome = createBridgeChrome({ browserInstanceId: "NOT-A-VALID-ID" });
  const first = new LocalSessionBridgeClient({ chromeApi: firstChrome });
  const second = new LocalSessionBridgeClient({ chromeApi: secondChrome });
  const malformed = new LocalSessionBridgeClient({ chromeApi: malformedChrome });

  try {
    await Promise.all([first.initialize(), second.initialize(), malformed.initialize()]);
    const firstId = firstChrome.storage.local.values.browserInstanceId;
    const secondId = secondChrome.storage.local.values.browserInstanceId;
    const replacementId = malformedChrome.storage.local.values.browserInstanceId;

    assert.equal(validBrowserInstanceId(firstId), true);
    assert.equal(validBrowserInstanceId(secondId), true);
    assert.equal(validBrowserInstanceId(replacementId), true);
    assert.notEqual(firstId, secondId);
    assert.notEqual(replacementId, "NOT-A-VALID-ID");
  } finally {
    for (const bridge of [first, second, malformed]) {
      bridge.clearHeartbeat();
      bridge.clearReconnect();
      bridge.disconnectSocket();
    }
    globalThis.WebSocket = previousWebSocket;
  }
});

test("local bridge automatically registers and routes a platform-scoped RPC with mock WebSocket", async () => {
  const previousWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket;
  MockWebSocket.instances.length = 0;

  const chromeApi = createBridgeChrome({ bridgeUrl: "ws://127.0.0.1:29999" });
  const bridge = new LocalSessionBridgeClient({
    chromeApi,
    errorCodes: new Set(["fixture_failed"]),
    adapters: {
      fixture: {
        handlers: {
          request: {
            timeout: 1000,
            async handle(message, context) {
              assert.equal(Object.hasOwn(message, "type"), false);
              assert.equal(Object.hasOwn(message, "id"), false);
              assert.equal(Object.hasOwn(message, "platform"), false);
              assert.equal(context.requestId, "fixture_request_1");
              assert.equal(context.platform, "fixture");
              return { payload: { echoed: message.value } };
            }
          }
        }
      }
    }
  });

  try {
    await bridge.initialize();
    const browserInstanceId = chromeApi.storage.local.values.browserInstanceId;
    const initialSocket = MockWebSocket.instances.at(-1);
    assert.equal(initialSocket.url, "ws://127.0.0.1:18765");
    initialSocket.emit("open");
    assert.equal(bridge.statusSnapshot().connection, "authenticating");
    assert.deepEqual(initialSocket.sent.at(-1), {
      type: "hello",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: browserInstanceId
    });

    await bridge.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: browserInstanceId,
      token: "t".repeat(40)
    }));
    assert.equal(bridge.statusSnapshot().ready, true);
    assert.equal(bridge.statusSnapshot().registered, true);
    assert.equal(bridge.statusSnapshot().browser_instance_id, browserInstanceId);
    assert.equal(chromeApi.storage.local.values.bridgeAuthToken, "t".repeat(40));

    await bridge.receiveWire(JSON.stringify({
      type: "request",
      id: "fixture_request_1",
      platform: "fixture",
      value: "accepted"
    }));
    assert.deepEqual(initialSocket.sent.at(-1), {
      type: "response",
      id: "fixture_request_1",
      platform: "fixture",
      payload: { echoed: "accepted" }
    });

    bridge.adapters.fixture.handlers.request.handle = async () => ({ error: "fixture_failed" });
    await bridge.receiveWire(JSON.stringify({
      type: "request",
      id: "fixture_request_2",
      platform: "fixture",
      value: "rejected"
    }));
    assert.deepEqual(initialSocket.sent.at(-1), {
      type: "response",
      id: "fixture_request_2",
      platform: "fixture",
      error: "fixture_failed"
    });

    bridge.reconnect();
    const reconnectSocket = MockWebSocket.instances.at(-1);
    assert.notEqual(reconnectSocket, initialSocket);
    reconnectSocket.emit("open");
    assert.deepEqual(reconnectSocket.sent.at(-1), {
      type: "hello",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: browserInstanceId,
      token: "t".repeat(40)
    });
    await bridge.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: browserInstanceId
    }));
    assert.equal(bridge.statusSnapshot().ready, true);
  } finally {
    bridge.clearHeartbeat();
    bridge.clearReconnect();
    bridge.disconnectSocket();
    globalThis.WebSocket = previousWebSocket;
  }
});

test("local bridge reports live round-trip and response metrics without storage writes", async () => {
  const previousWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket;
  MockWebSocket.instances.length = 0;
  let clock = 1000;
  let releaseRequest;
  const requestGate = new Promise((resolve) => {
    releaseRequest = resolve;
  });
  const chromeApi = createBridgeChrome({ bridgeAuthToken: "t".repeat(40) });
  const bridge = new LocalSessionBridgeClient({
    chromeApi,
    now: () => clock,
    errorCodes: new Set(["fixture_failed"]),
    adapters: {
      fixture: {
        handlers: {
          request: {
            timeout: 1000,
            async handle(message) {
              if (message.value === "pending") {
                return requestGate;
              }
              clock += 40;
              return { error: "fixture_failed" };
            }
          }
        }
      }
    }
  });

  try {
    await bridge.initialize();
    const socket = MockWebSocket.instances.at(-1);
    socket.emit("open");
    clock = 1018;
    await bridge.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: bridge.statusSnapshot().browser_instance_id
    }));
    assert.deepEqual(bridge.statusSnapshot().metrics, {
      rtt_ms: 18,
      in_flight: 0,
      queued: 0,
      succeeded: 0,
      failed: 0,
      last_response_ms: null
    });

    clock = 2000;
    const pending = bridge.receiveWire(JSON.stringify({
      type: "request",
      id: "metrics_success_fixture",
      platform: "fixture",
      value: "pending"
    }));
    await waitFor(() => bridge.statusSnapshot().metrics.in_flight === 1);
    assert.equal(bridge.statusSnapshot().metrics.queued, 0);
    clock = 2125;
    releaseRequest({ payload: { ok: true } });
    await pending;
    assert.deepEqual(bridge.statusSnapshot().metrics, {
      rtt_ms: 18,
      in_flight: 0,
      queued: 0,
      succeeded: 1,
      failed: 0,
      last_response_ms: 125
    });

    clock = 3000;
    await bridge.receiveWire(JSON.stringify({
      type: "request",
      id: "metrics_failure_fixture",
      platform: "fixture",
      value: "failed"
    }));
    assert.deepEqual(bridge.statusSnapshot().metrics, {
      rtt_ms: 18,
      in_flight: 0,
      queued: 0,
      succeeded: 1,
      failed: 1,
      last_response_ms: 40
    });
    assert.deepEqual(chromeApi.storage.local.values, {
      bridgeAuthToken: "t".repeat(40),
      browserInstanceId: bridge.statusSnapshot().browser_instance_id
    });
  } finally {
    releaseRequest?.({ error: "request_failed" });
    bridge.clearHeartbeat();
    bridge.clearReconnect();
    bridge.disconnectSocket();
    globalThis.WebSocket = previousWebSocket;
  }
});

test("superseded browser instance parks automatic reconnect until identity or user action changes", async () => {
  const previousWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket;
  MockWebSocket.instances.length = 0;
  const chromeApi = createBridgeChrome({
    bridgeAuthToken: "t".repeat(40),
    browserInstanceId: "0".repeat(32)
  });
  const bridge = new LocalSessionBridgeClient({ chromeApi });

  try {
    await bridge.initialize();
    const firstSocket = MockWebSocket.instances.at(-1);
    firstSocket.emit("open");
    await bridge.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: "0".repeat(32)
    }));
    firstSocket.emit("close", {
      code: BROWSER_INSTANCE_SUPERSEDED_CLOSE_CODE
    });
    assert.equal(bridge.statusSnapshot().connection, "parked");
    assert.equal(
      bridge.statusSnapshot().last_error,
      "browser_instance_superseded"
    );
    assert.equal(bridge.state.reconnectTimer, null);

    const parkedSocketCount = MockWebSocket.instances.length;
    await bridge.ensureConnection();
    assert.equal(MockWebSocket.instances.length, parkedSocketCount);

    chromeApi.storage.local.values.browserInstanceId = "1".repeat(32);
    await bridge.ensureConnection();
    assert.equal(MockWebSocket.instances.length, parkedSocketCount + 1);
    assert.equal(
      bridge.statusSnapshot().browser_instance_id,
      "1".repeat(32)
    );

    const changedIdentitySocket = MockWebSocket.instances.at(-1);
    changedIdentitySocket.emit("open");
    await bridge.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: "1".repeat(32)
    }));
    changedIdentitySocket.emit("close", {
      code: BROWSER_INSTANCE_SUPERSEDED_CLOSE_CODE
    });
    bridge.reconnect();
    assert.equal(bridge.statusSnapshot().connection, "connecting");

    const manualSocket = MockWebSocket.instances.at(-1);
    manualSocket.emit("open");
    await bridge.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: "1".repeat(32)
    }));
    manualSocket.emit("close", { code: 1001 });
    assert.equal(bridge.statusSnapshot().connection, "disconnected");
    assert.notEqual(bridge.state.reconnectTimer, null);
  } finally {
    bridge.clearHeartbeat();
    bridge.clearReconnect();
    bridge.disconnectSocket();
    globalThis.WebSocket = previousWebSocket;
  }
});

test("fresh registration accepts the first RPC while token persistence is pending", async () => {
  const previousWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket;
  MockWebSocket.instances.length = 0;

  const chromeApi = createBridgeChrome({
    browserInstanceId: "0123456789abcdef0123456789abcdef"
  });
  const originalSet = chromeApi.storage.local.set.bind(chromeApi.storage.local);
  let releasePersistence;
  const persistenceGate = new Promise((resolve) => {
    releasePersistence = resolve;
  });
  chromeApi.storage.local.set = async (next) => {
    if (Object.prototype.hasOwnProperty.call(next, "bridgeAuthToken")) {
      await persistenceGate;
    }
    await originalSet(next);
  };
  const bridge = new LocalSessionBridgeClient({
    chromeApi,
    adapters: {
      fixture: {
        handlers: {
          request: {
            timeout: 1000,
            async handle(message) {
              return { payload: { echoed: message.value } };
            }
          }
        }
      }
    }
  });

  try {
    await bridge.initialize();
    const socket = MockWebSocket.instances.at(-1);
    socket.emit("open");
    const accepting = bridge.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: bridge.statusSnapshot().browser_instance_id,
      token: "t".repeat(40)
    }));
    const dispatching = bridge.receiveWire(JSON.stringify({
      type: "request",
      id: "fresh_registration_request",
      platform: "fixture",
      value: "accepted"
    }));

    await dispatching;
    assert.equal(bridge.statusSnapshot().ready, true);
    assert.deepEqual(socket.sent.at(-1), {
      type: "response",
      id: "fresh_registration_request",
      platform: "fixture",
      payload: { echoed: "accepted" }
    });
    assert.equal(chromeApi.storage.local.values.bridgeAuthToken, undefined);

    releasePersistence();
    await accepting;
    assert.equal(chromeApi.storage.local.values.bridgeAuthToken, "t".repeat(40));
  } finally {
    releasePersistence?.();
    bridge.clearHeartbeat();
    bridge.clearReconnect();
    bridge.disconnectSocket();
    globalThis.WebSocket = previousWebSocket;
  }
});

test("local bridge rejects a daemon with a different protocol version", async () => {
  const previousWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket;
  MockWebSocket.instances.length = 0;
  const bridge = new LocalSessionBridgeClient({
    chromeApi: createBridgeChrome({ bridgeAuthToken: "t".repeat(40) })
  });

  try {
    await bridge.initialize();
    const socket = MockWebSocket.instances.at(-1);
    socket.emit("open");
    await bridge.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION - 1
    }));

    assert.equal(bridge.statusSnapshot().ready, false);
    assert.equal(bridge.statusSnapshot().last_error, "protocol_mismatch");
    assert.equal(socket.readyState, MockWebSocket.CLOSING);
  } finally {
    bridge.clearHeartbeat();
    bridge.clearReconnect();
    bridge.disconnectSocket();
    globalThis.WebSocket = previousWebSocket;
  }
});

test("local bridge rejects a ready frame for another browser profile", async () => {
  const previousWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket;
  MockWebSocket.instances.length = 0;
  const chromeApi = createBridgeChrome({
    bridgeAuthToken: "t".repeat(40),
    browserInstanceId: "0".repeat(32)
  });
  const bridge = new LocalSessionBridgeClient({ chromeApi });

  try {
    await bridge.initialize();
    const socket = MockWebSocket.instances.at(-1);
    socket.emit("open");
    await bridge.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: "1".repeat(32),
      token: "u".repeat(40)
    }));

    assert.equal(bridge.statusSnapshot().ready, false);
    assert.equal(bridge.statusSnapshot().last_error, "browser_instance_mismatch");
    assert.equal(chromeApi.storage.local.values.bridgeAuthToken, "t".repeat(40));
    assert.equal(socket.readyState, MockWebSocket.CLOSING);
  } finally {
    bridge.clearHeartbeat();
    bridge.clearReconnect();
    bridge.disconnectSocket();
    globalThis.WebSocket = previousWebSocket;
  }
});

test("local bridge timeout aborts and cleans the handler before responding", async () => {
  const previousWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket;
  MockWebSocket.instances.length = 0;
  const events = [];
  let handlerContext = null;
  const bridge = new LocalSessionBridgeClient({
    chromeApi: createBridgeChrome({ bridgeAuthToken: "t".repeat(40) }),
    adapters: {
      fixture: {
        handlers: {
          request: {
            timeout: 25,
            handle(_message, context) {
              handlerContext = context;
              context.signal.addEventListener("abort", () => {
                events.push(`abort:${context.signal.reason}`);
              });
              context.onCancel(async (reason) => {
                events.push(`cleanup_start:${reason}`);
                await delay(10);
                events.push(`cleanup_end:${reason}`);
              });
              return new Promise(() => {});
            }
          }
        }
      }
    }
  });

  try {
    await bridge.initialize();
    const socket = MockWebSocket.instances.at(-1);
    socket.emit("open");
    await bridge.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: bridge.statusSnapshot().browser_instance_id
    }));
    const send = socket.send.bind(socket);
    socket.send = (source) => {
      const message = JSON.parse(source);
      if (message.type === "response") {
        events.push(`response:${message.error}`);
      }
      send(source);
    };

    await bridge.receiveWire(JSON.stringify({
      type: "request",
      id: "timeout_fixture",
      platform: "fixture"
    }));
    await waitFor(() => socket.sent.some((message) => message.id === "timeout_fixture"));

    assert.equal(handlerContext.signal.aborted, true);
    assert.deepEqual(events, [
      "abort:timeout",
      "cleanup_start:timeout",
      "cleanup_end:timeout",
      "response:timeout"
    ]);
    assert.deepEqual(socket.sent.find((message) => message.id === "timeout_fixture"), {
      type: "response",
      id: "timeout_fixture",
      platform: "fixture",
      error: "timeout"
    });
    assert.equal(bridge.state.pending.size, 0);
  } finally {
    bridge.clearHeartbeat();
    bridge.clearReconnect();
    bridge.disconnectSocket();
    globalThis.WebSocket = previousWebSocket;
  }
});

test("local bridge cancel control frame aborts pending RPC without a response", async () => {
  const previousWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket;
  MockWebSocket.instances.length = 0;
  const events = [];
  let handlerStarted = false;
  const bridge = new LocalSessionBridgeClient({
    chromeApi: createBridgeChrome({ bridgeAuthToken: "t".repeat(40) }),
    adapters: {
      fixture: {
        handlers: {
          request: {
            timeout: 1000,
            handle(_message, context) {
              handlerStarted = true;
              context.signal.addEventListener("abort", () => {
                events.push(`abort:${context.signal.reason}`);
              });
              context.onCancel((reason) => {
                events.push(`cleanup:${reason}`);
              });
              return new Promise(() => {});
            }
          }
        }
      }
    }
  });

  try {
    await bridge.initialize();
    const socket = MockWebSocket.instances.at(-1);
    socket.emit("open");
    await bridge.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: bridge.statusSnapshot().browser_instance_id
    }));

    const dispatch = bridge.receiveWire(JSON.stringify({
      type: "request",
      id: "cancel_fixture",
      platform: "fixture"
    }));
    await waitFor(() => handlerStarted);
    await bridge.receiveWire(JSON.stringify({
      type: "cancel",
      id: "cancel_fixture",
      platform: "fixture"
    }));
    await dispatch;

    assert.deepEqual(events, ["abort:remote_cancel", "cleanup:remote_cancel"]);
    assert.equal(socket.sent.some((message) => message.id === "cancel_fixture"), false);
    assert.equal(bridge.state.pending.size, 0);
  } finally {
    bridge.clearHeartbeat();
    bridge.clearReconnect();
    bridge.disconnectSocket();
    globalThis.WebSocket = previousWebSocket;
  }
});

test("local bridge waits for cancel cleanup before starting the next RPC", async () => {
  const previousWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket;
  MockWebSocket.instances.length = 0;
  const events = [];
  let releaseCleanup;
  const cleanupGate = new Promise((resolve) => {
    releaseCleanup = resolve;
  });
  let calls = 0;
  const requestHandler = {
    timeout: 1000,
    handle(_message, context) {
      calls += 1;
      if (calls === 1) {
        events.push("first_started");
        context.onCancel(async () => {
          events.push("cleanup_started");
          await cleanupGate;
          events.push("cleanup_finished");
        });
        return new Promise(() => {});
      }
      events.push("second_started");
      return { payload: { call: calls } };
    }
  };
  const bridge = new LocalSessionBridgeClient({
    chromeApi: createBridgeChrome({ bridgeAuthToken: "t".repeat(40) }),
    adapters: {
      fixture: {
        family: "fixture",
        handlers: { request: requestHandler }
      },
      fixture_alias: {
        family: "fixture",
        handlers: { request: requestHandler }
      }
    }
  });

  try {
    await bridge.initialize();
    const socket = MockWebSocket.instances.at(-1);
    socket.emit("open");
    await bridge.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: bridge.statusSnapshot().browser_instance_id
    }));
    const firstDispatch = bridge.receiveWire(JSON.stringify({
      type: "request",
      id: "cancel_barrier_fixture_1",
      platform: "fixture"
    }));
    await waitFor(() => events.includes("first_started"));

    const cancelling = bridge.receiveWire(JSON.stringify({
      type: "cancel",
      id: "cancel_barrier_fixture_1",
      platform: "fixture"
    }));
    await waitFor(() => events.includes("cleanup_started"));
    const secondDispatch = bridge.receiveWire(JSON.stringify({
      type: "request",
      id: "cancel_barrier_fixture_2",
      platform: "fixture_alias"
    }));
    await delay(20);
    assert.equal(calls, 1);
    assert.equal(bridge.statusSnapshot().metrics.queued, 1);

    releaseCleanup();
    await Promise.all([firstDispatch, cancelling, secondDispatch]);
    assert.equal(bridge.statusSnapshot().metrics.queued, 0);
    assert.deepEqual(events, [
      "first_started",
      "cleanup_started",
      "cleanup_finished",
      "second_started"
    ]);
    assert.deepEqual(socket.sent.find((message) => message.id === "cancel_barrier_fixture_2"), {
      type: "response",
      id: "cancel_barrier_fixture_2",
      platform: "fixture_alias",
      payload: { call: 2 }
    });
  } finally {
    releaseCleanup?.();
    bridge.clearHeartbeat();
    bridge.clearReconnect();
    bridge.disconnectSocket();
    globalThis.WebSocket = previousWebSocket;
  }
});

test("local bridge keeps unrelated platform families concurrent during cancel cleanup", async () => {
  const previousWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket;
  MockWebSocket.instances.length = 0;
  let releaseCleanup;
  const cleanupGate = new Promise((resolve) => {
    releaseCleanup = resolve;
  });
  let firstStarted = false;
  let otherStarted = false;
  const bridge = new LocalSessionBridgeClient({
    chromeApi: createBridgeChrome({ bridgeAuthToken: "t".repeat(40) }),
    adapters: {
      fixture: {
        handlers: {
          request: {
            timeout: 1000,
            handle(_message, context) {
              firstStarted = true;
              context.onCancel(() => cleanupGate);
              return new Promise(() => {});
            }
          }
        }
      },
      unrelated: {
        handlers: {
          request: {
            timeout: 1000,
            handle() {
              otherStarted = true;
              return { payload: { concurrent: true } };
            }
          }
        }
      }
    }
  });

  try {
    await bridge.initialize();
    const socket = MockWebSocket.instances.at(-1);
    socket.emit("open");
    await bridge.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: bridge.statusSnapshot().browser_instance_id
    }));
    const firstDispatch = bridge.receiveWire(JSON.stringify({
      type: "request",
      id: "family_concurrency_fixture_1",
      platform: "fixture"
    }));
    await waitFor(() => firstStarted);
    const cancelling = bridge.receiveWire(JSON.stringify({
      type: "cancel",
      id: "family_concurrency_fixture_1",
      platform: "fixture"
    }));

    const unrelatedDispatch = bridge.receiveWire(JSON.stringify({
      type: "request",
      id: "family_concurrency_fixture_2",
      platform: "unrelated"
    }));
    await delay(20);
    assert.equal(otherStarted, true);
    await unrelatedDispatch;
    assert.deepEqual(socket.sent.find((message) => (
      message.id === "family_concurrency_fixture_2"
    )), {
      type: "response",
      id: "family_concurrency_fixture_2",
      platform: "unrelated",
      payload: { concurrent: true }
    });

    releaseCleanup();
    await Promise.all([firstDispatch, cancelling]);
  } finally {
    releaseCleanup?.();
    bridge.clearHeartbeat();
    bridge.clearReconnect();
    bridge.disconnectSocket();
    globalThis.WebSocket = previousWebSocket;
  }
});

test("local bridge remembers cancellation for an RPC queued behind cleanup", async () => {
  const previousWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket;
  MockWebSocket.instances.length = 0;
  let releaseCleanup;
  const cleanupGate = new Promise((resolve) => {
    releaseCleanup = resolve;
  });
  let calls = 0;
  const bridge = new LocalSessionBridgeClient({
    chromeApi: createBridgeChrome({ bridgeAuthToken: "t".repeat(40) }),
    adapters: {
      fixture: {
        handlers: {
          request: {
            timeout: 1000,
            handle(_message, context) {
              calls += 1;
              context.onCancel(() => cleanupGate);
              return new Promise(() => {});
            }
          }
        }
      }
    }
  });

  try {
    await bridge.initialize();
    const socket = MockWebSocket.instances.at(-1);
    socket.emit("open");
    await bridge.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: bridge.statusSnapshot().browser_instance_id
    }));
    const firstDispatch = bridge.receiveWire(JSON.stringify({
      type: "request",
      id: "queued_cancel_fixture_1",
      platform: "fixture"
    }));
    await waitFor(() => calls === 1);

    const firstCancel = bridge.receiveWire(JSON.stringify({
      type: "cancel",
      id: "queued_cancel_fixture_1",
      platform: "fixture"
    }));
    const queuedDispatch = bridge.receiveWire(JSON.stringify({
      type: "request",
      id: "queued_cancel_fixture_2",
      platform: "fixture"
    }));
    await bridge.receiveWire(JSON.stringify({
      type: "cancel",
      id: "queued_cancel_fixture_2",
      platform: "fixture"
    }));
    releaseCleanup();
    await Promise.all([firstDispatch, firstCancel, queuedDispatch]);

    assert.equal(calls, 1);
    assert.equal(socket.sent.some((message) => message.id === "queued_cancel_fixture_2"), false);
    assert.equal(bridge.state.pending.size, 0);
    assert.equal(bridge.state.queuedCancellations.size, 0);
  } finally {
    releaseCleanup?.();
    bridge.clearHeartbeat();
    bridge.clearReconnect();
    bridge.disconnectSocket();
    globalThis.WebSocket = previousWebSocket;
  }
});

test("local bridge disconnect cleanup finishes before a reconnected RPC starts", async () => {
  const previousWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket;
  MockWebSocket.instances.length = 0;
  const events = [];
  let calls = 0;
  const bridge = new LocalSessionBridgeClient({
    chromeApi: createBridgeChrome({ bridgeAuthToken: "t".repeat(40) }),
    adapters: {
      fixture: {
        handlers: {
          request: {
            timeout: 1000,
            handle(_message, context) {
              calls += 1;
              if (calls === 1) {
                events.push("first_started");
                context.onCancel(async () => {
                  events.push("disconnect_cleanup_started");
                  await delay(15);
                  events.push("disconnect_cleanup_finished");
                });
                return new Promise(() => {});
              }
              events.push("second_started");
              return { payload: { call: calls } };
            }
          }
        }
      }
    }
  });

  try {
    await bridge.initialize();
    const firstSocket = MockWebSocket.instances.at(-1);
    firstSocket.emit("open");
    await bridge.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: bridge.statusSnapshot().browser_instance_id
    }));
    const firstDispatch = bridge.receiveWire(JSON.stringify({
      type: "request",
      id: "disconnect_fixture_1",
      platform: "fixture"
    }));
    await waitFor(() => events.includes("first_started"));

    firstSocket.emit("close");
    await firstDispatch;
    bridge.clearReconnect();
    bridge.connect();
    const secondSocket = MockWebSocket.instances.at(-1);
    secondSocket.emit("open");
    await bridge.receiveWire(JSON.stringify({
      type: "ready",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: bridge.statusSnapshot().browser_instance_id
    }));
    await bridge.receiveWire(JSON.stringify({
      type: "request",
      id: "disconnect_fixture_2",
      platform: "fixture"
    }));

    assert.deepEqual(events, [
      "first_started",
      "disconnect_cleanup_started",
      "disconnect_cleanup_finished",
      "second_started"
    ]);
    assert.deepEqual(secondSocket.sent.find((message) => message.id === "disconnect_fixture_2"), {
      type: "response",
      id: "disconnect_fixture_2",
      platform: "fixture",
      payload: { call: 2 }
    });
  } finally {
    bridge.clearHeartbeat();
    bridge.clearReconnect();
    bridge.disconnectSocket();
    globalThis.WebSocket = previousWebSocket;
  }
});

test("authentication rejection clears the local token and automatically retries enrollment", async () => {
  const previousWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = MockWebSocket;
  MockWebSocket.instances.length = 0;

  const chromeApi = createBridgeChrome({ bridgeAuthToken: "t".repeat(40) });
  const bridge = new LocalSessionBridgeClient({ chromeApi });

  try {
    await bridge.initialize();
    const browserInstanceId = chromeApi.storage.local.values.browserInstanceId;
    const authenticatedSocket = MockWebSocket.instances.at(-1);
    authenticatedSocket.emit("open");
    assert.deepEqual(authenticatedSocket.sent.at(-1), {
      type: "hello",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: browserInstanceId,
      token: "t".repeat(40)
    });

    await bridge.receiveWire(JSON.stringify({ type: "error", code: "authentication_rejected" }));
    assert.equal(chromeApi.storage.local.values.bridgeAuthToken, undefined);
    const enrollingSocket = MockWebSocket.instances.at(-1);
    assert.notEqual(enrollingSocket, authenticatedSocket);
    enrollingSocket.emit("open");
    assert.deepEqual(enrollingSocket.sent.at(-1), {
      type: "hello",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: browserInstanceId
    });
  } finally {
    bridge.clearHeartbeat();
    bridge.clearReconnect();
    bridge.disconnectSocket();
    globalThis.WebSocket = previousWebSocket;
  }
});

test("Douyin adapter invokes MAIN world and strips sensitive response fields", async () => {
  const awemeId = "7372484719365098803";
  const tab = {
    id: 7,
    active: true,
    status: "complete",
    url: `https://www.douyin.com/video/${awemeId}`
  };
  const chromeApi = createAdapterChrome(tab, {
    ok: true,
    payload: {
      status_code: 0,
      comments: [{ cid: "1", text: "fixture", session_token: "secret" }],
      signed_url: "https://example.test/image?token=secret"
    }
  });
  const adapter = new DouyinSessionAdapter({ chromeApi });

  const result = await adapter.routeRequest({
    path: "/aweme/v1/web/comment/list/",
    entries: [["aweme_id", awemeId], ["cursor", "0"], ["count", "1"]],
    referer: `https://www.douyin.com/video/${awemeId}`
  });

  assert.deepEqual(result, {
    payload: {
      status_code: 0,
      comments: [{ cid: "1", text: "fixture" }]
    }
  });
  assert.equal(Object.hasOwn(result.payload, "signed_url"), false);
  const injection = chromeApi.calls.find((call) => call.type === "executeScript");
  assert.equal(injection.details.world, "MAIN");
  assert.equal(injection.details.target.tabId, tab.id);
  assert.equal(injection.details.args[0].kind, "request");
});

test("Douyin adapter propagates AbortSignal into one MAIN-world cancel operation", async () => {
  const awemeId = "7372484719365098803";
  const tab = {
    id: 7,
    active: true,
    status: "complete",
    url: `https://www.douyin.com/video/${awemeId}`
  };
  const chromeApi = createAdapterChrome(tab, { ok: true, payload: {} });
  let resolveRequestInjection = null;
  chromeApi.scripting.executeScript = async (details) => {
    chromeApi.calls.push({ type: "executeScript", details });
    const pageInput = details.args[0];
    if (pageInput.kind === "request") {
      return new Promise((resolve) => {
        resolveRequestInjection = resolve;
      });
    }
    assert.equal(pageInput.kind, "cancel");
    resolveRequestInjection([{ result: { ok: false, error: "request_failed" } }]);
    return [{ result: { ok: true, payload: { cancelled: true } } }];
  };
  const adapter = new DouyinSessionAdapter({ chromeApi });
  const controller = new AbortController();
  const cancelHandlers = new Set();
  const routed = adapter.routeRequest({
    path: "/aweme/v1/web/comment/list/",
    entries: [["aweme_id", awemeId], ["cursor", "0"], ["count", "1"]],
    referer: `https://www.douyin.com/video/${awemeId}`
  }, {
    signal: controller.signal,
    requestId: "adapter_cancel_fixture",
    onCancel(handler) {
      cancelHandlers.add(handler);
      return () => cancelHandlers.delete(handler);
    }
  });

  await waitFor(() => typeof resolveRequestInjection === "function");
  controller.abort("remote_cancel");
  await Promise.all([...cancelHandlers].map((handler) => handler("remote_cancel")));
  assert.deepEqual(await routed, { error: "request_failed" });

  const injections = chromeApi.calls.filter((call) => call.type === "executeScript");
  assert.equal(injections.length, 2);
  assert.deepEqual(injections.map((call) => call.details.args[0]), [
    {
      kind: "request",
      operation_id: "adapter_cancel_fixture",
      path: "/aweme/v1/web/comment/list/",
      entries: [["aweme_id", awemeId], ["cursor", "0"], ["count", "1"]]
    },
    {
      kind: "cancel",
      operation_id: "adapter_cancel_fixture"
    }
  ]);
});

test("Douyin adapter preserves verification state in session probes", async () => {
  const tab = {
    id: 7,
    active: true,
    status: "complete",
    url: "https://www.douyin.com/video/7372484719365098803"
  };
  const chromeApi = createAdapterChrome(tab, {
    ok: true,
    payload: {
      fingerprint: { user_agent: "fixture", cookie_enabled: true },
      logged_in: true,
      verification_required: true
    }
  });
  const adapter = new DouyinSessionAdapter({ chromeApi });

  assert.deepEqual(await adapter.routeSession(), {
    payload: {
      fingerprint: { user_agent: "fixture", cookie_enabled: true },
      logged_in: true,
      verification_required: true
    }
  });
});
