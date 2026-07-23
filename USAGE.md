# Usage Guide

A walkthrough for first-time users, including non-developers.

## Install (one-time, 2 minutes)

### 1. Install Python 3.10+

If you don't have it: https://www.python.org/downloads/ — pick the green "Download Python 3.x" button.

### 2. Install `jpjobs`

Open a terminal:

- **macOS**: press `⌘ + Space`, type "Terminal", hit Enter
- **Windows**: press `Win`, type "PowerShell", hit Enter
- **Linux**: open whatever you usually use

Paste this and hit Enter:

```bash
git clone https://github.com/Kaedeeeeeeeeee/jp-job-data.git
cd jp-job-data
python -m pip install -e .
```

### 3. Install Chromium (only if you want HelloWork or Indeed)

```bash
playwright install chromium
```

The other 8 sources work without this.

---

## Your first scan (30 seconds)

```bash
jpjobs --keyword="IT Support" --prefecture=tokyo --pages=1
```

This returns JSON to your terminal. To make it easier to read:

```bash
jpjobs --keyword="IT Support" --prefecture=tokyo --pages=1 --format=table
```

To save it to a file:

```bash
jpjobs --keyword="IT Support" --prefecture=tokyo --output=jobs.json
```

---

## Common recipes

### "Find English-friendly Tokyo IT roles"

```bash
jpjobs --sources=linkedin,tokyodev,japandev,gaijinpot,jobsinjapan \
       --keyword="IT Support" \
       --prefecture=tokyo \
       --english-filter \
       --format=table
```

### "Just want HelloWork — Japan's biggest board"

```bash
jpjobs --sources=hellowork --keyword=英語 --prefecture=tokyo --pages=2 --format=table
```

The `英語` (English) keyword surfaces foreign-affiliated employers within HelloWork.

### "Cast the widest possible net"

```bash
jpjobs --days=30 --pages=auto --max-pages=50 \
       --fetch-details --output=all-jobs.json
```

Runs every active source, enriches detail fields, and retains only jobs whose
posted dates can be verified inside the requested window. Automatic pagination
continues until the source ends, its newest-first results move beyond the
30-day boundary, or the safety cap is reached. Detail enrichment can take
several minutes.

The JSON `per_source` section records `pages_fetched`,
`pagination_stop_reasons`, and `coverage_complete`. A safety-cap warning means
the output is valid but that source may still have more in-window jobs.

### "Open a simple browser page for manual data review"

```bash
python experiments/build_audit_report.py all-jobs.json \
       --per-source=20 \
       --output=audit/index.html
```

Open `audit/index.html`. The page samples each source evenly, saves review
choices in the browser, and exports the completed review as JSON.

### "Part-time or contract roles"

```bash
jpjobs --keyword="IT Support" --employment-type=contract --format=table
```

### "Keep an incremental local database"

```bash
jpjobs --days=30 --fetch-details --database=jobs.sqlite3 --output=jobs.json
```

Repeated runs preserve each job's first- and last-seen timestamps.

---

## Using results with an AI assistant

### Step 1 — scan with the LLM-friendly format

```bash
jpjobs --sources=linkedin,tokyodev,gaijinpot \
       --keyword="IT Support" \
       --format=llm > jobs.txt
```

This produces a source-balanced text block with descriptions and language
signals, capped at 50 jobs.

### Step 2 — paste into Claude / ChatGPT / Codex

- Open your AI assistant of choice
- Replace `<paste resume here>` with your actual resume
- Replace `<paste jobs here>` with the contents of `jobs.txt`
- Send

The assistant will rank each job 0–10 against your resume and explain why.

---

## Troubleshooting

### `command not found: jpjobs`

`pip` installed it but your shell can't find it. Try:

```bash
python -m jpjobs --help
```

Or check your `PATH`:

```bash
pip show -f jpjobs | grep bin
```

### One source returns 0

Most often one of:
- **HelloWork** needs Japanese keywords — try `--keyword=英語` instead of "English"
- **Indeed / Wellfound / Doda** are marked `experimental` because of anti-bot — expect intermittent empties

Run `jpjobs --list-sources` to see each source's status.

### Browser sources fail

```bash
playwright install chromium
```

Then retry.

### Output is too big for my AI assistant

Switch to `--format=llm` (capped at 50 jobs) and add stricter filters:

```bash
jpjobs --sources=tokyodev --keyword="IT Support" --prefecture=tokyo --format=llm
```

---

## What `jpjobs` will not do

- Apply to jobs for you. (Always review before clicking submit.)
- Store your resume or any personal data. Anything you give to an AI assistant goes to that provider, not to this package.
- Bypass logins on Wantedly / Bizreach / Findy / Lapras. Those are intentionally unsupported.
- Replace your judgment about fit.

---

## Need help?

- README → high-level overview
- AGENTS.md → for AI assistants reading the repo
- `docs/baseline-vs-optimized.md` → reproducible quality comparison
- Open an issue on GitHub for everything else
