"""The scrolling news ticker (the same module as the tickets and venues systems): rich-text announcements in
Arabic and English, an optional RSS feed, speed, pulse, text shadow and the logo between items. Stored
as JSON in app_settings['ticker_config']; shown on every page by templates/_ticker.html, which reads
/api/ticker."""
import json
import re
import time
import xml.etree.ElementTree as ET
import requests

from db import get_setting, set_setting

DEFAULT_CONFIG = {
    'enabled': False,
    'html': '',           # rich HTML from the Quill editor (paragraphs, links, inline styles) — Arabic
    'htmlEn': '',          # same, English version
    'speedSeconds': 25,   # seconds for one full loop across the screen — lower = faster
    'pulse': False,       # blinking/pulsing show-hide effect
    'pulseSeconds': 1.6,  # seconds per blink cycle — lower = faster blinking
    'textShadow': 'light', # 'none' | 'light' | 'strong' — legibility shadow behind the ticker text
    'rssColor': '#ffffff', # text color for RSS-sourced segments specifically
    'rssBold': True,       # bold weight for RSS-sourced segments
    'rssFontSize': 16,     # px font size for RSS-sourced segments
    'logoBetween': False, # insert the org logo between each segment
    'bgColor': '#1B3358', # background colour of the bar
    'bgOpacity': 0,       # 0-100 % — 0 keeps the bar fully transparent (the original look)
    'textColor': '#ffffff', # colour of the text that has no colour of its own from the editor
    'rssUrl': '',         # optional RSS feed to pull extra items from
}

_rss_cache = {}  # url -> (fetched_at, items)
_RSS_CACHE_SECONDS = 300


_BAD_TAGS = re.compile(r'<\s*(script|style|iframe|object|embed|form|input|button|textarea|select|meta|link|base)\b'
                       r'[^>]*>(?:.*?<\s*/\s*\1\s*>)?', re.I | re.S)
_ON_ATTR = re.compile(r'\s+on[a-z]+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', re.I)
_JS_URL = re.compile(r'(href|src)\s*=\s*(["\']?)\s*(javascript|vbscript|data):', re.I)


def clean_html(html):
    """The editor's formatting (bold, colours, sizes, links) stays; scripts, event handlers and
    javascript: links are removed, since the ticker shows on every public page."""
    html = _BAD_TAGS.sub('', html or '')
    html = _ON_ATTR.sub('', html)
    return _JS_URL.sub(r'\1=\2#blocked:', html)[:20000]


def get_ticker_config():
    raw = get_setting('ticker_config')
    if not raw:
        return dict(DEFAULT_CONFIG)
    try:
        cfg = json.loads(raw)
    except Exception:
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update({k: v for k, v in cfg.items() if k in DEFAULT_CONFIG})
    return merged


def set_ticker_config(cfg):
    for k in ('html', 'htmlEn'):
        if k in cfg:
            cfg[k] = clean_html(cfg[k])
    merged = get_ticker_config()
    merged.update({k: v for k, v in cfg.items() if k in DEFAULT_CONFIG})
    set_setting('ticker_config', json.dumps(merged, ensure_ascii=False))
    return merged


def fetch_rss_items(url, limit=12):
    """Fetch and lightly parse an RSS 2.0 (or Atom-ish) feed into
    [{title, link}, ...]. Cached for a few minutes so every page view on
    the site doesn't re-fetch the feed. Fails soft (returns []) on any
    network/parse error — a broken feed should never take the ticker (or
    the page) down."""
    if not url:
        return []

    now = time.time()
    cached = _rss_cache.get(url)
    if cached and (now - cached[0]) < _RSS_CACHE_SECONDS:
        return cached[1]

    items = []
    try:
        r = requests.get(url, timeout=6, headers={'User-Agent': 'Mozilla/5.0 (AttendanceTicker/1.0)'})
        if r.status_code == 200:
            root = ET.fromstring(r.content)
            # RSS 2.0: rss/channel/item ; Atom: feed/entry
            for item in root.findall('.//item')[:limit]:
                title_el = item.find('title')
                link_el = item.find('link')
                title = (title_el.text or '').strip() if title_el is not None else ''
                link = (link_el.text or '').strip() if link_el is not None else ''
                if title:
                    items.append({'title': title, 'link': link})
            if not items:
                ns = {'atom': 'http://www.w3.org/2005/Atom'}
                for entry in root.findall('.//atom:entry', ns)[:limit]:
                    title_el = entry.find('atom:title', ns)
                    link_el = entry.find('atom:link', ns)
                    title = (title_el.text or '').strip() if title_el is not None else ''
                    link = (link_el.get('href') if link_el is not None else '') or ''
                    if title:
                        items.append({'title': title, 'link': link})
    except Exception as e:
        print(f"[ticker] RSS fetch/parse failed for {url}: {e}", flush=True)
        items = []

    _rss_cache[url] = (now, items)
    return items


def build_ticker_payload():
    """What the frontend needs to render the ticker: the config plus any
    resolved RSS items."""
    cfg = get_ticker_config()
    payload = dict(cfg)
    if cfg.get('enabled') and cfg.get('rssUrl'):
        payload['rssItems'] = [{'title': it['title'],
                                'link': it['link'] if re.match(r'^https?://', it.get('link') or '') else ''}
                               for it in fetch_rss_items(cfg['rssUrl'])]
    else:
        payload['rssItems'] = []
    return payload
