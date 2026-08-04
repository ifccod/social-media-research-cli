import {
  FAST_DISCOVERY_INTERVAL_MS,
  FAST_DISCOVERY_PROBE_TYPE
} from "./core/fast_discovery.js";

function probe() {
  void chrome.runtime.sendMessage({ type: FAST_DISCOVERY_PROBE_TYPE }).catch(() => undefined);
}

probe();
setInterval(probe, FAST_DISCOVERY_INTERVAL_MS);
