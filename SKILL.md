---
name: chatgpt-full-pdf-export
description: Export long ChatGPT conversations and other virtualized chat pages to complete PDF archives. Use when the user says ChatGPT printing is incomplete, asks to convert a ChatGPT conversation URL/page to PDF, wants a full long-chat archive, or needs a PDF from a lazy-loaded/virtual-scrolling web chat where normal browser print only captures the visible DOM.
---

# ChatGPT Full PDF Export

## Overview

Create a complete, auditable PDF archive from a long ChatGPT conversation whose page uses internal scrolling, virtualization, lazy loading, collapsed messages, file cards, or signed image attachments. Avoid relying on browser Print for the original page; instead collect materialized message nodes across scroll positions, deduplicate by message id, rebuild clean offline HTML, print that HTML to PDF, and render-check the result.

## Workflow

1. Use the Chrome skill for logged-in ChatGPT pages. Claim an existing user tab when possible; otherwise open the provided URL in Chrome.
2. Create a working directory such as `work/chatgpt_export_<slug>/` and an output PDF path under `outputs/`.
3. Read `references/chrome_collection.md` and run its Node REPL snippets in short batches:
   - bootstrap/claim the tab;
   - define `collectChatExportVisible`;
   - force top and make top-to-bottom scroll passes;
   - repeat passes until the message count is stable;
   - screenshot remote ChatGPT attachment images when needed;
   - save `chat_export_final.json`.
4. Run `scripts/build_chat_archive.py` to build offline HTML and PDF:

```bash
python <skill>/scripts/build_chat_archive.py \
  --input work/chatgpt_export_<slug>/chat_export_final.json \
  --html work/chatgpt_export_<slug>/chat_full.html \
  --pdf outputs/chatgpt_full.pdf \
  --image-dir work/chatgpt_export_<slug>/images \
  --check-dir work/chatgpt_export_<slug>/rendered \
  --qa-json work/chatgpt_export_<slug>/qa_summary.json
```

5. Inspect rendered QA PNGs from the first page, middle page, last page, and image pages. Do not deliver until the PDF has nonzero pages, extractable first/last text, and no obvious clipping, overlap, blank pages, or mojibake.
6. Finalize Chrome tabs after browser work. Keep the original user tab only if the user needs it.

## Collection Rules

- Use message ids (`data-message-id`) as the primary deduplication key.
- Prefer the longest observed HTML/text for each message id.
- Record scroll-derived page positions (`absTopNow`/`absTop`) for ordering, then sanity-check the first and last messages visually.
- Use several short scroll cells rather than one long browser call; virtualized ChatGPT pages can time out while still moving.
- If the message count increases during a pass, perform another pass. Stop only after a complete top-to-bottom/tail pass no longer increases the count.
- Treat `document.body.scrollHeight` as unreliable on ChatGPT. Find the internal scroll container with large `scrollHeight`, or use `dom_cua.scroll`.
- Do not inspect cookies, local storage, browser profiles, passwords, or session stores.
- Do not try to bypass browser or extension URL policies. If a backend API or extension page is blocked, continue with DOM collection.

## Images And Attachments

- Data URI images embedded in message HTML can usually remain in the rebuilt HTML.
- Remote ChatGPT file images often use signed URLs that may fail outside the logged-in browser. Bring them into view and screenshot their bounding boxes into `images/`, then write `localPath` into the relevant `imageRefs`.
- File cards that only expose names should remain as readable cards/text unless their preview image is visible and important.
- Tell the user if the PDF preserves visible file cards/previews but does not expand attached file contents.

## Output Expectations

- Deliver the final PDF from `outputs/`.
- Mention the captured message count, page count, and whether image pages were detected.
- If QA could not render pages because PyMuPDF/Poppler is unavailable, say so and include the fallback checks performed.

## Scripts

- `scripts/build_chat_archive.py`: turns collected JSON into offline HTML, prints PDF through Chrome/Edge headless, and optionally renders QA pages with PyMuPDF.

## Reference

- `references/chrome_collection.md`: browser-side collection snippets for Chrome + Node REPL.
