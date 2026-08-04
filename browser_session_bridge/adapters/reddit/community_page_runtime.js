// chrome.scripting 会将此函数序列化到 Reddit 的 MAIN world。仅读取已渲染的
// Explore 社区卡片；浏览器凭据和页面跟踪状态均保留在页面环境中。
export async function invokeRedditCommunityPageRuntime(input) {
  const ORIGIN = "https://www.reddit.com";
  const EXPLORE_PATH = "/bridge/v1/reddit/explore-feed";
  const TOPIC_PATH = "/bridge/v1/reddit/topic-feed";
  const TOPIC_ID = /^[a-z0-9]{1,16}$/;
  const TOPIC_SLUG = /^[a-z0-9]+(?:_[a-z0-9]+){0,15}$/;
  const SUBREDDIT = /^[A-Za-z0-9_]{2,21}$/;
  const SUBREDDIT_FULLNAME = /^t5_[a-z0-9]+$/;
  const GROUP_ID = /^[A-Za-z0-9_.:-]{1,256}$/;
  const METADATA = /^[A-Za-z0-9_.:-]{1,128}$/;
  const OPERATION_ID = /^[A-Za-z0-9_-]{1,96}$/;
  const MAX_RESULT_BYTES = 4 * 1024 * 1024;

  const PAGES = Object.freeze({
    [EXPLORE_PATH]: {
      kind: "explore_feed",
      source: "reddit_web_community_explore",
      pageType: "explore",
      routeName: "explore-page",
      reloadURL: "/svc/shreddit/feeds/explore-feed?",
      topic: false
    },
    [TOPIC_PATH]: {
      kind: "topic_feed",
      source: "reddit_web_topic_communities",
      pageType: "explore-topic",
      routeName: "explore-topic-page",
      reloadURL: "/svc/shreddit/feeds/explore-topic-feed?",
      topic: true
    }
  });

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function response(value) {
    try {
      if (new TextEncoder().encode(JSON.stringify(value)).byteLength <= MAX_RESULT_BYTES) {
        return value;
      }
    } catch {
      return { ok: false, error: "invalid_response" };
    }
    return { ok: false, error: "response_too_large" };
  }

  function text(value, maximum, allowEmpty = false) {
    const normalized = String(value || "").replace(/\s+/g, " ").trim();
    if (
      normalized.length > maximum ||
      normalized.includes("\0") ||
      (!allowEmpty && normalized === "")
    ) {
      throw new Error("reddit_invalid_response");
    }
    return normalized;
  }

  function originalText(element, maximum, allowEmpty = false) {
    if (!element?.cloneNode) throw new Error("reddit_invalid_response");
    const clone = element.cloneNode(true);
    for (const injected of clone.querySelectorAll?.(
      "font.notranslate, .immersive-translate-target-wrapper"
    ) || []) {
      injected.remove?.();
    }
    return text(clone.textContent, maximum, allowEmpty);
  }

  function integer(value, minimum, maximum) {
    if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
      throw new Error("reddit_invalid_response");
    }
    return value;
  }

  function integerAttribute(element, name, minimum, maximum) {
    const raw = element?.getAttribute?.(name);
    if (!/^\d+$/.test(String(raw || ""))) {
      throw new Error("reddit_invalid_response");
    }
    return integer(Number(raw), minimum, maximum);
  }

  function trackingContext(element) {
    const raw = element?.getAttribute?.("data-faceplate-tracking-context") || "";
    if (raw.length === 0 || raw.length > 32768) {
      throw new Error("reddit_invalid_response");
    }
    try {
      const parsed = JSON.parse(raw);
      if (!isRecord(parsed)) throw new Error("invalid");
      return parsed;
    } catch {
      throw new Error("reddit_invalid_response");
    }
  }

  function nullableMetadata(value) {
    if (value === null) return null;
    const item = text(value, 128);
    if (!METADATA.test(item)) throw new Error("reddit_invalid_response");
    return item;
  }

  function verificationRequired() {
    if (/^\/(?:challenge|verification)(?:\/|$)/i.test(location.pathname)) {
      return true;
    }
    return [...document.querySelectorAll(
      'iframe[src*="captcha"], iframe[src*="recaptcha"], [id*="captcha"] iframe'
    )].some((element) => {
      const rect = element?.getBoundingClientRect?.();
      return Boolean(rect && rect.width > 0 && rect.height > 0);
    });
  }

  function loggedIn() {
    if (/^\/(?:login|register)(?:\/|$)/i.test(location.pathname)) return false;
    return Boolean(
      document.querySelector('shreddit-app[user-logged-in="true"]') ||
      document.querySelector('[data-testid="reddit-profile-menu-button"]')
    );
  }

  function entryValues(path, entries) {
    const page = PAGES[path];
    const expected = page?.topic ? 3 : 1;
    const allowed = new Set(page?.topic ? ["topic_id", "slug", "limit"] : ["limit"]);
    if (!page || !Array.isArray(entries) || entries.length !== expected) return null;
    const values = new Map();
    for (const entry of entries) {
      if (
        !Array.isArray(entry) ||
        entry.length !== 2 ||
        typeof entry[0] !== "string" ||
        typeof entry[1] !== "string" ||
        !allowed.has(entry[0]) ||
        values.has(entry[0]) ||
        /[\r\n\0]/.test(entry[1])
      ) {
        return null;
      }
      values.set(entry[0], entry[1]);
    }
    const limit = values.get("limit") || "";
    if (!/^[1-9]\d?$/.test(limit) || Number(limit) > 50) return null;
    if (
      page.topic &&
      (
        !TOPIC_ID.test(values.get("topic_id") || "") ||
        (values.get("slug") || "").length > 80 ||
        !TOPIC_SLUG.test(values.get("slug") || "")
      )
    ) {
      return null;
    }
    return values;
  }

  function parseCommunity(card, expectedPosition, expectedFullname) {
    const context = trackingContext(card);
    const position = integer(
      context.action_info?.relative_position,
      0,
      100
    );
    if (position !== expectedPosition || !isRecord(context.subreddit)) {
      throw new Error("reddit_invalid_response");
    }
    const fullname = text(context.subreddit.id, 32).toLowerCase();
    const name = text(context.subreddit.name, 21);
    if (
      !SUBREDDIT_FULLNAME.test(fullname) ||
      !SUBREDDIT.test(name) ||
      fullname !== expectedFullname
    ) {
      throw new Error("reddit_invalid_response");
    }
    const link = card.querySelector?.("a[href]");
    let parsed;
    try {
      parsed = new URL(link?.getAttribute?.("href") || "", ORIGIN);
    } catch {
      throw new Error("reddit_invalid_response");
    }
    if (
      parsed.origin !== ORIGIN ||
      parsed.username ||
      parsed.password ||
      parsed.port ||
      parsed.search ||
      parsed.hash ||
      parsed.pathname.toLowerCase() !== `/r/${name}`.toLowerCase()
    ) {
      throw new Error("reddit_invalid_response");
    }
    const number = card.querySelector?.("faceplate-number[number]");
    const weeklyVisitors = integerAttribute(
      number,
      "number",
      0,
      1000000000
    );
    const paragraphs = [...(card.querySelectorAll?.("p") || [])];
    if (paragraphs.length < 2) throw new Error("reddit_invalid_response");
    return {
      id: fullname.slice(3),
      fullname,
      name,
      url: `${ORIGIN}/r/${name}`,
      position,
      weekly_visitors: weeklyVisitors,
      description: originalText(
        paragraphs[paragraphs.length - 1],
        2000,
        true
      )
    };
  }

  function parseGroup(group, expectedPosition) {
    const context = trackingContext(group);
    if (
      !isRecord(context.action_info) ||
      !isRecord(context.community_recommendation_unit)
    ) {
      throw new Error("reddit_invalid_response");
    }
    const position = integer(context.action_info.position, 1, 100);
    if (position !== expectedPosition) throw new Error("reddit_invalid_response");
    const unit = context.community_recommendation_unit;
    const id = text(unit.id, 256);
    if (!GROUP_ID.test(id)) throw new Error("reddit_invalid_response");
    if (
      !Array.isArray(unit.recommendation_ids) ||
      unit.recommendation_ids.length === 0 ||
      unit.recommendation_ids.length > 20
    ) {
      throw new Error("reddit_invalid_response");
    }
    const recommendationIDs = unit.recommendation_ids.map((value) =>
      text(value, 32).toLowerCase()
    );
    if (!recommendationIDs.every((value) => SUBREDDIT_FULLNAME.test(value))) {
      throw new Error("reddit_invalid_response");
    }
    const cards = [
      ...(group.querySelectorAll?.("community-recommendation") || [])
    ];
    if (cards.length !== recommendationIDs.length) {
      throw new Error("reddit_invalid_response");
    }
    const seen = new Set();
    const communities = cards.map((card, index) => {
      const community = parseCommunity(card, index, recommendationIDs[index]);
      if (seen.has(community.fullname)) throw new Error("reddit_invalid_response");
      seen.add(community.fullname);
      return community;
    });
    const titleElement = group.querySelector?.('h3[slot="title"]');
    return {
      id,
      position,
      title: originalText(titleElement, 200),
      model: nullableMetadata(unit.model),
      version: nullableMetadata(unit.version),
      communities
    };
  }

  function readPage(page, values) {
    if (verificationRequired()) throw new Error("reddit_verification_required");
    if (!loggedIn()) throw new Error("reddit_not_logged_in");
    let current;
    try {
      current = new URL(location.href);
    } catch {
      throw new Error("reddit_invalid_response");
    }
    const topicID = page.topic ? values.get("topic_id") : "";
    const slug = page.topic ? values.get("slug") : "";
    const expectedPath = page.topic
      ? `/explore/${topicID}/${slug}/`
      : "/explore/";
    if (
      current.origin !== ORIGIN ||
      current.username ||
      current.password ||
      current.port ||
      current.pathname !== expectedPath ||
      current.search ||
      current.hash
    ) {
      throw new Error("reddit_invalid_response");
    }
    const app = document.querySelector("shreddit-app");
    const feed = document.querySelector("shreddit-feed");
    if (
      !app ||
      !feed ||
      app.getAttribute("routename") !== page.routeName ||
      app.getAttribute("pagetype") !== page.pageType ||
      feed.getAttribute("reload-url") !== page.reloadURL
    ) {
      throw new Error("reddit_invalid_response");
    }
    const groupElements = [
      ...feed.querySelectorAll("in-feed-community-recommendations")
    ];
    if (groupElements.length === 0 || groupElements.length > 100) {
      throw new Error("reddit_invalid_response");
    }
    const seenGroups = new Set();
    const parsedGroups = groupElements.map((element, index) => {
      const group = parseGroup(element, index + 1);
      if (seenGroups.has(group.id)) throw new Error("reddit_invalid_response");
      seenGroups.add(group.id);
      return group;
    });
    const groups = parsedGroups.slice(0, Number(values.get("limit")));
    let topic = null;
    if (page.topic) {
      const expectedHref = `/explore/${topicID}/${slug}/`;
      const links = [
        ...document.querySelectorAll(`a[href="${expectedHref}"]`)
      ];
      const titles = new Set(
        links.map((link) => originalText(link, 200)).filter(Boolean)
      );
      if (titles.size !== 1) throw new Error("reddit_invalid_response");
      topic = {
        id: topicID,
        fullname: `tx1_${topicID}`,
        slug,
        title: [...titles][0]
      };
    }
    return {
      kind: page.kind,
      source: page.source,
      page_type: page.pageType,
      topic,
      requested_limit: Number(values.get("limit")),
      total: groups.length,
      community_total: groups.reduce(
        (total, group) => total + group.communities.length,
        0
      ),
      groups
    };
  }

  function errorCode(error) {
    const message = String(error?.message || "");
    if (message.includes("verification_required")) return "verification_required";
    if (message.includes("not_logged_in")) return "not_logged_in";
    if (message.includes("response_too_large")) return "response_too_large";
    if (message.includes("invalid_response")) return "invalid_response";
    return "runtime_unavailable";
  }

  if (
    !isRecord(input) ||
    input.kind !== "request" ||
    typeof input.operation_id !== "string" ||
    !OPERATION_ID.test(input.operation_id) ||
    typeof input.path !== "string" ||
    !Number.isInteger(input.request_interval_ms) ||
    input.request_interval_ms < 0 ||
    input.request_interval_ms > 30000
  ) {
    return { ok: false, error: "invalid_request" };
  }
  const page = PAGES[input.path];
  const values = entryValues(input.path, input.entries);
  if (!page || !values) return { ok: false, error: "invalid_request" };
  try {
    return response({ ok: true, payload: readPage(page, values) });
  } catch (error) {
    return { ok: false, error: errorCode(error) };
  }
}
