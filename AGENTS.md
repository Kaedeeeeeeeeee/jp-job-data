# AGENTS.md

If you're an AI assistant reading this, `jpjobs` lets you discover Japan job-board listings on behalf of your user. This document explains how to use it effectively without making assumptions about your user's setup.

## What jpjobs is

A unified Python CLI that scrapes major Japan job boards (HelloWork, LinkedIn, TokyoDev, JapanDev, GaijinPot, JobsInJapan, Daijob, Green, Forkwell, Wantedly + 7 experimental) and normalizes the output into a single job schema. No accounts, no API keys.

## What to ask the user before scanning

Don't assume — ask:

1. **Keywords** — what role are they looking for? (e.g., "IT Support", "Helpdesk", "DevOps")
2. **Location** — one of the 47 prefectures, or "all of Japan"?
3. **Employment type** — fulltime / parttime / contract / freelance?
4. **Language preference** — English-friendly only, or open to Japanese-required?
5. **Resume** (optional) — only if they want jobs ranked against their experience

## For Claude Code users

Run via Bash, parse JSON. Recommended chain:

```bash
jpjobs --sources=linkedin,hellowork \
       --keyword="IT Support" \
       --prefecture=tokyo \
       --english-filter \
       --format=json --output=/tmp/jobs.json

# then:
cat /tmp/jobs.json | jq '.jobs[] | select(.wage.min >= 300000)'
```

After fetching, ask the user for their resume to score each job. Use the prompts in `prompts/`.

## For ChatGPT / web-chat users

The user runs the CLI on their machine with `--format=llm` and pastes the output into the chat. You then apply one of the prompts in `prompts/`:

- `prompts/rank-against-resume.md`
- `prompts/filter-english-friendly.md`
- `prompts/extract-companies-for-research.md`
- `prompts/write-tailored-cover-letter.md`
- `prompts/summarize-market-trends.md`

## Unified job schema (every source returns this shape)

| Field                  | Type             | Notes |
|------------------------|------------------|-------|
| `id`                   | string           | Stable cross-source hash |
| `source`               | string           | `hellowork`, `linkedin`, etc. |
| `source_id`            | string           | Native ID from the source |
| `url`                  | string           | Direct link to posting |
| `found_on`             | array of string  | Sources that surfaced this job (dedup trail) |
| `title`                | string           | Job title |
| `company`              | string           | Employer name |
| `description`          | string           | Full text where available |
| `description_snippet`  | string           | ≤400 chars, LLM-safe |
| `workplace`            | string           | Raw posting text |
| `prefecture`           | string \| null   | `tokyo`, `osaka`, … |
| `prefecture_name`      | string \| null   | `Tokyo` / `東京` |
| `city`                 | string \| null   | |
| `remote`               | boolean \| null  | |
| `wage.min` / `.max`    | number \| null   | JPY |
| `wage.unit`            | string \| null   | `monthly` / `hourly` / `annual` |
| `wage.raw`             | string           | As posted |
| `employment_type`      | string \| null   | `fulltime` / `parttime` / `contract` / `dispatch` / `freelance` / `intern` |
| `date_posted`          | string \| null   | ISO8601 |
| `language`             | array of string  | `english` / `japanese` / `bilingual` signals |
| `matched_keyword`      | string \| null   | Which keyword surfaced this row |
| `scraped_at`           | string           | ISO8601 |

## Token-budget guidance

- `--format=llm` ≈ 40 tokens per job → 50 jobs ≈ 2K tokens
- Raw JSON ≈ 200 tokens per job → 50 jobs ≈ 10K tokens
- Filter aggressively before piping to context-constrained models

## Common workflows

1. **Find English-friendly Tokyo IT roles:**
   `jpjobs --keyword="IT Support" --prefecture=tokyo --english-filter --format=llm`
2. **Score against a resume:** scan → paste output + resume → use `prompts/rank-against-resume.md`
3. **Research companies:** scan → use `prompts/extract-companies-for-research.md`
4. **Daily diff:** save yesterday's JSON, diff against today's

## Pitfalls for AI agents

- **Don't hallucinate fields** not in the JSON — use null checks
- **Don't fabricate URLs** — only cite `url` as given
- **HelloWork URLs are session-bound** — if a URL fails, tell the user to search by `source_id` on hellowork.mhlw.go.jp
- **A source returning empty doesn't mean "no jobs available"** — it can mean rate-limited or anti-bot
- **The user's resume is NOT in this package** — always obtain it from the user directly

## What jpjobs does NOT do

- Apply to jobs on the user's behalf (always require explicit confirmation)
- Store user data
- Bypass authentication (Wantedly full apply, Bizreach, Findy, etc. are intentionally unsupported)
- Replace human judgment about fit
