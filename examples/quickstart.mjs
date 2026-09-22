import { BlazeCrawl } from "../sdks/node/src/index.js";

const bc = new BlazeCrawl({ apiKey: process.env.BLAZECRAWL_API_KEY });
const doc = await bc.scrape("https://example.com");
console.log("TITLE:", doc.metadata?.title);
console.log((doc.markdown || "").slice(0, 200));
