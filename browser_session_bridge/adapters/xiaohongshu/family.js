import { SerialRequestPolicy } from "../../core/serial_request_policy.js";
import { XiaohongshuSessionAdapter } from "./adapter.js";
import {
  XiaohongshuAppV2SessionAdapter
} from "../xiaohongshu_app_v2/adapter.js";
import {
  XiaohongshuPgySessionAdapter
} from "../xiaohongshu_pgy/adapter.js";

export function createXiaohongshuAdapterFamily({
  chromeApi,
  requestPolicy = new SerialRequestPolicy()
}) {
  return {
    web: new XiaohongshuSessionAdapter({ chromeApi, requestPolicy }),
    appV2: new XiaohongshuAppV2SessionAdapter({ chromeApi, requestPolicy }),
    pgy: new XiaohongshuPgySessionAdapter({ chromeApi, requestPolicy })
  };
}
