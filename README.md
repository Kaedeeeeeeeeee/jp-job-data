# jpjobs

> Unified scraper for Japan's major job boards, with AI-assistant integration.

Pure Python. No API keys. No account required. Output drops cleanly into Claude / ChatGPT / Codex for ranking, filtering, and cover-letter drafting.

## Why this exists

- LinkedIn and Indeed index only a fraction of Japan's job market — the rest live on Japanese-language boards.
- HelloWork (Japan's largest government job board, hundreds of thousands of listings) has no working public scraper. Its JavaScript-locked Maba form defeats naive HTTP scrapers.
- Existing alternatives like `python-jobspy` are degrading under LinkedIn's anti-bot.
- No unified job schema exists across Japan boards.

`jpjobs` solves all four behind one CLI and LLM-friendly output.

## Sources

**10 active** sources returning real jobs as of v0.2:

| Slug          | Type                     | Browser? | Description |
|---------------|--------------------------|----------|-------------|
| `hellowork`   | Playwright (Maba form)   | yes      | Japan MHLW government board |
| `linkedin`    | HTTP (jobs-guest)        | no       | LinkedIn public guest endpoint |
| `tokyodev`    | HTTP                     | no       | English-first IT |
| `japandev`    | HTTP                     | no       | English-first IT |
| `daijob`      | HTTP                     | no       | Bilingual professional |
| `gaijinpot`   | HTTP                     | no       | English-speaker general |
| `jobsinjapan` | HTTP                     | no       | English-speaker general |
| `green`       | HTTP                     | no       | IT/startup |
| `forkwell`    | HTTP                     | no       | Engineer-focused |
| `wantedly`    | HTTP                     | no       | Startups (public side) |

**7 experimental** (anti-bot or login walls — contributions welcome):
`indeed`, `careercross`, `jrecin`, `otta`, `wellfound`, `doda`, `enworld`

A typical Tokyo IT-Support scan across the 10 active sources returns **~300–400 deduplicated jobs**.

## Install

```bash
pip install jpjobs
playwright install chromium   # one-time, only for hellowork / indeed
```

## Quickstart

```bash
# List supported sources
jpjobs --list-sources

# Cast the widest net: every source, last 7 days
jpjobs --keyword="IT Support" --pages=2

# Tokyo English-friendly only, ready to paste into an AI assistant
jpjobs --sources=linkedin,tokyodev,japandev,gaijinpot \
       --keyword="IT Support" --prefecture=tokyo \
       --format=llm > jobs.txt
```

See [USAGE.md](./USAGE.md) for a step-by-step walkthrough including troubleshooting.

## CLI reference

| Flag                  | Purpose                                                       |
|-----------------------|---------------------------------------------------------------|
| `--list-sources`      | Show available sources and their capabilities                 |
| `--sources`           | Comma-separated slugs, or `all` (default)                     |
| `--keyword`           | Keyword filter — can be repeated                              |
| `--prefecture`        | One of 47 prefecture slugs (`tokyo`, `osaka`, …)              |
| `--location`          | Free-text location (LinkedIn)                                 |
| `--pages`             | Pagination depth per source (default 2)                       |
| `--days`              | Posted-within window (default 7)                              |
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
| `llm`      | Paste into Claude / ChatGPT (capped at 50 jobs)       |

## Using with AI assistants

See [`AGENTS.md`](./AGENTS.md). Typical flow:

```bash
# 1. Scan
jpjobs --sources=linkedin,tokyodev,gaijinpot \
       --keyword="IT Support" --format=llm > jobs.txt

# 2. Open one of the prompts, paste your resume + jobs.txt into Claude / ChatGPT
cat prompts/rank-against-resume.md
```

Ready-made prompts:

- [`prompts/rank-against-resume.md`](./prompts/rank-against-resume.md)
- [`prompts/filter-english-friendly.md`](./prompts/filter-english-friendly.md)
- [`prompts/extract-companies-for-research.md`](./prompts/extract-companies-for-research.md)
- [`prompts/summarize-market-trends.md`](./prompts/summarize-market-trends.md)
- [`prompts/write-tailored-cover-letter.md`](./prompts/write-tailored-cover-letter.md)

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

## Configuration (optional)

Drop a `jpjobs.config.json` in your working directory:

```json
{
  "sources": ["hellowork", "linkedin", "tokyodev"],
  "prefecture": "tokyo",
  "keywords": ["IT Support", "Helpdesk"],
  "pages": 2
}
```

No accounts, no API keys, no `.env`. Your resume and chat history go to whichever AI provider you paste them into — `jpjobs` never sees them.

## Adding a source

See [CONTRIBUTING.md](./CONTRIBUTING.md). Short version: copy `jpjobs/sources/_template.py`, implement the `scan()` function, register the slug in `aggregate.py`.

## Limitations

- Detail pages aren't scraped — listings only.
- Some boards (Wantedly full apply, Bizreach, Findy) are login-gated and intentionally unsupported.
- Heavy anti-bot sites (Wellfound, Doda from some networks) are shipped as `experimental` stubs.
- Rate limits apply. Large scans take minutes.

## Ethical use

Scrape responsibly. Respect each site's `robots.txt`. Throttle requests. Identify yourself via the default User-Agent. Don't spam employers or mass-apply — job boards exist to serve job seekers and employers both.

## License

MIT — see [LICENSE](./LICENSE).

## Disclaimer

This project is not affiliated with HelloWork, MHLW, LinkedIn, Indeed, TokyoDev, JapanDev, Daijob, CareerCross, GaijinPot, JobsInJapan, Green, Forkwell, Wantedly, or any other listed board. All trademarks belong to their respective owners.
