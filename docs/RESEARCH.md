# GitHub 热门开源项目每日 RSS — 数据源与实现方案调研

> 作者：researcher（调研角色） · 状态：已定稿，供工程师实现参考
> 日期：2025（调研基于 GitHub 官方文档与社区实践，2024–2025 仍有效）

---

## 1. 数据源选型

### 1.1 候选方案对比

| 维度 | A. 抓取 github.com/trending | B. GitHub Search API（stars 排序 + created 过滤） |
|---|---|---|
| 语义匹配度 | ✅ **完全匹配**：即「今日/本周/本月趋势」排行（按时间窗口内新增 star 数），与需求「每日热门/趋势项目」一致 | ⚠️ 近似：只能按**总 star 数**排序或按 `created:` 过滤，**无法按「某时间窗口内新增 star 数」排序**，无法还原 Trending 语义 |
| 是否需要 token | ❌ 不需要（匿名 GET + 正常 User-Agent 即可，无 API 限流） | ❌ 不需要（10 次/分钟，每日 1 次请求绰绰有余）；带 token 更稳（30 次/分钟） |
| 限流 / 稳定性 | 无 API 限流；风险在于 HTML 结构变动导致解析失效 | 官方 API、JSON 结构稳定；限流明确：Search API 未认证 **10 req/min**，认证 **30 req/min**（核心 API 未认证 60 req/h，认证 5,000 req/h） |
| 风险点 | 无官方承诺的 HTML 结构，GitHub 改版可能破坏解析（历史上结构较稳定，近年未大变） | 查询结果不等于 Trending；`created:` 过滤只能捕获「新创建即热门」的仓库，会漏掉「老仓库今日突然走红」 |
| 请求量 | 每期 1 次页面请求 | 每期 1 次 API 请求 |

参考来源：
- GitHub 官方速率限制文档：[REST API 的速率限制](https://docs.github.com/zh/rest/using-the-rest-api/rate-limits-for-the-rest-api)、[REST API endpoints for search](https://docs.github.com/en/rest/search/search)
- Trending 抓取实践：[How to Scrape GitHub Trending with Python](https://guides.proxiesapi.com/posts/scrape-github-trending-python)、[shibing624/github-hot 爬虫实现](https://github.com/shibing624/github-hot/blob/236b52c76ed7dcd5bb8cbffb9ad0db9d8293db6f/crawler.py)

### 1.2 最终选型（推荐）

**主数据源：抓取 `https://github.com/trending?since=daily`（BeautifulSoup 解析）**

理由：
1. Trending 的语义（按每日新增 star 数排序）是 Search API 无法替代的，这正是「GitHub 热门项目每日 RSS」想要的信号；
2. 无需 token、无 API 限流负担，每期仅 1 次请求；
3. 社区大量同类项目（github-trending RSS、github-hot 等）均采用此方式，可行性与稳定性已被验证。

**兜底数据源：GitHub Search API**（仅当抓取失败或解析出 0 条时启用）

- 查询：`https://api.github.com/search/repositories?q=created:>{today-30d}&sort=stars&order=desc&per_page=25`
- 未认证限流 10 req/min 完全够用（每日 1 次）；可选用 `GH_TOKEN`（免费）提升至 30 req/min 并增加可靠性。

### 1.3 抓取要点（给工程师）

- URL：`https://github.com/trending?since=daily`（可选 `weekly` / `monthly`，本期只用 daily）。
- **必须携带桌面浏览器 User-Agent**，否则可能被拒（403）。
- 页面结构（2024 年实测稳定，仍需防御式解析）：
  - 每个仓库为 `<article class="Box-row">`；
  - 仓库名：`h2 a.Link--primary`，href 形如 `/owner/repo`（**最可靠的字段**）；
  - 描述：`.col-9` 下的 `<p>`（可能缺失，需容错）；
  - 语言：`[itemprop="programmingLanguage"]`（可能缺失）；
  - 今日新增 star：`span.d-inline-block.float-sm-right` 中的 `"1,234 stars today"` 文本（服务器渲染，可直接取数）；
  - 总 star 数：`a.Link--muted` 内的数字（**注意**：近年部分数字由前端 JS 懒加载，可能为空占位符，解析时允许缺失，缺失时可用 0 或留空）。
- 容错：解析不到任何条目时自动切 Search API 兜底；单条字段缺失不丢弃整条。

---

## 2. RSS / Atom 规范要点

### 2.1 两种规范对比

| 要素 | RSS 2.0 | Atom 1.0 |
|---|---|---|
| 根元素 | `<rss version="2.0">` → `<channel>` | `<feed xmlns="http://www.w3.org/2005/Atom">` |
| channel/feed 必填 | `title`、`link`、`description` | `id`、`title`、`updated` |
| item/entry 必填 | `title` 或 `description`（至少其一；规范建议两者都给） | `id`、`title`、`updated` |
| item/entry 建议字段 | `link`、`pubDate`、`guid`、`description`、`author` | `link rel="alternate"`、`summary`/`content`、`author` |
| 时间格式 | RFC 822：`Wed, 05 Jun 2024 00:00:00 GMT` | RFC 3339（ISO 8601）：`2024-06-05T00:00:00Z` |
| 兼容性 | 最广，几乎所有阅读器（含老牌）都支持 | 标准更严谨，现代阅读器支持良好 |

参考：[RSS 2.0 规范（RSS Advisory Board）](https://www.rssboard.org/rss-specification)、[RSS 2.0 XSD](https://www.cs.cornell.edu/courses/cs431/2008sp/Projects/Project1/rss-2_0.xsd)

### 2.2 最终选型（推荐）

**采用 RSS 2.0**。理由：兼容性最广、语义贴合「每日摘要」（`pubDate` + `guid` 即足够标识），且 `feedgen` 库同时支持 RSS 2.0 与 Atom，后续切换成本为零。

**本期 feed 的 item 字段映射（工程师按此实现）**：

| RSS 字段 | 内容 | 备注 |
|---|---|---|
| `title`（必填） | `owner/repo`（仓库全名） | 如 `openai/whisper` |
| `link`（建议） | `https://github.com/owner/repo` | 仓库主页 |
| `description`（建议） | 描述 + 语言 + 今日新增 star + 总 star（如 `⭐ 今日 +1,234 · 共 56.7k · Python — <描述文本>`） | 纯文本即可 |
| `pubDate`（建议） | 生成日（UTC），RFC 822 格式 | 如 `Wed, 05 Jun 2024 00:00:00 GMT` |
| `guid`（建议） | 仓库 URL | `isPermaLink="true"`，天然全局唯一 |
| `author`（可选） | 仓库所有者 | 有则填 |

channel 层：`title`（如 "GitHub Trending 每日热门项目"）、`link`（feed 所在 URL 或仓库地址）、`description`（一句话说明）、`language`（`zh-CN`）、`lastBuildDate`（RFC 822）、`generator`（如 "github-trending-rss v0.1.0"）。

⚠️ 要点：所有文本做 XML 转义（`&` `<` `>` 等）；`pubDate`/`lastBuildDate` 必须 RFC 822（feedgen 自动处理）。

---

## 3. 每日自动更新部署方案

### 3.1 候选方案对比

| 方案 | 优点 | 缺点 |
|---|---|---|
| **GitHub Actions `schedule` cron**（推荐） | 免费、无需常驻机器、与代码同仓库、天然可审计；跑完自动提交/发布 feed | 定时有分钟级延迟，极端情况下 GitHub 可能跳过积压的 schedule 运行（会发通知）；只在默认分支运行 |
| 本地 cron / 服务器定时任务 | 完全自主可控 | 需要 7×24 在线机器，维护成本高，不推荐 |

### 3.2 最终选型（推荐）

**GitHub Actions `schedule` + `workflow_dispatch`**：

```yaml
on:
  schedule:
    - cron: '0 0 * * *'   # 每天 00:00 UTC（北京时间 08:00）
  workflow_dispatch: {}    # 支持手动触发，便于调试
```

工作流步骤：
1. `actions/checkout@v4`；
2. `actions/setup-python@v5`（runner 自带 Python，装 3.11+）；
3. `pip install -r requirements.txt`（依赖极少，见第 4 节）；
4. `python generate_feed.py` → 产出 `feed.xml`（放仓库根目录或 `docs/`）；
5. 提交并推送 `feed.xml`（`git config` 设置 `actions@github.com` 后 `git add` + `commit` + `push`；或使用 `peaceiris/actions-gh-pages@v4` 部署到 GitHub Pages）。

**feed 的对外发布方式（二选一，推荐 Pages）**：
- **GitHub Pages**（推荐）：启用仓库 Pages 后，feed 地址形如 `https://<user>.github.io/<repo>/feed.xml`，干净稳定；
- **raw.githubusercontent.com**：`https://raw.githubusercontent.com/<user>/<repo>/main/feed.xml`，有 CDN 缓存（通常几分钟内刷新，可接受）。

参考：[GitHub Actions 定时任务文档](https://docs.github.com/zh/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule)、[peaceiris/actions-gh-pages](https://github.com/peaceiris/actions-gh-pages)

---

## 4. 技术栈选型

### 4.1 候选对比

| 方案 | 依赖 | 优点 | 缺点 |
|---|---|---|---|
| **Python + requests + beautifulsoup4 + feedgen**（推荐） | 3 个纯 Python 小依赖 | 代码清晰、HTML 解析健壮、feedgen 自动处理 RSS 2.0 的转义/RFC 822 时间/guid，GitHub Actions runner 自带 Python | 3 个依赖（安装秒级，可忽略） |
| Python 纯标准库（urllib + html.parser + 手写 XML） | 0 依赖 | 最轻 | 手写 HTML 解析脆弱、手写 XML 转义/日期格式易出错 |
| Node.js（node-fetch + cheerio + rss） | 3 个 npm 依赖 | 同样可行 | 需维护 package.json/lockfile，node 生态略重 |

### 4.2 最终选型（推荐）

**Python 3.11+ + `requests` + `beautifulsoup4` + `feedgen`**（`requirements.txt` 仅 3 行）。

理由：
1. 满足「依赖尽量少、易部署」：3 个纯 Python 库，`pip install` 秒级完成，GitHub Actions ubuntu runner 自带 Python；
2. `beautifulsoup4` 让 Trending 页解析稳定、代码可读（一个文件搞定抓取+生成）；
3. `feedgen` 正确生成 RSS 2.0（XML 转义、RFC 822 日期、guid），避免手写 XML 的常见坑；
4. 如需极限精简，可后续降级为标准库版（不推荐作为首版）。

---

## 5. 结论（选型汇总）

| 决策项 | 选型 | 理由一句话 |
|---|---|---|
| 数据源 | **抓取 `github.com/trending?since=daily` 为主，Search API 兜底** | Trending 语义（按日新增 star 排序）API 无法替代；抓取无需 token、无限流；API 兜底保证稳定 |
| Feed 规范 | **RSS 2.0** | 兼容性最广，`pubDate`+`guid` 天然契合每日摘要；feedgen 可随时切 Atom |
| 部署 | **GitHub Actions schedule cron（每日 00:00 UTC）+ workflow_dispatch，提交 feed.xml 并发布到 Pages** | 免费、免维护、可审计 |
| 技术栈 | **Python 3.11+ + requests + beautifulsoup4 + feedgen** | 3 个纯 Python 依赖，易部署、解析健壮、RSS 生成正确 |

### 建议的仓库结构（供工程师参考）

```
.
├── .github/workflows/daily-feed.yml   # schedule + workflow_dispatch
├── generate_feed.py                   # 抓取 Trending（失败则 API 兜底）+ 生成 feed.xml
├── requirements.txt                   # requests, beautifulsoup4, feedgen
├── feed.xml                           # 产物（由 Actions 提交）
└── README.md                          # 使用与订阅说明
```
