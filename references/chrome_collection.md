# Chrome Collection Reference

Use these snippets with the Chrome skill and the Node REPL browser runtime. Keep calls short
enough to avoid long tool timeouts.

## Bootstrap And Claim Target Tab

After loading the Chrome skill runtime, claim an existing ChatGPT tab or open the user-provided URL.

```js
await browser.nameSession("Chat PDF export");
const targetUrl = "https://chatgpt.com/...";
const openTabs = await browser.user.openTabs();
const target = openTabs.find(t => (t.url || "").startsWith(targetUrl));
globalThis.chatExportTab = target
  ? await browser.user.claimTab(target)
  : await browser.tabs.new();
if (!target) await chatExportTab.goto(targetUrl);
await chatExportTab.playwright.waitForLoadState({ state: "domcontentloaded", timeoutMs: 15000 });
```

## Define Collection Helpers

This helper reads all currently materialized ChatGPT message nodes and stores the richest version
seen for each message id. It records a page-position value for ordering, but final ordering should
still be visually sanity-checked because virtualized lists can adjust heights while loading.

```js
globalThis.chatExportMessages = new Map();
globalThis.chatExportSequences = [];

globalThis.collectChatExportVisible = async function(label) {
  const payload = await chatExportTab.playwright.evaluate(() => {
    function cleanText(s) {
      return (s || "").replace(/\u00a0/g, " ").trim();
    }
    const root =
      Array.from(document.querySelectorAll("*")).find(el =>
        el.scrollHeight > el.clientHeight + 100000 &&
        getComputedStyle(el).overflowY === "auto"
      ) || document.scrollingElement;
    const scrollTop = root?.scrollTop || 0;
    const items = Array.from(document.querySelectorAll("[data-message-author-role]")).map((el, idx) => {
      const rect = el.getBoundingClientRect();
      const content = el.querySelector(".markdown") ||
        el.querySelector(".user-message-bubble-color") ||
        el;
      const text = cleanText(el.innerText || el.textContent || "");
      return {
        id: el.getAttribute("data-message-id") ||
          `${el.getAttribute("data-message-author-role")}-${idx}-${text.slice(0, 80)}`,
        role: el.getAttribute("data-message-author-role") || "unknown",
        model: el.getAttribute("data-message-model-slug") || "",
        text,
        html: content.innerHTML,
        imageRefs: Array.from(el.querySelectorAll("img")).map(img => ({
          alt: img.alt || "",
          src: img.currentSrc || img.src || "",
          w: img.naturalWidth || 0,
          h: img.naturalHeight || 0
        })),
        absTopNow: scrollTop + rect.top,
        seqHint: idx
      };
    });
    return {
      pos: {
        scrollTop,
        scrollHeight: root?.scrollHeight ?? null,
        clientHeight: root?.clientHeight ?? null,
        visibleCount: items.length
      },
      items
    };
  }, undefined, { timeoutMs: 15000 });

  for (const item of payload.items) {
    const old = chatExportMessages.get(item.id);
    const richer = !old ||
      (item.text || "").length > (old.text || "").length ||
      (item.html || "").length > (old.html || "").length;
    const merged = richer ? { ...item } : { ...old };
    merged.role = merged.role || item.role;
    merged.model = merged.model || item.model;
    merged.absTopNow = item.absTopNow;
    merged.absTop = old?.absTop ?? item.absTopNow;
    merged.firstSeenLabel = old?.firstSeenLabel || label;
    merged.lastSeenLabel = label;
    const oldRefs = old?.imageRefs || [];
    const key = new Set(oldRefs.map(r => `${r.alt}|${r.src}|${r.localPath || ""}`));
    merged.imageRefs = oldRefs.concat((item.imageRefs || []).filter(r => !key.has(`${r.alt}|${r.src}|${r.localPath || ""}`)));
    chatExportMessages.set(item.id, merged);
  }
  chatExportSequences.push({ label, pos: payload.pos, ids: payload.items.map(i => i.id) });
  return { label, collected: chatExportMessages.size, sequenceLen: payload.items.length, pos: payload.pos };
};
```

## Scan The Virtualized List

Run several short cells rather than one very long loop. First force the top, then make a top-to-bottom pass.
If the message count increases during a pass, make another pass until the count is stable.

```js
for (let k = 0; k < 8; k++) {
  let err = null;
  try { await chatExportTab.dom_cua.scroll({ x: 0, y: -100000 }); } catch (e) { err = String(e).slice(0, 160); }
  await chatExportTab.playwright.waitForTimeout(600);
  const r = await collectChatExportVisible(`up-${k}`);
  console.log({ err, collected: r.collected, scrollTop: r.pos.scrollTop, scrollHeight: r.pos.scrollHeight });
  if ((r.pos.scrollTop || 0) <= 5) break;
}
```

```js
const reports = [];
for (let k = 0; k < 8; k++) {
  const before = await collectChatExportVisible(`down-${k}-before`);
  reports.push(before);
  if ((before.pos.scrollHeight - before.pos.clientHeight - before.pos.scrollTop) < 1000) break;
  let err = null;
  try { await chatExportTab.dom_cua.scroll({ x: 0, y: 50000 }); } catch (e) { err = String(e).slice(0, 160); }
  await chatExportTab.playwright.waitForTimeout(700);
  const after = await collectChatExportVisible(`down-${k}-after`);
  reports.push({ ...after, err });
  if ((after.pos.scrollHeight - after.pos.clientHeight - after.pos.scrollTop) < 1000) break;
}
nodeRepl.write(JSON.stringify(reports.map(r => ({
  label: r.label,
  err: r.err,
  collected: r.collected,
  sequenceLen: r.sequenceLen,
  scrollTop: r.pos.scrollTop,
  scrollHeight: r.pos.scrollHeight
})), null, 2));
```

## Capture Visible Remote Attachment Images

ChatGPT file images can be signed URLs that return 403 outside the logged-in browser. If image refs are
important, bring each image into view and screenshot its bounding box. Repeat after scanning enough of
the page for the images to have been observed.

```js
globalThis.captureChatExportImages = async function(outDir) {
  const fs = await import("node:fs/promises");
  await fs.mkdir(outDir, { recursive: true });

  async function imageRects() {
    return await chatExportTab.playwright.evaluate(() =>
      Array.from(document.querySelectorAll("[data-message-author-role] img")).map((img, i) => {
        const r = img.getBoundingClientRect();
        return {
          i,
          alt: img.alt || "",
          src: img.currentSrc || img.src || "",
          x: r.x,
          y: r.y,
          top: r.top,
          bottom: r.bottom,
          width: r.width,
          height: r.height,
          viewportW: innerWidth,
          viewportH: innerHeight
        };
      }).filter(x => x.src.startsWith("https://chatgpt.com/backend-api/estuary/"))
    , undefined, { timeoutMs: 10000 });
  }

  const saved = [];
  let rects = await imageRects();
  for (const target of rects) {
    let rect = target;
    for (let attempt = 0; attempt < 10; attempt++) {
      if (rect.top >= 80 && rect.bottom <= rect.viewportH - 60) break;
      const delta = Math.max(-20000, Math.min(20000, rect.top - 140));
      try { await chatExportTab.dom_cua.scroll({ x: 0, y: delta }); } catch {}
      await chatExportTab.playwright.waitForTimeout(600);
      const updated = (await imageRects()).find(x => x.alt === target.alt && x.src === target.src);
      if (!updated) break;
      rect = updated;
    }
    if (!(rect.top >= 0 && rect.top < rect.viewportH)) continue;
    const safeAlt = (rect.alt || `image_${rect.i}.png`).replace(/[^a-zA-Z0-9_.-]/g, "_");
    const file = `${outDir}/attachment_${saved.length + 1}_${safeAlt}`;
    const clip = {
      x: Math.max(0, Math.floor(rect.x)),
      y: Math.max(0, Math.floor(rect.y)),
      width: Math.min(Math.ceil(rect.width), Math.floor(rect.viewportW - Math.max(0, rect.x))),
      height: Math.min(Math.ceil(rect.height), Math.floor(rect.viewportH - Math.max(0, rect.y)))
    };
    const bytes = await chatExportTab.screenshot({ clip });
    await fs.writeFile(file, Buffer.from(bytes));
    saved.push({ alt: rect.alt, src: rect.src, localPath: file });
  }

  for (const message of chatExportMessages.values()) {
    for (const ref of message.imageRefs || []) {
      const local = saved.find(x => (x.alt && x.alt === ref.alt) || (x.src && x.src === ref.src));
      if (local) ref.localPath = local.localPath;
    }
  }
  return saved;
};
```

## Save Final JSON

```js
const fs = await import("node:fs/promises");
const outDir = "Z:/path/to/work/chat_export";
await fs.mkdir(`${outDir}/images`, { recursive: true });
await captureChatExportImages(`${outDir}/images`);
const payload = {
  sourceUrl: await chatExportTab.url(),
  title: await chatExportTab.title(),
  exportedAt: new Date().toISOString(),
  messageCount: chatExportMessages.size,
  sequenceCount: chatExportSequences.length,
  messages: Array.from(chatExportMessages.values()),
  sequences: chatExportSequences
};
await fs.writeFile(`${outDir}/chat_export_final.json`, JSON.stringify(payload, null, 2), "utf8");
nodeRepl.write(JSON.stringify({ path: `${outDir}/chat_export_final.json`, messages: payload.messageCount }, null, 2));
```
