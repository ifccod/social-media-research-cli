import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  BILIBILI_UP_STAT_PATH,
  validBilibiliEntries,
  validBilibiliReferer,
  validBilibiliRequest
} from "./adapters/bilibili/contract.js";

const ENTRIES = [["mid", "178360345"]];
const REFERER = "https://space.bilibili.com/178360345";

test("Bilibili up-stat binds path, UID, and space referer", () => {
  assert.equal(validBilibiliEntries(BILIBILI_UP_STAT_PATH, ENTRIES), true);
  assert.equal(
    validBilibiliReferer(BILIBILI_UP_STAT_PATH, ENTRIES, REFERER),
    true
  );
  assert.equal(validBilibiliRequest({
    path: BILIBILI_UP_STAT_PATH,
    entries: ENTRIES,
    referer: REFERER,
    request_interval_ms: 3000
  }), true);

  for (const request of [
    {
      path: BILIBILI_UP_STAT_PATH,
      entries: [["mid", "0"]],
      referer: "https://space.bilibili.com/0",
      request_interval_ms: 3000
    },
    {
      path: BILIBILI_UP_STAT_PATH,
      entries: ENTRIES,
      referer: "https://space.bilibili.com/2",
      request_interval_ms: 3000
    },
    {
      path: BILIBILI_UP_STAT_PATH,
      entries: ENTRIES,
      referer: `${REFERER}?SESSDATA=secret`,
      request_interval_ms: 3000
    },
    {
      path: "/bridge/v1/bilibili/unknown",
      entries: ENTRIES,
      referer: REFERER,
      request_interval_ms: 3000
    }
  ]) {
    assert.equal(validBilibiliRequest(request), false);
  }
});

test("Bilibili page runtime keeps Cookie state in Chrome", () => {
  const source = readFileSync(
    new URL("./adapters/bilibili/page_runtime.js", import.meta.url),
    "utf8"
  );
  assert.match(source, /\/x\/space\/upstat\?mid=/);
  assert.match(source, /credentials:\s*"include"/);
  assert.match(source, /bilibili_web_browser/);
  assert.doesNotMatch(source, /chrome\.cookies/);
});
