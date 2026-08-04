import assert from "node:assert/strict";
import test from "node:test";

import {
  TIKTOK_CREATIVE_STUDIO_CREDITS_PATH,
  TIKTOK_CREATIVE_STUDIO_GENERATING_COUNT_PATH,
  TIKTOK_CREATIVE_STUDIO_GENERATE_PATH,
  TIKTOK_CREATIVE_STUDIO_I2V_GENERATE_PATH,
  TIKTOK_CREATIVE_STUDIO_HISTORY_PATH,
  TIKTOK_CREATIVE_STUDIO_LEDGER_PATH,
  TIKTOK_CREATIVE_STUDIO_MAX_COUNT_PATH,
  TIKTOK_CREATIVE_STUDIO_PERMISSIONS_PATH,
  TIKTOK_CREATIVE_STUDIO_TASK_PATH,
  TIKTOK_CREATIVE_STUDIO_TASK_DETAIL_PATH,
  TIKTOK_CREATIVE_STUDIO_UPLOAD_IMAGE_PATH,
  TIKTOK_CREATIVE_STUDIO_URL,
  TIKTOK_CREATIVE_STUDIO_VIDEO_INFO_PATH,
  isTikTokCreativeScopeTabUrl,
  sameTikTokCreativeRequestContext,
  validTikTokCreativeEntries,
  validTikTokCreativeRequest,
  validTikTokCreativeStudioReferer
} from "./adapters/tiktok_creative/contract.js";
import {
  invokeTikTokCreativePageRuntime
} from "./adapters/tiktok_creative/page_runtime.js";

const TASK_ID = "7667519430651838480";
const DRAFT_ID = "7667519189036662801";

function studioRequest(path, entries) {
  return {
    path,
    entries,
    referer: TIKTOK_CREATIVE_STUDIO_URL,
    request_interval_ms: 3000
  };
}

const STUDIO_T2V_URL =
  "https://ads.tiktok.com/creative/creativestudio/image-to-video" +
  "?subApp=CreativeStudio%2FMiniApp%2FTextToVideo";

function taskPayload(status = 2) {
  return {
    code: 0,
    data: {
      task_id: TASK_ID,
      draft_infos: [
        {
          id: DRAFT_ID,
          name: "Text to video",
          miniAppType: "T2V",
          taskId: TASK_ID,
          draftTaskStatus: status,
          renderTaskStatus: status,
          hasContent: status === 0,
          vid: status === 0 ? "v14033g50000d9k838nog65j01cfgom0" : "",
          watermarkVid: status === 0 ? "v10033g50000d9k83dvog65vd9o9k8q0" : "",
          coverImage: status === 0
            ? "https://p16.example.test/cover.jpeg"
            : "",
          previewLink: "",
          settings: JSON.stringify({
            aiModel: "5000005",
            duration: 5,
            prompt: "一杯冰咖啡",
            useEnhancePrompt: false
          })
        }
      ]
    }
  };
}

function videoPayload() {
  return {
    code: 0,
    data: {
      v14033g50000d9k838nog65j01cfgom0: {
        Duration: 5.062,
        PosterUrl: "https://p16.example.test/poster.jpeg",
        VideoInfos: [
          {
            MainUrl: "https://v16.example.test/video-720.mp4",
            BackupUrl: "https://v19.example.test/video-720.mp4",
            VideoMeta: {
              Width: "720",
              Height: "1280",
              Size: "846648",
              Bitrate: "1338045",
              FPS: "24",
              Definition: "720p",
              Format: "mp4"
            }
          }
        ]
      }
    }
  };
}

async function withStudioPage(
  fetchImpl,
  callback,
  pageURL = TIKTOK_CREATIVE_STUDIO_URL,
  windowExtras = {}
) {
  const names = [
    "window",
    "document",
    "Element",
    "location",
    "navigator",
    "screen",
    "fetch"
  ];
  const previous = new Map(names.map((name) => [
    name,
    Object.getOwnPropertyDescriptor(globalThis, name)
  ]));
  class FixtureElement {
    getBoundingClientRect() {
      return { width: 320, height: 180 };
    }
  }
  const locationValue = new URL(pageURL);
  const values = {
    window: {
      fetch: fetchImpl,
      getComputedStyle: () => ({
        display: "block",
        visibility: "visible",
        opacity: "1"
      }),
      devicePixelRatio: 1,
      innerWidth: 1280,
      innerHeight: 720,
      outerWidth: 1280,
      outerHeight: 800,
      ...windowExtras
    },
    document: {
      cookie:
        "csrftoken=fixture-csrf; " +
        "x-creative-csrf-token=fixture-creative-csrf",
      getElementById: () => null,
      querySelectorAll: () => []
    },
    Element: FixtureElement,
    location: locationValue,
    navigator: {
      userAgent: "fixture",
      language: "zh-CN",
      languages: ["zh-CN"],
      platform: "MacIntel",
      vendor: "Google Inc.",
      cookieEnabled: true,
      onLine: true
    },
    screen: {
      width: 1280,
      height: 720,
      availWidth: 1280,
      availHeight: 700,
      colorDepth: 24,
      pixelDepth: 24
    },
    fetch: fetchImpl
  };
  try {
    for (const [name, value] of Object.entries(values)) {
      Object.defineProperty(globalThis, name, {
        configurable: true,
        writable: true,
        value
      });
    }
    return await callback();
  } finally {
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

test("Creative Studio 合同只接受固定页面和固定操作", () => {
  assert.equal(validTikTokCreativeStudioReferer(TIKTOK_CREATIVE_STUDIO_URL), true);
  assert.equal(
    validTikTokCreativeStudioReferer(
      TIKTOK_CREATIVE_STUDIO_URL.replace("signup", "login")
    ),
    true
  );
  assert.equal(validTikTokCreativeStudioReferer(STUDIO_T2V_URL), true);
  assert.equal(isTikTokCreativeScopeTabUrl(STUDIO_T2V_URL, "studio"), true);
  assert.equal(
    sameTikTokCreativeRequestContext(
      STUDIO_T2V_URL,
      TIKTOK_CREATIVE_STUDIO_URL
    ),
    true
  );
  assert.equal(
    validTikTokCreativeStudioReferer(
      `${STUDIO_T2V_URL}&region=row`
    ),
    false
  );
  const firstFrameUrl =
    "https://p19-creative-tool-sg.ibyteimg.com/tos-alisg-i/test.image";
  assert.equal(
    validTikTokCreativeEntries(
      TIKTOK_CREATIVE_STUDIO_I2V_GENERATE_PATH,
      [
        ["prompt", "轻微推镜"],
        ["duration", "5"],
        ["firstFrameUrl", firstFrameUrl],
        ["lastFrameUrl", firstFrameUrl]
      ]
    ),
    true
  );
  assert.equal(
    validTikTokCreativeEntries(
      TIKTOK_CREATIVE_STUDIO_UPLOAD_IMAGE_PATH,
      [
        ["name", "frame.png"],
        ["mimeType", "image/png"],
        ["dataBase64", "aGVsbG8="]
      ]
    ),
    true
  );
  assert.equal(
    validTikTokCreativeStudioReferer(
      "https://ads.tiktok.com/creative/creativestudio/create?region=US"
    ),
    false
  );
  assert.equal(
    validTikTokCreativeEntries(
      TIKTOK_CREATIVE_STUDIO_GENERATE_PATH,
      [["prompt", "一杯冰咖啡"], ["duration", "5"], ["enhancePrompt", "0"]]
    ),
    true
  );
  assert.equal(
    validTikTokCreativeEntries(
      TIKTOK_CREATIVE_STUDIO_GENERATE_PATH,
      [["prompt", "一杯冰咖啡"], ["duration", "16"]]
    ),
    false
  );
  assert.equal(
    validTikTokCreativeRequest(
      studioRequest(TIKTOK_CREATIVE_STUDIO_CREDITS_PATH, [])
    ),
    true
  );
  assert.equal(
    validTikTokCreativeRequest(
      studioRequest(TIKTOK_CREATIVE_STUDIO_TASK_PATH, [["taskId", TASK_ID]])
    ),
    true
  );
  assert.equal(
    validTikTokCreativeRequest({
      ...studioRequest(
        TIKTOK_CREATIVE_STUDIO_TASK_PATH,
        [["taskId", TASK_ID]]
      ),
      referer: STUDIO_T2V_URL
    }),
    true
  );
  assert.equal(
    validTikTokCreativeRequest(
      studioRequest(TIKTOK_CREATIVE_STUDIO_PERMISSIONS_PATH, [])
    ),
    true
  );
  assert.equal(
    validTikTokCreativeRequest(
      studioRequest(
        TIKTOK_CREATIVE_STUDIO_LEDGER_PATH,
        [["pageSize", "20"], ["cursor", "next-page"]]
      )
    ),
    true
  );
  assert.equal(
    validTikTokCreativeRequest(
      studioRequest(
        TIKTOK_CREATIVE_STUDIO_HISTORY_PATH,
        [["offset", "0"], ["limit", "30"]]
      )
    ),
    true
  );
  assert.equal(
    validTikTokCreativeRequest(
      studioRequest(
        TIKTOK_CREATIVE_STUDIO_TASK_DETAIL_PATH,
        [["draftId", DRAFT_ID]]
      )
    ),
    true
  );
  assert.equal(
    validTikTokCreativeRequest(
      studioRequest(
        TIKTOK_CREATIVE_STUDIO_VIDEO_INFO_PATH,
        [["vid", "v14033g50000d9k838nog65j01cfgom0"]]
      )
    ),
    true
  );
});

test("Creative Studio 额度请求保留凭据并只返回额度字段", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      status: 200,
      json: async () => ({
        BaseResp: { StatusCode: 0, StatusMessage: "" },
        credits: "1995",
        bonus: "0",
        weekly_spent: "5",
        tier: 2,
        is_unlimited: false,
        user_info: { aio_user_id: "private" }
      })
    };
  };
  const result = await withStudioPage(fetchImpl, () =>
    invokeTikTokCreativePageRuntime({
      kind: "request",
      path: TIKTOK_CREATIVE_STUDIO_CREDITS_PATH,
      entries: [],
      session_verified: true
    })
  );
  assert.equal(result.ok, true);
  assert.deepEqual(result.payload, {
    credits: "1995",
    bonus: "0",
    weekly_spent: "5",
    tier: 2,
    is_unlimited: false
  });
  assert.match(calls[0].url, /aid=585599/);
  assert.equal(calls[0].options.credentials, "include");
  assert.equal(calls[0].options.headers["x-csrftoken"], "fixture-csrf");
  assert.equal(
    calls[0].options.headers["x-creative-csrf-token"],
    "fixture-creative-csrf"
  );
  assert.equal(calls[0].options.headers["x-creative-source"], "cue/avatar");
  const encoded = JSON.stringify(result);
  assert.equal(encoded.includes("fixture-csrf"), false);
  assert.equal(encoded.includes("fixture-creative-csrf"), false);
});

test("Creative Studio 真实 T2V 落地页可执行额度请求", async () => {
  const fetchImpl = async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      BaseResp: { StatusCode: 0, StatusMessage: "" },
      credits: "1995",
      bonus: "0",
      weekly_spent: "5",
      tier: 2,
      is_unlimited: false
    })
  });
  const result = await withStudioPage(
    fetchImpl,
    () => invokeTikTokCreativePageRuntime({
      kind: "request",
      path: TIKTOK_CREATIVE_STUDIO_CREDITS_PATH,
      entries: [],
      session_verified: true
    }),
    STUDIO_T2V_URL
  );
  assert.equal(result.ok, true);
  assert.equal(result.payload.credits, "1995");
});

test("Creative Studio 生成请求固定 Seedance 2.0 模型并返回任务", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      status: 200,
      json: async () => taskPayload(2)
    };
  };
  const result = await withStudioPage(fetchImpl, () =>
    invokeTikTokCreativePageRuntime({
      kind: "request",
      path: TIKTOK_CREATIVE_STUDIO_GENERATE_PATH,
      entries: [
        ["prompt", "一杯冰咖啡"],
        ["duration", "5"],
        ["enhancePrompt", "0"]
      ],
      session_verified: true
    })
  );
  assert.equal(result.ok, true);
  assert.equal(result.payload.task_id, TASK_ID);
  assert.equal(result.payload.status, "processing");
  assert.equal(result.payload.poll_after_ms, 5000);
  const body = JSON.parse(calls[0].options.body);
  assert.equal(body.model, "5000005");
  assert.equal(body.gokuModel, "5000005");
  assert.equal(body.duration, 5);
  assert.equal(JSON.parse(body.settings).useReferencePrompt, false);
});

test("Creative Studio I2V 请求携带首尾帧并固定 Seedance 2.0", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      status: 200,
      json: async () => taskPayload(2)
    };
  };
  const firstFrameUrl =
    "https://p19-creative-tool-sg.ibyteimg.com/tos-alisg-i/first.image";
  const lastFrameUrl =
    "https://p19-creative-tool-sg.ibyteimg.com/tos-alisg-i/last.image";
  const result = await withStudioPage(fetchImpl, () =>
    invokeTikTokCreativePageRuntime({
      kind: "request",
      path: TIKTOK_CREATIVE_STUDIO_I2V_GENERATE_PATH,
      entries: [
        ["prompt", "把门牌挂到门上"],
        ["duration", "5"],
        ["firstFrameUrl", firstFrameUrl],
        ["lastFrameUrl", lastFrameUrl]
      ],
      session_verified: true
    })
  );
  assert.equal(result.ok, true);
  assert.equal(result.payload.task_id, TASK_ID);
  const body = JSON.parse(calls[0].options.body);
  assert.equal(body.model, "4000005");
  assert.deepEqual(body.images, [firstFrameUrl, lastFrameUrl]);
  const settings = JSON.parse(body.settings);
  assert.equal(settings.images.length, 2);
  assert.equal(settings.image, firstFrameUrl);
});

test("Creative Studio 本机参考图通过页面上传模块进入 I2V 资产", async () => {
  const uploadCalls = [];
  const modules = {
    35970: {
      rh: async (file, options) => {
        uploadCalls.push({
          name: file.name,
          type: file.type,
          size: file.size,
          token: await options.getUploadToken()
        });
        return {
          imageUrl:
            "https://p19-creative-tool-sg.ibyteimg.com/tos-alisg-i/frame.image",
          imageUri: "tos-alisg-i/frame",
          imageWidth: 720,
          imageHeight: 1280
        };
      }
    },
    91304: {
      getToken: async () => ({ token: "fixture" })
    }
  };
  const chunks = [];
  chunks.push = (chunk) => {
    chunk[2]((moduleID) => modules[moduleID]);
    return 1;
  };
  const result = await withStudioPage(
    async () => {
      throw new Error("上传不应退化成普通 fetch");
    },
    () => invokeTikTokCreativePageRuntime({
      kind: "request",
      path: TIKTOK_CREATIVE_STUDIO_UPLOAD_IMAGE_PATH,
      entries: [
        ["name", "frame.png"],
        ["mimeType", "image/png"],
        ["dataBase64", "iVBORw0KGgo="]
      ],
      session_verified: true
    }),
    TIKTOK_CREATIVE_STUDIO_URL,
    { "@creative-ai/cue:fixture": chunks }
  );
  assert.equal(result.ok, true);
  assert.equal(result.payload.image_uri, "tos-alisg-i/frame");
  assert.equal(uploadCalls[0].name, "frame.png");
  assert.equal(uploadCalls[0].type, "image/png");
  assert.equal(uploadCalls[0].token.token, "fixture");
});

test("Creative Studio 任务终态包含视频标识和封面", async () => {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(url);
    return {
      ok: true,
      status: 200,
      json: async () => url.includes("/video_info")
        ? videoPayload()
        : {
          code: 0,
          data: {
            draft_infos: taskPayload(0).data.draft_infos
          }
        }
    };
  };
  const result = await withStudioPage(fetchImpl, () =>
    invokeTikTokCreativePageRuntime({
      kind: "request",
      path: TIKTOK_CREATIVE_STUDIO_TASK_PATH,
      entries: [["taskId", TASK_ID]],
      session_verified: true
    })
  );
  assert.equal(result.ok, true);
  assert.equal(result.payload.status, "succeeded");
  assert.equal(result.payload.poll_after_ms, 0);
  assert.equal(
    result.payload.drafts[0].vid,
    "v14033g50000d9k838nog65j01cfgom0"
  );
  assert.equal(
    result.payload.drafts[0].cover_image,
    "https://p16.example.test/cover.jpeg"
  );
  assert.equal(
    result.payload.drafts[0].video.video_url,
    "https://v16.example.test/video-720.mp4"
  );
  assert.match(calls[1], /\/video_info\?vid=/);
});

test("Creative Studio 权限与并发预检只返回业务状态", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    let payload;
    if (url.includes("get_miniapp_permission")) {
      payload = {
        code: 0,
        data: {
          miniappPermissions: {
            "CreativeStudio/MiniApp/TextToVideo": {
              entryPass: true,
              internalToken: "DROP"
            }
          },
          allowlist: [
            { tool: "cue_mini_i2v_seedance", auth: ["visit", "entry"] }
          ]
        }
      };
    } else if (url.includes("generating-task-count")) {
      payload = { code: 0, data: { total: 0 } };
    } else {
      payload = {
        code: 0,
        data: {
          "CreativeStudio/MiniApp/TextToVideo": 5,
          "CreativeStudio/MiniApp/ImageToVideo": 5
        }
      };
    }
    return { ok: true, status: 200, json: async () => payload };
  };
  const permissions = await withStudioPage(fetchImpl, () =>
    invokeTikTokCreativePageRuntime({
      kind: "request",
      path: TIKTOK_CREATIVE_STUDIO_PERMISSIONS_PATH,
      entries: [],
      session_verified: true
    })
  );
  const generating = await withStudioPage(fetchImpl, () =>
    invokeTikTokCreativePageRuntime({
      kind: "request",
      path: TIKTOK_CREATIVE_STUDIO_GENERATING_COUNT_PATH,
      entries: [],
      session_verified: true
    })
  );
  const maximum = await withStudioPage(fetchImpl, () =>
    invokeTikTokCreativePageRuntime({
      kind: "request",
      path: TIKTOK_CREATIVE_STUDIO_MAX_COUNT_PATH,
      entries: [],
      session_verified: true
    })
  );

  assert.equal(
    permissions.payload.permissions[
      "CreativeStudio/MiniApp/TextToVideo"
    ].entry_pass,
    true
  );
  assert.equal(JSON.stringify(permissions).includes("DROP"), false);
  assert.deepEqual(generating.payload, { total: 0 });
  assert.equal(
    maximum.payload.limits["CreativeStudio/MiniApp/TextToVideo"],
    5
  );
  assert.equal(calls[0].options.method, "GET");
  assert.equal(calls[1].options.method, "POST");
  assert.equal(Object.hasOwn(calls[1].options, "body"), false);
  assert.equal(calls[2].options.method, "GET");
});

test("Creative Studio 积分流水保留稳定分页并投影账本字段", async () => {
  let requestBody;
  const result = await withStudioPage(
    async (_url, options) => {
      requestBody = JSON.parse(options.body);
      return {
        ok: true,
        status: 200,
        json: async () => ({
          BaseResp: { StatusCode: 0, StatusMessage: "" },
          credit_ledger_entries: [
            {
              action: "generate",
              amount: -5,
              duration: 5,
              app_source: "t2v",
              created_at: 1785233491,
              updated_at: 1785233853,
              transaction_id: "txn-1",
              type: 2,
              aio_id: 7667516536974000144,
              extra: "{\"private\":\"DROP\"}"
            }
          ],
          has_more: true,
          next_cursor: "next-page"
        })
      };
    },
    () => invokeTikTokCreativePageRuntime({
      kind: "request",
      path: TIKTOK_CREATIVE_STUDIO_LEDGER_PATH,
      entries: [["pageSize", "20"]],
      session_verified: true
    })
  );

  assert.deepEqual(requestBody, { page_size: 20 });
  assert.equal(result.payload.entries[0].amount, -5);
  assert.equal(result.payload.entries[0].duration, 5);
  assert.equal(result.payload.has_more, true);
  assert.equal(result.payload.next_cursor, "next-page");
  assert.equal(JSON.stringify(result).includes("DROP"), false);
  assert.equal(Object.hasOwn(result.payload.entries[0], "aio_id"), false);
});

test("Creative Studio 历史、详情和视频信息形成恢复链路", async () => {
  const finishedDraft = taskPayload(0).data.draft_infos[0];
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    let payload;
    if (url.includes("/history/tasks")) {
      payload = {
        code: 0,
        data: {
          draft_infos: [finishedDraft],
          pageOffset: 0,
          pageLimit: 30,
          total: 1
        }
      };
    } else if (url.includes("/history/task/detail")) {
      payload = {
        code: 0,
        data: {
          ...finishedDraft,
          content: "{\"DraftFile\":\"DROP\"}"
        }
      };
    } else {
      payload = videoPayload();
    }
    return { ok: true, status: 200, json: async () => payload };
  };
  const history = await withStudioPage(fetchImpl, () =>
    invokeTikTokCreativePageRuntime({
      kind: "request",
      path: TIKTOK_CREATIVE_STUDIO_HISTORY_PATH,
      entries: [["offset", "0"], ["limit", "30"]],
      session_verified: true
    })
  );
  const detail = await withStudioPage(fetchImpl, () =>
    invokeTikTokCreativePageRuntime({
      kind: "request",
      path: TIKTOK_CREATIVE_STUDIO_TASK_DETAIL_PATH,
      entries: [["draftId", DRAFT_ID]],
      session_verified: true
    })
  );
  const video = await withStudioPage(fetchImpl, () =>
    invokeTikTokCreativePageRuntime({
      kind: "request",
      path: TIKTOK_CREATIVE_STUDIO_VIDEO_INFO_PATH,
      entries: [["vid", "v14033g50000d9k838nog65j01cfgom0"]],
      session_verified: true
    })
  );

  assert.deepEqual(
    JSON.parse(calls[0].options.body),
    {
      isAbridged: true,
      showPlayInfo: true,
      sorted: 2,
      pageOffset: 0,
      pageLimit: 30
    }
  );
  assert.equal(history.payload.total, 1);
  assert.equal(history.payload.has_more, false);
  assert.equal(history.payload.drafts[0].draft_id, DRAFT_ID);
  assert.match(calls[1].url, new RegExp(`draftId=${DRAFT_ID}`));
  assert.equal(detail.payload.video.vid, finishedDraft.vid);
  assert.equal(video.payload.vid, finishedDraft.vid);
  assert.equal(JSON.stringify(detail).includes("DROP"), false);
});
