import assert from "node:assert/strict";
import test from "node:test";

import {
  XIAOHONGSHU_SEARCH_FILTER_PATH,
  XIAOHONGSHU_SEARCH_NOTES_PATH,
  XIAOHONGSHU_WIDGETS_PATH,
  validXiaohongshuRequest
} from "./adapters/xiaohongshu/contract.js";
import {
  invokeXiaohongshuPageRuntime
} from "./adapters/xiaohongshu/page_runtime.js";

const NOTE_ID = "64c13017000000000103cde1";
const SEARCH_ID = "search_fixture_123";

test("小红书商业洞察合同固定筛选器、关联搜索与新增排序值", () => {
  assert.equal(validXiaohongshuRequest({
    method: "GET",
    path: XIAOHONGSHU_SEARCH_FILTER_PATH,
    entries: [["keyword", "露营"], ["search_id", SEARCH_ID]],
    referer: "https://www.xiaohongshu.com/search_result",
    request_interval_ms: 3000
  }), true);
  assert.equal(validXiaohongshuRequest({
    method: "POST",
    path: XIAOHONGSHU_WIDGETS_PATH,
    entries: [["note_id", NOTE_ID]],
    referer: `https://www.xiaohongshu.com/explore/${NOTE_ID}`,
    request_interval_ms: 3000
  }), true);
  for (const sort of ["comment_descending", "collect_descending"]) {
    assert.equal(validXiaohongshuRequest({
      method: "POST",
      path: XIAOHONGSHU_SEARCH_NOTES_PATH,
      entries: [
        ["keyword", "露营"],
        ["page", "1"],
        ["page_size", "20"],
        ["search_id", SEARCH_ID],
        ["sort", sort],
        ["note_type", "0"]
      ],
      referer: "https://www.xiaohongshu.com/search_result",
      request_interval_ms: 3000
    }), true);
  }
});

test("小红书关联搜索页面运行时固定 widgets 场景参数", () => {
  const source = String(invokeXiaohongshuPageRuntime);

  assert.match(source, /\/api\/sns\/web\/v2\/widgets/);
  assert.match(source, /scene:\s*"web"/);
  assert.match(source, /mode:\s*1/);
  assert.match(source, /source:\s*"web_feed"/);
  assert.match(source, /webSupportRelatedSearch:\s*true/);
});
