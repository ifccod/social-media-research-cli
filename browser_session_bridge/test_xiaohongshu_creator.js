import assert from "node:assert/strict";
import test from "node:test";

import {
  XiaohongshuCreatorSessionAdapter
} from "./adapters/xiaohongshu_creator/adapter.js";
import {
  XIAOHONGSHU_CREATOR_LOGIN_URL,
  XIAOHONGSHU_CREATOR_PUBLISH_NOTE_PATH,
  XIAOHONGSHU_CREATOR_UPLOAD_IMAGE_PATH,
  XIAOHONGSHU_CREATOR_UPLOAD_VIDEO_PATH,
  isXiaohongshuCreatorTabUrl,
  sameXiaohongshuCreatorRequestContext,
  validXiaohongshuCreatorRequest
} from "./adapters/xiaohongshu_creator/contract.js";
import {
  invokeXiaohongshuCreatorPageRuntime
} from "./adapters/xiaohongshu_creator/page_runtime.js";
import { SerialRequestPolicy } from "./core/serial_request_policy.js";

const NOTE_ID = "0123456789abcdef01234567";
const FILE_ID = "fixture-file-id";
const COVER_FILE_ID = "fixture-cover-id";
const PERMIT_SECRET = "PERMIT_SECRET";
const USER_INFO_URL = "https://creator.xiaohongshu.com/api/galaxy/user/info";
const PERMIT_URL = "https://creator.xiaohongshu.com/api/media/v1/upload/creator/permit";
const PNG_1X1 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
const VIDEO_CHUNK_A = Buffer.from("hel", "utf8").toString("base64");
const VIDEO_CHUNK_B = Buffer.from("lo", "utf8").toString("base64");

function uploadRequest(overrides = {}) {
  return {
    method: "POST",
    path: XIAOHONGSHU_CREATOR_UPLOAD_IMAGE_PATH,
    entries: [
      ["mimeType", "image/png"],
      ["dataBase64", PNG_1X1]
    ],
    referer: XIAOHONGSHU_CREATOR_LOGIN_URL,
    request_interval_ms: 3000,
    ...overrides
  };
}

function publishRequest(overrides = {}) {
  return {
    method: "POST",
    path: XIAOHONGSHU_CREATOR_PUBLISH_NOTE_PATH,
    entries: [
      ["title", "测试标题"],
      ["content", "测试正文"],
      ["file_ids", `spectrum/${FILE_ID}`]
    ],
    referer: XIAOHONGSHU_CREATOR_LOGIN_URL,
    request_interval_ms: 3000,
    ...overrides
  };
}

function videoBeginRequest(totalBytes = 5, overrides = {}) {
  return {
    method: "POST",
    path: XIAOHONGSHU_CREATOR_UPLOAD_VIDEO_PATH,
    entries: [
      ["command", "begin"],
      ["mimeType", "video/mp4"],
      ["total_bytes", String(totalBytes)]
    ],
    referer: XIAOHONGSHU_CREATOR_LOGIN_URL,
    request_interval_ms: 3000,
    ...overrides
  };
}

function videoChunkRequest(uploadId, segmentIndex, dataBase64, overrides = {}) {
  return {
    method: "POST",
    path: XIAOHONGSHU_CREATOR_UPLOAD_VIDEO_PATH,
    entries: [
      ["command", "chunk"],
      ["upload_id", uploadId],
      ["segment_index", String(segmentIndex)],
      ["dataBase64", dataBase64]
    ],
    referer: XIAOHONGSHU_CREATOR_LOGIN_URL,
    request_interval_ms: 3000,
    ...overrides
  };
}

function videoFinishRequest(uploadId, overrides = {}) {
  return {
    method: "POST",
    path: XIAOHONGSHU_CREATOR_UPLOAD_VIDEO_PATH,
    entries: [
      ["command", "finish"],
      ["upload_id", uploadId]
    ],
    referer: XIAOHONGSHU_CREATOR_LOGIN_URL,
    request_interval_ms: 3000,
    ...overrides
  };
}

function publishVideoRequest(overrides = {}) {
  return {
    method: "POST",
    path: XIAOHONGSHU_CREATOR_PUBLISH_NOTE_PATH,
    entries: [
      ["title", "测试标题"],
      ["content", "测试正文"],
      ["video_file_id", `spectrum/${FILE_ID}`],
      ["cover_file_id", `spectrum/${COVER_FILE_ID}`],
      ["width", "8"],
      ["height", "6"]
    ],
    referer: XIAOHONGSHU_CREATOR_LOGIN_URL,
    request_interval_ms: 3000,
    ...overrides
  };
}

function sessionCookie(cookie) {
  return /(?:^|;\s*)(?:galaxy_creator_session_id|access-token-creator|customer-sso-sid|web_session)=/.test(
    cookie
  );
}

function installPageFixture({
  href = XIAOHONGSHU_CREATOR_LOGIN_URL,
  cookie = "galaxy_creator_session_id=1",
  title = "小红书创作服务平台",
  includeWebpack = true,
  webpackName = "webpackChunkugc",
  hookPush = true,
  includeClient = true,
  includeConstants = true,
  loginState = "auto",
  onPostNote = null,
  onGet = null,
  onPut = null
} = {}) {
  const previous = {
    document: globalThis.document,
    navigator: globalThis.navigator,
    screen: globalThis.screen,
    window: globalThis.window,
    fetch: globalThis.fetch
  };
  const wrapperCalls = [];
  let sessionCleared = false;

  function clearSession() {
    sessionCleared = true;
    throw new TypeError("Cannot read properties of undefined (reading '_s')");
  }

  function loginPayload() {
    if (loginState === "anonymous" || (loginState === "auto" && !sessionCookie(cookie))) {
      const error = new Error("无登录信息");
      error.status = 401;
      error.code = -100;
      throw error;
    }
    return {
      success: true,
      data: { userId: NOTE_ID, nickname: "fixture" }
    };
  }

  const factories = {
    postNote(module) {
      /* POST_NOTE toSnakeCase capa_trace_info extractData:!1 */
      async function E(payload) {
        /* LV.post(POST_NOTE) */
        wrapperCalls.push({ kind: "post_note", payload });
        if (typeof onPostNote === "function") {
          return onPostNote(payload);
        }
        return {
          success: true,
          result: 0,
          data: { id: NOTE_ID }
        };
      }
      module.exports = { E };
    },
    ...(includeConstants ? { constants(module) {
      module.exports = {
        S: {
          UPLOADER_TOKEN: "https://edith.xiaohongshu.com/api/media/v1/upload/web/permit",
          UPLOADER_TOKEN_NEWV2: PERMIT_URL,
          USER_INFO: USER_INFO_URL
        }
      };
    } } : {}),
    ...(includeClient ? { httpClient(module) {
      /* LV interceptor get post put */
      const LV = {
        async get(url) {
          wrapperCalls.push({ kind: "get", url: String(url) });
          if (typeof onGet === "function") {
            return onGet(String(url));
          }
          if (String(url).includes("/api/galaxy/user/info")) {
            return loginPayload();
          }
          if (String(url).includes("/upload/creator/permit")) {
            return {
              success: true,
              data: {
                uploadTempPermits: [{
                  fileIds: [FILE_ID],
                  uploadAddr: "ros-upload.example",
                  token: PERMIT_SECRET
                }]
              }
            };
          }
          throw new Error("unexpected get");
        },
        async post(url, payload) {
          wrapperCalls.push({ kind: "post_note", url: String(url), payload });
          if (typeof onPostNote === "function") {
            return onPostNote(payload);
          }
          return {
            success: true,
            result: 0,
            data: { id: NOTE_ID }
          };
        },
        async put(url, body, config) {
          wrapperCalls.push({
            kind: "put",
            url: String(url),
            body,
            headers: config && config.headers
          });
          if (typeof onPut === "function") {
            return onPut(String(url), body, config);
          }
          return { status: 200 };
        }
      };
      module.exports = { LV };
    } } : {}),
    imageUploader(module) {
      module.exports = {
        h: {
          imageUploader: {
            upload() {
              return clearSession();
            },
            _uploader: {
              bizName: "spectrum",
              scene: "image",
              getToken() {
                return clearSession();
              }
            }
          }
        }
      };
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
  if (hookPush) {
    chunks.push = (chunk) => {
      const runtime = chunk[2];
      if (typeof runtime === "function") {
        runtime(runtimeRequire);
      }
      return Array.prototype.push.call(chunks, chunk);
    };
  }

  const document = {
    cookie,
    title,
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
    location: { href },
    navigator,
    outerHeight: 900,
    outerWidth: 1440,
    screen,
    devicePixelRatio: 2,
    getComputedStyle() {
      return { display: "none", opacity: "0", visibility: "hidden" };
    }
  };
  if (includeWebpack) {
    window[webpackName] = chunks;
  }

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
  globalThis.fetch = async (url, init) => {
    const method = init && init.method ? String(init.method).toUpperCase() : "GET";
    wrapperCalls.push({
      kind: method === "PUT" ? "put" : "fetch",
      url: String(url),
      body: init && init.body,
      headers: init && init.headers
    });
    if (method === "PUT") {
      return { status: 200 };
    }
    if (String(url).includes("/api/galaxy/user/info") && loginState !== "anonymous" &&
      (loginState === "logged_in" || sessionCookie(cookie))) {
      return {
        status: 200,
        async json() {
          return { success: true, data: { userId: NOTE_ID, nickname: "fixture" } };
        }
      };
    }
    return {
      status: 401,
      async json() {
        return { code: -100, success: false, msg: "无登录信息" };
      }
    };
  };
  restore.wrapperCalls = wrapperCalls;
  restore.sessionCleared = () => sessionCleared;
  return restore;
}

test("创作者页标签匹配发布页和已登录的笔记管理页", () => {
  assert.equal(isXiaohongshuCreatorTabUrl(XIAOHONGSHU_CREATOR_LOGIN_URL), true);
  assert.equal(
    isXiaohongshuCreatorTabUrl("https://creator.xiaohongshu.com/new/note-manager"),
    true
  );
  assert.equal(
    sameXiaohongshuCreatorRequestContext(
      "https://creator.xiaohongshu.com/new/note-manager",
      XIAOHONGSHU_CREATOR_LOGIN_URL
    ),
    true
  );
  assert.equal(
    isXiaohongshuCreatorTabUrl(
      "https://creator.xiaohongshu.com/publish/publish?from=cli"
    ),
    true
  );
  assert.equal(
    isXiaohongshuCreatorTabUrl("https://www.xiaohongshu.com/explore"),
    false
  );
  assert.equal(
    isXiaohongshuCreatorTabUrl("https://creator.xiaohongshu.com/"),
    false
  );
  assert.equal(
    isXiaohongshuCreatorTabUrl("https://creator.xiaohongshu.com/publish"),
    false
  );
  assert.equal(
    isXiaohongshuCreatorTabUrl("https://creator.xiaohongshu.com/login?redirectReason=401"),
    false
  );
  assert.equal(
    sameXiaohongshuCreatorRequestContext(
      "https://creator.xiaohongshu.com/publish/publish?x=1",
      XIAOHONGSHU_CREATOR_LOGIN_URL
    ),
    true
  );
});

test("创作者桥接受 upload/publish entries 并拒绝非法输入", () => {
  assert.equal(validXiaohongshuCreatorRequest(uploadRequest()), true);
  assert.equal(validXiaohongshuCreatorRequest(publishRequest()), true);
  assert.equal(validXiaohongshuCreatorRequest(videoBeginRequest()), true);
  assert.equal(
    validXiaohongshuCreatorRequest(videoChunkRequest("fixture1", 0, VIDEO_CHUNK_A)),
    true
  );
  assert.equal(
    validXiaohongshuCreatorRequest(videoFinishRequest("fixture1")),
    true
  );
  assert.equal(validXiaohongshuCreatorRequest(publishVideoRequest()), true);
  assert.equal(
    validXiaohongshuCreatorRequest(uploadRequest({ method: "GET" })),
    false
  );
  assert.equal(
    validXiaohongshuCreatorRequest(videoBeginRequest(5, {
      entries: [
        ["command", "begin"],
        ["mimeType", "video/avi"],
        ["total_bytes", "5"]
      ]
    })),
    false
  );
  assert.equal(
    validXiaohongshuCreatorRequest(publishVideoRequest({
      entries: [
        ["title", "测试标题"],
        ["content", "测试正文"],
        ["video_file_id", `spectrum/${FILE_ID}`],
        ["file_ids", `spectrum/${FILE_ID}`]
      ]
    })),
    false
  );
  assert.equal(
    validXiaohongshuCreatorRequest(publishVideoRequest({
      entries: [
        ["title", "测试标题"],
        ["content", "测试正文"],
        ["video_file_id", `spectrum/${FILE_ID}`],
        ["width", "8"],
        ["height", "6"]
      ]
    })),
    false
  );
  assert.equal(
    validXiaohongshuCreatorRequest(uploadRequest({
      entries: [["mimeType", "image/gif"], ["dataBase64", PNG_1X1]]
    })),
    false
  );
  assert.equal(
    validXiaohongshuCreatorRequest(publishRequest({
      entries: [
        ["title", ""],
        ["content", "正文"],
        ["file_ids", `spectrum/${FILE_ID}`]
      ]
    })),
    false
  );
  assert.equal(
    validXiaohongshuCreatorRequest(publishRequest({
      entries: [
        ["title", "一二三四五六七八九十一二三四五六七八九十一"],
        ["content", "正文"],
        ["file_ids", `spectrum/${FILE_ID}`]
      ]
    })),
    false
  );
  assert.equal(
    validXiaohongshuCreatorRequest(publishRequest({
      entries: [
        ["title", "标题"],
        ["content", "正文"],
        ["file_ids", ""]
      ]
    })),
    false
  );
  assert.equal(
    validXiaohongshuCreatorRequest(publishRequest({
      referer: "https://www.xiaohongshu.com/explore"
    })),
    false
  );
  assert.equal(
    validXiaohongshuCreatorRequest(publishRequest({
      headers: { authorization: "BROWSER_ONLY" }
    })),
    false
  );
});

test("缺 webpackChunkugc 时 runtime_unavailable", async () => {
  const restore = installPageFixture({ includeWebpack: false });
  try {
    assert.deepEqual(await invokeXiaohongshuCreatorPageRuntime({
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
        request_ready: false,
        verification_required: false
      }
    });
    assert.deepEqual(await invokeXiaohongshuCreatorPageRuntime({
      kind: "request",
      operation_id: "creator_missing_webpack",
      method: "POST",
      path: XIAOHONGSHU_CREATOR_PUBLISH_NOTE_PATH,
      entries: publishRequest().entries
    }), {
      ok: false,
      error: "runtime_unavailable"
    });
  } finally {
    restore();
  }
});

test("未挂钩的 webpack 数组不能当成运行时就绪", async () => {
  const restore = installPageFixture({ hookPush: false });
  try {
    const session = await invokeXiaohongshuCreatorPageRuntime({ kind: "session" });
    assert.equal(session.ok, true);
    assert.equal(session.payload.logged_in, true);
    assert.equal(session.payload.request_ready, false);
    assert.deepEqual(await invokeXiaohongshuCreatorPageRuntime({
      kind: "request",
      operation_id: "creator_unhooked_webpack",
      method: "POST",
      path: XIAOHONGSHU_CREATOR_UPLOAD_IMAGE_PATH,
      entries: uploadRequest().entries
    }), {
      ok: false,
      error: "runtime_unavailable"
    });
  } finally {
    restore();
  }
});

test("非 ugc 的 webpackChunk 全局名仍能发现 Uploader", async () => {
  const restore = installPageFixture({ webpackName: "webpackChunkcreator" });
  try {
    const session = await invokeXiaohongshuCreatorPageRuntime({ kind: "session" });
    assert.equal(session.payload.request_ready, true);
    const result = await invokeXiaohongshuCreatorPageRuntime({
      kind: "request",
      operation_id: "creator_alt_webpack",
      method: "POST",
      path: XIAOHONGSHU_CREATOR_UPLOAD_IMAGE_PATH,
      entries: uploadRequest().entries
    });
    assert.equal(result.ok, true);
    assert.equal(result.payload.file_id, FILE_ID);
  } finally {
    restore();
  }
});

test("imageUploader 单例存在时仍走 permit，失败的 getToken 不清会话", async () => {
  const restore = installPageFixture();
  try {
    const result = await invokeXiaohongshuCreatorPageRuntime({
      kind: "request",
      operation_id: "creator_image_uploader_singleton",
      method: "POST",
      path: XIAOHONGSHU_CREATOR_UPLOAD_IMAGE_PATH,
      entries: uploadRequest().entries
    });
    assert.equal(result.ok, true);
    assert.equal(result.payload.file_id, FILE_ID);
    assert.equal(JSON.stringify(result).includes(PERMIT_SECRET), false);
    assert.equal(restore.sessionCleared(), false);
    assert.equal(restore.wrapperCalls.some((call) => call.kind === "upload"), false);
    const permit = restore.wrapperCalls.find((call) => String(call.url || "").includes("/creator/permit"));
    const put = restore.wrapperCalls.find((call) => call.kind === "put");
    assert.equal(permit.url.includes("scene=image"), true);
    assert.equal(permit.url.includes("biz_name=spectrum"), true);
    assert.equal(permit.url.includes("version=1"), true);
    assert.equal(permit.url.includes("source=web"), true);
    assert.equal(permit.url.includes("edith.xiaohongshu.com"), false);
    assert.equal(put.url, `https://ros-upload.example/spectrum/${FILE_ID}`);
    assert.equal(put.body instanceof File, true);
    assert.equal(put.headers["x-cos-security-token"], PERMIT_SECRET);
  } finally {
    restore();
  }
});

test("页面 Uploader 把 base64 转成 File 并返回脱敏 file_id", async () => {
  const restore = installPageFixture();
  try {
    const result = await invokeXiaohongshuCreatorPageRuntime({
      kind: "request",
      operation_id: "creator_upload_fixture",
      method: "POST",
      path: XIAOHONGSHU_CREATOR_UPLOAD_IMAGE_PATH,
      entries: uploadRequest().entries
    });
    assert.equal(result.ok, true);
    assert.equal(result.payload.file_id, FILE_ID);
    assert.equal(typeof result.payload.width, "number");
    assert.equal(typeof result.payload.height, "number");
    assert.equal(JSON.stringify(result).includes(PNG_1X1), false);
    assert.equal(JSON.stringify(result).includes(PERMIT_SECRET), false);
    assert.equal(restore.sessionCleared(), false);
    const put = restore.wrapperCalls.find((call) => call.kind === "put");
    assert.equal(put.body instanceof File, true);
    assert.equal(put.body.type, "image/png");
  } finally {
    restore();
  }
});

test("视频 Uploader 使用 scene=video 并在 finish 后拼成 File", async () => {
  const restore = installPageFixture();
  try {
    const begin = await invokeXiaohongshuCreatorPageRuntime({
      kind: "request",
      operation_id: "creator_video_begin",
      method: "POST",
      path: XIAOHONGSHU_CREATOR_UPLOAD_VIDEO_PATH,
      entries: videoBeginRequest(5).entries
    });
    assert.equal(begin.ok, true);
    const uploadId = begin.payload.upload_id;
    assert.equal(typeof uploadId, "string");
    assert.match(uploadId, /^[A-Za-z0-9_-]{8,64}$/);
    const chunk0 = await invokeXiaohongshuCreatorPageRuntime({
      kind: "request",
      operation_id: "creator_video_chunk0",
      method: "POST",
      path: XIAOHONGSHU_CREATOR_UPLOAD_VIDEO_PATH,
      entries: videoChunkRequest(uploadId, 0, VIDEO_CHUNK_A).entries
    });
    assert.equal(chunk0.ok, true);
    const chunk1 = await invokeXiaohongshuCreatorPageRuntime({
      kind: "request",
      operation_id: "creator_video_chunk1",
      method: "POST",
      path: XIAOHONGSHU_CREATOR_UPLOAD_VIDEO_PATH,
      entries: videoChunkRequest(uploadId, 1, VIDEO_CHUNK_B).entries
    });
    assert.equal(chunk1.ok, true);
    const finish = await invokeXiaohongshuCreatorPageRuntime({
      kind: "request",
      operation_id: "creator_video_finish",
      method: "POST",
      path: XIAOHONGSHU_CREATOR_UPLOAD_VIDEO_PATH,
      entries: videoFinishRequest(uploadId).entries
    });
    assert.equal(finish.ok, true);
    assert.equal(finish.payload.file_id, FILE_ID);
    assert.equal(JSON.stringify(finish).includes(PERMIT_SECRET), false);
    const permit = restore.wrapperCalls.find((call) => String(call.url || "").includes("scene=video"));
    const put = restore.wrapperCalls.find((call) => call.kind === "put");
    assert.ok(permit);
    assert.equal(permit.url.includes("biz_name=spectrum"), true);
    assert.equal(put.body instanceof File, true);
    assert.equal(put.body.type, "video/mp4");
    assert.equal(put.body.size, 5);
  } finally {
    restore();
  }
});

test("发布视频 type=video、image_info null、有 fileid、无 post_loc", async () => {
  const restore = installPageFixture();
  try {
    const result = await invokeXiaohongshuCreatorPageRuntime({
      kind: "request",
      operation_id: "creator_publish_video_fixture",
      method: "POST",
      path: XIAOHONGSHU_CREATOR_PUBLISH_NOTE_PATH,
      entries: publishVideoRequest().entries
    });
    assert.equal(result.ok, true);
    assert.equal(result.payload.success, true);
    const body = restore.wrapperCalls.find((call) => call.kind === "post_note").payload;
    assert.equal(body.common.type, "video");
    assert.equal(body.image_info, null);
    assert.equal(body.video_info.fileid, `spectrum/${FILE_ID}`);
    assert.equal(body.video_info.file_id, `spectrum/${FILE_ID}`);
    assert.equal(body.video_info.format_width, 8);
    assert.equal(body.video_info.format_height, 6);
    assert.equal(body.video_info.cover.fileid, `spectrum/${COVER_FILE_ID}`);
    assert.equal(Object.hasOwn(body, "post_loc"), false);
    assert.equal(Object.hasOwn(body.common, "post_loc"), false);
    assert.equal(Object.hasOwn(body.common, "postLoc"), false);
  } finally {
    restore();
  }
});

test("发布包装函数收到 title/desc/type=normal/privacy 0/file_id 且无 post_loc", async () => {
  const restore = installPageFixture();
  try {
    const result = await invokeXiaohongshuCreatorPageRuntime({
      kind: "request",
      operation_id: "creator_publish_fixture",
      method: "POST",
      path: XIAOHONGSHU_CREATOR_PUBLISH_NOTE_PATH,
      entries: publishRequest().entries
    });
    assert.equal(result.ok, true);
    assert.equal(result.payload.success, true);
    assert.equal(result.payload.data.id, NOTE_ID);
    const body = restore.wrapperCalls.find((call) => call.kind === "post_note").payload;
    assert.equal(body.common.title, "测试标题");
    assert.equal(body.common.desc, "测试正文");
    assert.equal(body.common.type, "normal");
    assert.equal(body.common.privacy_info.type, 0);
    assert.equal(body.image_info.images[0].file_id, `spectrum/${FILE_ID}`);
    assert.equal(Object.hasOwn(body, "post_loc"), false);
    assert.equal(Object.hasOwn(body.common, "post_loc"), false);
  } finally {
    restore();
  }
});

test("HTTP 461 分类为 verification_required", async () => {
  const restore = installPageFixture({
    onPostNote() {
      const error = new Error("HTTPServerError");
      error.status = 461;
      throw error;
    }
  });
  try {
    assert.deepEqual(await invokeXiaohongshuCreatorPageRuntime({
      kind: "request",
      operation_id: "creator_461_fixture",
      method: "POST",
      path: XIAOHONGSHU_CREATOR_PUBLISH_NOTE_PATH,
      entries: publishRequest().entries
    }), {
      ok: false,
      error: "verification_required"
    });
  } finally {
    restore();
  }
});

test("业务 300013 频次异常分类为 rate_limited", async () => {
  const restore = installPageFixture({
    onPostNote() {
      return { success: false, code: 300013, msg: "访问频次异常" };
    }
  });
  try {
    assert.deepEqual(await invokeXiaohongshuCreatorPageRuntime({
      kind: "request",
      operation_id: "creator_300013_fixture",
      method: "POST",
      path: XIAOHONGSHU_CREATOR_PUBLISH_NOTE_PATH,
      entries: publishRequest().entries
    }), {
      ok: false,
      error: "rate_limited"
    });
  } finally {
    restore();
  }
});

test("未登录创作者页立即 not_logged_in", async () => {
  const restore = installPageFixture({
    cookie: "",
    title: ""
  });
  try {
    assert.deepEqual(await invokeXiaohongshuCreatorPageRuntime({
      kind: "request",
      operation_id: "creator_anonymous",
      method: "POST",
      path: XIAOHONGSHU_CREATOR_PUBLISH_NOTE_PATH,
      entries: publishRequest().entries
    }), {
      ok: false,
      error: "not_logged_in"
    });
    assert.equal(restore.wrapperCalls.some((call) => call.kind === "post_note"), false);
    assert.equal(restore.wrapperCalls.some((call) => call.kind === "put"), false);
    assert.equal(restore.sessionCleared(), false);
  } finally {
    restore();
  }
});

test("标题和发布文案不能当成已登录，用户信息 401 就是未登录", async () => {
  const restore = installPageFixture({
    cookie: "a1=device; webId=visitor",
    title: "小红书创作服务平台",
    loginState: "anonymous"
  });
  try {
    const session = await invokeXiaohongshuCreatorPageRuntime({ kind: "session" });
    assert.equal(session.ok, true);
    assert.equal(session.payload.logged_in, false);
    assert.equal(session.payload.request_ready, false);
    assert.equal(restore.sessionCleared(), false);
  } finally {
    restore();
  }
});

test("没有 LV 时上传 runtime_unavailable，且不调用 getToken", async () => {
  const restore = installPageFixture({ includeClient: false });
  try {
    const started = Date.now();
    const result = await invokeXiaohongshuCreatorPageRuntime({
      kind: "request",
      operation_id: "creator_missing_lv",
      method: "POST",
      path: XIAOHONGSHU_CREATOR_UPLOAD_IMAGE_PATH,
      entries: uploadRequest().entries
    });
    assert.deepEqual(result, { ok: false, error: "runtime_unavailable" });
    assert.equal(Date.now() - started < 1000, true);
    assert.equal(restore.sessionCleared(), false);
    assert.equal(restore.wrapperCalls.some((call) => call.kind === "put"), false);
  } finally {
    restore();
  }
});

test("permit 401 立即 not_logged_in，不走 getToken", async () => {
  const restore = installPageFixture({
    onGet(url) {
      if (url.includes("/creator/permit")) {
        return { status: 401, code: -100, success: false, msg: "无登录信息" };
      }
      return { success: true, data: { userId: NOTE_ID, nickname: "fixture" } };
    }
  });
  try {
    const started = Date.now();
    assert.deepEqual(await invokeXiaohongshuCreatorPageRuntime({
      kind: "request",
      operation_id: "creator_permit_401",
      method: "POST",
      path: XIAOHONGSHU_CREATOR_UPLOAD_IMAGE_PATH,
      entries: uploadRequest().entries
    }), {
      ok: false,
      error: "not_logged_in"
    });
    assert.equal(Date.now() - started < 1000, true);
    assert.equal(restore.sessionCleared(), false);
    assert.equal(restore.wrapperCalls.some((call) => call.kind === "put"), false);
  } finally {
    restore();
  }
});

test("会话探测缺发布页时不自行创建标签页", async () => {
  let created = 0;
  const chromeApi = {
    tabs: {
      onRemoved: { addListener: () => undefined },
      query: async () => [
        {
          id: 1,
          url: "https://www.xiaohongshu.com/explore",
          status: "complete"
        },
        {
          id: 2,
          url: "https://creator.xiaohongshu.com/",
          status: "complete"
        }
      ],
      create: async () => {
        created += 1;
        return { id: 9, url: XIAOHONGSHU_CREATOR_LOGIN_URL };
      }
    }
  };
  const adapter = new XiaohongshuCreatorSessionAdapter({ chromeApi });
  const result = await adapter.routeSession();
  assert.deepEqual(result, { error: "tab_unavailable" });
  assert.equal(created, 0);
});

test("写路径 429 不闩后续创作者请求", async () => {
  let clock = 1000;
  const policy = new SerialRequestPolicy({
    now: () => clock,
    delay: async (milliseconds) => {
      clock += milliseconds;
    }
  });
  const adapter = new XiaohongshuCreatorSessionAdapter({
    chromeApi: {},
    requestPolicy: policy
  });
  adapter.pickTab = async () => ({
    id: 7,
    status: "complete",
    url: XIAOHONGSHU_CREATOR_LOGIN_URL
  });
  let calls = 0;
  adapter.runInPage = async () => {
    calls += 1;
    if (calls === 1) {
      return { ok: false, error: "rate_limited" };
    }
    return { ok: true, payload: { success: true, result: 0 } };
  };
  const request = publishRequest({ request_interval_ms: 0 });
  assert.deepEqual(await adapter.routeRequest(request), {
    error: "rate_limited"
  });
  assert.deepEqual(await adapter.routeRequest(request), {
    payload: { success: true, result: 0 }
  });
  assert.equal(calls, 2);
});
