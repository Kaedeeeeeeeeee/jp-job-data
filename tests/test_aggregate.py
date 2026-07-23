import asyncio

from jpjobs.aggregate import Ctx, _deduplicate, _run_source
from jpjobs.normalize import normalize_job
from jpjobs.schema import Job


def make_job(source, source_id, company="KOMODO", title="Gameplay Engineer"):
    candidate = Job(
        id=f"{source}-{source_id}",
        source=source,
        source_id=source_id,
        url=f"https://example.com/{source}/{source_id}",
        title=title,
        company=company,
        workplace="Tokyo",
    )
    return normalize_job(candidate)


def test_cross_source_exact_jobs_are_merged_with_provenance():
    jobs = [
        make_job("tokyodev", "1", company="Komodo"),
        make_job("japandev", "2", company="KOMODO Inc."),
    ]

    deduplicated, merged = _deduplicate(jobs)

    assert merged == 1
    assert len(deduplicated) == 1
    assert deduplicated[0].found_on == ["tokyodev", "japandev"]
    assert set(deduplicated[0].source_urls) == {"tokyodev", "japandev"}
    assert set(deduplicated[0].source_ids) == {"tokyodev", "japandev"}


def test_same_source_same_title_is_not_cross_source_merged():
    jobs = [
        make_job("green", "1"),
        make_job("green", "2"),
    ]
    deduplicated, merged = _deduplicate(jobs)
    assert merged == 0
    assert len(deduplicated) == 2


def test_internal_source_error_is_not_reported_as_success():
    class Source:
        name = "fake"

        @staticmethod
        async def scan(opts, ctx):
            ctx.emit("source.error", source="fake", error="HTTP 403 blocked")
            return []

    outcome = asyncio.run(_run_source(Source, {}, Ctx()))
    assert outcome.status == "blocked"
    assert "403" in outcome.error
