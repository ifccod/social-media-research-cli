const REFRESH_INTERVAL_MS = 1000;
const BRIDGE_ENDPOINT_LABEL = "本机 · 127.0.0.1:18765";

const CONNECTION_VIEWS = Object.freeze({
  starting: { tone: "working", title: "正在启动", detail: BRIDGE_ENDPOINT_LABEL },
  connecting: { tone: "working", title: "正在连接", detail: BRIDGE_ENDPOINT_LABEL },
  authenticating: { tone: "working", title: "正在建立会话", detail: BRIDGE_ENDPOINT_LABEL },
  disconnected: { tone: "waiting", title: "等待本机服务", detail: BRIDGE_ENDPOINT_LABEL },
  parked: { tone: "waiting", title: "自动连接已暂停", detail: "实例已在其他窗口连接" },
  error: { tone: "error", title: "连接异常", detail: "本机桥接暂不可用" }
});

const ERROR_LABELS = Object.freeze({
  bridge_connect_failed: "本机服务尚未启动",
  bridge_connection_error: "本机连接已中断",
  bridge_error: "本机桥接异常",
  bridge_send_failed: "消息发送失败",
  protocol_mismatch: "扩展与本机服务版本不一致",
  browser_instance_mismatch: "浏览器实例不匹配",
  browser_instance_superseded: "实例已在其他窗口连接",
  invalid_auth_token: "本机会话信息异常",
  authentication_rejected: "正在重新建立本机会话",
  token_persistence_failed: "会话状态保存失败",
  response_too_large: "返回内容过大"
});
const EMPTY_METRIC = "—";

function countLabel(value) {
  return Number.isSafeInteger(value) && value >= 0 ? String(value) : EMPTY_METRIC;
}

function durationLabel(value) {
  if (!Number.isSafeInteger(value) || value < 0) {
    return EMPTY_METRIC;
  }
  if (value === 0) {
    return "<1 毫秒";
  }
  if (value < 1000) {
    return `${value} 毫秒`;
  }
  const seconds = value / 1000;
  return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} 秒`;
}

export function connectionView(value) {
  if (!value || typeof value !== "object") {
    return {
      tone: "working",
      title: "正在读取本机状态",
      detail: BRIDGE_ENDPOINT_LABEL
    };
  }
  const base = value.ready
    ? { tone: "ready", title: "已连接", detail: "即时通信已就绪" }
    : (CONNECTION_VIEWS[value.connection] || {
        tone: "waiting",
        title: "状态未知",
        detail: BRIDGE_ENDPOINT_LABEL
      });
  const error = typeof value.last_error === "string"
    ? ERROR_LABELS[value.last_error]
    : "";
  return { ...base, detail: error || base.detail };
}

export function metricsView(value) {
  const metrics = value && typeof value.metrics === "object" ? value.metrics : {};
  return {
    rtt: durationLabel(metrics.rtt_ms),
    inFlight: countLabel(metrics.in_flight),
    queued: countLabel(metrics.queued),
    succeeded: countLabel(metrics.succeeded),
    failed: countLabel(metrics.failed),
    lastResponse: durationLabel(metrics.last_response_ms)
  };
}

export function startPopup({ documentApi, chromeApi, windowApi }) {
  const status = documentApi.querySelector("#status");
  const statusDetail = documentApi.querySelector("#status-detail");
  const connection = documentApi.querySelector("#connection");
  const build = documentApi.querySelector("#build");
  const reconnect = documentApi.querySelector("#reconnect");
  const metricRtt = documentApi.querySelector("#metric-rtt");
  const metricInFlight = documentApi.querySelector("#metric-in-flight");
  const metricQueued = documentApi.querySelector("#metric-queued");
  const metricSucceeded = documentApi.querySelector("#metric-succeeded");
  const metricFailed = documentApi.querySelector("#metric-failed");
  const metricLastResponse = documentApi.querySelector("#metric-last-response");
  const extensionVersion = chromeApi.runtime.getManifest().version;

  let refreshTimer = null;
  let refreshing = false;
  let busy = false;
  let feedbackUntil = 0;

  function renderStatus(view) {
    connection.dataset.tone = view.tone;
    status.textContent = view.title;
    statusDetail.textContent = view.detail;
  }

  function renderMetrics(value) {
    const view = metricsView(value);
    metricRtt.textContent = view.rtt;
    metricInFlight.textContent = view.inFlight;
    metricQueued.textContent = view.queued;
    metricSucceeded.textContent = view.succeeded;
    metricFailed.textContent = view.failed;
    metricLastResponse.textContent = view.lastResponse;
  }

  function setBusy(value) {
    busy = value;
    reconnect.disabled = value;
  }

  function describe(value) {
    const protocol = Number.isInteger(value && value.protocol_version)
      ? ` · 协议 v${value.protocol_version}`
      : "";
    build.textContent = `扩展 ${extensionVersion}${protocol}`;
    renderMetrics(value);
    if (Date.now() >= feedbackUntil) {
      renderStatus(connectionView(value));
    }
  }

  async function send(message) {
    return chromeApi.runtime.sendMessage(message);
  }

  async function refresh() {
    if (refreshing || busy) {
      return;
    }
    refreshing = true;
    try {
      describe(await send({ type: "popup_status" }));
    } catch {
      renderMetrics(null);
      renderStatus({
        tone: "error",
        title: "状态读取失败",
        detail: "本机桥接暂不可用"
      });
    } finally {
      refreshing = false;
    }
  }

  reconnect.addEventListener("click", async () => {
    if (busy) {
      return;
    }
    feedbackUntil = 0;
    setBusy(true);
    renderStatus({
      tone: "working",
      title: "正在重新连接",
      detail: BRIDGE_ENDPOINT_LABEL
    });
    try {
      describe(await send({ type: "popup_reconnect" }));
    } catch {
      feedbackUntil = Date.now() + 2500;
      renderStatus({
        tone: "error",
        title: "重连请求未送达",
        detail: "本机桥接暂不可用"
      });
    } finally {
      setBusy(false);
    }
  });

  function stop() {
    if (refreshTimer !== null) {
      windowApi.clearInterval(refreshTimer);
      refreshTimer = null;
    }
  }

  windowApi.addEventListener("pagehide", stop, { once: true });

  const ready = (async () => {
    await refresh();
    refreshTimer = windowApi.setInterval(() => {
      void refresh();
    }, REFRESH_INTERVAL_MS);
  })();

  return { ready, refresh, stop };
}

if (
  typeof document !== "undefined" &&
  typeof chrome !== "undefined" &&
  chrome.runtime
) {
  startPopup({ documentApi: document, chromeApi: chrome, windowApi: window });
}
