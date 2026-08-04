import {
  DEFAULT_BRIDGE_URL,
  MAX_WIRE_BYTES,
  encodedByteLength,
  generateBrowserInstanceId,
  isRecord,
  normalizeLoopbackBridgeUrl,
  validErrorCode,
  validBrowserInstanceId,
  validRequestId
} from "./protocol.js";
import { BRIDGE_PROTOCOL_VERSION } from "./wire_protocol_v4.js";

const CORE_ERROR_CODES = new Set([
  "invalid_request",
  "request_failed",
  "timeout",
  "invalid_response",
  "response_too_large"
]);
const RECONNECT_DELAY_MS = 5000;
const CANCELLATION_GRACE_MS = 1500;
export const BROWSER_INSTANCE_SUPERSEDED_CLOSE_CODE = 4009;

function validPlatform(value) {
  return typeof value === "string" && /^[a-z][a-z0-9_-]{0,63}$/.test(value);
}

function validAuthToken(value) {
  return typeof value === "string" && value.length >= 8 && value.length <= 4096 && !/[\r\n\0]/.test(value);
}

function handlerMessage(message) {
  const {
    type: _type,
    id: _id,
    platform: _platform,
    ...payload
  } = message;
  return payload;
}

/**
 * 本地回环 WebSocket 桥接的共享客户端，负责扩展自动登记、重连、
 * 传输大小限制和 RPC 收敛；平台适配器只查询已有标签页并转发平台请求。
 */
export class LocalSessionBridgeClient {
  constructor({
    chromeApi,
    defaultBridgeUrl = DEFAULT_BRIDGE_URL,
    errorCodes = new Set(),
    adapters = {},
    now = () => performance.now(),
    storageKeys = {
      authToken: "bridgeAuthToken",
      browserInstanceId: "browserInstanceId"
    }
  }) {
    this.chrome = chromeApi;
    this.defaultBridgeUrl = defaultBridgeUrl;
    this.errorCodes = new Set([...CORE_ERROR_CODES, ...errorCodes]);
    this.adapters = adapters;
    this.now = now;
    this.storageKeys = {
      authToken: "bridgeAuthToken",
      browserInstanceId: "browserInstanceId",
      ...storageKeys
    };
    this.state = {
      initialized: false,
      initialization: null,
      bridgeUrl: defaultBridgeUrl,
      authToken: "",
      browserInstanceId: "",
      socket: null,
      connection: "starting",
      lastError: "",
      reconnectTimer: null,
      heartbeatTimer: null,
      pending: new Map(),
      queuedCancellations: new Map(),
      platformCancellationBarriers: new Map(),
      cancellationBarrier: Promise.resolve(),
      metrics: {
        helloSentAt: null,
        roundTripMs: null,
        queued: 0,
        succeeded: 0,
        failed: 0,
        lastResponseMs: null
      }
    };
  }

  async initialize() {
    if (this.state.initialized) {
      return;
    }
    if (this.state.initialization) {
      return this.state.initialization;
    }
    this.state.initialization = (async () => {
      const saved = await this.chrome.storage.local.get([
        this.storageKeys.authToken,
        this.storageKeys.browserInstanceId
      ]);
      const currentToken = saved[this.storageKeys.authToken];
      let browserInstanceId = saved[this.storageKeys.browserInstanceId];
      if (!validBrowserInstanceId(browserInstanceId)) {
        browserInstanceId = generateBrowserInstanceId();
        if (!validBrowserInstanceId(browserInstanceId)) {
          throw new Error("invalid_browser_instance_id");
        }
        await this.chrome.storage.local.set({
          [this.storageKeys.browserInstanceId]: browserInstanceId
        });
      }
      this.state.bridgeUrl = normalizeLoopbackBridgeUrl(this.defaultBridgeUrl, this.defaultBridgeUrl)
        || DEFAULT_BRIDGE_URL;
      this.state.authToken = validAuthToken(currentToken) ? currentToken : "";
      this.state.browserInstanceId = browserInstanceId;
      this.state.initialized = true;
      this.connect();
    })();
    try {
      await this.state.initialization;
    } finally {
      this.state.initialization = null;
    }
  }

  statusSnapshot() {
    return {
      bridge_url: this.state.bridgeUrl,
      protocol_version: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: validBrowserInstanceId(this.state.browserInstanceId)
        ? this.state.browserInstanceId
        : null,
      connection: this.state.connection,
      registered: Boolean(this.state.authToken),
      connected: this.authenticated(),
      ready: this.authenticated(),
      last_error: this.state.lastError || null,
      metrics: {
        rtt_ms: this.state.metrics.roundTripMs,
        in_flight: this.state.pending.size,
        queued: this.state.metrics.queued,
        succeeded: this.state.metrics.succeeded,
        failed: this.state.metrics.failed,
        last_response_ms: this.state.metrics.lastResponseMs
      }
    };
  }

  authenticated() {
    return this.state.connection === "ready";
  }

  reconnect() {
    this.clearReconnect();
    this.disconnectSocket();
    this.state.connection = "disconnected";
    this.state.lastError = "";
    this.connect();
  }

  // 供 Chrome 持久生命周期事件调用。健康连接保持不动，
  // 空闲 Worker 被唤醒时则立即重试。
  async ensureConnection() {
    await this.initialize();
    if (this.state.connection === "parked") {
      const saved = await this.chrome.storage.local.get([
        this.storageKeys.browserInstanceId
      ]);
      const browserInstanceId = saved[this.storageKeys.browserInstanceId];
      if (
        !validBrowserInstanceId(browserInstanceId) ||
        browserInstanceId === this.state.browserInstanceId
      ) {
        return;
      }
      this.state.browserInstanceId = browserInstanceId;
      this.state.connection = "disconnected";
      this.state.lastError = "";
    }
    if (this.authenticated() || this.state.socket) {
      return;
    }
    this.clearReconnect();
    this.connect();
  }

  connect() {
    if (
      !this.state.initialized ||
      this.state.socket ||
      this.state.connection === "parked"
    ) {
      return;
    }
    let socket;
    try {
      socket = new WebSocket(this.state.bridgeUrl);
    } catch {
      this.state.connection = "disconnected";
      this.state.lastError = "bridge_connect_failed";
      this.scheduleReconnect();
      return;
    }
    this.state.socket = socket;
    this.state.connection = "connecting";
    this.state.lastError = "";
    this.state.metrics.helloSentAt = null;
    this.state.metrics.roundTripMs = null;
    socket.addEventListener("open", () => {
      if (this.state.socket !== socket) {
        return;
      }
      this.state.connection = "authenticating";
      this.sendHello();
    });
    socket.addEventListener("message", (event) => {
      if (this.state.socket === socket) {
        void this.receiveWire(event.data, socket);
      }
    });
    socket.addEventListener("error", () => {
      if (this.state.socket === socket) {
        this.state.lastError = "bridge_connection_error";
      }
    });
    socket.addEventListener("close", (event) => {
      if (this.state.socket !== socket) {
        return;
      }
      this.clearHeartbeat();
      void this.cancelAllPending("connection_closed");
      this.state.socket = null;
      this.state.connection = "disconnected";
      this.state.metrics.helloSentAt = null;
      this.state.metrics.roundTripMs = null;
      if (event && event.code === BROWSER_INSTANCE_SUPERSEDED_CLOSE_CODE) {
        this.clearReconnect();
        this.state.connection = "parked";
        this.state.lastError = "browser_instance_superseded";
        return;
      }
      this.scheduleReconnect();
    });
  }

  disconnectSocket() {
    this.clearHeartbeat();
    void this.cancelAllPending("connection_closed");
    const socket = this.state.socket;
    this.state.socket = null;
    this.state.metrics.helloSentAt = null;
    this.state.metrics.roundTripMs = null;
    if (socket && socket.readyState < WebSocket.CLOSING) {
      try {
        socket.close();
      } catch {
        // 关闭结果不属于桥接协议。
      }
    }
  }

  scheduleReconnect() {
    if (
      this.state.connection === "parked" ||
      this.state.reconnectTimer !== null
    ) {
      return;
    }
    this.state.reconnectTimer = setTimeout(() => {
      this.state.reconnectTimer = null;
      if (this.state.connection !== "parked") {
        this.connect();
      }
    }, RECONNECT_DELAY_MS);
  }

  clearReconnect() {
    if (this.state.reconnectTimer !== null) {
      clearTimeout(this.state.reconnectTimer);
      this.state.reconnectTimer = null;
    }
  }

  clearHeartbeat() {
    if (this.state.heartbeatTimer !== null) {
      clearInterval(this.state.heartbeatTimer);
      this.state.heartbeatTimer = null;
    }
  }

  startHeartbeat() {
    this.clearHeartbeat();
    this.state.heartbeatTimer = setInterval(() => {
      if (this.authenticated()) {
        this.sendHello();
      }
    }, 20000);
  }

  sendHello() {
    if (!validBrowserInstanceId(this.state.browserInstanceId)) {
      this.state.lastError = "invalid_browser_instance_id";
      return false;
    }
    const message = {
      type: "hello",
      protocol: BRIDGE_PROTOCOL_VERSION,
      browser_instance_id: this.state.browserInstanceId
    };
    if (this.state.authToken) {
      message.token = this.state.authToken;
    }
    const sent = this.sendWire(message);
    if (sent) {
      this.state.metrics.helloSentAt = this.now();
    }
    return sent;
  }

  sendWire(message) {
    const socket = this.state.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return false;
    }
    try {
      const encoded = JSON.stringify(message);
      if (encodedByteLength(encoded) > MAX_WIRE_BYTES) {
        this.state.lastError = "response_too_large";
        return false;
      }
      socket.send(encoded);
      return true;
    } catch {
      this.state.lastError = "bridge_send_failed";
      return false;
    }
  }

  respond(id, value, platform = undefined, startedAt = null) {
    if (!validRequestId(id)) {
      return;
    }
    const platformField = validPlatform(platform) ? { platform } : {};
    let response;
    if (isRecord(value) && Object.prototype.hasOwnProperty.call(value, "payload")) {
      response = { type: "response", id, ...platformField, payload: value.payload };
    } else {
      response = {
        type: "response",
        id,
        ...platformField,
        error: validErrorCode(value && value.error, this.errorCodes)
      };
    }
    try {
      if (encodedByteLength(JSON.stringify(response)) > MAX_WIRE_BYTES) {
        response = { type: "response", id, ...platformField, error: "response_too_large" };
      }
    } catch {
      response = { type: "response", id, ...platformField, error: "invalid_response" };
    }
    const sent = this.sendWire(response);
    const metrics = this.state.metrics;
    const succeeded = sent && Object.prototype.hasOwnProperty.call(response, "payload");
    const counter = succeeded ? "succeeded" : "failed";
    metrics[counter] = Math.min(Number.MAX_SAFE_INTEGER, metrics[counter] + 1);
    if (Number.isFinite(startedAt)) {
      metrics.lastResponseMs = Math.max(0, Math.round(this.now() - startedAt));
    }
  }

  beginPending(id, timeout, platform, startedAt) {
    const controller = new AbortController();
    let notifyCancelled;
    const entry = {
      platform,
      controller,
      cancelHandlers: new Set(),
      cancelling: false,
      cancelCompletion: null,
      cancelled: new Promise((resolve) => {
        notifyCancelled = resolve;
      }),
      notifyCancelled,
      startedAt,
      timer: null
    };
    entry.timer = setTimeout(() => {
      void this.expirePending(id);
    }, timeout);
    this.state.pending.set(id, entry);
    return entry;
  }

  registerCancelHandler(entry, handler) {
    if (typeof handler !== "function") {
      return () => {};
    }
    if (entry.cancelling || entry.controller.signal.aborted) {
      void Promise.resolve().then(() => handler(entry.controller.signal.reason)).catch(
        () => undefined
      );
      return () => {};
    }
    entry.cancelHandlers.add(handler);
    return () => {
      entry.cancelHandlers.delete(handler);
    };
  }

  waitForCancellation(tasks) {
    if (tasks.length === 0) {
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      let finished = false;
      const timer = setTimeout(finish, CANCELLATION_GRACE_MS);
      function finish() {
        if (finished) {
          return;
        }
        finished = true;
        clearTimeout(timer);
        resolve();
      }
      void Promise.allSettled(tasks).then(finish);
    });
  }

  startCancellation(entry, reason) {
    if (entry.cancelCompletion) {
      return entry.cancelCompletion;
    }
    entry.cancelling = true;
    if (entry.timer !== null) {
      clearTimeout(entry.timer);
      entry.timer = null;
    }

    let finishCancellation;
    entry.cancelCompletion = new Promise((resolve) => {
      finishCancellation = resolve;
    });
    entry.controller.abort(reason);
    entry.notifyCancelled();
    const tasks = [...entry.cancelHandlers].map((handler) => (
      Promise.resolve().then(() => handler(reason))
    ));
    entry.cancelHandlers.clear();
    void this.waitForCancellation(tasks).then(finishCancellation);
    return entry.cancelCompletion;
  }

  async expirePending(id) {
    const entry = this.state.pending.get(id);
    if (!entry) {
      return;
    }
    await this.startCancellation(entry, "timeout");
    if (this.state.pending.get(id) !== entry) {
      return;
    }
    this.state.pending.delete(id);
    this.respond(id, { error: "timeout" }, entry.platform, entry.startedAt);
  }

  async cancelPending(id, platform, reason = "remote_cancel") {
    const entry = this.state.pending.get(id);
    if (!entry || entry.platform !== platform) {
      return false;
    }
    await this.trackPlatformCancellation(
      platform,
      this.startCancellation(entry, reason)
    );
    if (this.state.pending.get(id) === entry) {
      this.state.pending.delete(id);
    }
    return true;
  }

  async cancelAllPending(reason) {
    this.state.queuedCancellations.clear();
    const pending = [...this.state.pending.entries()];
    for (const [id, entry] of pending) {
      if (this.state.pending.get(id) === entry) {
        this.state.pending.delete(id);
      }
    }
    const cancellation = Promise.allSettled([
      ...pending.map(([, entry]) => this.startCancellation(entry, reason)),
      ...this.state.platformCancellationBarriers.values()
    ]);
    this.state.platformCancellationBarriers.clear();
    await this.trackCancellation(cancellation);
  }

  trackCancellation(cancellation) {
    const previousBarrier = this.state.cancellationBarrier;
    const barrier = Promise.allSettled([previousBarrier, cancellation]).then(() => undefined);
    this.state.cancellationBarrier = barrier;
    void barrier.then(() => {
      if (this.state.cancellationBarrier === barrier) {
        this.state.cancellationBarrier = Promise.resolve();
      }
    });
    return barrier;
  }

  platformFamily(platform) {
    const configured = this.adapters[platform] && this.adapters[platform].family;
    return validPlatform(configured) ? configured : platform;
  }

  trackPlatformCancellation(platform, cancellation) {
    const family = this.platformFamily(platform);
    const previous = this.state.platformCancellationBarriers.get(family) || Promise.resolve();
    const barrier = Promise.allSettled([previous, cancellation]).then(() => undefined);
    this.state.platformCancellationBarriers.set(family, barrier);
    void barrier.then(() => {
      if (this.state.platformCancellationBarriers.get(family) === barrier) {
        this.state.platformCancellationBarriers.delete(family);
      }
    });
    return barrier;
  }

  rememberQueuedCancellation(id, platform, socket) {
    if (this.state.queuedCancellations.size >= 1024) {
      const oldest = this.state.queuedCancellations.keys().next().value;
      this.state.queuedCancellations.delete(oldest);
    }
    this.state.queuedCancellations.set(id, { platform, socket });
  }

  consumeQueuedCancellation(id, platform, socket) {
    const queued = this.state.queuedCancellations.get(id);
    if (!queued || queued.platform !== platform || queued.socket !== socket) {
      return false;
    }
    this.state.queuedCancellations.delete(id);
    return true;
  }

  settle(id, value) {
    const pending = this.state.pending.get(id);
    if (!pending || pending.cancelling) {
      return;
    }
    if (pending.timer !== null) {
      clearTimeout(pending.timer);
    }
    pending.cancelHandlers.clear();
    this.state.pending.delete(id);
    this.respond(id, value, pending.platform, pending.startedAt);
  }

  async receiveWire(raw, sourceSocket = this.state.socket) {
    if (typeof raw !== "string" || encodedByteLength(raw) > MAX_WIRE_BYTES) {
      return;
    }
    let message;
    try {
      message = JSON.parse(raw);
    } catch {
      return;
    }
    if (!isRecord(message) || typeof message.type !== "string") {
      return;
    }
    if (sourceSocket !== this.state.socket) {
      return;
    }
    if (message.type === "ready") {
      await this.acceptReady(message);
      return;
    }
    if (message.type === "error") {
      await this.handleBridgeError(message);
      return;
    }
    if (message.type === "cancel") {
      if (
        this.authenticated() &&
        validRequestId(message.id) &&
        validPlatform(message.platform)
      ) {
        if (!this.state.pending.has(message.id)) {
          this.rememberQueuedCancellation(message.id, message.platform, sourceSocket);
        } else {
          await this.cancelPending(message.id, message.platform);
        }
      }
      return;
    }
    if (!this.authenticated()) {
      if (validRequestId(message.id)) {
        this.respond(message.id, { error: "request_failed" }, message.platform);
      }
      return;
    }
    await this.dispatch(message, sourceSocket);
  }

  async acceptReady(message) {
    if (message.protocol !== BRIDGE_PROTOCOL_VERSION) {
      this.state.connection = "error";
      this.state.lastError = "protocol_mismatch";
      this.disconnectSocket();
      this.scheduleReconnect();
      return;
    }
    if (
      !validBrowserInstanceId(message.browser_instance_id) ||
      message.browser_instance_id !== this.state.browserInstanceId
    ) {
      this.state.connection = "error";
      this.state.lastError = "browser_instance_mismatch";
      this.disconnectSocket();
      this.scheduleReconnect();
      return;
    }
    let persistToken = false;
    if (Object.prototype.hasOwnProperty.call(message, "token")) {
      if (!validAuthToken(message.token)) {
        this.state.connection = "error";
        this.state.lastError = "invalid_auth_token";
        return;
      }
      this.state.authToken = message.token;
      persistToken = true;
    }
    if (Number.isFinite(this.state.metrics.helloSentAt)) {
      this.state.metrics.roundTripMs = Math.max(
        0,
        Math.round(this.now() - this.state.metrics.helloSentAt)
      );
      this.state.metrics.helloSentAt = null;
    }
    // WebSocket 消息回调不会按 Promise 串行执行。同步进入 ready 状态，
    // 避免后续有序业务帧在令牌持久化完成前误判为未认证连接。
    this.state.connection = "ready";
    this.state.lastError = "";
    this.startHeartbeat();
    if (persistToken) {
      try {
        await this.chrome.storage.local.set({
          [this.storageKeys.authToken]: this.state.authToken
        });
      } catch {
        this.state.lastError = "token_persistence_failed";
      }
    }
  }

  async handleBridgeError(message) {
    const code = typeof message.code === "string" ? message.code : "bridge_error";
    this.state.lastError = code;
    this.state.connection = "error";
    if (code === "authentication_rejected") {
      this.state.authToken = "";
      await this.chrome.storage.local.remove(this.storageKeys.authToken);
      this.reconnect();
    } else if (code === "protocol_mismatch") {
      this.disconnectSocket();
      this.scheduleReconnect();
    }
  }

  async dispatch(message, sourceSocket = this.state.socket) {
    const startedAt = this.now();
    this.state.metrics.queued += 1;
    let queued = true;
    const leaveQueue = () => {
      if (queued) {
        queued = false;
        this.state.metrics.queued -= 1;
      }
    };
    try {
      await this.state.cancellationBarrier;
      if (sourceSocket !== this.state.socket || !this.authenticated()) {
        return;
      }
      const id = message.id;
      if (!validRequestId(id) || this.state.pending.has(id)) {
        this.respond(id, { error: "invalid_request" }, message.platform, startedAt);
        return;
      }
      const platform = message.platform;
      if (!validPlatform(platform)) {
        this.respond(id, { error: "invalid_request" }, undefined, startedAt);
        return;
      }
      const familyBarrier = this.state.platformCancellationBarriers.get(
        this.platformFamily(platform)
      );
      if (familyBarrier) {
        await familyBarrier;
        if (sourceSocket !== this.state.socket || !this.authenticated()) {
          return;
        }
      }
      if (this.state.pending.has(id)) {
        this.respond(id, { error: "invalid_request" }, platform, startedAt);
        return;
      }
      if (this.consumeQueuedCancellation(id, platform, sourceSocket)) {
        return;
      }
      const adapter = this.adapters[platform];
      const handler = adapter && adapter.handlers && adapter.handlers[message.type];
      if (!handler || typeof handler.handle !== "function") {
        this.respond(id, { error: "invalid_request" }, platform, startedAt);
        return;
      }
      const timeout = Number.isSafeInteger(handler.timeout) && handler.timeout > 0
        ? handler.timeout
        : 30000;
      const entry = this.beginPending(id, timeout, platform, startedAt);
      leaveQueue();
      const context = {
        signal: entry.controller.signal,
        requestId: id,
        platform,
        onCancel: (callback) => this.registerCancelHandler(entry, callback)
      };
      const payload = handlerMessage(message);
      const handled = Promise.resolve().then(() => handler.handle(payload, context)).then(
        (value) => ({ kind: "value", value }),
        () => ({ kind: "error" })
      );
      const outcome = await Promise.race([
        handled,
        entry.cancelled.then(() => ({ kind: "cancelled" }))
      ]);
      if (outcome.kind === "value") {
        this.settle(id, outcome.value);
      } else if (outcome.kind === "error") {
        this.settle(id, { error: "request_failed" });
      }
    } finally {
      leaveQueue();
    }
  }
}
