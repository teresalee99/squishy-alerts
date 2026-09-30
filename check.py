"""Checks Buyee search pages for new listings and emails you.

Env vars: GMAIL_USER, GMAIL_APP_PASSWORD, EMAIL_TO (defaults to GMAIL_USER),
          DRY_RUN=true  -> print what it finds (plus diagnostics), send/save nothing.
"""
import json
import os
import re
import smtplib
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# {q} = URL-encoded Japanese query. "urls" are tried in order; the next one is
# used only if the previous returned zero items. "pattern" matches item links.
# These URL/link patterns are best guesses and have NOT been tested live.
# Run a dry run and read the log; fix here if a marketplace shows 0 items.
MARKETPLACES = {
    "JDirectItems Auction": {
        "urls": [
            "https://buyee.jp/item/search/query/{q}?sort=start&order=d",
            "https://buyee.jp/jdirectitems/auction/search?query={q}&sort=start&order=d",
        ],
        "pattern": r"/item/jdirectitems/auction/[\w-]+",
    },
    "JDirectItems Fleamarket": {
        "urls": [
            "https://buyee.jp/jdirectitems/fleamarket/search?keyword={q}&sort=created_time&order=desc",
            "https://buyee.jp/jdirectitems/fleamarket/search?query={q}",
        ],
        "pattern": r"/(?:item/jdirectitems/fleamarket|jdirectitems/fleamarket/item)/[\w-]+",
    },
    "Mercari": {
        "urls": ["https://buyee.jp/mercari/search?keyword={q}&sort=created_time&order=desc"],
        "pattern": r"/mercari/item/[\w-]+",
    },
    "Rakuma": {
        "urls": ["https://buyee.jp/rakuma/search?keyword={q}&sort=created_at&order=desc"],
        "pattern": r"/rakuma/item/[\w-]+",
    },
    "PayPay Flea Market": {
        "urls": ["https://buyee.jp/paypayfleamarket/search?keyword={q}&sort=openTime&order=desc"],
        "pattern": r"/paypayfleamarket/item/[\w-]+",
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ja,en;q=0.8",
}
STATE_FILE = Path("seen.json")
WORKERS = 5            # parallel requests (keep low to avoid being blocked)
WARN_AFTER_RUNS = 6    # warn if a marketplace returns nothing this many runs in a row
DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"


def load_searches():
    out = []
    for line in Path("searches.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        query, _, label = line.partition("#")
        out.append((query.strip(), label.strip() or query.strip()))
    return out


def fetch(url):
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.text
            print(f"  HTTP {r.status_code} for {url}")
        except requests.RequestException as e:
            print(f"  error: {e}")
        time.sleep(2)
    return None


def parse_items(html, pattern, base="https://buyee.jp"):
    soup = BeautifulSoup(html, "html.parser")
    rx = re.compile(pattern)
    items = {}
    for a in soup.find_all("a", href=True):
        m = rx.search(a["href"])
        if not m:
            continue
        path = m.group(0)
        if path in items and items[path]["title"]:
            continue
        box = a.find_parent(["li", "div"]) or a
        text = box.get_text(" ", strip=True)
        img = a.find("img") or box.find("img")
        title = a.get_text(" ", strip=True) or (img.get("alt", "") if img else "")
        price = re.search(r"[\d,]+\s*円", text)
        items[path] = {
            "title": (title or text)[:100],
            "price": price.group(0) if price else "",
            "url": base + path,
        }
    return items


def diagnostics(html):
    """Sample of item-ish links on a page, to help fix the patterns."""
    soup = BeautifulSoup(html, "html.parser")
    hrefs = [a["href"] for a in soup.find_all("a", href=True) if "item" in a["href"]]
    return hrefs[:8]


def run_task(task):
    query, label, market = task
    cfg = MARKETPLACES[market]
    q = urllib.parse.quote(query)
    last_html = None
    for tpl in cfg["urls"]:
        html = fetch(tpl.format(q=q))
        time.sleep(0.5)
        if not html:
            continue
        last_html = html
        items = parse_items(html, cfg["pattern"])
        if items:
            return task, items, None
    return task, {}, last_html


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"seen": [], "fails": {}, "seeded": False}


def send_email(subject, body):
    user = os.environ["GMAIL_USER"]
    pw = os.environ["GMAIL_APP_PASSWORD"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = os.environ.get("EMAIL_TO") or user
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.send_message(msg)


def main():
    state = load_state()
    seen = set(state["seen"])
    searches = load_searches()
    tasks = [(q, label, m) for q, label in searches for m in MARKETPLACES]
    print(f"{len(searches)} searches x {len(MARKETPLACES)} marketplaces = {len(tasks)} tasks")

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(run_task, tasks))

    new_by_label = {}
    market_counts = {m: 0 for m in MARKETPLACES}
    shown_diag = set()
    for (query, label, market), items, empty_html in results:
        market_counts[market] += len(items)
        if DRY_RUN:
            print(f"{market} | {query}: {len(items)} items")
            if not items and empty_html and market not in shown_diag:
                shown_diag.add(market)
                print(f"  [diag] no items matched for {market}. item-ish links on page: "
                      f"{diagnostics(empty_html)}")
        for path, it in items.items():
            if path in seen:
                continue
            seen.add(path)
            new_by_label.setdefault(label, []).append((market, it))

    warnings = []
    for market, n in market_counts.items():
        state["fails"][market] = 0 if n else state["fails"].get(market, 0) + 1
        if state["fails"][market] == WARN_AFTER_RUNS:
            warnings.append(market)

    total_new = sum(len(v) for v in new_by_label.values())
    print(f"Totals per marketplace: {market_counts}")
    print(f"New this run: {total_new}. Already seeded: {state['seeded']}")

    if DRY_RUN:
        print("DRY RUN - nothing sent or saved.")
        return

    if state["seeded"] and total_new:
        lines = []
        for label, entries in new_by_label.items():
            lines.append(f"== {label} ==")
            for market, it in entries:
                lines.append(f"[{market}] {it['title']} {it['price']}\n{it['url']}")
            lines.append("")
        send_email(f"Squishy alert: {total_new} new listing(s)", "\n".join(lines))

    if warnings:
        send_email(
            "Squishy alerts: scraper may be broken",
            "No results for several runs in a row from: " + ", ".join(warnings)
            + "\nBuyee may have changed its pages or be blocking GitHub. "
              "Check the Actions log.",
        )

    state["seen"] = list(seen)[-50000:]
    state["seeded"] = True  # first real run records everything silently
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
