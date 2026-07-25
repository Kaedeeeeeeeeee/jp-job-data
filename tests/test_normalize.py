from jpjobs.normalize import canonical_text, normalize_job, parse_date
from jpjobs.schema import Job


def make_job(**overrides):
    values = {
        "id": "id",
        "source": "test",
        "source_id": "source-id",
        "url": "https://example.com/job",
    }
    values.update(overrides)
    return Job(**values)


def test_parse_supported_dates():
    assert parse_date("2026-07-23").isoformat() == "2026-07-23"
    assert parse_date("2026-07-23T04:00:00Z").isoformat() == "2026-07-23"
    assert parse_date("July 23, 2026").isoformat() == "2026-07-23"
    assert parse_date("2026年7月23日").isoformat() == "2026-07-23"


def test_normalize_job_fills_shared_fields_from_raw_text():
    job = make_job(
        title="  Backend   Engineer ",
        company="Example 株式会社",
        workplace="東京都 港区・ハイブリッド勤務",
        description_snippet="正社員。English and Japanese required.",
        date_posted="July 23, 2026",
    )

    normalize_job(job)

    assert job.title == "Backend Engineer"
    assert job.prefecture == "tokyo"
    assert job.prefecture_name == "Tokyo"
    assert job.remote is True
    assert job.employment_type == "fulltime"
    assert job.date_posted == "2026-07-23"
    assert set(job.language) == {"english", "japanese"}
    assert job.source_urls == {"test": job.url}
    assert "missing_date" not in job.quality_flags


def test_canonical_text_removes_company_form_and_width_variants():
    assert canonical_text("株式会社 ＫＯＭＯＤＯ") == canonical_text("KOMODO Inc.")
