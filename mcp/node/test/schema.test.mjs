import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SERVER = path.join(HERE, "..", "src", "index.js");

const EXPECTED_TOOLS = [
  {
    name: "scrape",
    description: "Scrape a URL and return clean Markdown (LLM-ready).",
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string", description: "http/https URL to scrape" },
        render: {
          type: "string",
          description: "Rendering mode: auto-select, static HTTP, or browser rendering",
          enum: ["auto", "static", "browser"],
          default: "auto",
        },
      },
      required: ["url"],
    },
  },
  {
    name: "map",
    description: "Discover the URL set of a site (sitemap + link graph).",
    inputSchema: {
      type: "object",
      properties: {
        url: {
          type: "string",
          description: "http/https site URL whose discoverable links should be mapped",
        },
      },
      required: ["url"],
    },
  },
  {
    name: "crawl",
    description: "Crawl a site (BFS, same-origin) and return page Markdown.",
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string", description: "http/https site URL to crawl" },
        max_pages: {
          type: "integer",
          description: "Maximum number of pages to return from the crawl",
        },
        max_depth: {
          type: "integer",
          description: "Maximum same-origin link depth from the starting URL",
        },
      },
      required: ["url"],
    },
  },
];

test("node MCP tool schema snapshot", async (t) => {
  const child = spawn(process.execPath, [SERVER], { stdio: ["pipe", "pipe", "pipe"] });
  t.after(() => child.kill());

  const response = await new Promise((resolve, reject) => {
    let buffer = "";
    const timer = setTimeout(() => reject(new Error("timed out waiting for tools/list")), 3000);

    child.stdout.on("data", (chunk) => {
      buffer += chunk.toString();
      const newline = buffer.indexOf("\n");
      if (newline < 0) return;
      clearTimeout(timer);
      resolve(JSON.parse(buffer.slice(0, newline)));
    });
    child.once("error", reject);
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }) + "\n");
  });

  assert.deepEqual(response.result.tools, EXPECTED_TOOLS);
});
