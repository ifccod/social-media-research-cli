import assert from "node:assert/strict";
import test from "node:test";

import {
  LINKEDIN_AUTHOR_ARTICLES_PATH,
  LINKEDIN_SEARCH_USERS_PATH,
  validLinkedInRequest
} from "./adapters/linkedin/contract.js";
import { invokeLinkedInPageRuntime } from "./adapters/linkedin/page_runtime.js";

function installBrowserGlobals({ pathname, scripts = [], anchors = [], loggedIn = true }) {
  const previous = {
    window: globalThis.window,
    document: globalThis.document,
    location: globalThis.location,
    navigator: globalThis.navigator,
    screen: globalThis.screen
  };
  globalThis.window = globalThis;
  globalThis.location = { pathname };
  globalThis.document = {
    cookie: loggedIn ? 'JSESSIONID="ajax:SECRET_BROWSER_ONLY"' : "",
    body: { innerText: "" },
    querySelector(selector) {
      if (selector.includes("global-nav") && loggedIn) return {};
      if (selector === "h1") return { textContent: "Bill Gates" };
      return null;
    },
    querySelectorAll(selector) {
      if (selector.includes("captcha")) return [];
      if (selector === 'script[type="application/ld+json"]') return scripts;
      if (selector === 'a[href*="/pulse/"]') return [];
      if (selector === 'a[href*="/in/"]') return anchors;
      return [];
    }
  };
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      userAgent: "Fixture Chrome",
      language: "en-US",
      languages: ["en-US"],
      platform: "MacIntel",
      vendor: "Google Inc.",
      cookieEnabled: true,
      onLine: true,
      hardwareConcurrency: 8,
      deviceMemory: 8
    }
  });
  globalThis.screen = {
    width: 1440, height: 900, availWidth: 1440, availHeight: 860,
    colorDepth: 24, pixelDepth: 24
  };
  globalThis.innerWidth = 1280;
  globalThis.innerHeight = 720;
  globalThis.outerWidth = 1440;
  globalThis.outerHeight = 900;
  globalThis.devicePixelRatio = 2;
  return () => {
    globalThis.window = previous.window;
    globalThis.document = previous.document;
    globalThis.location = previous.location;
    Object.defineProperty(globalThis, "navigator", {
      configurable: true,
      value: previous.navigator
    });
    globalThis.screen = previous.screen;
  };
}

test("LinkedIn contract binds parameters to the exact referer", () => {
  assert.equal(validLinkedInRequest({
    path: LINKEDIN_AUTHOR_ARTICLES_PATH,
    entries: [["slug", "williamhgates"], ["limit", "10"]],
    referer: "https://www.linkedin.com/in/williamhgates/recent-activity/articles/"
  }), true);
  assert.equal(validLinkedInRequest({
    path: LINKEDIN_SEARCH_USERS_PATH,
    entries: [["first_name", "Bill"], ["last_name", "Gates"], ["limit", "10"]],
    referer: "https://www.linkedin.com/search/results/people/?firstName=Other&lastName=Gates"
  }), false);
  assert.equal(validLinkedInRequest({
    path: LINKEDIN_SEARCH_USERS_PATH,
    entries: [["first_name", "Bill"], ["last_name", "Gates"], ["limit", "10"]],
    referer: "https://evil.example/search/results/people/?firstName=Bill&lastName=Gates"
  }), false);
});

test("LinkedIn runtime extracts bounded JSON-LD articles without session data", async () => {
  const scripts = [{
    textContent: JSON.stringify({
      "@graph": [
        { "@type": "Person", name: "Bill Gates", url: "https://www.linkedin.com/in/williamhgates" },
        {
          "@type": "Article",
          headline: "Fixture article",
          articleBody: "Fixture body",
          url: "https://www.linkedin.com/pulse/fixture-article/?trk=SECRET",
          datePublished: "2026-07-23",
          author: { name: "Bill Gates", url: "https://www.linkedin.com/in/williamhgates?trk=SECRET" }
        }
      ]
    })
  }];
  const restore = installBrowserGlobals({
    pathname: "/in/williamhgates/recent-activity/articles/",
    scripts
  });
  try {
    const result = await invokeLinkedInPageRuntime({
      kind: "request",
      operation_id: "fixture_author",
      path: LINKEDIN_AUTHOR_ARTICLES_PATH,
      entries: [["slug", "williamhgates"], ["limit", "1"]]
    });
    assert.equal(result.ok, true);
    assert.equal(result.payload.count, 1);
    assert.equal(result.payload.items[0].url, "https://www.linkedin.com/pulse/fixture-article");
    assert.equal(result.payload.items[0].author.url, "https://www.linkedin.com/in/williamhgates");
    assert.equal(result.payload.partial, true);
    assert.doesNotMatch(JSON.stringify(result), /SECRET_BROWSER_ONLY|JSESSIONID|ajax:/);
  } finally {
    restore();
  }
});

test("LinkedIn runtime extracts and deduplicates visible people results", async () => {
  const card = {
    textContent: "Bill Gates Co-chair at Gates Foundation Seattle",
    querySelector(selector) {
      if (selector.includes("title-text")) return { textContent: "Bill Gates" };
      if (selector === ".entity-result__primary-subtitle") return { textContent: "Co-chair at Gates Foundation" };
      if (selector === ".entity-result__secondary-subtitle") return { textContent: "Seattle" };
      if (selector === "img") return { currentSrc: "https://media.licdn.com/fixture.jpg" };
      return null;
    }
  };
  const anchor = {
    href: "https://www.linkedin.com/in/williamhgates?miniProfileUrn=SECRET",
    textContent: "Bill Gates",
    closest() { return card; }
  };
  const restore = installBrowserGlobals({
    pathname: "/search/results/people/",
    anchors: [anchor, anchor]
  });
  try {
    const result = await invokeLinkedInPageRuntime({
      kind: "request",
      operation_id: "fixture_search",
      path: LINKEDIN_SEARCH_USERS_PATH,
      entries: [["first_name", "Bill"], ["last_name", "Gates"], ["limit", "10"]]
    });
    assert.equal(result.ok, true);
    assert.equal(result.payload.count, 1);
    assert.equal(result.payload.items[0].slug, "williamhgates");
    assert.equal(result.payload.items[0].headline, "Co-chair at Gates Foundation");
    assert.equal(result.payload.partial, true);
  } finally {
    restore();
  }
});

test("LinkedIn runtime reports login loss before page extraction", async () => {
  const restore = installBrowserGlobals({ pathname: "/authwall", loggedIn: false });
  try {
    const session = await invokeLinkedInPageRuntime({ kind: "session" });
    assert.equal(session.ok, true);
    assert.equal(session.payload.logged_in, false);
    const request = await invokeLinkedInPageRuntime({
      kind: "request",
      operation_id: "fixture_logged_out",
      path: LINKEDIN_AUTHOR_ARTICLES_PATH,
      entries: [["slug", "williamhgates"], ["limit", "10"]]
    });
    assert.deepEqual(request, { ok: false, error: "not_logged_in" });
  } finally {
    restore();
  }
});

test("LinkedIn 页面数据未就绪时立即返回 runtime_unavailable", async () => {
  const restore = installBrowserGlobals({
    pathname: "/search/results/people/",
    anchors: []
  });
  try {
    const result = await invokeLinkedInPageRuntime({
      kind: "request",
      operation_id: "fixture_not_ready",
      path: LINKEDIN_SEARCH_USERS_PATH,
      entries: [["first_name", "Bill"], ["last_name", "Gates"], ["limit", "10"]]
    });
    assert.deepEqual(result, { ok: false, error: "runtime_unavailable" });
  } finally {
    restore();
  }
});
