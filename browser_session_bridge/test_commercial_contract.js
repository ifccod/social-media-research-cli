import assert from "node:assert/strict";
import test from "node:test";

import {
  XIAOHONGSHU_PGY_GOOD_CASE_CLASSES_PATH,
  XIAOHONGSHU_PGY_GOOD_LIVES_PATH,
  XIAOHONGSHU_PGY_GOOD_NOTES_PATH,
  XIAOHONGSHU_PGY_INDUSTRIES_PATH,
  XIAOHONGSHU_PGY_TOP_BLOGGERS_PATH,
  validXiaohongshuPgyRequest,
  xiaohongshuPgyMethod
} from "./adapters/xiaohongshu_pgy/contract.js";

const REFERER = "https://pgy.xiaohongshu.com/";

test("PGY 商业案例与达人榜合同只接受已观测的固定参数", () => {
  const requests = [
    {
      path: XIAOHONGSHU_PGY_GOOD_CASE_CLASSES_PATH,
      method: "GET",
      entries: []
    },
    {
      path: XIAOHONGSHU_PGY_GOOD_NOTES_PATH,
      method: "GET",
      entries: [["category", "美妆个护"]]
    },
    {
      path: XIAOHONGSHU_PGY_GOOD_LIVES_PATH,
      method: "GET",
      entries: [["category", "潮流运动"]]
    },
    {
      path: XIAOHONGSHU_PGY_TOP_BLOGGERS_PATH,
      method: "GET",
      entries: [["rank_type", "6"]]
    },
    {
      path: XIAOHONGSHU_PGY_INDUSTRIES_PATH,
      method: "GET",
      entries: []
    }
  ];

  for (const request of requests) {
    assert.equal(validXiaohongshuPgyRequest({
      ...request,
      referer: REFERER,
      request_interval_ms: 3000
    }), true);
    assert.equal(xiaohongshuPgyMethod(request.path), "GET");
  }
});

test("PGY 商业案例合同拒绝缺失、重复和扩展外参数", () => {
  const base = {
    path: XIAOHONGSHU_PGY_GOOD_NOTES_PATH,
    method: "GET",
    referer: REFERER
  };
  const invalidEntries = [
    [],
    [["category", " 美妆个护"]],
    [["category", "美妆个护"], ["category", "潮流运动"]],
    [["category", "美妆个护"], ["page", "2"]],
    [["category", "x".repeat(65)]]
  ];

  for (const entries of invalidEntries) {
    assert.equal(validXiaohongshuPgyRequest({ ...base, entries }), false);
  }
});
