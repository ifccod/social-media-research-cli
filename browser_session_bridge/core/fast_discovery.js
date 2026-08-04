export const FAST_DISCOVERY_DOCUMENT_PATH = "offscreen.html";
export const FAST_DISCOVERY_PROBE_TYPE = "bridge_fast_discovery_probe";
export const FAST_DISCOVERY_INTERVAL_MS = 5000;

// 离屏文档可在 MV3 Worker 休眠时存活，并通过本机探测唤醒 Worker。
// 它不处理站点数据或桥接流量。
export function createFastDiscoveryController({ chromeApi }) {
  const documentUrl = chromeApi.runtime.getURL(FAST_DISCOVERY_DOCUMENT_PATH);
  let creation = null;

  async function ensureDocument() {
    if (creation) {
      return creation;
    }
    creation = (async () => {
      try {
        if (await chromeApi.offscreen.hasDocument()) {
          return true;
        }
        await chromeApi.offscreen.createDocument({
          url: FAST_DISCOVERY_DOCUMENT_PATH,
          reasons: ["WORKERS"],
          justification: "Wake the local browser-session bridge every five seconds."
        });
        return true;
      } catch {
        return false;
      } finally {
        creation = null;
      }
    })();
    return creation;
  }

  function isProbe(message, sender) {
    return Boolean(
      message &&
      message.type === FAST_DISCOVERY_PROBE_TYPE &&
      sender &&
      sender.id === chromeApi.runtime.id &&
      sender.url === documentUrl
    );
  }

  return { ensureDocument, isProbe };
}
