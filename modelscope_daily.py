#!/usr/bin/env python3
"""
ModelScope 热门模型日报生成器
每天早上 8:30 由 cron 触发执行
"""

import json
import os
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen

# 输出目录
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modelscope")
# ModelScope OpenAPI
API_URL = "https://modelscope.cn/openapi/v1/models"
PAGE_SIZE = 20


def fetch_models(sort="likes", page_size=PAGE_SIZE):
    """从 ModelScope OpenAPI 获取模型列表"""
    url = f"{API_URL}?sort={sort}&page_size={page_size}&page_number=1"
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; ModelScope-DailyBot/1.0)",
        "Accept": "application/json",
    })
    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("data", {}).get("models", [])
    except Exception as e:
        print(f"Error fetching models (sort={sort}): {e}", file=sys.stderr)
        return []


def format_number(n):
    """格式化数字，如 1234567 -> 123.5万"""
    if n is None:
        return "—"
    if n >= 100_000_000:
        return f"{n/100_000_000:.2f}亿"
    if n >= 10_000:
        return f"{n/10_000:.1f}万"
    return str(n)


def format_tasks(tasks):
    """格式化任务类型列表"""
    if not tasks:
        return "—"
    task_map = {
        "voice-activity-detection": "语音端点检测",
        "auto-speech-recognition": "语音识别",
        "punctuation": "标点预测",
        "text-generation": "文本生成",
        "text-to-image": "文生图",
        "text-to-image-synthesis": "文生图",
        "image-to-image": "图生图",
        "text-to-video": "文生视频",
        "text-to-video-synthesis": "文生视频",
        "image-classification": "图像分类",
        "object-detection": "目标检测",
        "semantic-segmentation": "语义分割",
        "translation": "翻译",
        "summarization": "摘要生成",
        "named-entity-recognition": "命名实体识别",
        "speech-synthesis": "语音合成",
        "text-to-speech": "语音合成",
        "speaker-verification": "声纹识别",
        "speech-enhancement": "语音增强",
        "visual-question-answering": "视觉问答",
        "video-captioning": "视频描述",
        "visual-grounding": "视觉定位",
        "multimodal-representation": "多模态表示",
        "any-to-any": "全模态",
        "protein-structure-generation": "蛋白质结构生成",
        "protein-function-prediction": "蛋白质功能预测",
    }
    return "、".join([task_map.get(t, t) for t in tasks[:3]])


def build_report(models, date_str, sort_label):
    """生成 Markdown 报告"""
    now = datetime.now(timezone.utc).astimezone()
    tz_name = now.strftime("%Z")
    collect_time = now.strftime("%Y-%m-%d %H:%M") + f" ({tz_name})"

    lines = [
        f"# ModelScope 热门模型日报 — {date_str}",
        "",
        f"> 数据来源：[ModelScope 魔搭社区](https://modelscope.cn/models)  ",
        f"> 排序方式：**{sort_label}**  ",
        f"> 采集时间：{collect_time}",
        "",
        "---",
        "",
        f"## 今日热门模型（共 {len(models)} 个）",
        "",
    ]

    for idx, m in enumerate(models, 1):
        model_id = m.get("id", "unknown")
        display_name = m.get("display_name", model_id)
        description = m.get("description", "") or "暂无描述"
        likes = m.get("likes", 0)
        downloads = m.get("downloads", 0)
        license_ = m.get("license", "—")
        tasks = format_tasks(m.get("tasks", []))
        created = m.get("created_at", "")[:10]  # YYYY-MM-DD
        last_modified = m.get("last_modified", "")[:10]
        private = "🔒 私有" if m.get("private") else "🌐 公开"

        # 模型详情页链接
        link = f"https://modelscope.cn/models/{model_id}"

        lines.extend([
            f"### {idx}. {display_name}",
            f"- **模型 ID**：`{model_id}`",
            f"- **点赞**：{format_number(likes)} ❤️ | **下载**：{format_number(downloads)} 📥",
            f"- **许可协议**：{license_} | **可见性**：{private}",
            f"- **任务类型**：{tasks}",
            f"- **发布时间**：{created} | **最后更新**：{last_modified}",
            f"- **描述**：{description}",
            f"- **链接**：[modelscope.cn/models/{model_id}]({link})",
            "",
            "---",
            "",
        ])

    # 添加今日观察
    lines.extend([
        "## 今日观察",
        "",
    ])

    # 计算一些统计信息
    total_likes = sum(m.get("likes", 0) or 0 for m in models)
    total_downloads = sum(m.get("downloads", 0) or 0 for m in models)
    most_liked = max(models, key=lambda x: x.get("likes", 0) or 0) if models else None
    most_downloaded = max(models, key=lambda x: x.get("downloads", 0) or 0) if models else None

    lines.append(f"- **榜单总点赞数**：{format_number(total_likes)} | **总下载量**：{format_number(total_downloads)}")
    if most_liked:
        lines.append(f"- **点赞最高**：`{most_liked['id']}`（{format_number(most_liked.get('likes', 0))} ❤️）")
    if most_downloaded:
        lines.append(f"- **下载最高**：`{most_downloaded['id']}`（{format_number(most_downloaded.get('downloads', 0))} 📥）")

    # 统计任务类型分布
    task_counts = {}
    for m in models:
        for t in m.get("tasks", []):
            task_counts[t] = task_counts.get(t, 0) + 1
    if task_counts:
        top_tasks = sorted(task_counts.items(), key=lambda x: -x[1])[:3]
        task_str = "、".join([f"{t}({c}个)" for t, c in top_tasks])
        lines.append(f"- **热门任务类型**：{task_str}")

    lines.append("")

    return "\n".join(lines)


def main():
    # 确保输出目录存在
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 获取今天的日期
    today = datetime.now(timezone.utc).astimezone()
    date_str = today.strftime("%Y-%m-%d")
    output_path = os.path.join(OUTPUT_DIR, f"{date_str}.md")

    # 获取按 likes 排序的热门模型
    models = fetch_models(sort="likes", page_size=PAGE_SIZE)

    if not models:
        print("Failed to fetch models, aborting.", file=sys.stderr)
        sys.exit(1)

    # 生成报告
    report = build_report(models, date_str, "按点赞数降序")

    # 保存报告
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"Report saved to {output_path}")
    print(f"Models collected: {len(models)}")


if __name__ == "__main__":
    main()
