# Prompts

Copy-pasteable prompts for AI assistants. Each is designed to run RIGHT AFTER `jpjobs --format=llm`.

## How to use these (no coding required)

1. Run a scan to get jobs:
   ```bash
   jpjobs --sources=linkedin,hellowork --keyword="IT Support" --prefecture=tokyo --format=llm > jobs.txt
   ```
2. Open `jobs.txt` and copy everything.
3. Open the prompt file you want (e.g., `rank-against-resume.md`).
4. Copy the prompt body into your AI assistant (Claude / ChatGPT / Codex).
5. Replace the `<paste jobs here>` and `<paste resume here>` placeholders.
6. Send.

## Available prompts

- [`rank-against-resume.md`](./rank-against-resume.md) — rank by fit against your resume
- [`filter-english-friendly.md`](./filter-english-friendly.md) — score 0–10 on English-friendliness
- [`extract-companies-for-research.md`](./extract-companies-for-research.md) — dedup + research questions per company
- [`summarize-market-trends.md`](./summarize-market-trends.md) — aggregate analysis
- [`write-tailored-cover-letter.md`](./write-tailored-cover-letter.md) — given one job + resume, draft a letter
