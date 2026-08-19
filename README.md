# GitHub Trending RSS

每日抓取 GitHub 热门/趋势开源项目，生成 **RSS 2.0** 订阅源，并通过 GitHub Actions 定时自动更新。

- 数据源：**`github.com/trending?since=daily`**（主源，无需 token）＋ **GitHub Search API**（兜底）
- 输出：`feed.xml`（RSS 2.0，纯标准库实现，**零第三方依赖**）
- 更新：GitHub Actions `schedule` 每天 00:00 UTC（北京时间 08:00）自动生成并提交

---

## 特性

- 🏆 **Trending 语义**：以「时间窗口内新增 star 数」排序（`stars_today` 优先），与 GitHub Trending 页一致；Search API 无法还原此语义，故仅作兜底
- 📡 **RSS 2.0 规范**：channel 含 `title/link/description/language/generator/ttl/lastBuildDate`；item 含 `title/link/guid(pubDate)/description/content:encoded`，附 `atom:link rel=self` 支持
- 🔁 **健壮容错**：HTTP 5xx 指数退避重试、API 限流等待（Retry-After/X-RateLimit-Reset）、401 降级去 token、主源失败自动切兜底源、README 抓取失败静默降级为仓库描述
- 🛡 **安全**：token 仅经环境变量/命令行传入，不硬编码；`GITHUB_TOKEN` 由 Actions 自动注入
- 🪶 **零依赖**：仅需 Python 3.8+ 标准库（`urllib` / `html.parser` / `xml.etree`），`pip install` 一步到位（空 requirements）

## 环境要求

- Python 3.8+（CI 使用 3.11）
- 可选：`GITHUB_TOKEN` 环境变量（提升 Search API 兜底与 README 摘要的限流额度）

## 快速开始

```bash
# 生成默认 feed（Trending 主源，daily 窗口，最多 30 条 -> feed.xml）
python main.py

# 只取 Python 项目、周趋势窗口、50 条
python main.py -l python --since weekly -n 50

# 输出到自定义文件，跳过 README 摘要（快速测试用）
python main.py -o python-feed.xml --no-readme-summary

# 使用 token（或设置 GITHUB_TOKEN 环境变量）
python main.py --token ghp_xxx

# 仅用 Search API 兜底路径测试（禁用 Trending 主源时的降级行为）
python main.py --no-fallback
```

### 全部命令行参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `-l, --language LANG` | 无 | 按主语言过滤（如 python、go），作用于主源与兜底 |
| `--since {daily,weekly,monthly}` | `daily` | Trending 页时间窗口（主源） |
| `-d, --days N` | `7` | Search API 兜底的时间窗口（近 N 天创建） |
| `-n, --limit N` | `30` | 最多条数（1..100，Search API per_page 上限） |
| `-o, --output FILE` | `feed.xml` | 输出文件路径 |
| `--sort {stars,forks,updated}` | `stars` | Search API 兜底排序 |
| `--min-stars N` | `0` | 过滤总 star 数低于 N 的仓库 |
| `--token TOKEN` | 无 | GitHub token（覆盖 `GITHUB_TOKEN` 环境变量） |
| `--no-fallback` | 关 | 主源失败时不启用 Search API 兜底 |
| `--no-readme-summary` | 关 | 跳过 README 摘要，直接用仓库描述 |
| `--feed-title/--feed-link/--feed-description` | 见 `--help` | 自定义 channel 字段 |
| `--self-link URL` | 无 | 输出 `atom:link rel=self`（RSS 自动发现） |
| `--version` / `-v` | — | 版本 / 详细日志 |

## 数据源说明

| 数据源 | 角色 | 优点 | 限制 |
|---|---|---|---|
| `https://github.com/trending?since=daily` | **主源** | 语义完全匹配「热门/趋势」（按窗口内新增 star 排序）；无需 token、无 API 限流 | 无官方 API，依赖 HTML 结构（解析器容错，主源失败自动切换） |
| GitHub Search API（`created:>=今日-N天` + stars 排序） | **兜底** | 官方稳定 JSON；未认证 10 req/min、认证 30 req/min | 无法还原 Trending 语义（只能近似「新近创建的高 star 仓库」） |

详细选型论证见 [docs/RESEARCH.md](docs/RESEARCH.md)。

## Feed 格式（RSS 2.0）

- **channel**：`title`、`link`、`description`、`language`（zh-CN）、`generator`、`ttl`（1440）、`lastBuildDate`、`docs`，可选 `atom:link rel=self`
- **item**：
  - `title` — 仓库全名（`owner/repo`）
  - `link` — 仓库主页
  - `guid` — 仓库 URL（`isPermaLink="true"`，天然唯一）
  - `pubDate` — 生成时间（RFC 822，每日摘要语义，统一为 UTC）
  - `description` — README 摘要/仓库描述 ＋ 元信息（今日新增 star、总 star、forks、语言、许可证、创建时间）
  - `content:encoded` — 富文本 HTML 版描述

## 每日自动更新（GitHub Actions）

工作流 [.github/workflows/daily-feed.yml](.github/workflows/daily-feed.yml)：

```yaml
on:
  schedule:
    - cron: '0 0 * * *'   # 每天 00:00 UTC（北京时间 08:00）
  workflow_dispatch: {}   # 手动触发（调试/补跑）
permissions:
  contents: write         # 用于提交 feed.xml
```

流程：checkout → setup-python(3.11) → `pip install -r requirements.txt`（零依赖，no-op）→ `python main.py`（自动注入 `GITHUB_TOKEN`）→ `git add -f feed.xml` → 有变化则 commit + push。

> 注：`feed.xml` 为构建产物，已在 `.gitignore` 中忽略，工作流用 `git add -f` 强制提交以对外发布。

### 订阅地址（二选一）

- **raw**：`https://raw.githubusercontent.com/<user>/<repo>/main/feed.xml`（CDN 缓存，通常几分钟内刷新）
- **GitHub Pages**（推荐）：仓库 Settings → Pages → Deploy from a branch（main / root），订阅 `https://<user>.github.io/<repo>/feed.xml`

## 测试

```bash
python tests/test_rss_offline.py       # RSS 2.0 结构与转义（离线）
python tests/test_trending_parser.py   # Trending 页解析器（离线 fixture）
python tests/test_retry_logic.py       # 重试/限流/404 逻辑（本地 HTTP server，离线）
```

三个测试均为标准库实现、无需网络，可在 CI 或本地直接运行。

## 项目结构

```
.
├── .github/workflows/daily-feed.yml   # 每日定时生成 + 提交 feed.xml
├── main.py                            # CLI 入口
├── requirements.txt                   # 零第三方依赖（占位）
├── feed.xml                           # 生成产物（gitignore，由 Actions 提交发布）
├── github_trending/
│   ├── __init__.py                    # 版本号
│   ├── fetcher.py                     # 抓取：Trending 页解析 + Search API 兜底 + 重试/限流/README 摘要
│   └── rss.py                         # RSS 2.0 生成（xml.etree，含转义与命名空间）
├── tests/                             # 离线测试 + fixture
└── docs/RESEARCH.md                   # 数据源/RSS/部署/技术栈选型调研
```

## 常见问题

- **feed 条目数少于 `--limit`**：Trending 页实际渲染行数即上限（约 25 行），属预期。
- **本地无 token 跑默认参数**：README 摘要会并发请求约 30 次，未认证 core 限流 60 次/小时，接近上限时可加 `--no-readme-summary`。
- **`feed.xml` 无法被 `git add`**：该文件在 `.gitignore` 中，需用 `git add -f feed.xml`（工作流已内置）。
