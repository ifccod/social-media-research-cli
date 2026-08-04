import fs from "node:fs";
import vm from "node:vm";
import { performance as nodePerformance } from "node:perf_hooks";

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

let input;
try {
  input = JSON.parse(fs.readFileSync(0, "utf8"));
} catch (error) {
  fail(`invalid challenge input: ${error?.message || error}`);
}

const { source, meta, page_url: pageUrl, user_agent: userAgent } = input || {};
if (![source, meta, pageUrl, userAgent].every((value) => typeof value === "string" && value)) {
  fail("challenge input is missing source, meta, page_url, or user_agent");
}

let settled = false;
let resolveToken;
const tokenPromise = new Promise((resolve) => { resolveToken = resolve; });
const cookieValues = new Map();
const script = {
  dataset: { assetsTrackerConfig: JSON.stringify({ appName: "zse_ck" }) },
  tagName: "SCRIPT",
};
const inertNode = { observe() {}, querySelectorAll() { return []; } };
const location = {
  href: pageUrl,
  protocol: "https:",
  host: "www.zhihu.com",
  hostname: "www.zhihu.com",
  origin: "https://www.zhihu.com",
  pathname: new URL(pageUrl).pathname,
  reload() {},
  toString() { return this.href; },
};

const metaNode = { getAttribute: (name) => name === "content" ? meta : null };
const document = {
  currentScript: script,
  referrer: "https://www.zhihu.com/",
  readyState: "complete",
  body: inertNode,
  head: inertNode,
  documentElement: inertNode,
  getElementById(id) { return id === "zh-zse-ck" ? metaNode : null; },
  getElementsByTagName() { return [metaNode]; },
  querySelector() { return script; },
  addEventListener() {},
  removeEventListener() {},
};
Object.defineProperty(document, "cookie", {
  configurable: true,
  get() { return [...cookieValues].map(([name, value]) => `${name}=${value}`).join("; "); },
  set(rawValue) {
    const pair = String(rawValue).split(";", 1)[0];
    const separator = pair.indexOf("=");
    if (separator < 1) return;
    const name = pair.slice(0, separator);
    const value = pair.slice(separator + 1);
    cookieValues.set(name, value);
    if (!settled && name === "__zse_ck" && value.startsWith("005_") && value.includes("-")) {
      settled = true;
      resolveToken(value);
    }
  },
});

class XMLHttpRequest {
  open() {}
  setRequestHeader() {}
  send() {}
  addEventListener() {}
}
class PerformanceObserver {
  observe() {}
  disconnect() {}
}
class MutationObserver {
  observe() {}
  disconnect() {}
}

const silentConsole = {
  log() {}, info() {}, warn() {}, error() {}, debug() {}, trace() {}, exception() {}, table() {},
};
const target = {
  console: silentConsole,
  __g: {},
  document,
  navigator: {
    userAgent,
    webdriver: false,
    language: "zh-CN",
    languages: ["zh-CN", "zh", "en"],
    platform: "MacIntel",
    hardwareConcurrency: 8,
  },
  location,
  sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
  performance: { now: () => nodePerformance.now(), getEntriesByType: () => [] },
  XMLHttpRequest,
  PerformanceObserver,
  MutationObserver,
  requestAnimationFrame: (callback) => setTimeout(callback, 0),
  cancelAnimationFrame: clearTimeout,
  addEventListener() {},
  removeEventListener() {},
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  TextEncoder,
  TextDecoder,
  URL,
  URLSearchParams,
  atob: (value) => Buffer.from(value, "base64").toString("binary"),
  btoa: (value) => Buffer.from(value, "binary").toString("base64"),
};

target.window = target;
target.self = target;
target.globalThis = target;
const context = vm.createContext(target);
vm.runInContext(`
  Object.defineProperty(document.currentScript, Symbol.toStringTag, {
    configurable: true,
    value: "HTMLScriptElement",
  });
`, context);

let fatalError;
process.on("unhandledRejection", (reason) => {
  if (reason?.name === "RuntimeError" && reason?.message === "unreachable") return;
  fatalError = reason;
});

try {
  vm.runInContext(source, context, { filename: "zhihu-zse-ck-v4.js", timeout: 30_000 });
} catch (error) {
  fatalError = error;
}

const timeoutToken = new Promise((resolve) => setTimeout(() => resolve(null), 3500));
let token = await Promise.race([tokenPromise, timeoutToken]);
if (!token && typeof target.__g?.ck === "string" && target.__g.ck.startsWith("005_")) {
  token = `${target.__g.ck}-${meta}`;
}
if (!token) {
  fail(`challenge produced no token${fatalError ? `: ${fatalError?.message || fatalError}` : ""}`);
}
process.stdout.write(JSON.stringify({ token }));
process.exit(0);
