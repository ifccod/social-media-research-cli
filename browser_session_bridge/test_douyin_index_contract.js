import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  DouyinIndexSessionAdapter
} from "./adapters/douyin_index/adapter.js";
import {
  DOUYIN_INDEX_KEYWORD_TREND_PATH,
  DOUYIN_INDEX_LOGIN_URL,
  validDouyinIndexEntries,
  validDouyinIndexReferer,
  validDouyinIndexRequest
} from "./adapters/douyin_index/contract.js";

const VALID_ENTRIES = [
  ["keyword_list", '["美食","旅游"]'],
  ["start_date", "20260624"],
  ["end_date", "20260724"],
  ["app_name", "aweme"],
  ["region", '["北京","上海"]']
];

function validRequest(overrides = {}) {
  return {
    path: DOUYIN_INDEX_KEYWORD_TREND_PATH,
    entries: VALID_ENTRIES,
    referer: DOUYIN_INDEX_LOGIN_URL,
    request_interval_ms: 3000,
    ...overrides
  };
}

function replaceEntry(entries, name, value) {
  return entries.map((entry) =>
    entry[0] === name ? [name, value] : [...entry]
  );
}

test("Douyin Index contract pins keywords, dates, region, and creator referer", () => {
  assert.equal(validDouyinIndexEntries(VALID_ENTRIES), true);
  assert.equal(validDouyinIndexReferer(DOUYIN_INDEX_LOGIN_URL), true);
  assert.equal(validDouyinIndexRequest(validRequest()), true);

  const invalid = [
    validRequest({ path: "/api/v2/index/other" }),
    validRequest({ referer: `${DOUYIN_INDEX_LOGIN_URL}?token=TOKEN` }),
    validRequest({
      entries: [...VALID_ENTRIES, ["token", "TOKEN"]]
    }),
    validRequest({
      entries: replaceEntry(VALID_ENTRIES, "keyword_list", '["美食","美食"]')
    }),
    validRequest({
      entries: replaceEntry(VALID_ENTRIES, "start_date", "20260725")
    }),
    validRequest({
      entries: replaceEntry(VALID_ENTRIES, "app_name", "other")
    }),
    validRequest({ request_interval_ms: 10001 }),
    { ...validRequest(), extra: true }
  ];
  for (const request of invalid) {
    assert.equal(validDouyinIndexRequest(request), false);
  }
});

test("Douyin Index runtime uses the observed page module instead of a raw HTTP client", () => {
  const source = readFileSync(
    new URL("./adapters/douyin_index/page_runtime.js", import.meta.url),
    "utf8"
  );
  assert.match(source, /const MODULE_ID = 42487;/);
  assert.match(source, /module\.Ul\.get_multi_keyword_hot_trend/);
  assert.match(source, /transport_modules_changed/);
  assert.doesNotMatch(source, /\bfetch\s*\(/);
  assert.doesNotMatch(source, /XMLHttpRequest/);
});

test("Douyin Index adapter invokes MAIN world and removes credential fields", async () => {
  const tab = {
    id: 7,
    windowId: 1,
    status: "complete",
    url: DOUYIN_INDEX_LOGIN_URL
  };
  let injection = null;
  const chromeApi = {
    tabs: {
      query: async () => [tab],
      get: async () => tab,
      update: async (_tabID, changes) => ({ ...tab, ...changes }),
      create: async (changes) => ({ ...tab, ...changes }),
      onRemoved: {
        addListener: () => undefined
      },
      onUpdated: {
        addListener: () => undefined,
        removeListener: () => undefined
      }
    },
    windows: {
      update: async () => undefined
    },
    scripting: {
      executeScript: async (input) => {
        injection = input;
        return [{
          result: {
            ok: true,
            payload: {
              status_code: 0,
              data: {
                hot_list: [{ keyword: "美食", hot_list: [] }]
              },
              cookie: "COOKIE",
              nested: { authorization: "TOKEN", retained: true }
            }
          }
        }];
      }
    }
  };
  const adapter = new DouyinIndexSessionAdapter({ chromeApi });
  const result = await adapter.routeRequest(
    validRequest(),
    { requestId: "request_1" }
  );

  assert.equal(injection.target.tabId, tab.id);
  assert.equal(injection.world, "MAIN");
  assert.equal(injection.injectImmediately, true);
  assert.deepEqual(injection.args[0], {
    kind: "request",
    operation_id: "request_1",
    path: DOUYIN_INDEX_KEYWORD_TREND_PATH,
    entries: VALID_ENTRIES
  });
  assert.equal(result.payload.status_code, 0);
  assert.equal(result.payload.cookie, undefined);
  assert.deepEqual(result.payload.nested, { retained: true });
});
