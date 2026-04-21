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
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.parse

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://news.yaozh.com/",
}


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
    """用 Tavily 搜索 site:news.yaozh.com，返回 [{title, url, content, published_date}]"""
    query = f"site:news.yaozh.com {term}"
    payload = json.dumps({
        "query": query,
        "search_depth": "advanced",
        "max_results": max_results,
        "include_domains": ["news.yaozh.com"],
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
                "content": None,
            })
    return results


def fetch_article(url: str) -> dict:
    """HTTP 抓取单篇药智新闻文章，返回 {title, url, date, content}"""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    # Title
    title_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
    title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else ""

    # Date - yaozh format: "2025 04/22" in page text
    date_match = re.search(r'(\d{4})\s+(\d{2}/\d{2})', html)
    if date_match:
        year = date_match.group(1)
        md = date_match.group(2).replace("/", "-")
        date = f"{year}-{md}"
    else:
        dm2 = re.search(r'(\d{4}-\d{2}-\d{2})', html)
        date = dm2.group(1) if dm2 else ""

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

    # Step 2: 抓取每篇文章全文
    articles = []
    for i, r in enumerate(results):
        try:
            article = fetch_article(r["url"])
            # Fallback to Tavily snippet if content is empty
            if not article["content"] and r.get("snippet"):
                article["content"] = r["snippet"]
            if not article["title"] and r.get("title"):
                article["title"] = r["title"]
            if not article["date"] and r.get("date"):
                article["date"] = r["date"]
            articles.append(article)
            if i < len(results) - 1:
                time.sleep(0.5)
        except Exception as e:
            print(f"  跳过 {r['url']}: {e}", file=sys.stderr)
            # Still include with Tavily data
            articles.append({
                "title": r.get("title", ""),
                "url": r["url"],
                "date": r.get("date", ""),
                "content": r.get("snippet", ""),
            })

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
