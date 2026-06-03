from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import quote


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def role_label(role: str) -> str:
    labels = {"user": "User", "assistant": "ChatGPT", "tool": "Tool", "system": "System"}
    return labels.get(role or "", role or "Message")


def order_top(message: dict) -> float:
    for key in ("order", "absTopNow", "absTop", "captureIndex"):
        value = message.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def find_chrome(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    candidates: list[str] = []
    if sys.platform.startswith("win"):
        envs = ["PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"]
        for env in envs:
            root = os.environ.get(env)
            if root:
                candidates.append(str(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"))
                candidates.append(str(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
    elif sys.platform == "darwin":
        candidates += [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    else:
        candidates += ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"]

    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return str(path)
        if "/" not in candidate and "\\" not in candidate:
            try:
                result = subprocess.run(
                    [candidate, "--version"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                if result.returncode == 0:
                    return candidate
            except OSError:
                pass
    raise FileNotFoundError("Could not find Chrome/Edge. Pass --chrome explicitly.")


def file_url(path: Path) -> str:
    return path.resolve().as_uri()


def rel_or_uri(path: Path, html_dir: Path) -> str:
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(html_dir.resolve())
        return quote(rel.as_posix())
    except ValueError:
        return resolved.as_uri()


def search_image(image_dir: Path | None, alt: str) -> Path | None:
    if not image_dir or not alt or not image_dir.exists():
        return None
    direct = image_dir / alt
    if direct.is_file():
        return direct
    matches = list(image_dir.rglob(f"*{alt}"))
    return matches[0] if matches else None


def image_local_path(ref: dict, html_dir: Path, image_dir: Path | None) -> str | None:
    local = ref.get("localPath") or ref.get("path")
    alt = ref.get("alt") or ""
    if local:
        path = Path(local)
        if not path.is_absolute():
            path = html_dir / path
        if path.exists():
            return rel_or_uri(path, html_dir)
    found = search_image(image_dir, alt)
    if found:
        return rel_or_uri(found, html_dir)
    src = ref.get("src") or ""
    if src.startswith("data:image/"):
        return src
    return None


def strip_risky_html(html: str) -> str:
    html = re.sub(r"<script\b.*?</script>", "", html or "", flags=re.I | re.S)
    html = re.sub(r"<style\b.*?</style>", "", html, flags=re.I | re.S)
    html = re.sub(r"\son[a-zA-Z]+=\"[^\"]*\"", "", html)
    html = re.sub(r"\sdata-[a-zA-Z0-9_-]+=\"[^\"]*\"", "", html)
    html = html.replace('contenteditable="false"', "")
    html = re.sub(r"<button\b([^>]*)>\s*(?:<svg\b.*?</svg>\s*)+</button>", "", html, flags=re.S)
    return html


def replace_known_images(html: str, message: dict, html_dir: Path, image_dir: Path | None) -> tuple[str, list[str]]:
    used: list[str] = []
    for ref in message.get("imageRefs") or []:
        local = image_local_path(ref, html_dir, image_dir)
        if not local:
            continue
        alt = ref.get("alt") or ""
        src = ref.get("src") or ""
        if src and src in html:
            html = html.replace(src, local)
            used.append(local)
            continue
        if alt:
            pattern = r'(<img\b(?=[^>]*\balt="' + re.escape(alt) + r'")[^>]*\bsrc=")[^"]*(")'
            new_html, count = re.subn(pattern, r"\1" + local + r"\2", html)
            if count:
                html = new_html
                used.append(local)
    return html, used


def attachment_figures(message: dict, html: str, html_dir: Path, image_dir: Path | None, used: list[str]) -> str:
    blocks: list[str] = []
    seen = set(used)
    for ref in message.get("imageRefs") or []:
        local = image_local_path(ref, html_dir, image_dir)
        if not local or local in seen or local in html:
            continue
        seen.add(local)
        alt = ref.get("alt") or "attachment image"
        blocks.append(
            "<figure class='attachment-image'>"
            f"<img src='{escape(local)}' alt='{escape(alt)}'>"
            f"<figcaption>{escape(alt)}</figcaption>"
            "</figure>"
        )
    return "\n".join(blocks)


def css() -> str:
    return """
@page { size: A4; margin: 15mm 13mm; }
* { box-sizing: border-box; }
body {
  margin: 0;
  color: #20262d;
  background: #fff;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Segoe UI", Arial, sans-serif;
  font-size: 10.5pt;
  line-height: 1.55;
}
.cover { border-bottom: 2px solid #263238; padding-bottom: 14px; margin-bottom: 18px; }
.cover h1 { margin: 0 0 8px; font-size: 21pt; line-height: 1.2; color: #263238; }
.meta-line { color: #5f6b76; font-size: 9pt; overflow-wrap: anywhere; }
.message { border: 1px solid #d9e0e6; border-radius: 8px; padding: 9px 11px; margin: 0 0 11px; background: #fff; }
.message.user { border-color: #cddfd4; background: #f6fbf7; }
.message.assistant { border-color: #d8dee8; background: #fbfcfe; }
.msg-meta { color: #506070; font-size: 8.5pt; font-weight: 700; margin-bottom: 5px; break-after: avoid; }
.msg-content { overflow-wrap: anywhere; }
p { margin: 0 0 0.62em; }
ul, ol { margin: 0.45em 0 0.75em 1.25em; padding: 0; }
li { margin: 0.2em 0; }
h1, h2, h3, h4 { color: #263238; line-height: 1.25; margin: 0.9em 0 0.4em; break-after: avoid; }
h1 { font-size: 16pt; } h2 { font-size: 13pt; } h3 { font-size: 11.5pt; }
blockquote { margin: 0.7em 0; padding: 0.2em 0 0.2em 0.8em; border-left: 3px solid #8da3b8; color: #394653; }
table { width: 100%; border-collapse: collapse; margin: 0.7em 0; font-size: 8.6pt; }
th, td { border: 1px solid #d2d9e0; padding: 4px 5px; vertical-align: top; }
th { background: #eef3f6; font-weight: 700; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f3f5f7; border: 1px solid #dce2e8; border-radius: 6px; padding: 8px; font-size: 8.5pt; line-height: 1.4; }
code { font-family: "Cascadia Mono", "Consolas", "Courier New", monospace; font-size: 0.92em; }
p code, li code { background: #eef2f5; border-radius: 4px; padding: 0.05em 0.25em; }
img { max-width: 100%; height: auto !important; object-fit: contain; border-radius: 4px; }
figure.attachment-image { margin: 0.6em 0; padding: 6px; border: 1px solid #dce2e8; border-radius: 6px; background: #fff; }
figure.attachment-image figcaption { color: #64717d; font-size: 8pt; margin-top: 4px; }
svg { display: none !important; }
button { all: unset; color: #215f8a; font-weight: 600; }
button:empty, .sr-only { display: none !important; }
a { color: #215f8a; text-decoration: none; }
hr { border: 0; border-top: 1px solid #dce2e8; margin: 1em 0; }
"""


def build_html(data: dict, html_path: Path, image_dir: Path | None) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    messages = sorted(data.get("messages", []), key=order_top)
    title = data.get("title") or "ChatGPT full PDF export"
    source = data.get("sourceUrl") or ""
    exported_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    parts: list[str] = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{escape(title)}</title>",
        "<style>",
        css(),
        "</style></head><body>",
        "<section class='cover'>",
        f"<h1>{escape(title)}</h1>",
        f"<div class='meta-line'>Source: {escape(source)}</div>",
        f"<div class='meta-line'>Exported: {escape(exported_at)} - Messages captured: {len(messages)}</div>",
        "</section>",
    ]

    html_dir = html_path.parent
    for index, message in enumerate(messages, 1):
        role = message.get("role") or "message"
        model = message.get("model") or ""
        meta = f"{index:03d} - {role_label(role)}"
        if model:
            meta += f" - {model}"
        fragment = strip_risky_html(message.get("html") or "")
        fragment, used = replace_known_images(fragment, message, html_dir, image_dir)
        if not fragment.strip():
            text = escape(message.get("text") or "").replace("\n", "<br>")
            fragment = f"<p>{text}</p>"
        extra = attachment_figures(message, fragment, html_dir, image_dir, used)
        if extra:
            fragment += "\n" + extra
        parts += [
            f"<article class='message {escape(role)}'>",
            f"<div class='msg-meta'>{escape(meta)}</div>",
            f"<div class='msg-content'>{fragment}</div>",
            "</article>",
        ]

    parts.append("</body></html>")
    html_path.write_text("\n".join(parts), encoding="utf-8")


def print_pdf(html_path: Path, pdf_path: Path, chrome: str | None) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    if pdf_path.exists():
        pdf_path.unlink()
    chrome_bin = find_chrome(chrome)
    command = [
        chrome_bin,
        "--headless=new",
        "--disable-gpu",
        "--allow-file-access-from-files",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path.resolve()}",
        file_url(html_path),
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if not pdf_path.exists():
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"Chrome did not create PDF: {pdf_path}")
    if result.returncode != 0:
        print("Chrome returned a non-zero code but created the PDF; continuing.", file=sys.stderr)


def qa_pdf(pdf_path: Path, check_dir: Path | None) -> dict:
    summary = {"pdf": str(pdf_path), "size": pdf_path.stat().st_size}
    try:
        import fitz  # type: ignore
    except Exception as exc:
        summary["qaSkipped"] = f"PyMuPDF unavailable: {exc}"
        return summary

    doc = fitz.open(pdf_path)
    image_pages = [i + 1 for i, page in enumerate(doc) if page.get_images(full=True)]
    summary["pages"] = doc.page_count
    summary["imagePages"] = image_pages
    summary["firstPageTextStart"] = (doc.load_page(0).get_text("text") or "")[:300]
    summary["lastPageTextStart"] = (doc.load_page(doc.page_count - 1).get_text("text") or "")[:300]
    if check_dir:
        check_dir.mkdir(parents=True, exist_ok=True)
        render_indices = {0, max(0, doc.page_count // 2), max(0, doc.page_count - 1)}
        render_indices.update(page - 1 for page in image_pages[:4])
        rendered: list[str] = []
        for index in sorted(render_indices):
            pix = doc.load_page(index).get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
            out = check_dir / f"page_{index + 1:03d}.png"
            pix.save(out)
            rendered.append(str(out))
        summary["renderedChecks"] = rendered
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a clean HTML/PDF archive from collected ChatGPT messages.")
    parser.add_argument("--input", required=True, type=Path, help="Collected chat JSON.")
    parser.add_argument("--html", required=True, type=Path, help="Output offline HTML.")
    parser.add_argument("--pdf", type=Path, help="Optional output PDF.")
    parser.add_argument("--image-dir", type=Path, help="Directory containing screenshot-captured attachment images.")
    parser.add_argument("--chrome", help="Path to Chrome/Edge executable.")
    parser.add_argument("--check-dir", type=Path, help="Optional directory for rendered QA PNG pages.")
    parser.add_argument("--qa-json", type=Path, help="Optional QA summary JSON path.")
    args = parser.parse_args()

    data = read_json(args.input)
    build_html(data, args.html, args.image_dir)
    print(f"HTML: {args.html.resolve()}")

    if args.pdf:
        print_pdf(args.html, args.pdf, args.chrome)
        print(f"PDF: {args.pdf.resolve()}")
        summary = qa_pdf(args.pdf, args.check_dir)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if args.qa_json:
            args.qa_json.parent.mkdir(parents=True, exist_ok=True)
            args.qa_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
