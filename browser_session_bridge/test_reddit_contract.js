import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  REDDIT_EXPLORE_FEED_PATH,
  REDDIT_HOME_FEED_PATH,
  REDDIT_NEWS_FEED_PATH,
  REDDIT_POPULAR_FEED_PATH,
  REDDIT_TOPIC_FEED_PATH,
  isRedditCommunityPagePath,
  validRedditEntries,
  validRedditReferer,
  validRedditRequest
} from "./adapters/reddit/contract.js";

const AFTER = btoa("t3_fixture");

const FEEDS = [
  {
    path: REDDIT_HOME_FEED_PATH,
    referer: "https://www.reddit.com/",
    entries: [["sort", "BEST"], ["limit", "25"], ["after", AFTER]]
  },
  {
    path: REDDIT_POPULAR_FEED_PATH,
    referer: "https://www.reddit.com/r/popular/",
    entries: [
      ["sort", "TOP"], ["limit", "25"], ["after", AFTER], ["time", "WEEK"]
    ]
  },
  {
    path: REDDIT_NEWS_FEED_PATH,
    referer: "https://www.reddit.com/news?feed=news",
    entries: [
      ["sort", "RISING"], ["limit", "100"], ["after", ""], ["time", "ALL"]
    ]
  }
];

test("Reddit feed family keeps path, entries, and referer bound together", () => {
  for (const feed of FEEDS) {
    assert.equal(validRedditEntries(feed.path, feed.entries), true, feed.path);
    assert.equal(validRedditReferer(feed.referer, feed.path), true, feed.path);
    assert.equal(validRedditRequest({
      path: feed.path,
      entries: feed.entries,
      referer: feed.referer,
      request_interval_ms: 3000
    }), true, feed.path);
  }

  assert.equal(validRedditRequest({
    path: REDDIT_NEWS_FEED_PATH,
    entries: FEEDS[2].entries,
    referer: FEEDS[1].referer,
    request_interval_ms: 3000
  }), false);
  assert.equal(validRedditRequest({
    path: REDDIT_HOME_FEED_PATH,
    entries: [...FEEDS[0].entries, ["time", "ALL"]],
    referer: FEEDS[0].referer,
    request_interval_ms: 3000
  }), false);
  assert.equal(validRedditRequest({
    path: REDDIT_POPULAR_FEED_PATH,
    entries: FEEDS[1].entries.map((entry) =>
      entry[0] === "time" ? ["time", "DECADE"] : entry
    ),
    referer: FEEDS[1].referer,
    request_interval_ms: 3000
  }), false);
});

test("Reddit page runtime pins every Web feed to its observed Shreddit origin", () => {
  const source = readFileSync(
    new URL("./adapters/reddit/page_runtime.js", import.meta.url),
    "utf8"
  );
  for (const path of [
    "/svc/shreddit/feeds/home-feed",
    "/svc/shreddit/feeds/popular-feed",
    "/svc/shreddit/feeds/news-feed"
  ]) {
    assert.match(source, new RegExp(path.replaceAll("/", "\\/")));
  }
  assert.match(source, /reddit_web_personalized_home/);
  assert.match(source, /reddit_web_popular_feed/);
  assert.match(source, /reddit_web_news_feed/);
});

test("Reddit community discovery keeps topic identity bound to the page referer", () => {
  const explore = {
    path: REDDIT_EXPLORE_FEED_PATH,
    entries: [["limit", "25"]],
    referer: "https://www.reddit.com/explore/",
    request_interval_ms: 3000
  };
  const topic = {
    path: REDDIT_TOPIC_FEED_PATH,
    entries: [
      ["topic_id", "2q2no54"],
      ["slug", "games"],
      ["limit", "50"]
    ],
    referer: "https://www.reddit.com/explore/2q2no54/games/",
    request_interval_ms: 3000
  };
  assert.equal(validRedditRequest(explore), true);
  assert.equal(validRedditRequest(topic), true);
  assert.equal(isRedditCommunityPagePath(explore.path), true);
  assert.equal(isRedditCommunityPagePath(topic.path), true);

  assert.equal(validRedditRequest({
    ...topic,
    referer: "https://www.reddit.com/explore/29m4k39/technology/"
  }), false);
  assert.equal(validRedditRequest({
    ...topic,
    entries: topic.entries.map((entry) =>
      entry[0] === "slug" ? ["slug", "games-and-more"] : entry
    ),
    referer: "https://www.reddit.com/explore/2q2no54/games-and-more/"
  }), false);
  assert.equal(validRedditRequest({
    ...explore,
    entries: [["limit", "51"]]
  }), false);
});

test("Reddit community page runtime pins observed Explore components and no Games alias", () => {
  const source = readFileSync(
    new URL(
      "./adapters/reddit/community_page_runtime.js",
      import.meta.url
    ),
    "utf8"
  );
  assert.match(source, /\/svc\/shreddit\/feeds\/explore-feed\?/);
  assert.match(source, /\/svc\/shreddit\/feeds\/explore-topic-feed\?/);
  assert.match(source, /in-feed-community-recommendations/);
  assert.match(source, /community-recommendation/);
  assert.match(source, /reddit_web_community_explore/);
  assert.match(source, /reddit_web_topic_communities/);
  assert.doesNotMatch(source, /games-feed/);
});
