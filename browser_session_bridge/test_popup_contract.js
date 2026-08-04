import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { connectionView, metricsView, startPopup } from "./ui/popup_v2.js";

class FakeElement {
  constructor() {
    this.dataset = {};
    this.disabled = false;
    this.textContent = "";
    this.value = "";
    this.listeners = new Map();
    this.children = [];
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  replaceChildren(...children) {
    this.children = children;
  }

  async dispatch(type) {
    let prevented = false;
    const event = {
      preventDefault() {
        prevented = true;
      }
    };
    await Promise.all(
      (this.listeners.get(type) || []).map((listener) => listener(event))
    );
    return prevented;
  }
}

function popupFixture() {
  const selectors = Object.fromEntries([
    "#status",
    "#status-detail",
    "#connection",
    "#build",
    "#reconnect",
    "#metric-rtt",
    "#metric-in-flight",
    "#metric-queued",
    "#metric-succeeded",
    "#metric-failed",
    "#metric-last-response"
  ].map((selector) => [selector, new FakeElement()]));
  const messages = [];
  const windowListeners = new Map();
  const intervals = [];
  const cleared = [];
  const status = {
    connection: "ready",
    ready: true,
    protocol_version: 3,
    metrics: {
      rtt_ms: 18,
      in_flight: 2,
      queued: 1,
      succeeded: 12,
      failed: 3,
      last_response_ms: 1240
    }
  };
  const chromeApi = {
    runtime: {
      getManifest: () => ({ version: "1.0.0" }),
      async sendMessage(message) {
        messages.push(message);
        if (message.type === "popup_status" || message.type === "popup_reconnect") {
          return status;
        }
        return { ok: true, status };
      }
    }
  };
  const documentApi = {
    querySelector: (selector) => selectors[selector],
    createElement: () => new FakeElement()
  };
  const windowApi = {
    addEventListener(type, listener) {
      windowListeners.set(type, listener);
    },
    setInterval(callback, milliseconds) {
      intervals.push({ callback, milliseconds });
      return intervals.length;
    },
    clearInterval(id) {
      cleared.push(id);
    }
  };
  return {
    chromeApi,
    documentApi,
    windowApi,
    selectors,
    messages,
    windowListeners,
    intervals,
    cleared
  };
}

test("popup maps bridge states and errors to concise Chinese status", () => {
  assert.deepEqual(connectionView({ ready: true, connection: "ready" }), {
    tone: "ready",
    title: "已连接",
    detail: "即时通信已就绪"
  });
  assert.deepEqual(connectionView({
    ready: false,
    connection: "error",
    last_error: "protocol_mismatch"
  }), {
    tone: "error",
    title: "连接异常",
    detail: "扩展与本机服务版本不一致"
  });
  assert.deepEqual(connectionView({
    ready: false,
    connection: "disconnected",
    last_error: "bridge_connection_error"
  }), {
    tone: "waiting",
    title: "等待本机服务",
    detail: "本机连接已中断"
  });
  assert.deepEqual(connectionView({
    ready: false,
    connection: "parked",
    last_error: "browser_instance_superseded"
  }), {
    tone: "waiting",
    title: "自动连接已暂停",
    detail: "实例已在其他窗口连接"
  });
});

test("popup formats compact runtime metrics without inventing unavailable values", () => {
  assert.deepEqual(metricsView({
    metrics: {
      rtt_ms: 0,
      in_flight: 2,
      queued: 1,
      succeeded: 12,
      failed: 3,
      last_response_ms: 1240
    }
  }), {
    rtt: "<1 毫秒",
    inFlight: "2",
    queued: "1",
    succeeded: "12",
    failed: "3",
    lastResponse: "1.2 秒"
  });
  assert.deepEqual(metricsView(null), {
    rtt: "—",
    inFlight: "—",
    queued: "—",
    succeeded: "—",
    failed: "—",
    lastResponse: "—"
  });
});

test("popup only reports bridge state and reconnects explicitly", async () => {
  const fixture = popupFixture();
  const controller = startPopup(fixture);
  await controller.ready;

  assert.deepEqual(fixture.messages, [{ type: "popup_status" }]);
  assert.equal(fixture.intervals[0].milliseconds, 1000);
  assert.equal(fixture.selectors["#metric-rtt"].textContent, "18 毫秒");
  assert.equal(fixture.selectors["#metric-in-flight"].textContent, "2");
  assert.equal(fixture.selectors["#metric-queued"].textContent, "1");
  assert.equal(fixture.selectors["#metric-succeeded"].textContent, "12");
  assert.equal(fixture.selectors["#metric-failed"].textContent, "3");
  assert.equal(fixture.selectors["#metric-last-response"].textContent, "1.2 秒");

  await fixture.selectors["#reconnect"].dispatch("click");
  assert.deepEqual(fixture.messages.at(-1), { type: "popup_reconnect" });

  fixture.windowListeners.get("pagehide")();
  assert.deepEqual(fixture.cleared, [1]);
});

test("popup and manifest keep the native accessibility and loopback contract", () => {
  const html = readFileSync(new URL("./ui/popup.html", import.meta.url), "utf8");
  const manifest = JSON.parse(
    readFileSync(new URL("./manifest.json", import.meta.url), "utf8")
  );

  assert.equal(manifest.version, "1.0.1");
  assert.match(
    manifest.content_security_policy.extension_pages,
    /ws:\/\/127\.0\.0\.1:18765(?:\s|$)/
  );
  assert.doesNotMatch(
    manifest.content_security_policy.extension_pages,
    /ws:\/\/127\.0\.0\.1:\*/
  );
  assert.doesNotMatch(html, /id="platform-form"/);
  assert.doesNotMatch(html, /id="open-platform"/);
  assert.match(
    html,
    /id="reconnect"[^>]+aria-label="重新连接"[^>]+title="重新连接"/
  );
  assert.equal((html.match(/aria-live=/g) || []).length, 1);
  assert.doesNotMatch(html, /id="status"[^>]+role="status"/);
  assert.match(html, /data-lucide="refresh-cw"/);
  assert.match(html, /class="metrics" aria-label="通信指标"/);
  assert.match(html, /id="metric-rtt"/);
  assert.match(html, /id="metric-in-flight"/);
  assert.match(html, /id="metric-queued"/);
  assert.match(html, /id="metric-succeeded"/);
  assert.match(html, /id="metric-failed"/);
  assert.match(html, /id="metric-last-response"/);
  assert.match(html, /:focus-visible/);
  assert.match(html, /prefers-reduced-motion/);
  assert.match(html, /prefers-reduced-transparency/);
  assert.match(html, /prefers-contrast/);
});
