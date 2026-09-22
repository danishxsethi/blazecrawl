# @blazecrawl/sdk (Node.js)

```js
import { BlazeCrawl } from "@blazecrawl/sdk";

const bc = new BlazeCrawl({ apiKey: "blz_local_..." });
const doc = await bc.scrape("https://example.com");
console.log(doc.markdown);
```

Zero runtime dependencies (uses global `fetch`, Node 18+).
