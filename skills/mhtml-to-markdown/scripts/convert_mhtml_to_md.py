#!/usr/bin/env python3

from __future__ import annotations

import argparse
import html as html_lib
import re
import subprocess
import sys
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlparse


START_TOKEN = '<div class="WB_editor_iframe_new" node-type="contentBody" style="opacity: 1; zoom: 1;">'
END_TOKEN = '<div style="color: #999;font-size: 14px;text-align: left;margin: 0 0 0 0;">'


def first_group(pattern: str, text: str, default: str = "") -> str:
    match = re.search(pattern, text, re.S)
    return html_lib.unescape(match.group(1).strip()) if match else default


def sanitize_base_name(source: Path) -> str:
    return source.stem.strip() or "converted"


def ensure_pandoc() -> None:
    try:
        subprocess.run(["pandoc", "--version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise SystemExit("pandoc is required but was not found in PATH")


def extract_html(message_path: Path) -> tuple[object, str]:
    msg = BytesParser(policy=policy.default).parse(message_path.open("rb"))
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return msg, part.get_payload(decode=True).decode("utf-8", errors="replace")
    raise SystemExit("No HTML part found in the MHTML file")


def extract_fragment(html_doc: str) -> str:
    start = html_doc.find(START_TOKEN)
    end = html_doc.find(END_TOKEN, start if start != -1 else 0)
    if start == -1:
        raise SystemExit("Could not isolate the main article body")
    if end == -1:
        fragment = html_doc[start + len(START_TOKEN):]
    else:
        fragment = html_doc[start + len(START_TOKEN):end]
    if fragment.endswith("</div>"):
        fragment = fragment[:-6]
    return fragment


def collect_parts(msg: object) -> dict[str, object]:
    url_to_part = {}
    for part in msg.walk():
        loc = part.get("Content-Location")
        if loc:
            url_to_part[loc] = part
    return url_to_part


def localize_images(fragment: str, cover_url: str, parts: dict[str, object], assets_dir: Path) -> tuple[str, str]:
    article_urls: list[str] = []
    for url in ([cover_url] if cover_url else []) + re.findall(r'<img[^>]+src="(https?://[^"]+)"', fragment):
        if url and url not in article_urls:
            article_urls.append(url)

    url_to_local: dict[str, str] = {}
    body_index = 1
    for url in article_urls:
        part = parts.get(url)
        if not part:
            continue
        parsed = urlparse(url)
        ext = Path(parsed.path).suffix or ".bin"
        if url == cover_url:
            name = f"cover{ext}"
        else:
            body_index += 1
            name = f"image-{body_index:02d}{ext}"
        dest = assets_dir / name
        dest.write_bytes(part.get_payload(decode=True))
        url_to_local[url] = f"./{assets_dir.name}/{name}"

    for url, rel in url_to_local.items():
        fragment = fragment.replace(url, rel)

    return fragment, url_to_local.get(cover_url, "")


def build_article_html(title: str, author: str, date: str, location: str, source_url: str, cover_rel: str, fragment: str) -> str:
    lines = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8" />',
        f"<title>{html_lib.escape(title)}</title>",
        "</head>",
        "<body>",
        f"<h1>{html_lib.escape(title)}</h1>",
        "<p>",
        f"<strong>作者：</strong>{html_lib.escape(author)}<br />",
        f"<strong>发布时间：</strong>{html_lib.escape(date)}<br />",
        f"<strong>发布地：</strong>{html_lib.escape(location)}<br />",
        f'<strong>来源：</strong><a href="{html_lib.escape(source_url)}">{html_lib.escape(source_url)}</a>',
        "</p>",
    ]
    if cover_rel:
        lines.append(f'<figure><img src="{cover_rel}" alt="题图" /><figcaption>题图</figcaption></figure>')
    lines.extend([fragment, "</body>", "</html>", ""])
    return "\n".join(lines)


def cleanup_markdown(markdown: str, source_url: str) -> str:
    markdown = markdown.replace("\\&nbsp;", " ")
    markdown = markdown.replace("&nbsp;", " ")
    markdown = markdown.replace("\u200b", "")
    markdown = markdown.replace("\\", "")
    markdown = markdown.replace("**来源：**[]()", f"**来源：**<{source_url}>")
    markdown = re.sub(r'^<span style="font-size:20px;">\*\*(.+?)\*\*</span>$', r"## \1", markdown, flags=re.M)
    markdown = re.sub(r'^<span style="font-size:16px;">\*\*\s*\*\*(.+?)</span>$', r"\1", markdown, flags=re.M)
    markdown = re.sub(r"(?s)<div class=\"DCI_v2 clearfix\">.*$", "", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown.strip() + "\n"


def convert(source: Path, output_dir: Path | None) -> tuple[Path, Path]:
    ensure_pandoc()
    msg, html_doc = extract_html(source)

    title = first_group(r'<div class="title" node-type="articleTitle">(.*?)</div>', html_doc, source.stem)
    author = first_group(r'<span class="author1[^"]*">.*?<em class="W_autocut">(.*?)</em>', html_doc)
    date = first_group(r'<span class="time"[^>]*>(.*?)</span>', html_doc)
    location = first_group(r'<div style="color: #999;font-size: 14px;text-align: left;margin: 0 0 0 0;">(.*?)</div>', html_doc)
    cover = first_group(r'<img node-type="articleHeaderPic"\s+src="(.*?)"', html_doc)
    source_url = first_group(r"Snapshot-Content-Location: (.*?)\r?\n", source.read_text("utf-8", errors="replace"))

    fragment = extract_fragment(html_doc)
    out_root = output_dir if output_dir else source.parent
    out_root.mkdir(parents=True, exist_ok=True)

    base = sanitize_base_name(source)
    assets_dir = out_root / f"{base}.assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    fragment, cover_rel = localize_images(fragment, cover, collect_parts(msg), assets_dir)
    article_html = build_article_html(title, author, date, location, source_url, cover_rel, fragment)

    html_path = out_root / f"{base}.article.html"
    md_path = out_root / f"{base}.md"
    html_path.write_text(article_html, encoding="utf-8")

    subprocess.run(["pandoc", str(html_path), "-f", "html", "-t", "gfm", "--wrap=none", "-o", str(md_path)], check=True)

    markdown = cleanup_markdown(md_path.read_text("utf-8"), source_url)
    md_path.write_text(markdown, encoding="utf-8")
    return md_path, assets_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert .mhtml/.mht article pages into Markdown with localized assets.")
    parser.add_argument("source", type=Path, help="Path to the source .mhtml or .mht file")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for the generated Markdown and assets")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.source.exists():
        raise SystemExit(f"Source file not found: {args.source}")
    if args.source.suffix.lower() not in {".mhtml", ".mht"}:
        raise SystemExit("Source file must have .mhtml or .mht extension")

    md_path, assets_dir = convert(args.source, args.output_dir)
    print(md_path)
    print(assets_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
