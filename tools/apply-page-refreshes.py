"""
Applies dated refreshes to existing app pages on allyonoofficial.com.

The refresh definitions are in tools/page_refreshes.json. On or after an entry's
"date" this script, for that page:

  - replaces the <title>, meta description, og:/twitter: title and description
  - appends extra meta keywords
  - inserts a "which app is it?" section just before the "Suggested Apps" block
  - adds FAQPage structured data
  - sets the page's <lastmod> in sitemap.xml and submits the URL to IndexNow

It is idempotent (each page carries a <!--REFRESH:id--> marker) and never touches
anything before its date. It does not commit or push; run it where the site is
served, then commit as you would any manual edit.

    cd /www/wwwroot/allyonoofficial.com
    python3 tools/apply-page-refreshes.py            # applies what is due today
    python3 tools/apply-page-refreshes.py --date 2026-10-25   # preview as of a date
    python3 tools/apply-page-refreshes.py --dry-run
"""
import argparse
import datetime
import html
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SITE = "https://allyonoofficial.com"
INDEXNOW_KEY = "9e4c1d7b3a6f48e2b5c0d8a1f7e3b264"
ANCHOR = '<h2 class="section-cursive">Suggested Apps</h2>'


def esc(s):
    return html.escape(s, quote=True)


def apply(entry, dry):
    page = os.path.join(ROOT, entry["page"], "index.html")
    if not os.path.isfile(page):
        return f"{entry['page']}: page not found"
    t = open(page, encoding="utf-8").read()
    marker = f"<!--REFRESH:{entry['id']}-->"
    if marker in t:
        return None
    if ANCHOR not in t:
        return f"{entry['page']}: anchor block not found, skipped"

    title, desc = esc(entry["title"]), esc(entry["description"])
    t = re.sub(r"<title>.*?</title>", lambda m: f"<title>{title}</title>", t, count=1, flags=re.S)
    t = re.sub(r'(<meta name="description" content=")[^"]*(")', lambda m: m.group(1) + desc + m.group(2), t, count=1)
    t = re.sub(r'(<meta property="og:title" content=")[^"]*(")', lambda m: m.group(1) + title + m.group(2), t, count=1)
    t = re.sub(r'(<meta property="og:description" content=")[^"]*(")', lambda m: m.group(1) + desc + m.group(2), t, count=1)
    t = re.sub(r'(<meta name="twitter:title" content=")[^"]*(")', lambda m: m.group(1) + title + m.group(2), t, count=1)
    t = re.sub(r'(<meta name="twitter:description" content=")[^"]*(")', lambda m: m.group(1) + desc + m.group(2), t, count=1)
    t = re.sub(r'(<meta name="keywords" content=")([^"]*)(")',
               lambda m: m.group(1) + m.group(2).rstrip(", ") + ", " + esc(entry["keywords_add"]) + m.group(3), t, count=1)

    faq = {"@context": "https://schema.org", "@type": "FAQPage",
           "mainEntity": [{"@type": "Question", "name": q,
                           "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in entry["faqs"]]}
    ld = '<script type="application/ld+json">\n' + json.dumps(faq, indent=2, ensure_ascii=False) + "\n  </script>\n"
    t = t.replace("</head>", ld + "</head>", 1)
    t = t.replace(ANCHOR, marker + "\n" + entry["html"] + "\n" + ANCHOR, 1)

    if not dry:
        open(page, "w", encoding="utf-8", newline="").write(t)
    return "applied"


def sitemap_lastmod(pages, today, dry):
    p = os.path.join(ROOT, "sitemap.xml")
    if not os.path.isfile(p) or dry:
        return
    s = open(p, encoding="utf-8").read()
    for page in pages:
        url = f"{SITE}/{page}/"
        s = re.sub(r"(<loc>" + re.escape(url) + r"</loc>\s*<lastmod>)[^<]*(</lastmod>)", r"\g<1>" + today + r"\g<2>", s)
    open(p, "w", encoding="utf-8").write(s)


def indexnow(urls):
    body = json.dumps({"host": "allyonoofficial.com", "key": INDEXNOW_KEY,
                       "keyLocation": f"{SITE}/{INDEXNOW_KEY}.txt", "urlList": urls}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"IndexNow: HTTP {r.status}")
    except Exception as e:
        print(f"IndexNow failed ({e})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    entries = json.load(open(os.path.join(ROOT, "tools", "page_refreshes.json"), encoding="utf-8"))
    done = []
    for e in entries:
        if e["date"] > a.date:
            continue
        r = apply(e, a.dry_run)
        if r == "applied":
            print(f"{e['page']}: refreshed ({e['id']})")
            done.append(e["page"])
        elif r:
            print(r)
    if done and not a.dry_run:
        sitemap_lastmod(done, a.date, a.dry_run)
        indexnow([f"{SITE}/{p}/" for p in done])
    if not done:
        print("Nothing to refresh.")


if __name__ == "__main__":
    sys.exit(main())
