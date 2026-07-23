from datetime import date

from jpjobs.filtering import evaluate_job
from jpjobs.schema import Job


def job(**overrides):
    values = {
        "id": "id",
        "source": "test",
        "source_id": "source-id",
        "url": "https://example.com/job",
        "title": "Software Engineer",
        "company": "Example",
        "workplace": "Tokyo",
        "prefecture": "tokyo",
        "employment_type": "fulltime",
        "date_posted": "2026-07-20",
        "language": ["english"],
    }
    values.update(overrides)
    return Job(**values)


def evaluate(candidate, **overrides):
    options = {
        "keywords": None,
        "prefecture": None,
        "days": 30,
        "as_of": date(2026, 7, 23),
        "employment_types": None,
        "language": None,
        "include_unknown_dates": False,
    }
    options.update(overrides)
    return evaluate_job(candidate, **options)


def test_date_window_is_strict_by_default():
    assert evaluate(job()).keep
    assert evaluate(job(date_posted="2026-06-01")).reason == "before_date_window"
    assert evaluate(job(date_posted=None)).reason == "unknown_date"
    assert evaluate(job(date_posted="2026-07-24")).reason == "after_date_window"


def test_unknown_dates_can_be_retained_explicitly():
    assert evaluate(job(date_posted=None), include_unknown_dates=True).keep


def test_global_filters_apply_consistently():
    candidate = job(
        title="Backend Engineer",
        description_snippet="Python platform",
        language=["bilingual"],
    )
    assert evaluate(candidate, keywords=["Python"]).keep
    assert evaluate(candidate, keywords=["Sales"]).reason == "keyword_mismatch"
    assert evaluate(candidate, prefecture="osaka").reason == "prefecture_mismatch"
    assert evaluate(candidate, employment_types=["contract"]).reason == (
        "employment_type_mismatch"
    )
    assert evaluate(candidate, language="english").keep
