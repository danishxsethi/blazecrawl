/**
 * BlazeCrawl Node.js SDK (OSS).
 *
 * Zero-dependency client using the global fetch (Node 18+).
 *
 *   import { BlazeCrawl } from "@blazecrawl/sdk";
 *   const bc = new BlazeCrawl({ apiKey: "blz_local_..." });
 *   const doc = await bc.scrape("https://example.com");
 *   console.log(doc.markdown);
 */

export class BlazeCrawlError extends Error {
  constructor(message, statusCode, payload) {
    super(message);
    this.name = "BlazeCrawlError";
    this.statusCode = statusCode;
    this.payload = payload;
  }
}

export class BlazeCrawl {
  constructor({ apiKey, baseUrl, timeout } = {}) {
    this.apiKey = apiKey || process.env.BLAZECRAWL_API_KEY || null;
    this.baseUrl = (baseUrl || process.env.BLAZECRAWL_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
    this.timeout = timeout ?? 120000;
  }

  async _request(method, path, body) {
    const headers = { "Content-Type": "application/json" };
    if (this.apiKey) headers["Authorization"] = `Bearer ${this.apiKey}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);
    let resp;
    try {
      resp = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
    const text = await resp.text();
    let payload;
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      payload = { error: text };
    }
    if (resp.status >= 400) {
      const msg = payload?.detail?.message || payload?.error || resp.statusText;
      throw new BlazeCrawlError(msg, resp.status, payload);
    }
    return payload;
  }

  /** Scrape a URL. Returns the `data` object (markdown, html, links, ...). */
  async scrape(url, options = {}) {
    const res = await this._request("POST", "/v1/scrape", { url, ...options });
    return res.data ?? res;
  }

  /** Map a site. Returns { success, urls, count, ... }. */
  async map(url, options = {}) {
    return this._request("POST", "/v1/map", { url, ...options });
  }

  /** Start a crawl; returns the job (with job_id) or polls to completion. */
  async crawl(url, { wait = true, pollInterval = 1000, ...options } = {}) {
    const job = await this._request("POST", "/v1/crawl", { url, ...options });
    if (!wait) return job;
    const id = job.job_id;
    for (;;) {
      const st = await this._request("GET", `/v1/crawl/${id}`);
      if (["completed", "failed", "cancelled"].includes(st.status)) return st;
      await new Promise((r) => setTimeout(r, pollInterval));
    }
  }

  async crawlStatus(jobId) {
    return this._request("GET", `/v1/crawl/${jobId}`);
  }

  async health() {
    return this._request("GET", "/health");
  }
}

export default BlazeCrawl;
