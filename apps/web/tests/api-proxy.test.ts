import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import { GET, POST } from "../src/app/api/[...path]/route.ts";

const BASE = "http://api.internal:9000";
const realFetch = globalThis.fetch;
let calls: { url: string; init: RequestInit }[] = [];

beforeEach(() => {
  process.env.API_BASE_URL = BASE + "/";
  calls = [];
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

function req(method = "GET", search = "", headers: Record<string, string> = {}) {
  return {
    method,
    nextUrl: { search },
    headers: new Headers(headers),
    arrayBuffer: async () => new ArrayBuffer(0),
  } as never;
}
const run = (h: typeof GET, path: string[], r = req()) =>
  h(r, { params: Promise.resolve({ path }) });

describe("proxy path handling", () => {
  for (const bad of [
    [".."],
    ["lists", ".."],
    ["."],
    [""],
    ["//evil.com"],
    ["http://evil.com"],
    ["lists", "a/b"],
    ["..\\x"],
    [],
  ]) {
    it(`rejects ${JSON.stringify(bad)} without fetching`, async () => {
      const res = await run(GET, bad);
      assert.equal(res.status, 404);
      assert.equal(calls.length, 0);
    });
  }

  for (const odd of [
    ["%2e%2e"],
    ["%2e%2e", "%2e%2e", "etc"],
    ["%2F%2Fevil.com"],
    ["evil.com"],
    ["@evil.com"],
    ["x?y=1#z"],
  ]) {
    it(`keeps ${JSON.stringify(odd)} under /v1/`, async () => {
      await run(GET, odd);
      assert.equal(calls.length, 1);
      const u = new URL(calls[0].url);
      assert.equal(u.origin, BASE);
      assert.ok(u.pathname.startsWith("/v1/"), u.pathname);
      assert.ok(!u.pathname.includes("/../"));
      assert.equal(u.search, "");
    });
  }

  it("healthz maps to /healthz, other paths to /v1", async () => {
    await run(GET, ["healthz"]);
    await run(GET, ["workspace"], req("GET", "?a=1"));
    assert.equal(calls[0].url, `${BASE}/healthz`);
    assert.equal(calls[1].url, `${BASE}/v1/workspace?a=1`);
  });

  it("injects seller header and drops client x-seller-id/cookie", async () => {
    await run(
      POST,
      ["calls"],
      req("POST", "", { "x-seller-id": "evil", cookie: "s=1", "content-type": "application/json" }),
    );
    const h = new Headers(calls[0].init.headers);
    assert.equal(h.get("x-seller-id"), "demo-seller");
    assert.equal(h.get("cookie"), null);
    assert.equal(h.get("content-type"), "application/json");
  });

  it("returns 502 when upstream is down", async () => {
    globalThis.fetch = (async () => {
      throw new TypeError("fetch failed");
    }) as typeof fetch;
    const res = await run(GET, ["workspace"]);
    assert.equal(res.status, 502);
  });

  it("passes 204 through with null body", async () => {
    globalThis.fetch = (async () => new Response(null, { status: 204 })) as typeof fetch;
    const res = await run(GET, ["x"]);
    assert.equal(res.status, 204);
  });
});

