---
name: clinicaltrials-search
description: "综合查询药物/靶点的临床试验进展和行业新闻。(1) 在 ClinicalTrials.gov 上搜索临床试验，支持按 Last Update Posted 时间范围过滤，整理 NCT ID、状态、Sponsor、入组人数、Phase 等关键字段；(2) 在药智新闻（news.yaozh.com）上搜索同一药物/靶点的相关报道，抓取全文并提取与靶点相关的内容摘要，输出标题、链接、发表时间。当用户要求查询药物/化合物（如 BMS-986278、admilparant）或靶点（如 LPA1、PDE4B）的临床试验进展、注册状态、近期新闻报道时使用此 Skill。"
---

# ClinicalTrials + 药智新闻 综合搜索 Skill

## 工作流程

用户提供**药物名/化合物编号/靶点**，完整流程分两步：

### Step 1: ClinicalTrials.gov 搜索

> ⚠️ **默认使用 `--days 60`**，除非用户明确指定时间范围，否则始终加上 `--days 60`。

```bash
python3 scripts/search_trials.py --term BMS-986278 --days 60
```

### Step 2: 药智新闻搜索

```bash
# API key 自动从 /home/ubuntu/.openclaw/openclaw.json 读取
python3 scripts/search_yaozh.py --term BMS-986278 --max 5
```

**获取 Tavily Key（脚本自动处理，无需手动操作）：**
```python
import json
d = json.load(open('/home/ubuntu/.openclaw/openclaw.json'))
api_key = d['skills']['entries']['tavily']['apiKey']
```

---

## search_trials.py 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--term` | 必填 | 搜索词（药物名、化合物、INN 等） |
| `--days` | **60（固定默认）** | Last Update Posted 在最近 N 天内；**用户未指定时间范围时固定用 60，不得省略** |
| `--status` | (全部) | 状态过滤：RECRUITING / COMPLETED / ACTIVE_NOT_RECRUITING 等 |
| `--json` | off | 输出 JSON |

输出字段：NCT ID、Title、Status、Sponsor、Information Provided By、Last Update Posted、Study Start、Primary Completion、Study Completion、Enrollment、Phase、Study Overview

## search_yaozh.py 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--term` | 必填 | 搜索词（支持英文化合物编号、中文名、靶点名） |
| `--max` | 5 | 最多获取文章数 |
| `--api-key` | 自动读取 | Tavily API key（通常无需指定） |
| `--json` | off | 输出 JSON（含 title/url/date/content 完整字段） |

---

## 格式化输出指南

### ClinicalTrials 部分

严格按以下格式输出，每条研究一个卡片：

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

**状态 emoji 对照：**
- 🟢 RECRUITING → Recruiting（招募中）
- 🔴 ACTIVE_NOT_RECRUITING → Active, Not Recruiting（招募已关闭，研究进行中）
- 🟡 NOT_YET_RECRUITING → Not Yet Recruiting（尚未开始招募）
- ✅ COMPLETED → Completed（已完成）
- ⛔ TERMINATED → Terminated（已终止）

**AI 需要补充的字段（脚本不输出，需要自行推断）：**
- **研究简短中文标题**：根据标题和适应症自行概括，例如「IPF 关键 III 期研究」「TQT 安全性研究」「长期延伸研究（LTE）」
- **Study Overview 中文简述**：将英文摘要翻译/概括为 1-2 句中文
- **Phase 补充说明**：Phase 为空时，根据研究规模和设计推断并注明，如「未标注（关键疗效研究）」
- **Enrollment 单位**：ACTUAL → 实际入组，ESTIMATED → 预估；数字加千分位逗号
- **状态一句话解释**：括号内补充说明，如「招募已关闭，研究进行中」

### 药智新闻部分
对每篇文章，提取并输出：
1. **标题**
2. **链接**
3. **发表时间**
4. **与搜索靶点相关的内容摘要**（机制、临床数据、竞争格局、监管动态等）

忽略与靶点无关的背景段落（市场规模、其他药物介绍等），聚焦用户关心的靶点信息。

---

## 注意事项

- ClinicalTrials API 无需 key，直接调用
- 药智新闻搜索依赖 Tavily（site:news.yaozh.com），需要有效 API key
- 药智新闻的英文化合物编号搜索效果依赖 Tavily 索引覆盖，也可用中文通用名搜索（如「利雷西帕」）
- `search_yaozh.py` 抓取文章时有 0.5s 礼貌延迟，避免 IP 封禁
