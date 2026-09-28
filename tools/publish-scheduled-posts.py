"""
Publishes staged blog posts on allyonoofficial.com on their scheduled date.

Staged pages live in tools/scheduled/<slug>/index.html (robots noindex, excluded
in robots.txt) with {{DATE_ISO}} / {{DATE_HUMAN}} placeholders. The schedule is
tools/scheduled_posts.json. On or after a post's published_date this script:

  - renders the page into blog/<slug>/ with the real date and index, follow
  - leaves out links to staged posts that are not live yet (restored later)
  - adds it to sitemap.xml, the blog listing and its ItemList, and llms.txt
  - commits, pushes to GitHub, and submits the new URLs to IndexNow

Run daily from cron on the server; running it twice in a day does nothing new.

    cd /www/wwwroot/allyonoofficial.com && python3 tools/publish-scheduled-posts.py
"""
import datetime
import json
import os
import re
import subprocess
import urllib.request

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SITE = "https://allyonoofficial.com"
TODAY = datetime.date.today().isoformat()
MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
INDEXNOW_KEY = "9e4c1d7b3a6f48e2b5c0d8a1f7e3b264"
STAGED_ROBOTS = '<meta name="robots" content="noindex, nofollow" /><!--STAGED-->'
LIVE_ROBOTS = '<meta name="robots" content="index, follow" />'
SCHEDULE = json.load(open(os.path.join(ROOT, "tools", "scheduled_posts.json"), encoding="utf-8"))


def path(*p):
    return os.path.join(ROOT, *p)


def read(p):
    return open(p, encoding="utf-8").read()


def write(p, t):
    open(p, "w", encoding="utf-8").write(t)


def human(iso):
    y, m, d = iso.split("-")
    return f"{int(d)} {MONTHS[int(m) - 1]} {y}"


def render(post, live):
    t = read(path("tools", "scheduled", post["slug"], "index.html"))
    t = t.replace("{{DATE_ISO}}", post["published_date"]).replace("{{DATE_HUMAN}}", human(post["published_date"]))
    t = t.replace(STAGED_ROBOTS, LIVE_ROBOTS)
    for p in SCHEDULE:
        if p["slug"] not in live:
            t = re.sub(r'<a href="/blog/' + re.escape(p["slug"]) + r'/">(.*?)</a>', r"\1", t)
    out = path("blog", post["slug"], "index.html")
    if os.path.isfile(out) and read(out) == t:
        return False
    os.makedirs(os.path.dirname(out), exist_ok=True)
    write(out, t)
    return True


def in_sitemap(slug):
    return f"{SITE}/blog/{slug}/" in read(path("sitemap.xml"))


def add_sitemap(post):
    s = read(path("sitemap.xml"))
    s = s.replace("</urlset>", f"  <url><loc>{SITE}/blog/{post['slug']}/</loc>\n    <lastmod>{TODAY}</lastmod></url>\n</urlset>")
    write(path("sitemap.xml"), s)


def add_listing(post):
    b = read(path("blog", "index.html"))
    card = (f'\n      <a class="blog-card" href="/blog/{post["slug"]}/" aria-label="Read: {post["title"]}">\n'
            f'        <img class="blog-card-img" src="/blog-img/{post["slug"]}.webp" alt="{post["image_alt"]}" width="1200" height="675" '
            f'loading="lazy" decoding="async" onerror="this.style.display=\'none\'">\n'
            f'        <div class="blog-card-body">\n          <span class="card-category">{post["category"]}</span>\n'
            f'          <h2>{post["title"]}</h2>\n          <p>{post["excerpt"]}</p>\n        </div>\n      </a>')
    b = b.replace('<div class="blog-card-list">', '<div class="blog-card-list">' + card, 1)

    def add_item(node):
        # The blog ItemList sits inside CollectionPage.mainEntity; find it at any depth.
        if isinstance(node, dict):
            if node.get("@type") == "ItemList" and "itemListElement" in node:
                items = [{"@type": "ListItem", "url": f"{SITE}/blog/{post['slug']}/", "name": post["title"]}] + node["itemListElement"]
                for i, it in enumerate(items, 1):
                    it["position"] = i
                node["itemListElement"] = items
                return True
            return any(add_item(v) for v in node.values())
        if isinstance(node, list):
            return any(add_item(v) for v in node)
        return False

    def itemlist(m):
        d = json.loads(m.group(1))
        if not add_item(d):
            return m.group(0)
        return '<script type="application/ld+json">\n' + json.dumps(d, indent=2, ensure_ascii=False) + "\n  </script>"
    b = re.sub(r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', itemlist, b, flags=re.S)
    write(path("blog", "index.html"), b)


def add_llms(post):
    t = read(path("llms.txt"))
    line = f"- [{post['title']}]({SITE}/blog/{post['slug']}/)\n"
    if line in t:
        return
    head = "## New Guides\n\n"
    if head not in t:
        t = t.replace("## Legal and Safety", head + "\n## Legal and Safety", 1)
    write(path("llms.txt"), t.replace(head, head + line, 1))


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
    live = {p["slug"] for p in SCHEDULE if p["published_date"] <= TODAY}
    published, refreshed = [], []
    for post in SCHEDULE:
        if post["slug"] not in live:
            continue
        changed = render(post, live)
        if not in_sitemap(post["slug"]):
            add_sitemap(post)
            add_listing(post)
            add_llms(post)
            published.append(post["slug"])
        elif changed:
            refreshed.append(post["slug"])
    if not published and not refreshed:
        print(f"{TODAY}: nothing due to publish.")
        return
    for s in published:
        print(f"Published blog/{s}/")
    for s in refreshed:
        print(f"Refreshed blog/{s}/ (links to newly published posts restored)")
    subprocess.run(["git", "add", "-A", "blog", "sitemap.xml", "llms.txt"], cwd=ROOT, check=True)
    subprocess.run(["git", "-c", "user.name=AllYonoOfficial server", "-c", "user.email=server@allyonoofficial.com",
                    "commit", "-m", "Publish scheduled post: " + ", ".join(published or refreshed)], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=ROOT, check=True)
    if published:
        indexnow([f"{SITE}/blog/{s}/" for s in published] + [f"{SITE}/blog/"])


if __name__ == "__main__":
    main()
