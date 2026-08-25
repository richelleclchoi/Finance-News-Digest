"""
Daily business/economy news digest.
Sources: BBC RSS, NYT RSS, NewsData.io
Categorizes into UK / US / Investors (no overlap), no AI summarization.
Run: python digest.py
Requires: pip install feedparser requests
Requires env var: NEWSDATA_API_KEY
"""
import os
import html
import re
from html.parser import HTMLParser
import feedparser
import requests
from datetime import date

BBC_RSS = "http://feeds.bbci.co.uk/news/business/rss.xml"
NYT_RSS = "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"
NEWSDATA_URL = "https://newsdata.io/api/1/news"
NEWSDATA_API_KEY = os.environ.get("NEWSDATA_API_KEY")

INVESTOR_KEYWORDS = [
    "stocks", "shares", "markets", "fed", "interest rate",
    "earnings", "nasdaq", "dow jones", "s&p", "investor", "bond yield",
]

MAX_SNIPPET_LEN = 220


# ---------------------------------------------------------------------------
# HTML sanitizing helpers
# ---------------------------------------------------------------------------

class _TagStripper(HTMLParser):
    """Strips HTML tags, keeping only text content."""
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, d):
        self.parts.append(d)


def strip_tags(text):
    if not text:
        return ""
    stripper = _TagStripper()
    stripper.feed(text)
    return "".join(stripper.parts)


def clean_snippet(text, max_len=MAX_SNIPPET_LEN):
    """Strip tags, collapse whitespace, truncate to a clean word boundary."""
    text = strip_tags(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    truncated = text[:max_len].rsplit(" ", 1)[0]
    return truncated + "…"


def esc(text):
    return html.escape(text or "", quote=True)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_rss(url, region):
    articles = []
    feed = feedparser.parse(url)
    for entry in feed.entries:
        articles.append({
            "title": entry.get("title", "").strip(),
            "snippet": entry.get("summary", ""),
            "link": entry.get("link", ""),
            "source": feed.feed.get("title", url),
            "region": region,
        })
    return articles


def fetch_newsdata(country, region):
    if not NEWSDATA_API_KEY:
        print(f"[ERROR] NEWSDATA_API_KEY not set, skipping NewsData.io ({country})")
        return []
    params = {
        "apikey": NEWSDATA_API_KEY,
        "category": "business",
        "country": country,
        "language": "en",
    }
    try:
        resp = requests.get(NEWSDATA_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[ERROR] NewsData.io fetch failed for country={country}: {e}")
        return []

    articles = []
    for item in data.get("results", []):
        articles.append({
            "title": (item.get("title", "") or "").strip(),
            "snippet": item.get("description", "") or "",
            "link": item.get("link", "") or "",
            "source": item.get("source_id", "newsdata.io"),
            "region": region,
        })
    return articles


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def apply_investor_override(articles):
    for a in articles:
        text = (a["title"] + " " + a["snippet"]).lower()
        if any(kw in text for kw in INVESTOR_KEYWORDS):
            a["region"] = "Investors"
    return articles


def _normalize_title(title):
    """Lowercase, strip punctuation/whitespace for fuzzy duplicate matching."""
    t = title.lower()
    t = re.sub(r"[^a-z0-9\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def dedupe(articles):
    """De-dupe by link when present, falling back to normalized title+source
    when link is missing or blank. Also catches same-story-different-link
    cases via normalized title."""
    seen_links = set()
    seen_titles = set()
    result = []
    for a in articles:
        link = a["link"].strip()
        norm_title = _normalize_title(a["title"])

        if link:
            key = ("link", link)
        else:
            key = ("title_source", norm_title, a["source"])

        if key in seen_links or (norm_title and norm_title in seen_titles):
            continue

        seen_links.add(key)
        if norm_title:
            seen_titles.add(norm_title)
        result.append(a)
    return result


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

REGION_META = {
    "UK": {"emoji": "🇬🇧", "accent": "#1d4ed8"},
    "US": {"emoji": "🇺🇸", "accent": "#b91c1c"},
    "Investors": {"emoji": "📈", "accent": "#047857"},
}


def render_article(a):
    title = esc(a["title"])
    link = esc(a["link"])
    snippet = esc(clean_snippet(a["snippet"]))
    source = esc(a["source"])

    snippet_html = f'<p class="snippet">{snippet}</p>' if snippet else ""

    return f"""
        <li class="article">
          <a class="headline" href="{link}">{title}</a>
          {snippet_html}
          <span class="source">{source}</span>
        </li>"""


def render_section(region, items):
    meta = REGION_META.get(region, {"emoji": "🗞️", "accent": "#374151"})
    items_html = "\n".join(render_article(a) for a in items)
    return f"""
      <section class="region" style="--accent: {meta['accent']};">
        <div class="region-header">
          <span class="region-emoji">{meta['emoji']}</span>
          <h2>{esc(region)}</h2>
          <span class="count">{len(items)} stories</span>
        </div>
        <ul class="article-list">{items_html}
        </ul>
      </section>"""


def render_html(articles):
    regions = ["UK", "US", "Investors"]
    today = date.today().strftime("%A, %d %B %Y")
    total = len(articles)

    sections = "\n".join(
        render_section(region, [a for a in articles if a["region"] == region])
        for region in regions
        if any(a["region"] == region for a in articles)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Business Digest — {esc(date.today().isoformat())}</title>
<style>
  :root {{
    --bg: #f4f3ef;
    --card: #ffffff;
    --ink: #1a1a1a;
    --muted: #6b6b6b;
    --border: #e8e6df;
  }}

  * {{ box-sizing: border-box; }}

  body {{
    font-family: "Georgia", "Iowan Old Style", serif;
    background: var(--bg);
    color: var(--ink);
    margin: 0;
    padding: 40px 16px 80px;
  }}

  .wrap {{
    max-width: 680px;
    margin: 0 auto;
  }}

  .masthead {{
    text-align: center;
    padding-bottom: 24px;
    border-bottom: 3px double var(--ink);
    margin-bottom: 32px;
  }}

  .masthead .kicker {{
    font-family: "Helvetica Neue", Arial, sans-serif;
    letter-spacing: 3px;
    text-transform: uppercase;
    font-size: 11px;
    color: var(--muted);
    margin-bottom: 8px;
  }}

  .masthead h1 {{
    font-size: 34px;
    margin: 0 0 10px;
    letter-spacing: 0.5px;
  }}

  .masthead .date {{
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    color: var(--muted);
  }}

  .region {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 24px 28px;
    margin-bottom: 24px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
  }}

  .region-header {{
    display: flex;
    align-items: baseline;
    gap: 10px;
    border-bottom: 2px solid var(--accent);
    padding-bottom: 10px;
    margin-bottom: 6px;
  }}

  .region-emoji {{ font-size: 18px; }}

  .region-header h2 {{
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 15px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--accent);
    margin: 0;
    flex: 1;
  }}

  .region-header .count {{
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 11px;
    color: var(--muted);
  }}

  .article-list {{
    list-style: none;
    margin: 0;
    padding: 0;
  }}

  .article {{
    padding: 16px 0;
    border-bottom: 1px solid var(--border);
  }}

  .article:last-child {{ border-bottom: none; }}

  .headline {{
    display: block;
    font-size: 18px;
    line-height: 1.35;
    color: var(--ink);
    text-decoration: none;
    font-weight: 700;
  }}

  .headline:hover {{ text-decoration: underline; }}

  .snippet {{
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 14px;
    line-height: 1.5;
    color: #3a3a3a;
    margin: 8px 0 6px;
  }}

  .source {{
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--muted);
  }}

  .footer {{
    text-align: center;
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 11px;
    color: var(--muted);
    margin-top: 32px;
  }}
</style>
</head>
<body>
<div class="wrap">
  <div class="masthead">
    <div class="kicker">Business &amp; Economy</div>
    <h1>The Daily Digest</h1>
    <div class="date">{esc(today)} · {total} stories</div>
  </div>

  {sections}

  <div class="footer">Compiled automatically from BBC, NYT &amp; NewsData.io — no AI summarization.</div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    articles = []
    articles += fetch_rss(BBC_RSS, "UK")
    articles += fetch_rss(NYT_RSS, "US")
    articles += fetch_newsdata("gb", "UK")
    articles += fetch_newsdata("us", "US")

    articles = apply_investor_override(articles)
    articles = dedupe(articles)

    html_out = render_html(articles)

    out_dir = "docs"
    os.makedirs(out_dir, exist_ok=True)

    # Stable URL for GitHub Pages (this is what visitors see)
    index_path = os.path.join(out_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html_out)

    # Dated archive copy
    archive_dir = os.path.join(out_dir, "archive")
    os.makedirs(archive_dir, exist_ok=True)
    archive_path = os.path.join(archive_dir, f"digest_{date.today().isoformat()}.html")
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(html_out)

    print(f"Saved {index_path} and {archive_path} ({len(articles)} articles)")


if __name__ == "__main__":
    main()
