export const DEFAULT_BRIDGE_URL = "ws://127.0.0.1:18765";
export { BRIDGE_PROTOCOL_VERSION } from "./wire_protocol_v4.js";
export const MAX_WIRE_BYTES = 7 * 1024 * 1024;
export const MAX_REQUEST_INTERVAL_MS = 10000;
export const BROWSER_INSTANCE_ID = /^[a-f0-9]{32}$/;
export const REQUEST_ID = /^[A-Za-z0-9_-]{1,96}$/;
export const SHORT_CODE = /^[a-z_]{1,64}$/;

export function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function validRequestId(value) {
  return typeof value === "string" && REQUEST_ID.test(value);
}

export function validBrowserInstanceId(value) {
  return typeof value === "string" && BROWSER_INSTANCE_ID.test(value);
}

export function generateBrowserInstanceId(cryptoApi = globalThis.crypto) {
  if (!cryptoApi || typeof cryptoApi.getRandomValues !== "function") {
    throw new Error("secure_random_unavailable");
  }
  const bytes = new Uint8Array(16);
  cryptoApi.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

export function validOptionalRequestIntervalMs(value) {
  return value === undefined || (
    Number.isInteger(value) &&
    value >= 0 &&
    value <= MAX_REQUEST_INTERVAL_MS
  );
}

export function normalizeLoopbackBridgeUrl(value, fallback = DEFAULT_BRIDGE_URL) {
  const source = typeof value === "string" && value.trim() ? value.trim() : fallback;
  let parsed;
  try {
    parsed = new URL(source);
  } catch {
    return null;
  }
  if (
    parsed.protocol !== "ws:" ||
    parsed.hostname !== "127.0.0.1" ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash ||
    !parsed.port ||
    Number(parsed.port) < 1 ||
    Number(parsed.port) > 65535
  ) {
    return null;
  }
  return parsed.toString().replace(/\/$/, "");
}

export function encodedByteLength(value) {
  return new TextEncoder().encode(value).byteLength;
}

export function validErrorCode(value, errorCodes, fallback = "request_failed") {
  return typeof value === "string" && SHORT_CODE.test(value) && errorCodes.has(value)
    ? value
    : fallback;
}
