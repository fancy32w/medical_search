---
name: clinicaltrials-search
description: "综合查询药物/靶点的临床试验进展和行业新闻。(1) ClinicalTrials.gov 临床试验，按 Last Update Posted 时间范围过滤；(2) 药智新闻（news.yaozh.com）；(3) 药渡（data.pharmacodia.com/pharmnews，调官方 API，无需 Tavily），含栏目分类、涉及药物/关键词标签；(4) bydrug（bydrug.pharmcube.com/news/detail）。每源单独抓取并输出标题、链接、发表时间、正文摘要。当用户要求查询药物/化合物（如 BMS-986278、admilparant）或靶点（如 LPA1、PDE4B）的临床试验进展、注册状态、近期新闻报道时使用此 Skill。"
---

# ClinicalTrials + 多源医药新闻 综合搜索 Skill

## 工作流程

用户提供**药物名/化合物编号/靶点**，按以下顺序执行：

### Step 1: ClinicalTrials.gov

> ⚠️ 用户未指定时间范围时**必须**加 `--days 60`。

```bash
python3 scripts/search_trials.py --term BMS-986278 --days 60
```

### Step 2: 药智新闻

```bash
python3 scripts/search_yaozh.py --term BMS-986278 --max 5
```

### Step 3: 药渡 (pharmacodia)

```bash
python3 scripts/search_pharma_news.py --site pharmacodia --term BMS-986278 --max 5
```

> 走药渡官方公开 API（`dapi.pharmacodia.com/api/pharmnews/big_box/search`），**无需 Tavily 也无需登录**。一次返回标题、`brief` 摘要、原文链接（多为微信公众号或外站）、发表日期、来源站点、栏目分类（盘点总结/临床结果首发/药研进展/投融资/并购 等）、自动结构化的 `pnDrugList`（涉及药物列表）和 `pnKeyWordsList`（关键词，含靶点/适应症/公司/阶段）。

### Step 4: bydrug (pharmcube)

```bash
python3 scripts/search_pharma_news.py --site bydrug --term BMS-986278 --max 5
```

> 走 Tavily 搜索 + 直连正文，命中页是 `bydrug.pharmcube.com/news/detail/<hash>`。正文 SSR 公开，多数 `direct` 拿到全文。

Tavily Key 解析顺序（仅药智 + bydrug 路径需要）：`--api-key` > `TAVILY_API_KEY` env > `openclaw config get skills.entries.tavily.apiKey`（容器路径 `/home/openclaw/.openclaw/openclaw.json`，**不是** `/home/ubuntu/...`）。**药渡路径不需要 key。**

---

## 脚本参数

### search_trials.py

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--term` | 必填 | 药物名/化合物编号/INN |
| `--days` | **60** | Last Update Posted 在最近 N 天内 |
| `--status` | 全部 | RECRUITING / COMPLETED / ACTIVE_NOT_RECRUITING 等 |
| `--json` | off | JSON 输出 |

### search_yaozh.py

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--term` | 必填 | 药物名/化合物编号/中文名/靶点 |
| `--max` | 5 | 最多文章数 |
| `--api-key` | 自动 | 通常无需指定 |
| `--json` | off | JSON 输出（含 title/url/date/content/source） |

### search_pharma_news.py（药渡 + bydrug 共用，但走两条不同路径）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--site` | 必填 | `pharmacodia`（药渡，调官方 API）或 `bydrug`（Tavily + 直连） |
| `--term` | 必填 | 药物名/化合物编号/中文名/靶点 |
| `--max` | 5 | 最多文章数 |
| `--api-key` | 自动 | 仅 `--site bydrug` 时需要 Tavily key |
| `--json` | off | JSON 输出 |

**两路径输出字段差异：**

- `--site pharmacodia`：除 title/url/date/content/source/site 外，额外有 `site_name`（原始来源站点，如"药渡 / 医学新视点 / Insight数据库 / Drugs.com"等）、`category`（栏目数组）、`drugs`（涉及药物列表）、`keywords`（关键词列表，含靶点/适应症/公司/阶段）。`source` 永远是 `pharmacodia-api`。
- `--site bydrug`：与 `search_yaozh.py` 同款，四层兜底（direct → tavily-search-raw → tavily-extract → tavily-snippet）。

---

## 输出格式（**严格遵循**）

### ClinicalTrials 部分

每条研究一个卡片：

```
🔬 {药物名} 临床试验追踪（近 {N} 天更新）

{序号}️⃣ {NCT_ID} — {研究简短中文标题}
{状态emoji} 状态：{中文状态}（{一句话解释}）

- 标题： {英文原标题}
- ClinicalTrials.gov ID： {NCT_ID}
- 原文链接： https://clinicaltrials.gov/study/{NCT_ID}
- Sponsor： {sponsor}
- Information Provided By： {info_provided}
- Last Update Posted： {date}
- Study Overview： {中文简述，1-2句}
- Study Start： {date}
- Primary Completion： {date}
- Study Completion： {date}
- Enrollment： {数字} 人（实际入组 / 预估）
- Phase： {phase 或 "未标注（研究类型说明）"}

📌 总结速览

| NCT ID | 适应症 | 状态 | 入组人数 | 主要完成时间 | 链接 |
|--------|--------|------|---------|------------|------|
| ... | ... | ... | ... | ... | [查看](https://clinicaltrials.gov/study/NCT...) |
```

**状态 emoji：** 🟢 RECRUITING ｜ 🔴 ACTIVE_NOT_RECRUITING ｜ 🟡 NOT_YET_RECRUITING ｜ ✅ COMPLETED ｜ ⛔ TERMINATED

**AI 需补充：** 中文短标题 ｜ Study Overview 中文简述 ｜ Phase 为空时根据规模推断 ｜ Enrollment 单位（ACTUAL=实际入组，ESTIMATED=预估，加千分位） ｜ 状态一句话解释。

### 新闻部分（药智 / 药渡 / bydrug 三源通用）

> 🚨 **铁律**：每篇文章都必须出现在输出里——即使正文抓取失败，标题 + 链接 + 时间也来自搜索结果，永远是已知的。**不允许"因为没拿到正文就跳过这条"。**

每个新闻源**单独**输出一组卡片，标题区分来源（药智新闻 / 药渡 / bydrug）。每篇文章一个卡片，**严格按下面格式**：

```
📰 {药物名/靶点} {新闻源} 追踪（共 {N} 篇，按时间倒序）

{序号}️⃣ {标题}
🕐 {YYYY-MM-DD}  ｜  🔗 [原文]({url})  ｜  📥 内容来源：{source}
{仅药渡：📡 来源站点：{site_name}  ｜  🏷 栏目：{category}}

📝 靶点相关摘要：
{3-5 句中文摘要，按以下要素组织——只要原文涉及就写，不涉及就省略；不要塞与靶点无关的背景}
- 机制/化合物：{靶点、作用机制、化合物代号、阶段}
- 临床进展：{试验编号 / Phase / 主要终点 / 数据}
- 竞争格局：{同靶点竞品、市场格局}
- 监管动态：{获批 / 上市 / 突破性疗法 / 优先审评 等}
- 商业事件：{授权 / 合作 / 融资 / 里程碑付款}

📌 总结速览

| 序号 | 时间 | 标题（点击查看） | 核心要点 |
|------|------|-----------------|----------|
| 1 | YYYY-MM-DD | [简短标题](url) | 一句话核心信息 |
| ... | ... | ... | ... |
```

**字段填写规则（不得自行发挥）：**

- **`内容来源`** 字段直接抄脚本 JSON 输出里的 `source` 值：
  - `direct` — 直连抓取成功（药智、bydrug）
  - `pharmacodia-api` — 药渡官方 API 返回（药渡专属，**永远是这个**）
  - `tavily-search-raw` — 直连失败，用 Tavily search 自带全文兜底
  - `tavily-extract` — 用 Tavily Extract API 兜底
  - `tavily-snippet` — 仅有 snippet，正文不可得
  - 空字符串 — 全部兜底失败 → 摘要处写 `⚠️ 正文抓取失败，仅有标题`

- **药渡专属字段**：`site_name` 是原始内容站（"药渡"、"Insight数据库"、"医学新视点"、"Drugs.com" 等），`category` 是栏目数组，两者都直接抄输出，**不要省略**——这是药渡的核心价值之一（看出文章是聚合自哪里、属于哪个栏目）。`drugs` / `keywords` 列表可以在摘要里穿插引用，帮助识别同一篇是否同时涉及多个目标药物。
- **排序**：按发表时间倒序（最新在前）。无日期的排最后。
- **摘要长度**：单篇 3-5 句。**不要复述全文**，不要写市场规模、其他无关药物的背景介绍。
- **总结表**：必须有，行数 = 文章数。`核心要点` 一句话不超过 30 字。
- **不要省略**任何一篇，即使内容重复或质量低。

---

## 常见问题排查

只看 stderr 里的标签前缀判断错误归属——**不要混淆 Tavily 和药智站**：

| stderr 标签 | 含义 | 行动 |
|-------------|------|------|
| `[TAVILY][OK] auth=OK` | Tavily key 有效 | 正常输出，不要再说 key 无效 |
| `[TAVILY][AUTH-FAIL]` 401 | Tavily key 无效/过期 | 检查 `TAVILY_API_KEY` 或 `openclaw.json` |
| `[TAVILY][EMPTY]` | Tavily 未收录该药物 | 换中文名/靶点名/公司名重试 |
| `[YAOZH-DIRECT][BLOCKED]` / `[BYDRUG-DIRECT][BLOCKED]` 403 | 站点反爬（非 key 问题） | 无需处理，脚本会自动兜底 |
| `[FALLBACK][OK]` | 兜底成功拿到正文 | 正常使用，按 `内容来源` 字段标注 |
| `[FALLBACK][EXHAUSTED]` | 仅该篇兜底全失败 | 仍输出标题/链接/时间，摘要处标"⚠️ 正文抓取失败" |
| `[PHARMACODIA-API][OK]` | 药渡 API 返回正常 | 正常使用 |
| `[PHARMACODIA-API][EMPTY]` | 药渡 API 该词无收录 | 换中文名/英文名/靶点重试 |
| `[PHARMACODIA-API][ERR]` | API 异常（一般是网络） | 重试，必要时检查 `dapi.pharmacodia.com` 可达性 |

**典型预期路径**（不是事故）：

```
[YAOZH-DIRECT][BLOCKED] url=...  → [FALLBACK][OK] tavily-search-raw url=...
```

---

## 其它

- ClinicalTrials API 和药渡 pharmnews API 都无需 key
- 药智 / bydrug 两路径走 Tavily，英文化合物编号命中率依赖索引，可改用中文通用名（如"利雷西帕"）
- bydrug 文章间有 ~0.8s 延迟，礼貌抓取；药渡走单次 API 调用，无延迟
- bydrug 命中页限定 `bydrug.pharmcube.com/news/detail/` 形式
- 药渡返回的 `siteUrl` 多数指向**外站**（mp.weixin.qq.com 公众号原文 / drugs.com / pharmaceutical-technology 等）——这是药渡聚合而非自产的体现，不要误以为脚本"漏抓"了药渡自己的页面
