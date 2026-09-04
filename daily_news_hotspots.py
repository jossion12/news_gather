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
    {"name": "澎湃新闻", "url": "https://www.thepaper.cn/rss.xml", "lang": "zh", "region": "domestic", "is_hotlist": True},
    {"name": "中新网即时新闻", "url": "https://www.chinanews.com.cn/rss/scroll-news.xml", "lang": "zh", "region": "domestic", "is_hotlist": True},
    {"name": "新京报", "url": "https://www.bjnews.com.cn/", "lang": "zh", "region": "domestic", "is_hotlist": True, "fetch": "html_bjnews"},
    {"name": "36氪", "url": "https://gateway.36kr.com/api/mis/nav/home/nav/rank/hot", "lang": "zh", "region": "domestic", "is_hotlist": True, "fetch": "api_36kr"},
    {"name": "少数派", "url": "https://sspai.com/feed", "lang": "zh", "region": "domestic", "is_hotlist": False},
    {"name": "爱范儿", "url": "https://www.ifanr.com/feed", "lang": "zh", "region": "domestic", "is_hotlist": False},
    {"name": "FT中文网", "url": "http://www.ftchinese.com/rss/news", "lang": "zh", "region": "international", "is_hotlist": False},
    {"name": "BBC中文", "url": "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml", "lang": "zh", "region": "international", "is_hotlist": True},
    {"name": "NPR News", "url": "https://feeds.npr.org/1001/rss.xml", "lang": "en", "region": "international", "is_hotlist": True},
    {"name": "France 24", "url": "https://www.france24.com/en/rss", "lang": "en", "region": "international", "is_hotlist": True},
    {"name": "Washington Post World", "url": "https://feeds.washingtonpost.com/rss/world", "lang": "en", "region": "international", "is_hotlist": True},
    {"name": "BBC World", "url": "http://feeds.bbci.co.uk/news/world/rss.xml", "lang": "en", "region": "international", "is_hotlist": True},
    {"name": "The Guardian World", "url": "https://www.theguardian.com/world/rss", "lang": "en", "region": "international", "is_hotlist": True},
    {"name": "NYT HomePage", "url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", "lang": "en", "region": "international", "is_hotlist": True},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml", "lang": "en", "region": "international", "is_hotlist": True},
    {"name": "DW English", "url": "https://rss.dw.com/xml/rss-en-all", "lang": "en", "region": "international", "is_hotlist": True}
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


def ms_to_iso(ms: int) -> str:
    """毫秒时间戳转 ISO 字符串（CST，秒级精度）。"""
    return datetime.fromtimestamp(ms / 1000, tz=CST).replace(microsecond=0).isoformat()


def fetch_36kr_hotlist(source_cfg: dict, timeout: int = 15, retries: int = 2) -> list:
    """36氪 24小时热榜（官方 JSON API）。

    www.36kr.com 全站有 WAF JS 挑战，纯 Python 无法绕过；
    改用未受 WAF 限制的 gateway API。
    """
    payload = {
        "partner_id": "web",
        "timestamp": int(now_cst().timestamp() * 1000),
        "param": {"rankType": 0, "platformId": 1, "siteId": 1},
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; DailyNewsBot/1.0)",
        "Content-Type": "application/json",
        "Origin": "https://36kr.com",
        "Referer": "https://36kr.com/",
    }

    data = None
    for attempt in range(retries):
        try:
            req = Request(source_cfg["url"], data=json.dumps(payload).encode("utf-8"), headers=headers)
            with urlopen(req, timeout=timeout) as resp:
                resp_data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if resp_data.get("code") == 0:
                data = resp_data["data"]
                break
            print(f"    尝试 {attempt + 1}/{retries} 失败: API 返回 code={resp_data.get('code')} {resp_data.get('msg')}", flush=True)
        except Exception as e:
            print(f"    尝试 {attempt + 1}/{retries} 失败: {e}", flush=True)
        if attempt < retries - 1:
            import time
            time.sleep(2)

    items = []
    for rank, entry in enumerate((data or {}).get("hotRankList", []), start=1):
        material = entry.get("templateMaterial") or {}
        title = re.sub(r"</?em>", "", material.get("widgetTitle") or "").strip()
        if not title:
            continue
        item_id = entry.get("itemId")
        pub_ms = entry.get("publishTime") or material.get("publishTime") or 0
        items.append({
            "title": title,
            "link": f"https://36kr.com/p/{item_id}" if item_id else "",
            "source": source_cfg["name"],
            "published_at": ms_to_iso(pub_ms) if pub_ms else "",
            "summary": "",
            "category": "",
            "rank": rank,
        })
    return items


def fetch_bjnews_hotlist(source_cfg: dict, timeout: int = 15, retries: int = 2) -> list:
    """新京报首页热点（HTML 抓取）。

    /feed 接口已下线且全站套了移动端 JS 跳转页，改为直接抓取桌面端首页，
    从文章 ID（雪花 ID，前 13 位为毫秒时间戳）推导发布时间。
    """
    html_text = fetch_rss(source_cfg["url"], timeout=timeout, retries=retries)
    if not html_text:
        return []

    items = []
    seen = set()
    for m in re.finditer(
        r'<a[^>]+href=["\']((https?://(?:www|m)\.bjnews\.com\.cn)?/detail/(\d+)\.html)["\'][^>]*>(.*?)</a>',
        html_text, re.S,
    ):
        url, _, detail_id, inner = m.groups()
        if url.startswith("/"):
            url = "https://www.bjnews.com.cn" + url
        url = url.replace("https://m.bjnews.com.cn", "https://www.bjnews.com.cn")
        if url in seen:
            continue
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", inner)).strip()
        if len(title) < 6:
            continue
        seen.add(url)

        pub = ""
        if len(detail_id) >= 13:
            try:
                pub = ms_to_iso(int(detail_id[:13]))
            except (ValueError, OSError, OverflowError):
                pass

        items.append({
            "title": title,
            "link": url,
            "source": source_cfg["name"],
            "published_at": pub,
            "summary": "",
            "category": "",
            "rank": len(items) + 1,
        })
    return items


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
        fetch_type = cfg.get("fetch", "rss")
        print(f"[RSS] 抓取: {name}", flush=True)

        if fetch_type == "rss":
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
        elif fetch_type == "api_36kr":
            items = fetch_36kr_hotlist(cfg)
        elif fetch_type == "html_bjnews":
            items = fetch_bjnews_hotlist(cfg)
        else:
            print(f"  ✗ 未知抓取类型: {fetch_type}", flush=True)
            items = []

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
