#!/usr/bin/env python3
"""
Daily News & Hotspots Sync
抓取 19 个新闻与热点 RSS 源，生成 JSON。

用法:
    python daily_news_hotspots.py
"""

import json
import os
import re
import socket
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen

# 全局 socket 超时
socket.setdefaulttimeout(15)

CST = timezone(timedelta(hours=8))
OUTPUT_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "data" / "news"
STATE_FILE = OUTPUT_DIR / ".last_run"

# ── 源配置 ──────────────────────────────────────────────

SOURCES = [
    {"name": "爱范儿", "url": "https://www.ifanr.com/feed", "lang": "zh", "region": "domestic", "is_hotlist": False},
    {"name": "人人都是产品经理", "url": "https://www.woshipm.com/feed", "lang": "zh", "region": "domestic", "is_hotlist": False},
    {"name": "博客园", "url": "https://feed.cnblogs.com/news/rss", "lang": "zh", "region": "domestic", "is_hotlist": False},
    {"name": "少数派", "url": "https://sspai.com/feed", "lang": "zh", "region": "domestic", "is_hotlist": False},
    {"name": "开源中国", "url": "https://www.oschina.net/news/rss?show=industry", "lang": "zh", "region": "domestic", "is_hotlist": False},
    {"name": "雷锋网", "url": "https://www.leiphone.com/feed", "lang": "zh", "region": "domestic", "is_hotlist": False},
    {"name": "IT之家", "url": "https://www.ithome.com/rss/", "lang": "zh", "region": "domestic", "is_hotlist": False},
    {"name": "Solidot", "url": "https://www.solidot.org/index.rss", "lang": "zh", "region": "domestic", "is_hotlist": False},
    {"name": "HelloGitHub", "url": "https://www.hellogithub.com/rss", "lang": "zh", "region": "domestic", "is_hotlist": False},
    {"name": "极客公园", "url": "https://www.geekpark.net/rss", "lang": "zh", "region": "domestic", "is_hotlist": False},
    {"name": "MakeUseOf", "url": "https://feeds.feedburner.com/Makeuseof", "lang": "en", "region": "international", "is_hotlist": False},
    {"name": "TechCrunch", "url": "https://feeds.feedburner.com/TechCrunch/", "lang": "en", "region": "international", "is_hotlist": False},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index", "lang": "en", "region": "international", "is_hotlist": False},
    {"name": "Engadget", "url": "https://www.engadget.com/rss.xml", "lang": "en", "region": "international", "is_hotlist": False},
    {"name": "CNET", "url": "https://www.cnet.com/rss/news/", "lang": "en", "region": "international", "is_hotlist": False},
    {"name": "Hacker News Top", "url": "https://hnrss.org/frontpage?points=100", "lang": "en", "region": "international", "is_hotlist": False},
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml", "lang": "en", "region": "international", "is_hotlist": False},
    {"name": "GitHub Blog", "url": "https://github.blog/feed/", "lang": "en", "region": "international", "is_hotlist": False},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml", "lang": "en", "region": "international", "is_hotlist": False},
]


# ── 通用工具 ────────────────────────────────────────────

def now_cst() -> datetime:
    return datetime.now(CST)


def parse_pub_date(pub: str) -> datetime:
    """解析多种日期格式，返回 aware datetime。"""
    if not pub:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(pub.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    # 清理后尝试
    clean = re.sub(r'\+\d{4}$', '', pub.strip())
    try:
        dt = datetime.strptime(clean, "%a, %d %b %Y %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    return None


def fetch_rss(url: str, timeout: int = 15, retries: int = 2) -> str:
    for attempt in range(retries):
        try:
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; DailyNewsBot/1.0)",
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            })
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"    尝试 {attempt + 1}/{retries} 失败: {e}", flush=True)
            if attempt < retries - 1:
                import time
                time.sleep(2)
    return ""


def resolve_google_news_redirect(url: str, timeout: int = 10) -> str:
    """解析 Google News 重定向链接。"""
    if not url or "news.google.com" not in url:
        return url
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
        req.add_header("Accept", "*/*")
        # urlopen 默认会跟随重定向
        with urlopen(req, timeout=timeout) as resp:
            return resp.geturl()
    except Exception:
        return url


def parse_rss_items(xml_text: str, source_cfg: dict) -> list:
    """解析 RSS XML，返回条目列表。"""
    items = []
    if not xml_text:
        return items

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"    XML 解析失败: {e}", flush=True)
        return items

    channel = root.find("channel")
    if channel is not None:
        entries = channel.findall("item")
    else:
        entries = root.findall("entry")
        if not entries:
            entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    rank = 0
    for entry in entries:
        rank += 1

        # title
        title_elem = entry.find("title")
        title = unescape(title_elem.text.strip()) if title_elem is not None and title_elem.text else ""

        # link
        link = ""
        link_elem = entry.find("link")
        if link_elem is not None:
            link = link_elem.text.strip() if link_elem.text else link_elem.get("href", "")
        if not link:
            guid_elem = entry.find("guid")
            if guid_elem is not None and guid_elem.text:
                link = guid_elem.text.strip()

        # 解析 Google News 重定向
        if source_cfg.get("is_google_news") and link:
            link = resolve_google_news_redirect(link)

        # pubDate
        pub_date = ""
        for tag in ["pubDate", "published", "dc:date"]:
            elem = entry.find(tag)
            if elem is not None and elem.text:
                pub_date = elem.text.strip()
                break

        # summary
        summary = ""
        for tag in ["description", "summary", "content"]:
            elem = entry.find(tag)
            if elem is not None and elem.text:
                summary = unescape(elem.text.strip())
                break
        summary = re.sub(r'<[^>]+>', '', summary)

        item = {
            "title": title,
            "link": link,
            "source": source_cfg["name"],
            "published_at": pub_date,
            "summary": summary[:500] if summary else "",
            "category": "",
        }
        if source_cfg.get("is_hotlist"):
            item["rank"] = rank

        items.append(item)

    return items


def filter_by_time(items: list, cutoff: datetime) -> list:
    """过滤过去时间窗口内的条目。"""
    filtered = []
    for item in items:
        dt = parse_pub_date(item.get("published_at", ""))
        if dt and dt >= cutoff:
            filtered.append(item)
    return filtered


def dedup(items: list) -> list:
    seen = set()
    result = []
    for item in items:
        link = item.get("link", "")
        if link and link not in seen:
            seen.add(link)
            result.append(item)
    return result


def load_last_run() -> datetime:
    """读取上次执行时间，默认 6 小时前。"""
    if STATE_FILE.exists():
        try:
            ts = float(STATE_FILE.read_text().strip())
            return datetime.fromtimestamp(ts, tz=CST)
        except Exception:
            pass
    return now_cst() - timedelta(hours=6)


def save_last_run():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(str(now_cst().timestamp()))


def main():
    today = now_cst()
    date_str = today.strftime("%Y-%m-%d")
    cutoff = load_last_run()

    print(f"[{today.strftime('%Y-%m-%d %H:%M')}] Daily News Hotspots Sync 开始", flush=True)
    print(f"时间过滤: {cutoff.strftime('%Y-%m-%d %H:%M')} 之后", flush=True)
    print()

    all_sources = []
    total_items = 0
    domestic_count = 0
    intl_count = 0
    success_count = 0

    for cfg in SOURCES:
        name = cfg["name"]
        print(f"[RSS] 抓取: {name}", flush=True)

        xml_text = fetch_rss(cfg["url"])
        if not xml_text:
            print(f"  ✗ 抓取失败", flush=True)
            all_sources.append({
                "source": name,
                "source_type": "rss",
                "language": cfg["lang"],
                "region": cfg["region"],
                "item_count": 0,
                "items": [],
            })
            continue

        items = parse_rss_items(xml_text, cfg)
        items = filter_by_time(items, cutoff)
        items = dedup(items)

        all_sources.append({
            "source": name,
            "source_type": "rss",
            "language": cfg["lang"],
            "region": cfg["region"],
            "item_count": len(items),
            "items": items,
        })
        total_items += len(items)
        if cfg["region"] == "domestic":
            domestic_count += len(items)
        else:
            intl_count += len(items)
        if items:
            success_count += 1
        print(f"  ✓ {len(items)} 条", flush=True)
        print()

    # 生成 JSON
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{date_str}_news_hotspots.json"

    result = {
        "date": date_str,
        "meta": {
            "generated_at": today.isoformat(),
            "total_sources": len(SOURCES),
            "total_items": total_items,
            "domestic_items": domestic_count,
            "international_items": intl_count,
        },
        "sources": all_sources,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[JSON] 已保存: {output_path}", flush=True)
    print(f"       总计: {total_items} 条 (国内 {domestic_count}, 国际 {intl_count})", flush=True)
    print()

    # 保存执行时间
    save_last_run()

    # 汇报
    print()
    print("=" * 50, flush=True)
    print(f"📰 Daily News Hotspots Sync 汇报 ({date_str})", flush=True)
    print("=" * 50, flush=True)
    for src in all_sources:
        status = "✓" if src["item_count"] > 0 else "○"
        flag = "🇨🇳" if src["region"] == "domestic" else "🌍"
        print(f"  {flag} {status} {src['source']}: {src['item_count']} 条", flush=True)
    print(f"\n总计: {total_items} 条 | 国内: {domestic_count} | 国际: {intl_count}", flush=True)
    print("=" * 50, flush=True)


if __name__ == "__main__":
    main()
