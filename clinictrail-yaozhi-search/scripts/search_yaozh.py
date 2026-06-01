#!/usr/bin/env python3
"""
搜索 news.yaozh.com 并提取文章内容。
搜索方式：Tavily Search API（site:news.yaozh.com）
抓取方式：直接 HTTP 请求解析正文

Usage:
    python3 search_yaozh.py --term BMS-986278 --api-key tvly-xxx
    python3 search_yaozh.py --term "利雷西帕" --max 5
    python3 search_yaozh.py --term BMS-986278 --json
    
API Key: 从环境变量 TAVILY_API_KEY 读取，或通过 --api-key 传入
         也可通过 openclaw config get skills.entries.tavily.apiKey 获取
"""

import argparse
import gzip
import io
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

# 一组真实 Chrome/Edge UA，随机选取以降低指纹一致性
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
]


def _browser_headers(referer: str = "https://news.yaozh.com/", ua: str = None) -> dict:
    """构造接近真实浏览器导航请求的头部。"""
    ua = ua or random.choice(USER_AGENTS)
    is_edge = "Edg/" in ua
    brand = '"Microsoft Edge"' if is_edge else '"Google Chrome"'
    ver = re.search(r"Chrome/(\d+)", ua)
    ver = ver.group(1) if ver else "130"
    platform = '"macOS"' if "Mac OS X" in ua else '"Windows"'
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
        "Sec-Fetch-Site": "same-origin" if "yaozh.com" in referer else "none",
        "Sec-Fetch-User": "?1",
        "Referer": referer,
    }


def _decode_response(resp) -> str:
    """读取并按 Content-Encoding 解压响应体。"""
    raw = resp.read()
    enc = (resp.headers.get("Content-Encoding") or "").lower()
    if enc == "gzip":
        raw = gzip.decompress(raw)
    elif enc == "deflate":
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    # 大多数页面是 utf-8；保留 errors=replace 兜底
    return raw.decode("utf-8", errors="replace")


def _build_opener() -> urllib.request.OpenerDirector:
    """带 cookie jar 的 opener，在站内导航时携带服务端 set-cookie。"""
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.HTTPRedirectHandler(),
    )


def get_tavily_key(explicit_key: str = None) -> str:
    """获取 Tavily API key，优先级：参数 > 环境变量 > openclaw config"""
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


def tavily_search(term: str, api_key: str, max_results: int = 10) -> list:
    """用 Tavily 搜索 site:news.yaozh.com，返回 [{title, url, content, published_date}]

    打开 include_raw_content：让 Tavily 直接返回正文，避免后续大量二次抓取触发 403。
    """
    query = f"site:news.yaozh.com {term}"
    payload = json.dumps({
        "query": query,
        "search_depth": "advanced",
        "max_results": max_results,
        "include_domains": ["news.yaozh.com"],
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
        if "news.yaozh.com/archive/" in url:
            results.append({
                "title": r.get("title", ""),
                "url": url,
                "date": r.get("published_date", ""),
                "snippet": r.get("content", ""),
                "raw_content": r.get("raw_content") or "",
                "content": None,
            })
    return results


def tavily_extract(url: str, api_key: str) -> str:
    """调用 Tavily Extract API 用其代理池代抓正文，绕开本地 IP 被封。

    返回纯文本正文；失败/空内容时返回空串（由调用方继续兜底）。
    """
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


def http_get(url: str, opener: urllib.request.OpenerDirector, referer: str,
             ua: str, retries: int = 3) -> str:
    """带重试/退避的 HTTP GET。403/429/5xx 时换 UA 重试。"""
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
                ua = random.choice(USER_AGENTS)  # 换指纹
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


def _warmup(opener: urllib.request.OpenerDirector, ua: str) -> None:
    """先访问首页拿一次 cookie，更接近真实浏览器行为，提高文章页通过率。"""
    try:
        http_get("https://news.yaozh.com/", opener, referer="https://www.google.com/",
                 ua=ua, retries=2)
    except Exception:
        pass


def extract_date_from_text(text: str) -> str:
    """从 HTML 或纯文本里提取首个发表日期，归一为 YYYY-MM-DD。"""
    if not text:
        return ""
    m = re.search(r'add_date["\']?\s*:\s*["\'](\d{4}-\d{2}-\d{2})', text)
    if m:
        return m.group(1)
    m = re.search(r'class="line_time"[^>]*>.*?(\d{4})\D+(\d{1,2})\D+(\d{1,2})', text, re.S)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r'(?:发表时间|发布时间|时间)\s*[:：]\s*(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})', text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def fetch_article(url: str, opener: urllib.request.OpenerDirector, ua: str) -> dict:
    """HTTP 抓取单篇药智新闻文章，返回 {title, url, date, content}"""
    html = http_get(url, opener, referer="https://news.yaozh.com/", ua=ua, retries=3)

    # Title — 优先 .l_title，再回退到 <title>，避免拿到首个 logo h1
    title = ""
    m = re.search(r'<h1[^>]*class="[^"]*l_title[^"]*"[^>]*>(.*?)</h1>', html, re.S)
    if m:
        title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
    if not title:
        m = re.search(r'<title>(.*?)</title>', html, re.S)
        if m:
            title = re.sub(r'_药智新闻\s*$', '', m.group(1).strip())

    date = extract_date_from_text(html)

    # Clean HTML
    clean = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.S)
    clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.S)

    # Extract body between h1 and footer markers
    body_match = re.search(r'<h1[^>]*>.*?</h1>(.*?)(?:责任编辑|声明：本文系|友情链接)', clean, re.S)
    body_html = body_match.group(1) if body_match else clean

    # Extract paragraphs
    paragraphs = re.findall(r'<(?:p|li)[^>]*>(.*?)</(?:p|li)>', body_html, re.S)
    text_parts = []
    for p in paragraphs:
        text = re.sub(r'<[^>]+>', '', p).strip()
        text = re.sub(r'\s+', ' ', text)
        if len(text) > 10:
            text_parts.append(text)

    content = "\n\n".join(text_parts)
    return {"title": title, "url": url, "date": date, "content": content}


def main():
    parser = argparse.ArgumentParser(description="搜索 news.yaozh.com 药物/靶点相关新闻")
    parser.add_argument("--term", required=True, help="搜索词（药物名、化合物编号、靶点等）")
    parser.add_argument("--max", type=int, default=5, help="最多获取文章数（默认5）")
    parser.add_argument("--api-key", help="Tavily API key（可选，默认从环境变量或 openclaw config 读取）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    api_key = get_tavily_key(args.api_key)
    if not api_key:
        print("错误：未找到 Tavily API key。", file=sys.stderr)
        print("请设置环境变量 TAVILY_API_KEY 或通过 --api-key 传入。", file=sys.stderr)
        sys.exit(1)

    # Step 1: Tavily 搜索
    print(f"搜索药智新闻 (Tavily): site:news.yaozh.com {args.term}", file=sys.stderr)
    try:
        results = tavily_search(args.term, api_key, args.max)
    except Exception as e:
        print(f"Tavily 搜索失败: {e}", file=sys.stderr)
        sys.exit(1)

    if not results:
        print(f"未找到 news.yaozh.com 上关于 '{args.term}' 的文章。", file=sys.stderr)
        if args.json:
            print(json.dumps([], ensure_ascii=False))
        return

    print(f"找到 {len(results)} 篇文章，正在抓取全文...", file=sys.stderr)

    # Step 2: 抓取每篇文章全文 —— 共享 cookie/UA 模拟同一会话
    opener = _build_opener()
    ua = random.choice(USER_AGENTS)
    _warmup(opener, ua)

    articles = []
    for i, r in enumerate(results):
        # 四层兜底：直接抓 → Tavily search 自带 raw_content → Tavily Extract API → snippet
        title = r.get("title", "")
        date = r.get("date", "")
        content = ""
        source = ""

        try:
            article = fetch_article(r["url"], opener, ua)
            if article["title"]:
                title = article["title"]
            if article["date"]:
                date = article["date"]
            if article["content"]:
                content = article["content"]
                source = "direct"
        except Exception as e:
            print(f"  直接抓取失败: {r['url']} ({e})", file=sys.stderr)

        if not content and r.get("raw_content"):
            content = r["raw_content"]
            source = "tavily-search-raw"

        if not content:
            print(f"  使用 Tavily Extract 兜底: {r['url']}", file=sys.stderr)
            ex = tavily_extract(r["url"], api_key)
            if ex:
                content = ex
                source = "tavily-extract"

        if not content and r.get("snippet"):
            content = r["snippet"]
            source = "tavily-snippet"

        # 直连失败走兜底时 date 仍为空 —— 从已拿到的正文里再抽一次
        if not date:
            date = extract_date_from_text(content)

        articles.append({
            "title": title,
            "url": r["url"],
            "date": date,
            "content": content,
            "source": source,
        })
        if i < len(results) - 1:
            time.sleep(0.8 + random.random() * 0.7)

    if args.json:
        print(json.dumps(articles, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'=' * 70}")
        print(f"药智新闻 | 搜索词: '{args.term}' | 共 {len(articles)} 篇")
        print(f"{'=' * 70}")
        for i, a in enumerate(articles, 1):
            print(f"\n[{i}] {a['title']}")
            print(f"  发表时间: {a['date']}")
            print(f"  链接: {a['url']}")
            if a.get("source"):
                print(f"  内容来源: {a['source']}")
            if a.get("content"):
                print(f"  正文预览:")
                import textwrap
                preview = a["content"][:600]
                for line in preview.split("\n"):
                    if line.strip():
                        for wrapped in textwrap.wrap(line, 76):
                            print(f"    {wrapped}")
                if len(a["content"]) > 600:
                    print(f"    ... (共约 {len(a['content'])} 字)")


if __name__ == "__main__":
    main()

