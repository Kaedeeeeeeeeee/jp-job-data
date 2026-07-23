# Baseline vs. optimized results

This comparison uses the same 2026-06-23 through 2026-07-23 requested window,
the same 10 active sources, no keyword, all Japan, and a two-page limit.

## Outcome

The optimized pipeline returned fewer final rows because it removed unverifiable
and expired listings, but it more than doubled the number of jobs that could be
confirmed to satisfy the requested 30-day window.

| Metric | Baseline | Optimized | Change |
|---|---:|---:|---:|
| Raw/final rows | 507 | 641 raw / 397 final | 241 filtered, 3 merged |
| Verified in requested window | 193 (38.1%) | 397 (100.0%) | +204 verified jobs |
| Unknown posted date | 301 | 0 | −301 |
| Out-of-window rows in final output | 13 | 0 | −13 |
| Implicit LinkedIn keyword rows | 81 | 0 | −81 |
| Remaining exact cross-source duplicate groups | 7 | 0 | −7 |

## Field completeness

| Field | Baseline | Optimized | Percentage-point change |
|---|---:|---:|---:|
| Company | 96.4% | 100.0% | +3.6 |
| Description snippet | 8.9% | 97.5% | +88.6 |
| Prefecture | 5.9% | 91.7% | +85.8 |
| Employment type | 29.0% | 89.4% | +60.4 |
| Posted date | 40.6% | 100.0% | +59.4 |
| Language signals | 71.2% | 74.3% | +3.1 |
| Wage | 21.7% | 88.4% | +66.7 |

## What changed

1. The default source set now includes active sources only.
2. An omitted keyword remains an unfiltered search instead of activating
   LinkedIn's previous built-in IT-support keyword bundle.
3. All source results pass through shared date, text, location, employment, and
   language normalization.
4. Requested filters are enforced after retrieval, even when a source does not
   support equivalent server-side parameters.
5. Optional detail enrichment parses schema.org `JobPosting` data.
6. HelloWork, Daijob, GaijinPot, JobsInJapan, Green, Forkwell, Wantedly, and
   JapanDev now honor the requested pagination depth.
7. Exact normalized company-and-title matches from different sources are merged
   while retaining every source URL and native ID.
8. Source outcomes distinguish success, no results, partial results, blocks,
   parse errors, and other errors.
9. SQLite persistence records first- and last-seen timestamps for incremental
   runs.
10. LLM output includes job summaries and balances its 50-row sample across
    sources.

## Interpretation

The row count decreased from 507 to 397, but this is an improvement rather than
a loss of coverage:

- the optimized adapters fetched 641 raw listings instead of 507;
- 240 were demonstrably too old;
- 1 had no recoverable date;
- 3 duplicated jobs were merged;
- every retained row can be verified to fall inside the requested window.

The largest remaining gap is language classification. Some Japanese-only sources
do not expose explicit language requirements in listing or structured detail
data, so language signals remain intentionally conservative.

