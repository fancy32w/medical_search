#!/usr/bin/env python3
"""
搜索药渡 (pharmacodia) 或 bydrug (pharmcube) 上的药物/靶点相关新闻。

两个站点走两条不同的路径：
  - pharmacodia 走 dapi.pharmacodia.com 官方公开 API（无需 Tavily / 无需登录）
  - bydrug 走 Tavily Search + 直连正文抓取（同 yaozh 套路）

Usage:
    python3 search_pharma_news.py --site pharmacodia --term BMS-986278
    python3 search_pharma_news.py --site bydrug --term 利雷西帕 --max 5
    python3 search_pharma_news.py --site pharmacodia --term LPA1 --json

Tavily Key（仅 bydrug 需要）：从 --api-key / TAVILY_API_KEY / openclaw config 取。
"""

import argparse
import gzip
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar
import zlib


USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
]


# 每个站的搜索/抓取规则
SITES = {
    "pharmacodia": {
        "label": "药渡",
        "method": "api",
        # 药渡 SPA 背后的官方 API，前端 https://data.pharmacodia.com/pharmnews 就是调它
        "api_url": "https://dapi.pharmacodia.com/api/pharmnews/big_box/search",
        "api_origin": "https://data.pharmacodia.com",
    },
    "bydrug": {
        "label": "bydrug",
        "method": "tavily",
        "search_query": "site:bydrug.pharmcube.com",
        "include_domains": ["bydrug.pharmcube.com"],
        "url_filter": "bydrug.pharmcube.com/news/detail/",
        "referer": "https://bydrug.pharmcube.com/",
        # bydrug 正文落在 div.news-content 内，止于 div.news-tag
        "body_pattern": re.compile(
            r'class="[^"]*news-content[^"]*"[^>]*>(.*?)(?=<div[^>]*class="[^"]*news-tag)',
            re.S,
        ),
    },
}


def _browser_headers(referer: str, ua: str = None) -> dict:
    ua = ua or random.choice(USER_AGENTS)
    is_edge = "Edg/" in ua
    brand = '"Microsoft Edge"' if is_edge else '"Google Chrome"'
    ver = re.search(r"Chrome/(\d+)", ua)
    ver = ver.group(1) if ver else "130"
    platform = '"macOS"' if "Mac OS X" in ua else '"Windows"'
    ref_host = urllib.parse.urlparse(referer).hostname or ""
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Ch-Ua": f'"Chromium";v="{ver}", {brand};v="{ver}", "Not?A_Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": platform,
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin" if ref_host else "none",
        "Sec-Fetch-User": "?1",
        "Referer": referer,
    }


def _decode_response(resp) -> str:
    raw = resp.read()
    enc = (resp.headers.get("Content-Encoding") or "").lower()
    if enc == "gzip":
        raw = gzip.decompress(raw)
    elif enc == "deflate":
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw.decode("utf-8", errors="replace")


def _build_opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.HTTPRedirectHandler(),
    )


def get_tavily_key(explicit_key: str = None) -> str:
    if explicit_key:
        return explicit_key
    key = os.environ.get("TAVILY_API_KEY", "")
    if key:
        return key
    try:
        result = subprocess.run(
            ["openclaw", "config", "get", "skills.entries.tavily.apiKey"],
            capture_output=True, text=True, timeout=5
        )
        key = result.stdout.strip().strip('"')
        if key and key != "__OPENCLAW_REDACTED__":
            return key
    except Exception:
        pass
    return ""


# ---------- pharmacodia: 官方 API ----------

def pharmacodia_api_search(term: str, site_cfg: dict, max_results: int = 10) -> list:
    """调用药渡 pharmnews 官方搜索 API，返回标准化记录。"""
    payload = json.dumps({
        "qs": term,
        "searchType": "QS",
        "page": 1,
        "size": max_results,
        "sortBy": "",
        "sortOrder": "",
    }).encode("utf-8")
    req = urllib.request.Request(
        site_cfg["api_url"],
        data=payload,
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "Origin": site_cfg["api_origin"],
            "Referer": site_cfg["api_origin"] + "/",
            "User-Agent": random.choice(USER_AGENTS),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)

    if data.get("code") != "0":
        raise RuntimeError(f"pharmacodia API error: {data.get('msg')}")

    records = data.get("data", {}).get("hits", {}).get("records", []) or []
    out = []
    for r in records:
        drugs = [d.get("strName") for d in (r.get("pnDrugList") or []) if d.get("strName")]
        keywords = [k.get("strName") for k in (r.get("pnKeyWordsList") or []) if k.get("strName")]
        out.append({
            "title": r.get("pnTitle") or "",
            "url": r.get("siteUrl") or "",
            "date": r.get("publishDate") or "",
            "content": r.get("brief") or "",
            "source": "pharmacodia-api",
            "site": "pharmacodia",
            "site_name": r.get("siteName") or "",
            "category": r.get("categoryName") or [],
            "drugs": drugs,
            "keywords": keywords,
        })
    return out


# ---------- bydrug: Tavily + 直连 ----------

def tavily_search(term: str, site_cfg: dict, api_key: str, max_results: int = 10) -> list:
    query = f"{site_cfg['search_query']} {term}"
    payload = json.dumps({
        "query": query,
        "search_depth": "advanced",
        "max_results": max_results,
        "include_domains": site_cfg["include_domains"],
        "include_raw_content": True,
        "topic": "general",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)

    results = []
    for r in data.get("results", []):
        url = r.get("url", "")
        if site_cfg["url_filter"] not in url:
            continue
        results.append({
            "title": r.get("title", ""),
            "url": url,
            "date": r.get("published_date", ""),
            "snippet": r.get("content", ""),
            "raw_content": r.get("raw_content") or "",
        })
    return results


def tavily_extract(url: str, api_key: str) -> str:
    payload = json.dumps({
        "urls": [url],
        "extract_depth": "advanced",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.tavily.com/extract",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except Exception:
        return ""
    for item in data.get("results", []):
        if item.get("url") == url or item.get("raw_content"):
            return item.get("raw_content") or ""
    return ""


def http_get(url: str, opener, referer: str, ua: str, retries: int = 3) -> str:
    last_err = None
    for attempt in range(retries):
        headers = _browser_headers(referer=referer, ua=ua)
        req = urllib.request.Request(url, headers=headers)
        try:
            with opener.open(req, timeout=20) as resp:
                return _decode_response(resp)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (403, 429, 500, 502, 503, 504) and attempt < retries - 1:
                ua = random.choice(USER_AGENTS)
                time.sleep(1.5 * (attempt + 1) + random.random())
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError("http_get exhausted retries")


def _warmup(opener, referer: str, ua: str) -> None:
    try:
        http_get(referer, opener, referer="https://www.google.com/", ua=ua, retries=2)
    except Exception:
        pass


def extract_date_from_text(text: str) -> str:
    if not text:
        return ""
    m = re.search(r'(?:发表时间|发布时间|时间|date)\s*[:：]?\s*(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})', text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def _strip_tags(html_chunk: str) -> str:
    clean = re.sub(r'<script[^>]*>.*?</script>', '', html_chunk, flags=re.S)
    clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.S)
    text = re.sub(r'<[^>]+>', ' ', clean)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_article(html: str, site_cfg: dict) -> dict:
    title = ""
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
    if m:
        t = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if t and len(t) < 200:
            title = t
    if not title:
        m = re.search(r'<title>(.*?)</title>', html, re.S)
        if m:
            title = m.group(1).strip()
            title = re.sub(r'\s*[-_|—]\s*(药渡|pharmacodia|bydrug|药融云|医药魔方).*$', '', title, flags=re.I)

    date = extract_date_from_text(html)

    body_html = None
    pat = site_cfg.get("body_pattern")
    if pat:
        bm = pat.search(html)
        if bm:
            body_html = bm.group(1)
    if body_html is None:
        body_html = html

    content = _strip_tags(body_html)
    return {"title": title, "date": date, "content": content}


def fetch_article(url: str, opener, site_cfg: dict, ua: str) -> dict:
    html = http_get(url, opener, referer=site_cfg["referer"], ua=ua, retries=3)
    parsed = parse_article(html, site_cfg)
    parsed["url"] = url
    return parsed


def run_tavily_site(args, site_cfg) -> list:
    """bydrug 路径：Tavily search → 直连正文 → tavily-extract → snippet。"""
    api_key = get_tavily_key(args.api_key)
    if not api_key:
        print("错误：未找到 Tavily API key（bydrug 路径必需）。", file=sys.stderr)
        print("请设置 TAVILY_API_KEY 或通过 --api-key 传入。", file=sys.stderr)
        sys.exit(1)

    print(f"[{site_cfg['label']}] 搜索: {site_cfg['search_query']} {args.term}", file=sys.stderr)
    try:
        results = tavily_search(args.term, site_cfg, api_key, args.max)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("[TAVILY][AUTH-FAIL] 401 — Tavily key 无效/过期", file=sys.stderr)
        else:
            print(f"[TAVILY][ERR] {e.code} {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[TAVILY][ERR] {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[TAVILY][OK] auth=OK results={len(results)}", file=sys.stderr)

    if not results:
        print(f"[TAVILY][EMPTY] '{args.term}' 在 {site_cfg['label']} 无收录", file=sys.stderr)
        return []

    opener = _build_opener()
    ua = random.choice(USER_AGENTS)
    _warmup(opener, site_cfg["referer"], ua)

    articles = []
    for i, r in enumerate(results):
        title = r.get("title", "")
        date = r.get("date", "")
        content = ""
        source = ""

        try:
            article = fetch_article(r["url"], opener, site_cfg, ua)
            if article["title"]:
                title = article["title"]
            if article["date"]:
                date = article["date"]
            if article["content"]:
                content = article["content"]
                source = "direct"
        except urllib.error.HTTPError as e:
            print(f"[BYDRUG-DIRECT][BLOCKED] {e.code} url={r['url']}", file=sys.stderr)
        except Exception as e:
            print(f"[BYDRUG-DIRECT][ERR] {e} url={r['url']}", file=sys.stderr)

        if not content and r.get("raw_content"):
            content = r["raw_content"]
            source = "tavily-search-raw"
            print(f"[FALLBACK][OK] tavily-search-raw url={r['url']}", file=sys.stderr)

        if not content:
            ex = tavily_extract(r["url"], api_key)
            if ex:
                content = ex
                source = "tavily-extract"
                print(f"[FALLBACK][OK] tavily-extract url={r['url']}", file=sys.stderr)

        if not content and r.get("snippet"):
            content = r["snippet"]
            source = "tavily-snippet"
            print(f"[FALLBACK][OK] tavily-snippet url={r['url']}", file=sys.stderr)

        if not content:
            print(f"[FALLBACK][EXHAUSTED] url={r['url']}", file=sys.stderr)

        if not date:
            date = extract_date_from_text(content)

        articles.append({
            "title": title,
            "url": r["url"],
            "date": date,
            "content": content,
            "source": source,
            "site": "bydrug",
        })
        if i < len(results) - 1:
            time.sleep(0.8 + random.random() * 0.7)

    return articles


def run_pharmacodia(args, site_cfg) -> list:
    """药渡路径：直接调官方 pharmnews API，无需 Tavily。"""
    print(f"[{site_cfg['label']}] API 搜索: qs='{args.term}' size={args.max}", file=sys.stderr)
    try:
        articles = pharmacodia_api_search(args.term, site_cfg, args.max)
    except urllib.error.HTTPError as e:
        print(f"[PHARMACODIA-API][ERR] {e.code} {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[PHARMACODIA-API][ERR] {e}", file=sys.stderr)
        sys.exit(1)
    print(f"[PHARMACODIA-API][OK] results={len(articles)}", file=sys.stderr)
    if not articles:
        print(f"[PHARMACODIA-API][EMPTY] '{args.term}' 无命中", file=sys.stderr)
    return articles


def main():
    parser = argparse.ArgumentParser(description="搜索药渡/bydrug 药物相关新闻")
    parser.add_argument("--site", required=True, choices=sorted(SITES.keys()),
                        help="目标站点：pharmacodia 或 bydrug")
    parser.add_argument("--term", required=True, help="搜索词（药物名、化合物编号、靶点等）")
    parser.add_argument("--max", type=int, default=5, help="最多文章数（默认5）")
    parser.add_argument("--api-key", help="Tavily API key（仅 bydrug 路径需要）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    site_cfg = SITES[args.site]

    if site_cfg["method"] == "api":
        articles = run_pharmacodia(args, site_cfg)
    else:
        articles = run_tavily_site(args, site_cfg)

    if args.json:
        print(json.dumps(articles, ensure_ascii=False, indent=2))
        return

    print(f"\n{'=' * 70}")
    print(f"{site_cfg['label']} | 搜索词: '{args.term}' | 共 {len(articles)} 篇")
    print(f"{'=' * 70}")
    for i, a in enumerate(articles, 1):
        print(f"\n[{i}] {a['title']}")
        print(f"  发表时间: {a.get('date', '')}")
        print(f"  链接: {a['url']}")
        if a.get("source"):
            print(f"  内容来源: {a['source']}")
        if a.get("site_name"):
            print(f"  来源站点: {a['site_name']}")
        if a.get("category"):
            cats = a["category"] if isinstance(a["category"], list) else [a["category"]]
            print(f"  栏目: {' / '.join(cats)}")
        if a.get("drugs"):
            print(f"  涉及药物: {', '.join(a['drugs'][:8])}{'...' if len(a['drugs']) > 8 else ''}")
        if a.get("keywords"):
            print(f"  关键词: {', '.join(a['keywords'][:8])}{'...' if len(a['keywords']) > 8 else ''}")
        if a.get("content"):
            import textwrap
            preview = a["content"][:600]
            print(f"  正文预览:")
            for line in preview.split("\n"):
                if line.strip():
                    for wrapped in textwrap.wrap(line, 76):
                        print(f"    {wrapped}")
            if len(a["content"]) > 600:
                print(f"    ... (共约 {len(a['content'])} 字)")


if __name__ == "__main__":
    main()
