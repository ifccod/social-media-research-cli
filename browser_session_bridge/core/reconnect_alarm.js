export const BRIDGE_RECONNECT_ALARM = "local-session-bridge-reconnect";
export const BRIDGE_RECONNECT_PERIOD_MINUTES = 0.5;

function wakeBridge(bridge) {
  void Promise.resolve(bridge.ensureConnection()).catch(() => undefined);
}

// 本机服务未监听时，Chrome 可能挂起 MV3 Service Worker。
// 闹钟由 Chrome 持久化，即使内存重连计时器已失效，
// 下次 CLI 启动本机服务后仍可触发发现。
export function installReconnectAlarm({ chromeApi, bridge }) {
  const ensureAlarm = () => {
    try {
      chromeApi.alarms.create(BRIDGE_RECONNECT_ALARM, {
        periodInMinutes: BRIDGE_RECONNECT_PERIOD_MINUTES
      });
    } catch {
      // 若 Chrome 拒绝创建闹钟，弹窗仍可立即触发重连。
    }
    wakeBridge(bridge);
  };

  chromeApi.runtime.onInstalled.addListener(ensureAlarm);
  chromeApi.runtime.onStartup.addListener(ensureAlarm);
  chromeApi.alarms.onAlarm.addListener((alarm) => {
    if (alarm && alarm.name === BRIDGE_RECONNECT_ALARM) {
      wakeBridge(bridge);
    }
  });
  ensureAlarm();
}
