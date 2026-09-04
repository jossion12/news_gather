# 每日新闻采集 (news_gather)

每日自动采集 ModelScope 热门模型、技术资讯和新闻热点，输出 Markdown 日报和 JSON 数据。

## 快速开始

```bash
# 一次执行全部三个采集任务（推荐入口）
python main.py
```

也可以单独执行某个任务：

```bash
python modelscope_daily.py      # ModelScope 热门模型日报
python daily_tech_rss.py        # 技术资讯 RSS 同步（8 个源）
python daily_news_hotspots.py   # 新闻热点 RSS 同步（19 个源）
```

> Windows 注意：如果 `python` 命令不可用或报退出码 49（Store 占位程序），请改用 `py -3`。
> `main.py` 已内置 UTF-8 输出处理，直接运行即可避免 GBK 编码错误。

## 任务说明

| 任务 | 输出 | 说明 |
| --- | --- | --- |
| `modelscope_daily.py` | `modelscope/YYYY-MM-DD.md` | ModelScope 按点赞数排序的热门模型日报（20 个） |
| `daily_tech_rss.py` | `data/tech/YYYY-MM-DD_tech_rss.json` | 抓取 HN、GitHub Blog、arXiv 等技术源（约 24 小时内的内容） |
| `daily_news_hotspots.py` | `data/news/YYYY-MM-DD_news_hotspots.json` | 抓取国内（IT之家、雷锋网等）和国际（The Verge、Ars 等）新闻源 |

## 输出目录

```
modelscope/   # ModelScope 日报 Markdown
data/tech/    # 技术资讯 JSON
data/news/    # 新闻热点 JSON
log/          # 执行日志
```

## 执行日志

`main.py` 运行时自动创建 `log/` 目录：

- `log/YYYY-MM-DD.log` — 当日主日志，包含全部任务输出与汇总（同一天多次运行会追加）
- `log/YYYY-MM-DD_<子任务名>.log` — 每个子任务的详细执行日志，含执行时间戳和退出码

## 已知问题

- 部分国外 RSS 源可能因网络原因超时或返回 403，脚本会自动重试并跳过失败的源。
