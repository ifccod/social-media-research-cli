const SENSITIVE_NAME = /(?:cookie|authorization|token|ms[_-]?token|a[_-]?bogus|x[_-]?bogus|signature|webid|uifid|session|passport|csrf|sid(?:_|$)|odin)/i;

function cleanUrl(value) {
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return value;
    }
    for (const [name] of parsed.searchParams) {
      if (SENSITIVE_NAME.test(name)) {
        return `${parsed.protocol}//${parsed.host}${parsed.pathname}`;
      }
    }
    return value;
  } catch {
    return value;
  }
}

/**
 * 数据离开扩展前移除凭据和签名 URL。
 * 平台适配器可在此之前执行更严格的定向过滤。
 */
export function sanitizeBrowserPayload(value, depth = 0, seen = new WeakSet()) {
  if (depth > 24 || value === null) {
    return value === null ? null : undefined;
  }
  if (typeof value === "string") {
    if (value.length > 32768 || SENSITIVE_NAME.test(value.split("=")[0] || "")) {
      return undefined;
    }
    return cleanUrl(value);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  if (Array.isArray(value)) {
    return value
      .slice(0, 10000)
      .map((item) => sanitizeBrowserPayload(item, depth + 1, seen))
      .filter((item) => item !== undefined);
  }
  if (value === undefined || typeof value !== "object" || seen.has(value)) {
    return undefined;
  }
  seen.add(value);
  const output = {};
  for (const key of Object.keys(value).slice(0, 1000)) {
    if (SENSITIVE_NAME.test(key)) {
      continue;
    }
    const item = sanitizeBrowserPayload(value[key], depth + 1, seen);
    if (item !== undefined) {
      output[key] = item;
    }
  }
  seen.delete(value);
  return output;
}
