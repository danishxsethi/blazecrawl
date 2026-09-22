import { test } from "node:test";
import assert from "node:assert/strict";
import { BlazeCrawl, BlazeCrawlError } from "../src/index.js";

// These tests exercise the client's request construction and error mapping
// against a stub fetch, so they run without a live server.

function stubFetch(handler) {
  globalThis.fetch = handler;
}

const ok = (obj) =>
  new Response(JSON.stringify(obj), { status: 200, headers: { "Content-Type": "application/json" } });

test("scrape returns data", async () => {
  stubFetch(async (url, init) => {
    assert.equal(url, "http://x/v1/scrape");
    assert.equal(init.headers["Authorization"], "Bearer KEY");
    return ok({ success: true, data: { markdown: "# Hi" } });
  });
  const bc = new BlazeCrawl({ apiKey: "KEY", baseUrl: "http://x" });
  const doc = await bc.scrape("https://example.com");
  assert.equal(doc.markdown, "# Hi");
});

test("auth header omitted when no key", async () => {
  stubFetch(async (url, init) => {
    assert.equal(init.headers["Authorization"], undefined);
    return ok({ success: true, data: {} });
  });
  const bc = new BlazeCrawl({ baseUrl: "http://x" });
  await bc.scrape("https://example.com");
});

test("error mapping raises BlazeCrawlError", async () => {
  stubFetch(async () => new Response(JSON.stringify({ detail: { message: "url_rejected" } }), { status: 400 }));
  const bc = new BlazeCrawl({ apiKey: "K", baseUrl: "http://x" });
  await assert.rejects(() => bc.scrape("http://127.0.0.1/"), BlazeCrawlError);
});

test("crawl polls until completed", async () => {
  let polls = 0;
  stubFetch(async (url, init) => {
    if (url.endsWith("/v1/crawl") && init.method === "POST") return ok({ success: true, job_id: "j1" });
    polls++;
    return ok({ status: polls >= 2 ? "completed" : "running", pages_crawled: 1 });
  });
  const bc = new BlazeCrawl({ apiKey: "K", baseUrl: "http://x" });
  const st = await bc.crawl("https://example.com", { pollInterval: 1 });
  assert.equal(st.status, "completed");
});
