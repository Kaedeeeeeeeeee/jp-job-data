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
pip install jpjobs
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
jpjobs --keyword="IT Support" --pages=3 --output=all-jobs.json
```

Runs every active source in parallel. Takes ~30-60 seconds.

### "Part-time or contract roles"

```bash
jpjobs --keyword="IT Support" --employment-type=contract --format=table
```

### "Save your defaults"

Create `jpjobs.config.json` in the folder you run scans from:

```json
{
  "sources": ["linkedin", "tokyodev", "hellowork"],
  "prefecture": "tokyo",
  "keywords": ["IT Support", "Helpdesk"],
  "pages": 2
}
```

(The file isn't read automatically yet in v0.2 — copy-paste your favorite flags from here.)

---

## Using results with an AI assistant

### Step 1 — scan with the LLM-friendly format

```bash
jpjobs --sources=linkedin,tokyodev,gaijinpot \
       --keyword="IT Support" \
       --format=llm > jobs.txt
```

This produces a compact text block, ~40 tokens per job, capped at 50 jobs.

### Step 2 — open one of the included prompts

```bash
cat prompts/rank-against-resume.md
```

### Step 3 — paste into Claude / ChatGPT / Codex

- Open your AI assistant of choice
- Paste the prompt template from `prompts/rank-against-resume.md`
- Replace `<paste resume here>` with your actual resume
- Replace `<paste jobs here>` with the contents of `jobs.txt`
- Send

The assistant will rank each job 0–10 against your resume and explain why.

### Other prompts in `prompts/`

| Prompt | What it does |
|---|---|
| `rank-against-resume.md` | Score every job against your resume |
| `filter-english-friendly.md` | Score 0–10 on English-friendliness |
| `extract-companies-for-research.md` | Dedup company list with research questions |
| `summarize-market-trends.md` | Aggregate analysis (volume, comp, skills) |
| `write-tailored-cover-letter.md` | Draft a cover letter for one job |

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
- **TokyoDev** filter ignores ≤2-char keywords — use longer search terms
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
- CONTRIBUTING.md → adding a new source
- `prompts/` → ready-to-use AI prompt templates
- Open an issue on GitHub for everything else
