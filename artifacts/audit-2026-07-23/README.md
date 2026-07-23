# Manual audit sample

Open [`index.html`](./index.html) in a browser.

- Input: `artifacts/optimized-2026-07-23/jobs.json`
- Input rows: 397
- Sampling rule: up to 20 evenly spaced rows per source
- Sample rows: 136
- Sources represented with jobs: 9
- Source shown with zero jobs: Forkwell

Review choices are stored in the browser's local storage and are not written
back to this repository. Use **导出审核结果** in the page to save a JSON copy.

## Review outcome

The manual review accepted the other sources' data quality and rejected
LinkedIn's public guest listings as too vague and incomplete for routine use.
LinkedIn remains reproducible in the historical artifacts but is opt-in from
v0.4 onward; default scans now use nine active sources.
