#!/usr/bin/env python3
"""
每日新闻采集主入口
依次执行:
    1. modelscope_daily.py        - ModelScope 热门模型日报
    2. daily_tech_rss.py          - 技术资讯 RSS 同步
    3. daily_news_hotspots.py     - 新闻热点 RSS 同步

输出:
    modelscope/YYYY-MM-DD.md          ModelScope 日报
    data/tech/YYYY-MM-DD_tech_rss.json
    data/news/YYYY-MM-DD_news_hotspots.json
    log/YYYY-MM-DD.log                当日主日志（多次运行追加）
    log/YYYY-MM-DD_<子任务>.log        各子任务详细日志

用法:
    python main.py
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = BASE_DIR / "log"

# 让子进程也以 UTF-8 模式运行，避免 Windows GBK 控制台编码错误
CHILD_ENV = {**os.environ, "PYTHONUTF8": "1"}

# 按执行顺序排列的任务
TASKS = [
    ("ModelScope 日报", "modelscope_daily.py"),
    ("技术 RSS 同步", "daily_tech_rss.py"),
    ("新闻热点同步", "daily_news_hotspots.py"),
]


def make_printer(*writers):
    def printer(msg=""):
        line = str(msg)
        for w in writers:
            w.write(line + "\n")
            w.flush()
    return printer


def run_task(name, script, date_str, master_print):
    """执行单个脚本，详细输出写入子任务日志，同时汇入主日志，返回是否成功"""
    task_log_path = LOG_DIR / f"{date_str}_{Path(script).stem}.log"

    master_print(f"\n{'=' * 50}")
    master_print(f"▶ 开始任务: {name} ({script})")
    master_print(f"{'=' * 50}")

    with open(task_log_path, "a", encoding="utf-8") as task_log:
        task_print = make_printer(sys.stdout, task_log)

        task_print(f"===== {datetime.now():%Y-%m-%d %H:%M:%S} 开始执行 {script} =====")

        result = subprocess.run(
            [sys.executable, script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=CHILD_ENV,
        )

        output = (result.stdout or "") + (result.stderr or "")
        task_print(output.rstrip() or "(无输出)")
        task_print(f"===== 结束，退出码 {result.returncode} =====")

        # 子任务输出同时汇入主日志
        master_print(output.rstrip() or "(无输出)")

    if result.returncode == 0:
        master_print(f"✓ 任务完成: {name}  (详细日志: {task_log_path.name})")
    else:
        master_print(f"✗ 任务失败: {name} (退出码 {result.returncode})  (详细日志: {task_log_path.name})")

    return result.returncode == 0


def main():
    # 强制 UTF-8 输出，避免 Windows GBK 控制台编码错误
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    os.makedirs(LOG_DIR, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    master_log_path = LOG_DIR / f"{date_str}.log"

    with open(master_log_path, "a", encoding="utf-8") as master_log:
        master_print = make_printer(sys.stdout, master_log)

        master_print(f"[{datetime.now():%Y-%m-%d %H:%M}] 每日新闻采集任务开始")
        master_print(f"主日志: {master_log_path}")

        results = []
        for name, script in TASKS:
            ok = run_task(name, script, date_str, master_print)
            results.append((name, ok))

        master_print(f"\n{'=' * 50}")
        master_print("📋 任务汇总")
        master_print(f"{'=' * 50}")
        failed = 0
        for name, ok in results:
            mark = "✓" if ok else "✗"
            master_print(f"  {mark} {name}")
            if not ok:
                failed += 1

        master_print(f"\n完成: {len(results) - failed}/{len(results)} 个任务成功")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
