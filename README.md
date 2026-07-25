# jp-job-data / jpjobs 0.4

> Unified scraper for Japan's major job boards, with AI-assistant integration.

Pure Python. No API keys. No account required. Output drops cleanly into Claude / ChatGPT / Codex for ranking, filtering, and cover-letter drafting.

This repository starts from the PyPI `jpjobs==0.2.0` source distribution and
adds reproducible data-quality improvements. See
[the baseline comparison](./docs/baseline-vs-optimized.md) and
[the audit and automatic-pagination guide](./docs/audit-and-auto-pagination.md),
plus
[upstream provenance](./UPSTREAM.md).

The optimized pipeline adds:

- strict, source-independent post-filtering;
- optional schema.org `JobPosting` detail enrichment;
- normalized dates, prefectures, employment types, and language signals;
- real pagination for the supported active boards;
- date-aware automatic pagination with explicit coverage status and safety caps;
- cross-source deduplication with retained source URLs and native IDs;
- explicit source health states and filter reasons;
- optional SQLite persistence for incremental runs;
- source-balanced LLM output with job summaries.

## Why this exists

- LinkedIn and Indeed index only a fraction of Japan's job market — the rest live on Japanese-language boards.
- HelloWork (Japan's largest government job board, hundreds of thousands of listings) has no working public scraper. Its JavaScript-locked Maba form defeats naive HTTP scrapers.
- Existing alternatives like `python-jobspy` are degrading under LinkedIn's anti-bot.
- No unified job schema exists across Japan boards.

`jpjobs` solves all four behind one CLI and LLM-friendly output.

## Sources

**9 active** sources returning real jobs as of v0.4:

| Slug          | Type                     | Browser? | Description |
|---------------|--------------------------|----------|-------------|
| `hellowork`   | Playwright (Maba form)   | yes      | Japan MHLW government board |
| `tokyodev`    | HTTP                     | no       | English-first IT |
| `japandev`    | HTTP                     | no       | English-first IT |
| `daijob`      | HTTP                     | no       | Bilingual professional |
| `gaijinpot`   | HTTP                     | no       | English-speaker general |
| `jobsinjapan` | HTTP                     | no       | English-speaker general |
| `green`       | HTTP                     | no       | IT/startup |
| `forkwell`    | HTTP                     | no       | Engineer-focused |
| `wantedly`    | HTTP                     | no       | Startups (public side) |

**8 opt-in / experimental** sources:
`linkedin`, `indeed`, `careercross`, `jrecin`, `otta`, `wellfound`, `doda`,
`enworld`

LinkedIn remains available when explicitly requested, but it is excluded from
`--sources=all` because its public guest listings were consistently too vague
for this project's quality bar: descriptions, responsibilities, and
compensation were often missing or non-actionable.

A typical broad scan across the 9 active sources returns hundreds of
deduplicated jobs.

## Install

```bash
git clone https://github.com/Kaedeeeeeeeeee/jp-job-data.git
cd jp-job-data
python -m pip install -e .
playwright install chromium   # one-time, only for hellowork / indeed
```

## Quickstart

```bash
# List supported sources
jpjobs --list-sources

# Verified jobs posted in the last 30 days, with date-aware pagination
jpjobs --days=30 --pages=auto --max-pages=50 \
       --fetch-details --output=jobs.json

# Tokyo English-friendly only, ready to paste into an AI assistant
jpjobs --sources=tokyodev,japandev,gaijinpot \
       --keyword="IT Support" --prefecture=tokyo \
       --format=llm > jobs.txt
```

See [USAGE.md](./USAGE.md) for a step-by-step walkthrough including troubleshooting.

## CLI reference

| Flag                  | Purpose                                                       |
|-----------------------|---------------------------------------------------------------|
| `--list-sources`      | Show available sources and their capabilities                 |
| `--sources`           | Comma-separated slugs; `all` means active sources only         |
| `--keyword`           | Keyword filter — can be repeated                              |
| `--prefecture`        | One of 47 prefecture slugs (`tokyo`, `osaka`, …)              |
| `--location`          | Free-text location (LinkedIn)                                 |
| `--pages`             | Page depth, or `auto` to continue through the date window     |
| `--max-pages`         | Per-source safety cap for automatic pagination (default 50)   |
| `--source-max-pages`  | Override the auto cap for one source (`SOURCE=N`; repeatable)  |
| `--start-page`        | Resume one source at a page (`SOURCE=N`; repeatable)           |
| `--checkpoint`        | Save page progress to JSON and resume matching scans           |
| `--days`              | Posted-within window (default 7)                              |
| `--as-of`             | Reproducible end date for the window (`YYYY-MM-DD`)           |
| `--include-unknown-dates` | Keep rows whose posted date cannot be verified            |
| `--fetch-details`     | Parse schema.org data from detail pages                       |
| `--database`          | Upsert the result into a SQLite database                      |
| `--employment-type`   | `fulltime` / `parttime` / `contract` / `dispatch` / `freelance` / `intern` |
| `--language`          | `english` / `japanese` / `bilingual`                          |
| `--english-filter`    | Post-filter results for English-signal jobs                   |
| `--format`            | `json` (default) / `csv` / `markdown` / `table` / `llm`       |
| `--output`            | Write to file instead of stdout                               |
| `--quiet`             | Suppress progress events on stderr                            |
| `--no-headless`       | Run browser in visible mode (debugging)                       |
| `--rate-limit`        | Inter-request pacing in ms (default 700)                      |

## Output formats

| Format     | Best for                                              |
|------------|-------------------------------------------------------|
| `json`     | Pipe to `jq` or downstream code                       |
| `csv`      | Open in spreadsheets                                  |
| `markdown` | Embed in a GitHub README                              |
| `table`    | Read in the terminal                                  |
| `llm`      | Source-balanced sample with summaries (capped at 50)  |

## Using with AI assistants

See [`AGENTS.md`](./AGENTS.md). Typical flow:

```bash
# 1. Scan
jpjobs --sources=tokyodev,japandev,gaijinpot \
       --keyword="IT Support" --format=llm > jobs.txt

# 2. Open one of the prompts, paste your resume + jobs.txt into Claude / ChatGPT
cat prompts/rank-against-resume.md
```

## Job schema

Every source returns the same shape. Useful when piping to `jq` or AI assistants:

| Field                  | Type           | Notes |
|------------------------|----------------|-------|
| `id`                   | string         | Stable cross-source hash |
| `source`               | string         | `hellowork`, `linkedin`, etc. |
| `url`                  | string         | Direct link to posting |
| `title`                | string         | Job title |
| `company`              | string         | Employer name |
| `description_snippet`  | string         | ≤400 chars, LLM-safe |
| `workplace`            | string         | Raw posting text |
| `prefecture`           | string \| null | Normalized slug (`tokyo`, `osaka`, …) |
| `prefecture_name`      | string \| null | `Tokyo` / `東京` |
| `wage.min` / `.max`    | number \| null | JPY |
| `wage.unit`            | string \| null | `monthly` / `hourly` / `annual` |
| `employment_type`      | string \| null | `fulltime` / `parttime` / `contract` / … |
| `date_posted`          | string \| null | ISO8601 |
| `language`             | array          | `english`, `japanese`, `bilingual` signals |
| `source_urls`          | object         | URL retained for every matching source |
| `source_ids`           | object         | Native ID retained for every matching source |
| `quality_flags`        | array          | Explicit missing-field signals |
| `first_seen_at` / `last_seen_at` | string \| null | Populated by SQLite persistence |

No accounts, no API keys, no `.env`. Your resume and chat history go to whichever AI provider you paste them into — `jpjobs` never sees them.

## Adding a source

Copy `jpjobs/sources/_template.py`, implement the `scan()` function, and
register the slug in `aggregate.py`.

## Limitations

- Detail pages are fetched only when `--fetch-details` is supplied.
- `--pages=auto` stops at the date boundary only when a source has a reliable
  newest-first signal. Otherwise it runs to the source end or `--max-pages`.
- A safety-cap or repeated-page stop is reported as incomplete coverage rather
  than silently claiming the whole window was collected.
- Strict date filtering excludes unknown dates unless `--include-unknown-dates`
  is supplied.
- Some boards (Wantedly full apply, Bizreach, Findy) are login-gated and intentionally unsupported.
- Heavy anti-bot sites (Wellfound, Doda from some networks) are shipped as `experimental` stubs.
- Rate limits apply. Large scans take minutes.

## Ethical use

Scrape responsibly. Respect each site's `robots.txt`. Throttle requests. Identify yourself via the default User-Agent. Don't spam employers or mass-apply — job boards exist to serve job seekers and employers both.

## License

MIT — see [LICENSE](./LICENSE).

## Disclaimer

This project is not affiliated with HelloWork, MHLW, LinkedIn, Indeed, TokyoDev, JapanDev, Daijob, CareerCross, GaijinPot, JobsInJapan, Green, Forkwell, Wantedly, or any other listed board. All trademarks belong to their respective owners.
