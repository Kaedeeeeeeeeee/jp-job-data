from jpjobs.output import format_llm
from jpjobs.schema import Job, ScanResult


def job(source, number):
    return Job(
        id=f"{source}-{number}",
        source=source,
        source_id=str(number),
        url=f"https://example.com/{source}/{number}",
        found_on=[source],
        title=f"{source} job {number}",
        company="Example",
        description_snippet="Useful role details.",
        language=["english"],
    )


def test_llm_output_balances_sources_and_includes_matching_context():
    result = ScanResult(
        scanned_at="2026-07-23T00:00:00Z",
        total_kept=5,
        jobs=[
            job("large", 1),
            job("large", 2),
            job("large", 3),
            job("small", 1),
            job("small", 2),
        ],
    )
    output = format_llm(result, max_jobs=4)
    titles = [line for line in output.splitlines() if line.startswith("[")]
    assert "large job 1" in titles[0]
    assert "small job 1" in titles[1]
    assert "Summary: Useful role details." in output
    assert "Language signals: english" in output
