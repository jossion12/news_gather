#!/usr/bin/env python3
"""
Daily Tech RSS Sync
抓取 8 个技术信息源，生成 JSON。

用法:
    python daily_tech_rss.py
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen

CST = timezone(timedelta(hours=8))
OUTPUT_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "data" / "tech"

# RSS 源配置
RSS_SOURCES = {
    "Hacker News Top 100": {
        "url": "https://hnrss.org/frontpage?points=100",
        "type": "rss",
    },
    "Hugging Face Blog": {
        "url": "https://huggingface.co/blog/feed.xml",
        "type": "rss",
    },
    "GitHub Blog": {
        "url": "https://github.blog/feed/",
        "type": "rss",
    },
    "arXiv cs.AI": {
        "url": "https://rss.arxiv.org/rss/cs.AI",
        "type": "rss",
    },
    "BleepingComputer": {
        "url": "https://www.bleepingcomputer.com/feed/",
        "type": "rss",
    },
    "The Pragmatic Engineer": {
        "url": "https://blog.pragmaticengineer.com/rss/",
        "type": "rss",
    },
}

# arXiv 关键词过滤（可选）
ARXIV_KEYWORDS = ["LLM", "Agent", "RAG", "Transformer", "Multimodal", "Diffusion", "Reasoning"]


def now_cst() -> datetime:
    return datetime.now(CST)


def fetch_rss(url: str, timeout: int = 30, retries: int = 3) -> str:
    """抓取 RSS feed，失败重试。"""
    for attempt in range(retries):
        try:
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; DailyTechRSS/1.0)",
                "Accept": "application/rss+xml, application/xml, text/xml",
            })
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            print(f"  [RSS] 尝试 {attempt + 1}/{retries} 失败: {e}")
            if attempt < retries - 1:
                import time
                time.sleep(2 ** attempt)
    return ""


def parse_rss(xml_text: str, source_name: str) -> list:
    """解析 RSS XML，提取条目。"""
    items = []
    if not xml_text:
        return items

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"  [RSS] XML 解析失败: {e}")
        return items

    # 处理 RSS 2.0 和 Atom 命名空间
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    # 找 channel → item (RSS 2.0) 或 feed → entry (Atom)
    channel = root.find("channel")
    if channel is not None:
        entries = channel.findall("item")
    else:
        entries = root.findall(".//atom:entry", ns)
        if not entries:
            entries = root.findall("entry")

    for entry in entries:
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

        # pubDate / published
        pub_date = ""
        for tag in ["pubDate", "published", "dc:date"]:
            elem = entry.find(tag)
            if elem is not None and elem.text:
                pub_date = elem.text.strip()
                break

        # summary / description / content
        summary = ""
        for tag in ["description", "summary", "content"]:
            elem = entry.find(tag)
            if elem is not None and elem.text:
                summary = unescape(elem.text.strip())
                break

        # 清理 HTML 标签
        summary = re.sub(r'<[^>]+>', '', summary)

        items.append({
            "title": title,
            "link": link,
            "source": source_name,
            "published_at": pub_date,
            "summary": summary[:500] if summary else "",
            "category": "",
        })

    return items


def filter_last_24h(items: list, cutoff: datetime) -> list:
    """过滤过去 24 小时内的条目。"""
    filtered = []
    for item in items:
        pub = item.get("published_at", "")
        if not pub:
            continue
        try:
            # 尝试多种日期格式
            dt = None
            for fmt in [
                "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d",
            ]:
                try:
                    dt = datetime.strptime(pub, fmt)
                    break
                except ValueError:
                    continue
            if dt is None:
                # 尝试清理后解析
                clean = re.sub(r'\+\d{4}$', '', pub).strip()
                try:
                    dt = datetime.strptime(clean, "%a, %d %b %Y %H:%M:%S")
                    dt = dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
            if dt is None:
                continue
            # 统一为 aware datetime
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                filtered.append(item)
        except Exception:
            continue
    return filtered


def filter_arxiv(items: list) -> list:
    """arXiv 可选关键词过滤。"""
    filtered = []
    for item in items:
        title = item.get("title", "").lower()
        if any(kw.lower() in title for kw in ARXIV_KEYWORDS):
            filtered.append(item)
    return filtered


def parse_github_trending_md(filepath: Path) -> list:
    """从 GitHub Trending 日报 markdown 提取条目。"""
    items = []
    if not filepath.exists():
        return items
    content = filepath.read_text(encoding="utf-8")

    for m in re.finditer(
        r'### (\d+)\.\s*\[([^\]]+)\]\(([^\)]+)\)\s*(?:🔥)?\s*\n'
        r'(?:- \*\*描述\*\*[:：]\s*([^\n]+)\n)?'
        r'(?:- \*\*语言\*\*[:：]\s*([^\n]+)\n)?'
        r'(?:- \*\*星标\*\*[:：]\s*([^\n]+)\n)?'
        r'(?:- \*\*今日新增\*\*[:：]\s*([^\n]+)\n)?',
        content,
    ):
        name = m.group(2).strip()
        link = m.group(3).strip()
        desc = (m.group(4) or "").strip()
        lang = (m.group(5) or "").strip()
        stars = (m.group(6) or "").strip()
        today = (m.group(7) or "").strip()

        summary = desc
        if stars:
            summary += f" | 星标: {stars}"
        if today:
            summary += f" | 今日新增: {today}"

        items.append({
            "title": name,
            "link": link,
            "source": "GitHub Trending",
            "published_at": filepath.stem + "T00:00:00+08:00",
            "summary": summary,
            "category": lang or "",
        })

    return items


def parse_modelscope_md(filepath: Path) -> list:
    """从 ModelScope 日报 markdown 提取条目。"""
    items = []
    if not filepath.exists():
        return items
    content = filepath.read_text(encoding="utf-8")

    for m in re.finditer(
        r'### (\d+)\.\s*([^\n]+)\s*\n'
        r'.*?- \*\*模型 ID\*\*：?`([^`]+)`\s*\n'
        r'.*?- \*\*点赞\*\*[:：]\s*(.+?)\s*\|'
        r'.*?- \*\*任务类型\*\*[:：]\s*([^\n]+)\n'
        r'.*?- \*\*描述\*\*[:：]\s*([^\n]+)\n',
        content,
        re.DOTALL,
    ):
        name = m.group(2).strip()
        model_id = m.group(3).strip()
        likes = m.group(4).strip()
        task = m.group(5).strip()
        desc = m.group(6).strip()

        items.append({
            "title": name,
            "link": f"https://modelscope.cn/models/{model_id}",
            "source": "ModelScope",
            "published_at": filepath.stem + "T00:00:00+08:00",
            "summary": f"点赞: {likes} | 任务: {task} | {desc}",
            "category": task or "",
        })

    return items

def dedup(items: list) -> list:
    """基于 link 去重，保留第一个。"""
    seen = set()
    result = []
    for item in items:
        link = item.get("link", "")
        if link and link not in seen:
            seen.add(link)
            result.append(item)
    return result


def main():
    today = now_cst()
    date_str = today.strftime("%Y-%m-%d")
    cutoff = today - timedelta(hours=24)

    print(f"[{today.strftime('%Y-%m-%d %H:%M')}] Daily Tech RSS Sync 开始")
    print(f"时间过滤: {cutoff.strftime('%Y-%m-%d %H:%M')} 之后")
    print()

    all_sources = []
    total_items = 0
    success_count = 0

    # ── 1. 抓取 6 个 RSS 源 ──────────────────────────────
    for name, cfg in RSS_SOURCES.items():
        print(f"[RSS] 抓取: {name}")
        xml_text = fetch_rss(cfg["url"])
        if not xml_text:
            print(f"  ✗ 抓取失败")
            all_sources.append({
                "source": name,
                "source_type": "rss",
                "item_count": 0,
                "items": [],
            })
            continue

        items = parse_rss(xml_text, name)
        # arXiv 关键词过滤
        if name == "arXiv cs.AI":
            items = filter_arxiv(items)
        # 时间过滤
        items = filter_last_24h(items, cutoff)
        items = dedup(items)

        all_sources.append({
            "source": name,
            "source_type": "rss",
            "item_count": len(items),
            "items": items,
        })
        total_items += len(items)
        if items:
            success_count += 1
        print(f"  ✓ {len(items)} 条")
        print()

    # ── 2. 读取 GitHub Trending 日报 ─────────────────────
    print("[本地] 读取 GitHub Trending 日报")
    gh_file = Path(os.path.dirname(os.path.abspath(__file__))) / "github_trend" / f"{date_str}.md"
    gh_items = parse_github_trending_md(gh_file)
    all_sources.append({
        "source": "GitHub Trending",
        "source_type": "api",
        "item_count": len(gh_items),
        "items": gh_items,
    })
    total_items += len(gh_items)
    if gh_items:
        success_count += 1
    print(f"  ✓ {len(gh_items)} 条")
    print()

    # ── 3. 读取 ModelScope 日报 ──────────────────────────
    print("[本地] 读取 ModelScope 日报")
    ms_file = Path(os.path.dirname(os.path.abspath(__file__))) / "modelscope" / f"{date_str}.md"
    ms_items = parse_modelscope_md(ms_file)
    all_sources.append({
        "source": "ModelScope",
        "source_type": "api",
        "item_count": len(ms_items),
        "items": ms_items,
    })
    total_items += len(ms_items)
    if ms_items:
        success_count += 1
    print(f"  ✓ {len(ms_items)} 条")
    print()

    # ── 4. 生成 JSON ─────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{date_str}_tech_rss.json"

    result = {
        "date": date_str,
        "meta": {
            "generated_at": today.isoformat(),
            "total_sources": 8,
            "total_items": total_items,
        },
        "sources": all_sources,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[JSON] 已保存: {output_path}")
    print(f"       总计: {total_items} 条, {success_count}/8 个源有数据")
    print()

    # ── 5. 汇报 ──────────────────────────────────────────
    print()
    print("=" * 50)
    print(f"📊 Daily Tech RSS Sync 汇报 ({date_str})")
    print("=" * 50)
    for src in all_sources:
        status = "✓" if src["item_count"] > 0 else "○"
        print(f"  {status} {src['source']}: {src['item_count']} 条")
    print(f"\n总计: {total_items} 条")
    print("=" * 50)


if __name__ == "__main__":
    main()
