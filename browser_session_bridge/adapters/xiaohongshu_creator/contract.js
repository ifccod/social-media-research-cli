import {
  isRecord,
  validOptionalRequestIntervalMs
} from "../../core/protocol.js";

export const XIAOHONGSHU_CREATOR_ORIGIN = "https://creator.xiaohongshu.com";
export const XIAOHONGSHU_CREATOR_PUBLISH_PATH = "/publish/publish";
export const XIAOHONGSHU_CREATOR_LOGIN_URL =
  `${XIAOHONGSHU_CREATOR_ORIGIN}${XIAOHONGSHU_CREATOR_PUBLISH_PATH}`;
export const XIAOHONGSHU_CREATOR_TAB_PATTERNS = [
  `${XIAOHONGSHU_CREATOR_ORIGIN}/*`
];

export const XIAOHONGSHU_CREATOR_UPLOAD_IMAGE_PATH =
  "/bridge/v1/xiaohongshu-creator/upload-image";
export const XIAOHONGSHU_CREATOR_UPLOAD_VIDEO_PATH =
  "/bridge/v1/xiaohongshu-creator/upload-video";
export const XIAOHONGSHU_CREATOR_PUBLISH_NOTE_PATH =
  "/bridge/v1/xiaohongshu-creator/publish-note";

export const XIAOHONGSHU_CREATOR_ERROR_CODES = new Set([
  "forbidden",
  "invalid_request",
  "invalid_response",
  "not_logged_in",
  "rate_limited",
  "request_failed",
  "response_too_large",
  "runtime_unavailable",
  "tab_unavailable",
  "timeout",
  "verification_required"
]);

const MIME_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const VIDEO_MIME_TYPES = new Set(["video/mp4", "video/quicktime"]);
const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;
const FILE_ID = /^(?:spectrum\/)?[A-Za-z0-9._-]{1,128}$/;
const UPLOAD_ID = /^[A-Za-z0-9_-]{8,64}$/;
const TOTAL_BYTES = /^[1-9][0-9]{0,7}$/;
const SEGMENT_INDEX = /^(?:0|[1-9][0-9]{0,2})$/;
const DIMENSION = /^(?:0|[1-9][0-9]{0,4})$/;
const MAX_UPLOAD_BASE64 = 7 * 1024 * 1024;
const MAX_VIDEO_BYTES = 64_000_000;
const MAX_TITLE_CHARS = 20;
const MAX_CONTENT_CHARS = 1000;
const MAX_IMAGES = 9;
const FORBIDDEN_REQUEST_FIELDS = Object.freeze([
  "body",
  "headers",
  "params",
  "cookie",
  "cookies",
  "authorization",
  "xsec",
  "xsec_token",
  "xsec_source",
  "signature"
]);

const OPERATIONS = Object.freeze({
  [XIAOHONGSHU_CREATOR_UPLOAD_IMAGE_PATH]: validUploadEntries,
  [XIAOHONGSHU_CREATOR_UPLOAD_VIDEO_PATH]: validUploadVideoEntries,
  [XIAOHONGSHU_CREATOR_PUBLISH_NOTE_PATH]: validPublishEntries
});

function entriesObject(entries) {
  if (!Array.isArray(entries) || entries.length > 8) {
    return null;
  }
  const result = {};
  for (const entry of entries) {
    if (
      !Array.isArray(entry) ||
      entry.length !== 2 ||
      typeof entry[0] !== "string" ||
      typeof entry[1] !== "string" ||
      Object.hasOwn(result, entry[0])
    ) {
      return null;
    }
    result[entry[0]] = entry[1];
  }
  return result;
}

function characterCount(value) {
  return [...value].length;
}

function validUploadEntries(entries) {
  const values = entriesObject(entries);
  if (!values) {
    return false;
  }
  const names = Object.keys(values);
  const dataBase64 = values.dataBase64 || "";
  return (
    names.length === 2 &&
    names.every((name) => ["mimeType", "dataBase64"].includes(name)) &&
    MIME_TYPES.has(values.mimeType) &&
    dataBase64.length >= 4 &&
    dataBase64.length <= MAX_UPLOAD_BASE64 &&
    BASE64.test(dataBase64)
  );
}

function validFileIds(value) {
  if (typeof value !== "string" || !value) {
    return false;
  }
  const items = value.split(",");
  if (items.length < 1 || items.length > MAX_IMAGES) {
    return false;
  }
  const seen = new Set();
  for (const item of items) {
    if (!FILE_ID.test(item) || seen.has(item)) {
      return false;
    }
    seen.add(item);
  }
  return true;
}

function validFileId(value) {
  return typeof value === "string" && FILE_ID.test(value);
}

function validTitleContent(values) {
  return (
    typeof values.title === "string" &&
    characterCount(values.title) >= 1 &&
    characterCount(values.title) <= MAX_TITLE_CHARS &&
    !/[\r\n\0]/.test(values.title) &&
    typeof values.content === "string" &&
    characterCount(values.content) >= 1 &&
    characterCount(values.content) <= MAX_CONTENT_CHARS &&
    !/[\r\0]/.test(values.content)
  );
}

function validUploadVideoEntries(entries) {
  const values = entriesObject(entries);
  if (!values) {
    return false;
  }
  const names = Object.keys(values);
  if (values.command === "begin") {
    const totalBytes = Number(values.total_bytes);
    return (
      names.length === 3 &&
      names.every((name) => ["command", "mimeType", "total_bytes"].includes(name)) &&
      VIDEO_MIME_TYPES.has(values.mimeType) &&
      TOTAL_BYTES.test(values.total_bytes) &&
      Number.isInteger(totalBytes) &&
      totalBytes >= 1 &&
      totalBytes <= MAX_VIDEO_BYTES
    );
  }
  if (values.command === "chunk") {
    const dataBase64 = values.dataBase64 || "";
    return (
      names.length === 4 &&
      names.every((name) =>
        ["command", "upload_id", "segment_index", "dataBase64"].includes(name)
      ) &&
      UPLOAD_ID.test(values.upload_id) &&
      SEGMENT_INDEX.test(values.segment_index) &&
      dataBase64.length >= 4 &&
      dataBase64.length <= MAX_UPLOAD_BASE64 &&
      BASE64.test(dataBase64)
    );
  }
  if (values.command === "finish") {
    return (
      names.length === 2 &&
      names.every((name) => ["command", "upload_id"].includes(name)) &&
      UPLOAD_ID.test(values.upload_id)
    );
  }
  return false;
}

function validPublishEntries(entries) {
  const values = entriesObject(entries);
  if (!values || !validTitleContent(values)) {
    return false;
  }
  const names = Object.keys(values);
  if (names.includes("file_ids")) {
    return (
      names.length === 3 &&
      names.every((name) => ["title", "content", "file_ids"].includes(name)) &&
      validFileIds(values.file_ids)
    );
  }
  return (
    names.length === 6 &&
    names.every((name) =>
      ["title", "content", "video_file_id", "cover_file_id", "width", "height"].includes(name)
    ) &&
    validFileId(values.video_file_id) &&
    validFileId(values.cover_file_id) &&
    DIMENSION.test(values.width) &&
    DIMENSION.test(values.height)
  );
}

function normalizePathname(pathname) {
  if (pathname.length > 1 && pathname.endsWith("/")) {
    return pathname.slice(0, -1);
  }
  return pathname;
}

export function validXiaohongshuCreatorReferer(value) {
  if (typeof value !== "string" || value.length > 4096) {
    return false;
  }
  try {
    const parsed = new URL(value);
    return (
      parsed.origin === XIAOHONGSHU_CREATOR_ORIGIN &&
      normalizePathname(parsed.pathname) === XIAOHONGSHU_CREATOR_PUBLISH_PATH &&
      !parsed.username &&
      !parsed.password &&
      !parsed.port &&
      !parsed.hash
    );
  } catch {
    return false;
  }
}

export function isXiaohongshuCreatorTabUrl(value) {
  return validXiaohongshuCreatorReferer(value);
}

export function sameXiaohongshuCreatorRequestContext(current, referer) {
  if (
    !validXiaohongshuCreatorReferer(current) ||
    !validXiaohongshuCreatorReferer(referer)
  ) {
    return false;
  }
  return new URL(current).origin === new URL(referer).origin;
}

export function validXiaohongshuCreatorEntries(path, value) {
  return Object.hasOwn(OPERATIONS, path) && OPERATIONS[path](value);
}

export function validXiaohongshuCreatorRequest(message) {
  if (
    !isRecord(message) ||
    FORBIDDEN_REQUEST_FIELDS.some((name) =>
      Object.prototype.hasOwnProperty.call(message, name)
    )
  ) {
    return false;
  }
  return Boolean(
    message.method === "POST" &&
    validOptionalRequestIntervalMs(message.request_interval_ms) &&
    validXiaohongshuCreatorEntries(message.path, message.entries) &&
    validXiaohongshuCreatorReferer(message.referer)
  );
}

