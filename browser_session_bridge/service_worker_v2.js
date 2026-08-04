import { LocalSessionBridgeClient } from "./core/local_bridge_v2.js";
import { DEFAULT_BRIDGE_URL, isRecord } from "./core/protocol.js";
import { installReconnectAlarm } from "./core/reconnect_alarm.js";
import { createFastDiscoveryController } from "./core/fast_discovery.js";
import { SerialRequestPolicy } from "./core/serial_request_policy.js";
import { DouyinSessionAdapter } from "./adapters/douyin/adapter.js";
import { DOUYIN_ERROR_CODES } from "./adapters/douyin/contract.js";
import {
  DouyinIndexSessionAdapter
} from "./adapters/douyin_index/adapter.js";
import {
  DOUYIN_INDEX_ERROR_CODES
} from "./adapters/douyin_index/contract.js";
import { XIAOHONGSHU_ERROR_CODES } from "./adapters/xiaohongshu/contract.js";
import {
  createXiaohongshuAdapterFamily
} from "./adapters/xiaohongshu/family.js";
import {
  XIAOHONGSHU_APP_V2_ERROR_CODES
} from "./adapters/xiaohongshu_app_v2/contract.js";
import {
  XIAOHONGSHU_PGY_ERROR_CODES
} from "./adapters/xiaohongshu_pgy/contract.js";
import { LinkedInSessionAdapter } from "./adapters/linkedin/adapter.js";
import { LINKEDIN_ERROR_CODES } from "./adapters/linkedin/contract.js";
import { RedditSessionAdapter } from "./adapters/reddit/adapter.js";
import { REDDIT_ERROR_CODES } from "./adapters/reddit/contract.js";
import { TwitterSessionAdapter } from "./adapters/twitter/adapter.js";
import { TWITTER_ERROR_CODES } from "./adapters/twitter/contract.js";
import { BilibiliSessionAdapter } from "./adapters/bilibili/adapter.js";
import { BILIBILI_ERROR_CODES } from "./adapters/bilibili/contract.js";
import {
  TikTokCreativeSessionAdapter
} from "./adapters/tiktok_creative/adapter.js";
import {
  TIKTOK_CREATIVE_ERROR_CODES
} from "./adapters/tiktok_creative/contract.js";

function passiveChromeApi(chromeApi) {
  return Object.freeze({
    tabs: Object.freeze({
      onRemoved: chromeApi.tabs.onRemoved,
      onUpdated: chromeApi.tabs.onUpdated,
      query: (...args) => chromeApi.tabs.query(...args),
      get: (...args) => chromeApi.tabs.get(...args)
    }),
    scripting: Object.freeze({
      executeScript: (...args) => chromeApi.scripting.executeScript(...args)
    })
  });
}

const passiveChrome = passiveChromeApi(chrome);
const douyin = new DouyinSessionAdapter({ chromeApi: passiveChrome });
const douyinIndex = new DouyinIndexSessionAdapter({ chromeApi: passiveChrome });
const xiaohongshuFamily = createXiaohongshuAdapterFamily({ chromeApi: passiveChrome });
const xiaohongshu = xiaohongshuFamily.web;
const xiaohongshuAppV2 = xiaohongshuFamily.appV2;
const xiaohongshuPgy = xiaohongshuFamily.pgy;
const linkedin = new LinkedInSessionAdapter({ chromeApi: passiveChrome });
const reddit = new RedditSessionAdapter({ chromeApi: passiveChrome });
const twitterRequestPolicy = new SerialRequestPolicy();
const twitterHome = new TwitterSessionAdapter({
  chromeApi: passiveChrome,
  requestPolicy: twitterRequestPolicy,
  scope: "home"
});
const twitterSearch = new TwitterSessionAdapter({
  chromeApi: passiveChrome,
  requestPolicy: twitterRequestPolicy,
  scope: "search"
});
const bilibili = new BilibiliSessionAdapter({ chromeApi: passiveChrome });
const tiktokCreativeRequestPolicy = new SerialRequestPolicy();
const tiktokCreative = new TikTokCreativeSessionAdapter({
  chromeApi: passiveChrome,
  requestPolicy: tiktokCreativeRequestPolicy,
  scope: "hashtag"
});
const tiktokCreativeTopAds = new TikTokCreativeSessionAdapter({
  chromeApi: passiveChrome,
  requestPolicy: tiktokCreativeRequestPolicy,
  scope: "top_ads"
});
const tiktokCreativeStudio = new TikTokCreativeSessionAdapter({
  chromeApi: passiveChrome,
  requestPolicy: tiktokCreativeRequestPolicy,
  scope: "studio"
});
const tiktokOne = new TikTokCreativeSessionAdapter({
  chromeApi: passiveChrome,
  requestPolicy: tiktokCreativeRequestPolicy,
  scope: "one"
});
const tiktokAdsManager = new TikTokCreativeSessionAdapter({
  chromeApi: passiveChrome,
  requestPolicy: tiktokCreativeRequestPolicy,
  scope: "ads_manager"
});
const PLATFORM_ADAPTERS = Object.freeze({
  douyin: {
    label: "抖音",
    adapter: douyin,
    errorCodes: DOUYIN_ERROR_CODES,
    handlers: {
      request: {
        timeout: 35000,
        handle: (message, context) => douyin.routeRequest(message, context)
      },
      session: {
        timeout: 15000,
        handle: (_message, context) => douyin.routeSession(context)
      }
    }
  },
  douyin_index: {
    label: "抖音指数",
    family: "douyin",
    adapter: douyinIndex,
    errorCodes: DOUYIN_INDEX_ERROR_CODES,
    handlers: {
      request: {
        timeout: 35000,
        handle: (message, context) =>
          douyinIndex.routeRequest(message, context)
      },
      session: {
        timeout: 15000,
        handle: (_message, context) =>
          douyinIndex.routeSession(context)
      }
    }
  },
  xiaohongshu: {
    label: "小红书",
    family: "xiaohongshu",
    adapter: xiaohongshu,
    errorCodes: XIAOHONGSHU_ERROR_CODES,
    handlers: {
      request: {
        timeout: 35000,
        handle: (message, context) => xiaohongshu.routeRequest(message, context)
      },
      session: {
        timeout: 15000,
        handle: (_message, context) => xiaohongshu.routeSession(context)
      }
    }
  },
  xiaohongshu_app_v2: {
    label: "小红书 App V2",
    family: "xiaohongshu",
    adapter: xiaohongshuAppV2,
    errorCodes: XIAOHONGSHU_APP_V2_ERROR_CODES,
    handlers: {
      request: {
        timeout: 35000,
        handle: (message, context) =>
          xiaohongshuAppV2.routeRequest(message, context)
      },
      session: {
        timeout: 15000,
        handle: (_message, context) =>
          xiaohongshuAppV2.routeSession(context)
      }
    }
  },
  xiaohongshu_pgy: {
    label: "小红书蒲公英",
    family: "xiaohongshu",
    adapter: xiaohongshuPgy,
    errorCodes: XIAOHONGSHU_PGY_ERROR_CODES,
    handlers: {
      request: {
        timeout: 45000,
        handle: (message, context) => xiaohongshuPgy.routeRequest(message, context)
      },
      session: {
        timeout: 20000,
        handle: (_message, context) => xiaohongshuPgy.routeSession(context)
      }
    }
  },
  linkedin: {
    label: "LinkedIn",
    adapter: linkedin,
    errorCodes: LINKEDIN_ERROR_CODES,
    handlers: {
      request: {
        timeout: 35000,
        handle: (message, context) => linkedin.routeRequest(message, context)
      },
      session: {
        timeout: 15000,
        handle: (_message, context) => linkedin.routeSession(context)
      }
    }
  },
  reddit: {
    label: "Reddit",
    adapter: reddit,
    errorCodes: REDDIT_ERROR_CODES,
    handlers: {
      request: {
        timeout: 35000,
        handle: (message, context) => reddit.routeRequest(message, context)
      },
      session: {
        timeout: 15000,
        handle: (_message, context) => reddit.routeSession(context)
      }
    }
  },
  twitter_home: {
    label: "X 推荐流",
    family: "twitter",
    adapter: twitterHome,
    errorCodes: TWITTER_ERROR_CODES,
    handlers: {
      request: {
        timeout: 35000,
        handle: (message, context) =>
          twitterHome.routeRequest(message, context)
      },
      session: {
        timeout: 15000,
        handle: (_message, context) =>
          twitterHome.routeSession(context)
      }
    }
  },
  twitter_search: {
    label: "X 主动搜索",
    family: "twitter",
    adapter: twitterSearch,
    errorCodes: TWITTER_ERROR_CODES,
    handlers: {
      request: {
        timeout: 35000,
        handle: (message, context) =>
          twitterSearch.routeRequest(message, context)
      },
      session: {
        timeout: 15000,
        handle: (_message, context) =>
          twitterSearch.routeSession(context)
      }
    }
  },
  bilibili: {
    label: "Bilibili",
    adapter: bilibili,
    errorCodes: BILIBILI_ERROR_CODES,
    handlers: {
      request: {
        timeout: 35000,
        handle: (message, context) => bilibili.routeRequest(message, context)
      },
      session: {
        timeout: 15000,
        handle: (_message, context) => bilibili.routeSession(context)
      }
    }
  },
  tiktok_creative: {
    label: "TikTok Creative Center",
    family: "tiktok",
    adapter: tiktokCreative,
    errorCodes: TIKTOK_CREATIVE_ERROR_CODES,
    handlers: {
      request: {
        timeout: 35000,
        handle: (message, context) =>
          tiktokCreative.routeRequest(message, context)
      },
      session: {
        timeout: 15000,
        handle: (message, context) =>
          tiktokCreative.routeSession(message, context)
      }
    }
  },
  tiktok_creative_topads: {
    label: "TikTok Creative Center Top Ads",
    family: "tiktok",
    adapter: tiktokCreativeTopAds,
    errorCodes: TIKTOK_CREATIVE_ERROR_CODES,
    handlers: {
      request: {
        timeout: 35000,
        handle: (message, context) =>
          tiktokCreativeTopAds.routeRequest(message, context)
      },
      session: {
        timeout: 15000,
        handle: (message, context) =>
          tiktokCreativeTopAds.routeSession(message, context)
      }
    }
  },
  tiktok_creative_studio: {
    label: "TikTok Symphony Creative Studio",
    family: "tiktok",
    adapter: tiktokCreativeStudio,
    errorCodes: TIKTOK_CREATIVE_ERROR_CODES,
    handlers: {
      request: {
        timeout: 35000,
        handle: (message, context) =>
          tiktokCreativeStudio.routeRequest(message, context)
      },
      session: {
        timeout: 15000,
        handle: (message, context) =>
          tiktokCreativeStudio.routeSession(message, context)
      }
    }
  },
  tiktok_one: {
    label: "TikTok One 达人广场",
    family: "tiktok",
    adapter: tiktokOne,
    errorCodes: TIKTOK_CREATIVE_ERROR_CODES,
    handlers: {
      request: {
        timeout: 35000,
        handle: (message, context) =>
          tiktokOne.routeRequest(message, context)
      },
      session: {
        timeout: 15000,
        handle: (message, context) =>
          tiktokOne.routeSession(message, context)
      }
    }
  },
  tiktok_ads_manager: {
    label: "TikTok Ads Keyword Planner",
    family: "tiktok",
    adapter: tiktokAdsManager,
    errorCodes: TIKTOK_CREATIVE_ERROR_CODES,
    handlers: {
      request: {
        timeout: 35000,
        handle: (message, context) =>
          tiktokAdsManager.routeRequest(message, context)
      },
      session: {
        timeout: 15000,
        handle: (message, context) =>
          tiktokAdsManager.routeSession(message, context)
      }
    }
  }
});
const bridge = new LocalSessionBridgeClient({
  chromeApi: chrome,
  defaultBridgeUrl: DEFAULT_BRIDGE_URL,
  errorCodes: new Set(
    Object.values(PLATFORM_ADAPTERS).flatMap((value) => [...(value.errorCodes || [])])
  ),
  adapters: Object.fromEntries(
    Object.entries(PLATFORM_ADAPTERS).map(([platform, value]) => [
      platform,
      { family: value.family || platform, handlers: value.handlers }
    ])
  )
});
const fastDiscovery = createFastDiscoveryController({ chromeApi: chrome });

for (const platform of Object.values(PLATFORM_ADAPTERS)) {
  platform.adapter.registerLifecycle?.();
}

installReconnectAlarm({ chromeApi: chrome, bridge });
void fastDiscovery.ensureDocument();
chrome.runtime.onInstalled.addListener(() => { void fastDiscovery.ensureDocument(); });
chrome.runtime.onStartup.addListener(() => { void fastDiscovery.ensureDocument(); });

async function popupStatus() {
  await bridge.initialize();
  return bridge.statusSnapshot();
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!isRecord(message) || sender.id !== chrome.runtime.id) {
    return;
  }
  if (fastDiscovery.isProbe(message, sender)) {
    void bridge.ensureConnection().then(() => {
      sendResponse({ ok: true, status: bridge.statusSnapshot() });
    }).catch(() => {
      sendResponse({ ok: false, status: bridge.statusSnapshot() });
    });
    return true;
  }
  if (message.type === "popup_status") {
    void popupStatus().then(sendResponse).catch(() => {
      sendResponse({ connection: "error", registered: false, connected: false, ready: false, last_error: "bridge_error" });
    });
    return true;
  }
  if (message.type === "popup_reconnect") {
    void bridge.initialize().then(() => {
      bridge.reconnect();
      sendResponse(bridge.statusSnapshot());
    }).catch(() => {
      sendResponse({ connection: "error", registered: false, connected: false, ready: false, last_error: "bridge_error" });
    });
    return true;
  }
});
