import asyncio

import jpjobs.aggregate as aggregate
from jpjobs.aggregate import Ctx, _deduplicate, _run_source
from jpjobs.enrich import DetailStats
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


def test_incremental_detail_fetch_skips_known_source_ids(monkeypatch):
    class Source:
        name = "fake"
        status = "active"

        @staticmethod
        async def scan(opts, ctx):
            ctx.emit(
                "source.pagination_stop",
                source="fake",
                reason="source_end",
                coverage_complete=True,
            )
            return [
                make_job("fake", "known"),
                make_job("fake", "new"),
            ]

    attempted = []

    async def fake_enrich(jobs, **_):
        attempted.extend(job.source_id for job in jobs)
        return jobs, {"fake": DetailStats(attempted=len(jobs))}

    monkeypatch.setitem(aggregate._EXTRA_SOURCES, "fake", Source)
    monkeypatch.setattr(aggregate, "enrich_jobs", fake_enrich)
    result = asyncio.run(
        aggregate.scan(
            sources=["fake"],
            days=None,
            fetch_details=True,
            skip_detail_keys={("fake", "known")},
        )
    )

    assert attempted == ["new"]
    assert result.total_kept == 2
