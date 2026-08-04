import { MAX_REQUEST_INTERVAL_MS } from "./protocol.js";

const DEFAULT_MINIMUM_START_INTERVAL_MS = 3000;
const DEFAULT_TRIPPING_ERRORS = Object.freeze([
  "rate_limited",
  "verification_required",
  "forbidden"
]);

function requestAbortedError() {
  return new Error("request_aborted");
}

function throwIfAborted(signal) {
  if (signal && signal.aborted) {
    throw requestAbortedError();
  }
}

function defaultDelay(milliseconds, signal) {
  throwIfAborted(signal);
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => finish(resolve), milliseconds);
    const onAbort = () => finish(() => reject(requestAbortedError()));

    function finish(callback) {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      if (signal && typeof signal.removeEventListener === "function") {
        signal.removeEventListener("abort", onAbort);
      }
      callback();
    }

    if (signal && typeof signal.addEventListener === "function") {
      signal.addEventListener("abort", onAbort, { once: true });
      if (signal.aborted) {
        onAbort();
      }
    }
  });
}

function waitForTurn(turn, signal) {
  throwIfAborted(signal);
  if (!signal || typeof signal.addEventListener !== "function") {
    return turn;
  }
  return new Promise((resolve, reject) => {
    let settled = false;
    const onAbort = () => finish(() => reject(requestAbortedError()));

    function finish(callback) {
      if (settled) {
        return;
      }
      settled = true;
      signal.removeEventListener("abort", onAbort);
      callback();
    }

    signal.addEventListener("abort", onAbort, { once: true });
    if (signal.aborted) {
      onAbort();
      return;
    }
    turn.then(
      () => finish(resolve),
      () => finish(resolve)
    );
  });
}

export class SerialRequestPolicy {
  constructor({
    minimumStartIntervalMs = DEFAULT_MINIMUM_START_INTERVAL_MS,
    now = () => Date.now(),
    delay = defaultDelay,
    trippingErrors = DEFAULT_TRIPPING_ERRORS
  } = {}) {
    const configuredMinimum =
      Number.isInteger(minimumStartIntervalMs) &&
      minimumStartIntervalMs >= 0 &&
      minimumStartIntervalMs <= MAX_REQUEST_INTERVAL_MS
        ? minimumStartIntervalMs
        : DEFAULT_MINIMUM_START_INTERVAL_MS;
    this.minimumStartIntervalMs = Math.max(
      DEFAULT_MINIMUM_START_INTERVAL_MS,
      configuredMinimum
    );
    this.now = typeof now === "function" ? now : () => Date.now();
    this.delay = typeof delay === "function" ? delay : defaultDelay;
    this.trippingErrors = new Set(trippingErrors);
    this.turn = Promise.resolve();
    this.nextAllowedAt = null;
    this.trippedError = "";
  }

  async run(signal, requestedIntervalMs, operation) {
    if (typeof requestedIntervalMs === "function" && operation === undefined) {
      return this.runWithInterval(signal, 0, requestedIntervalMs);
    }
    return this.runWithInterval(signal, requestedIntervalMs, operation);
  }

  async runWithInterval(signal, requestedIntervalMs, operation) {
    return this.runSerial(
      signal,
      requestedIntervalMs,
      operation,
      true
    );
  }

  async runWithoutRiskLatch(signal, requestedIntervalMs, operation) {
    return this.runSerial(
      signal,
      requestedIntervalMs,
      operation,
      false
    );
  }

  async runSerial(signal, requestedIntervalMs, operation, useRiskLatch) {
    throwIfAborted(signal);
    if (useRiskLatch && this.trippedError) {
      return { error: this.trippedError };
    }

    const previousTurn = this.turn;
    let releaseTurn;
    const currentTurn = new Promise((resolve) => {
      releaseTurn = resolve;
    });
    this.turn = previousTurn.then(() => currentTurn, () => currentTurn);

    try {
      await waitForTurn(previousTurn, signal);
      throwIfAborted(signal);
      if (useRiskLatch && this.trippedError) {
        return { error: this.trippedError };
      }
      const result = await operation(
        () => this.beginPlatformRequest(signal, requestedIntervalMs)
      );
      const error = result && typeof result.error === "string"
        ? result.error
        : "";
      if (useRiskLatch && this.trippingErrors.has(error)) {
        this.trippedError = error;
      }
      return result;
    } finally {
      releaseTurn();
    }
  }

  async beginPlatformRequest(signal, requestedIntervalMs = 0) {
    throwIfAborted(signal);
    while (this.nextAllowedAt !== null) {
      const remaining = this.nextAllowedAt - this.now();
      if (remaining <= 0) {
        break;
      }
      await this.delay(remaining, signal);
      throwIfAborted(signal);
    }
    const interval = this.effectiveStartInterval(requestedIntervalMs);
    const candidate = this.now() + interval;
    this.nextAllowedAt = this.nextAllowedAt === null
      ? candidate
      : Math.max(this.nextAllowedAt, candidate);
  }

  effectiveStartInterval(requestedIntervalMs) {
    const requested =
      Number.isInteger(requestedIntervalMs) &&
      requestedIntervalMs >= 0 &&
      requestedIntervalMs <= MAX_REQUEST_INTERVAL_MS
        ? requestedIntervalMs
        : 0;
    return Math.max(this.minimumStartIntervalMs, requested);
  }
}

export {
  DEFAULT_MINIMUM_START_INTERVAL_MS,
  DEFAULT_TRIPPING_ERRORS
};
