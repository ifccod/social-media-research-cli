import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_MINIMUM_START_INTERVAL_MS,
  SerialRequestPolicy
} from "./core/serial_request_policy.js";
import {
  createXiaohongshuAdapterFamily
} from "./adapters/xiaohongshu/family.js";

function nextTurn() {
  return new Promise((resolve) => setImmediate(resolve));
}

test("serial request policy spaces platform starts and never overlaps operations", async () => {
  let clock = 1000;
  const delays = [];
  const starts = [];
  let releaseFirst;
  const firstPending = new Promise((resolve) => {
    releaseFirst = resolve;
  });
  const policy = new SerialRequestPolicy({
    now: () => clock,
    delay: async (milliseconds) => {
      delays.push(milliseconds);
      clock += milliseconds;
    }
  });

  const first = policy.run(null, async (beginPlatformRequest) => {
    await beginPlatformRequest();
    starts.push({ name: "first", at: clock });
    await firstPending;
    return { payload: { name: "first" } };
  });
  const second = policy.run(null, async (beginPlatformRequest) => {
    await beginPlatformRequest();
    starts.push({ name: "second", at: clock });
    return { payload: { name: "second" } };
  });

  await nextTurn();
  assert.deepEqual(starts, [{ name: "first", at: 1000 }]);
  releaseFirst();
  assert.deepEqual(await Promise.all([first, second]), [
    { payload: { name: "first" } },
    { payload: { name: "second" } }
  ]);
  assert.deepEqual(delays, [DEFAULT_MINIMUM_START_INTERVAL_MS]);
  assert.deepEqual(starts, [
    { name: "first", at: 1000 },
    {
      name: "second",
      at: 1000 + DEFAULT_MINIMUM_START_INTERVAL_MS
    }
  ]);
});

test("serial request policy applies the hard floor and preserves a higher reserved boundary", async () => {
  let clock = 1000;
  const delays = [];
  const starts = [];
  const policy = new SerialRequestPolicy({
    minimumStartIntervalMs: 0,
    now: () => clock,
    delay: async (milliseconds) => {
      delays.push(milliseconds);
      clock += milliseconds;
    }
  });
  const run = (interval) => policy.run(
    null,
    interval,
    async (beginPlatformRequest) => {
      await beginPlatformRequest();
      starts.push(clock);
      return { payload: {} };
    }
  );

  await run(8000);
  await run(1000);
  await run(0);

  assert.equal(policy.minimumStartIntervalMs, DEFAULT_MINIMUM_START_INTERVAL_MS);
  assert.deepEqual(delays, [8000, DEFAULT_MINIMUM_START_INTERVAL_MS]);
  assert.deepEqual(starts, [
    1000,
    9000,
    9000 + DEFAULT_MINIMUM_START_INTERVAL_MS
  ]);
});

test("serial request policy latches each risk response for the worker lifetime", async (t) => {
  for (const error of [
    "rate_limited",
    "verification_required",
    "forbidden"
  ]) {
    await t.test(error, async () => {
      let operationCalls = 0;
      const policy = new SerialRequestPolicy({ minimumStartIntervalMs: 0 });
      assert.deepEqual(await policy.run(null, async (beginPlatformRequest) => {
        operationCalls += 1;
        await beginPlatformRequest();
        return { error };
      }), { error });
      assert.deepEqual(await policy.run(null, async () => {
        operationCalls += 1;
        return { payload: {} };
      }), { error });
      assert.equal(operationCalls, 1);
    });
  }
});

test("serial request policy can schedule a recovery probe without consuming its risk latch", async () => {
  const policy = new SerialRequestPolicy({ minimumStartIntervalMs: 0 });
  await policy.run(null, async () => ({ error: "verification_required" }));
  let probeCalls = 0;
  assert.deepEqual(
    await policy.runWithoutRiskLatch(null, 0, async () => {
      probeCalls += 1;
      return { payload: { request_ready: true } };
    }),
    { payload: { request_ready: true } }
  );
  assert.equal(probeCalls, 1);
  assert.equal(policy.trippedError, "verification_required");
  assert.deepEqual(
    await policy.run(null, async () => ({ payload: {} })),
    { error: "verification_required" }
  );
});

test("the service-worker factory shares one policy across all Xiaohongshu adapters", async () => {
  const requestPolicy = new SerialRequestPolicy({ minimumStartIntervalMs: 0 });
  const family = createXiaohongshuAdapterFamily({
    chromeApi: {},
    requestPolicy
  });
  assert.equal(family.web.requestPolicy, requestPolicy);
  assert.equal(family.appV2.requestPolicy, requestPolicy);
  assert.equal(family.pgy.requestPolicy, requestPolicy);

  await family.web.requestPolicy.run(null, async () => ({
    error: "rate_limited"
  }));
  let crossPlatformOperationCalls = 0;
  assert.deepEqual(await family.pgy.requestPolicy.run(null, async () => {
    crossPlatformOperationCalls += 1;
    return { payload: {} };
  }), {
    error: "rate_limited"
  });
  assert.equal(crossPlatformOperationCalls, 0);
});

test("a cancelled queued operation does not release a later operation early", async () => {
  let releaseFirst;
  const firstPending = new Promise((resolve) => {
    releaseFirst = resolve;
  });
  const events = [];
  let clock = 1000;
  const policy = new SerialRequestPolicy({
    minimumStartIntervalMs: 0,
    now: () => clock,
    delay: async (milliseconds) => {
      clock += milliseconds;
    }
  });

  const first = policy.run(null, async (beginPlatformRequest) => {
    await beginPlatformRequest();
    events.push("first_started");
    await firstPending;
    events.push("first_finished");
    return { payload: {} };
  });
  const controller = new AbortController();
  const cancelled = policy.run(
    controller.signal,
    async () => {
      events.push("cancelled_started");
      return { payload: {} };
    }
  );
  const third = policy.run(null, async (beginPlatformRequest) => {
    await beginPlatformRequest();
    events.push("third_started");
    return { payload: {} };
  });

  await nextTurn();
  controller.abort();
  await assert.rejects(cancelled, /request_aborted/);
  await nextTurn();
  assert.deepEqual(events, ["first_started"]);
  releaseFirst();
  await Promise.all([first, third]);
  assert.deepEqual(events, [
    "first_started",
    "first_finished",
    "third_started"
  ]);
});
