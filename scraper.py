#!/usr/bin/env python3
"""
Three-stage crawler for an internal site (default: MarakiReports2012).

  Stage 1  map        Opens a visible browser, waits for YOU to log in, then
                      crawls links and writes  output/link_map.json
  Stage 2  structure  Visits every page in the link map and adds detail
                      (forms, tables, headings, iframes...) ->
                      output/site_structure.json
  Stage 3  scrape     Visits pages that contain data tables and saves each
                      table as CSV -> output/tables/*.csv (+ index.json)

  python maraki_crawler.py map
  python maraki_crawler.py structure
  python maraki_crawler.py scrape
  python maraki_crawler.py all          # runs the three in sequence

Setup:
  pip install playwright
  playwright install chromium
"""
import argparse
import csv
import json
import re
import sys
import time
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urldefrag, urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

START_URL = "http://192.168.1.24/MarakiReports2012/index.php"
SCOPE_PREFIX = "/MarakiReports2012/"   # only crawl paths under this
OUT = Path("output")
STATE_FILE = OUT / "auth_state.json"   # saved cookies/session
LINK_MAP = OUT / "link_map.json"
STRUCTURE = OUT / "site_structure.json"
TABLE_DIR = OUT / "tables"

# Never click/visit links that look destructive.
SKIP_LINK_RE = re.compile(r"logout|log-out|signout|sign-out|delete|remove|drop|truncate", re.I)
# Files we record but do not navigate to.
FILE_EXT_RE = re.compile(r"\.(pdf|zip|rar|7z|png|jpe?g|gif|svg|ico|css|js|xlsx?|csv|docx?|pptx?|mp[34]|exe)$", re.I)

MAX_PAGES = 500
POLITE_DELAY = 0.3   # seconds between requests
NAV_TIMEOUT = 30_000


# ----------------------------------------------------------------- helpers
def norm(url: str) -> str:
    """Strip fragment; keep query string (it often selects the report)."""
    return urldefrag(url)[0]


def in_scope(url: str) -> bool:
    a, b = urlparse(url), urlparse(START_URL)
    return a.netloc == b.netloc and a.path.startswith(SCOPE_PREFIX)


def is_login_page(page) -> bool:
    try:
        return page.locator("input[type=password]").count() > 0
    except Exception:
        return False


def safe_goto(page, url) -> bool:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except PWTimeout:
            pass
        return True
    except Exception as e:  # download links, timeouts, etc.
        print(f"   ! could not load {url}: {str(e).splitlines()[0]}")
        return False


def slug(url: str) -> str:
    p = urlparse(url)
    s = (p.path.replace(SCOPE_PREFIX, "") + ("_" + p.query if p.query else "")) or "index"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")[:120]


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[saved] {path}")


def load_json(path: Path):
    if not path.exists():
        sys.exit(f"Missing {path}. Run the previous stage first.")
    return json.loads(path.read_text(encoding="utf-8"))


def wait_for_manual_login(page):
    print("\n=== LOGIN REQUIRED ===")
    print("Log in using the browser window, then come back here and press Enter.")
    input("Press Enter once you are logged in... ")
    time.sleep(1)
    if is_login_page(page):
        print("A password field is still visible - login may not have completed.")
        input("Press Enter to continue anyway (Ctrl+C to abort)... ")


def open_context(pw, headless: bool):
    browser = pw.chromium.launch(headless=headless)
    kwargs = {}
    if STATE_FILE.exists():
        kwargs["storage_state"] = str(STATE_FILE)
    ctx = browser.new_context(**kwargs)
    ctx.set_default_navigation_timeout(NAV_TIMEOUT)
    return browser, ctx


def ensure_session(ctx, page, headless):
    """For stages 2/3: confirm the saved session still works."""
    safe_goto(page, START_URL)
    if is_login_page(page):
        if headless:
            sys.exit("Session expired. Re-run with --headed (or run `map`) to log in again.")
        wait_for_manual_login(page)
        ctx.storage_state(path=str(STATE_FILE))


# ------------------------------------------------------------ extraction JS
LINKS_JS = """
() => Array.from(document.querySelectorAll('a[href], area[href]')).map(a => ({
    href: a.href,
    text: (a.innerText || a.title || a.getAttribute('alt') || '').trim().replace(/\\s+/g, ' ').slice(0, 120)
}))
"""

STRUCTURE_JS = """
() => {
  const txt = e => (e.innerText || '').trim().replace(/\\s+/g, ' ');
  const tables = Array.from(document.querySelectorAll('table')).map((t, i) => {
    const rows = Array.from(t.rows);
    const nested = !!t.querySelector('table');
    let headers = [];
    const th = t.querySelectorAll('thead th, thead td');
    if (th.length) headers = Array.from(th).map(txt);
    else if (rows.length && rows[0].querySelector('th')) headers = Array.from(rows[0].cells).map(txt);
    return {
      index: i, id: t.id || null, class: t.className || null,
      rows: rows.length,
      cols: rows.reduce((m, r) => Math.max(m, r.cells.length), 0),
      headers, nested_layout_table: nested,
      sample_row: rows.length > 1 ? Array.from(rows[1].cells).map(txt).slice(0, 12) : []
    };
  });
  const forms = Array.from(document.forms).map(f => ({
    id: f.id || null, name: f.name || null,
    action: f.action, method: (f.method || 'get').toLowerCase(),
    fields: Array.from(f.elements).filter(e => e.name || e.id).map(e => ({
      tag: e.tagName.toLowerCase(), type: e.type || null, name: e.name || e.id,
      options: e.tagName === 'SELECT'
        ? Array.from(e.options).slice(0, 50).map(o => ({value: o.value, label: o.text.trim()})) : undefined
    }))
  }));
  return {
    title: document.title,
    headings: Array.from(document.querySelectorAll('h1,h2,h3')).map(h => ({tag: h.tagName.toLowerCase(), text: txt(h)})).slice(0, 40),
    tables, forms,
    iframes: Array.from(document.querySelectorAll('iframe,frame')).map(f => f.src),
    buttons: Array.from(document.querySelectorAll('button, input[type=button], input[type=submit]'))
               .map(b => (b.innerText || b.value || '').trim()).filter(Boolean).slice(0, 40),
    has_pagination: !!document.querySelector('.pagination, .pager, a[href*="page="], a[href*="p="]'),
    text_length: document.body ? document.body.innerText.length : 0
  };
}
"""

TABLES_JS = """
() => Array.from(document.querySelectorAll('table')).map((t, i) => ({
    index: i,
    nested: !!t.querySelector('table'),
    rows: Array.from(t.rows).map(r =>
        Array.from(r.cells).map(c => (c.innerText || '').trim().replace(/\\s+/g, ' ')))
}))
"""


# -------------------------------------------------------------- Stage 1: map
def stage_map(args):
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)  # must be visible for login
        ctx = browser.new_context()
        ctx.set_default_navigation_timeout(NAV_TIMEOUT)
        page = ctx.new_page()

        safe_goto(page, START_URL)
        if is_login_page(page):
            wait_for_manual_login(page)
        else:
            print("No login form detected - continuing (already authenticated?).")
        ctx.storage_state(path=str(STATE_FILE))

        start = norm(page.url) if in_scope(page.url) else norm(START_URL)
        queue = deque([(start, 0, None)])
        seen = {start}
        link_map, external, files = {}, {}, {}

        while queue and len(link_map) < args.max_pages:
            url, depth, parent = queue.popleft()
            if args.max_depth is not None and depth > args.max_depth:
                continue
            print(f"[{len(link_map)+1}] depth={depth} {url}")
            if not safe_goto(page, url):
                link_map[url] = {"depth": depth, "found_on": parent, "error": "load_failed", "links": []}
                continue
            if is_login_page(page) and url != start:
                print("   ! redirected to login (session lost or protected page) - skipping")
                link_map[url] = {"depth": depth, "found_on": parent, "error": "login_redirect", "links": []}
                continue

            found = []
            for frame in page.frames:
                try:
                    found += frame.evaluate(LINKS_JS)
                except Exception:
                    pass

            out_links = []
            for l in found:
                href = l["href"]
                if not href.startswith(("http://", "https://")):
                    continue  # mailto:, javascript:, tel: ...
                href = norm(urljoin(page.url, href))
                if SKIP_LINK_RE.search(href) or SKIP_LINK_RE.search(l["text"] or ""):
                    continue
                if not in_scope(href):
                    external[href] = l["text"]
                    continue
                if FILE_EXT_RE.search(urlparse(href).path):
                    files[href] = l["text"]
                    continue
                out_links.append({"url": href, "text": l["text"]})
                if href not in seen:
                    seen.add(href)
                    queue.append((href, depth + 1, url))

            link_map[url] = {
                "title": page.title(),
                "depth": depth,
                "found_on": parent,
                "links": out_links,
            }
            time.sleep(POLITE_DELAY)

        save_json(LINK_MAP, {
            "start_url": START_URL,
            "pages": link_map,
            "external_links": external,
            "file_links": files,
            "unvisited_queue": [u for u, _, _ in queue],
        })
        print(f"\nMapped {len(link_map)} pages.")
        browser.close()


# --------------------------------------------------------- Stage 2: structure
def stage_structure(args):
    data = load_json(LINK_MAP)
    raw_pages = data.get("pages", {})
    pages = {}

    # Filter out links where text is "(new)"
    for url, info in raw_pages.items():
        # Check if the link text is "(new)"
        if info.get("text", "").strip() == "(new)":
            continue
        pages[url] = info

    # Resume support: keep what's already been done
    result = load_json(STRUCTURE)["pages"] if STRUCTURE.exists() and args.resume else {}

    with sync_playwright() as pw:
        browser, ctx = open_context(pw, headless=not args.headed)
        page = ctx.new_page()
        ensure_session(ctx, page, not args.headed)

        todo = [u for u, info in pages.items() if not info.get("error") and u not in result]
        for n, url in enumerate(todo, 1):
            print(f"[{n}/{len(todo)}] {url}")
            entry = dict(pages[url])  # start from the previous map -> "increasing detail"
            if not safe_goto(page, url):
                entry["structure_error"] = "load_failed"
            elif is_login_page(page):
                entry["structure_error"] = "login_redirect"
            else:
                try:
                    entry["structure"] = page.evaluate(STRUCTURE_JS)
                    entry["final_url"] = page.url
                except Exception as e:
                    entry["structure_error"] = str(e).splitlines()[0]
            result[url] = entry
            if n % 10 == 0:
                save_json(STRUCTURE, {"start_url": data["start_url"], "pages": result})
            time.sleep(POLITE_DELAY)

        save_json(STRUCTURE, {
            "start_url": data["start_url"],
            "pages": result,
            "external_links": data.get("external_links", {}),
            "file_links": data.get("file_links", {}),
        })
        with_tables = sum(1 for p in result.values() if p.get("structure", {}).get("tables"))
        print(f"\nStructured {len(result)} pages; {with_tables} contain tables.")
        browser.close()

# ------------------------------------------------------------ Stage 3: scrapedef stage_scrape(args):
    data = load_json(STRUCTURE)
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    index = []

    with sync_playwright() as pw:
        browser, ctx = open_context(pw, headless=not args.headed)
        page = ctx.new_page()
        ensure_session(ctx, page, not args.headed)

        targets = {
            u: p for u, p in data["pages"].items()
            if any(not t["nested_layout_table"] and t["rows"] >= args.min_rows
                   for t in p.get("structure", {}).get("tables", []))
        }
        print(f"{len(targets)} pages have data tables.")

        for n, (url, info) in enumerate(targets.items(), 1):
            print(f"[{n}/{len(targets)}] {url}")
            if not safe_goto(page, url) or is_login_page(page):
                print("   ! skipped")
                continue
            try:
                tables = page.evaluate(TABLES_JS)
            except Exception as e:
                print(f"   ! extract failed: {e}")
                continue
            
            page_tables = []
            for t in tables:
                if t["nested"] or len(t["rows"]) < args.min_rows:
                    continue
                page_tables.append({
                    "table_index": t["index"],
                    "rows": t["rows"]
                })
            
            if page_tables:
                fname = f"{slug(url)}.json"
                save_json(TABLE_DIR / fname, page_tables)
                index.append({
                    "page": url, 
                    "file": fname, 
                    "tables_extracted": len(page_tables)
                })
                print(f"   -> {fname} ({len(page_tables)} tables)")
                
            time.sleep(POLITE_DELAY)

        save_json(TABLE_DIR / "index.json", index)
        print(f"\nSaved {len(index)} pages to {TABLE_DIR}/")
        browser.close()
# ------------------------------------------------------------------------ CLI
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("map", help="stage 1: login + link map")
    m.add_argument("--max-pages", type=int, default=MAX_PAGES)
    m.add_argument("--max-depth", type=int, default=None)

    s = sub.add_parser("structure", help="stage 2: page structure")
    s.add_argument("--headed", action="store_true", help="show browser (needed if session expired)")
    s.add_argument("--resume", action="store_true", help="skip pages already in site_structure.json")

    t = sub.add_parser("scrape", help="stage 3: table scraper")
    t.add_argument("--headed", action="store_true")
    t.add_argument("--min-rows", type=int, default=2)

    a = sub.add_parser("all", help="run all three stages")
    a.add_argument("--max-pages", type=int, default=MAX_PAGES)
    a.add_argument("--max-depth", type=int, default=None)

    args = ap.parse_args()
    if args.cmd == "map":
        stage_map(args)
    elif args.cmd == "structure":
        stage_structure(args)
    elif args.cmd == "scrape":
        stage_scrape(args)
    else:
        stage_map(args)
        ns = argparse.Namespace(headed=False, resume=False, min_rows=2)
        stage_structure(ns)
        stage_scrape(ns)


if __name__ == "__main__":
    main()