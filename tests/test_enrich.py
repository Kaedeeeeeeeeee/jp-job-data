from jpjobs.enrich import apply_job_posting, extract_job_posting
from jpjobs.schema import Job


HTML = """
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "Platform Engineer",
  "description": "<p>Build reliable systems with Python.</p>",
  "datePosted": "2026-07-21T10:00:00+09:00",
  "employmentType": "FULL_TIME",
  "hiringOrganization": {"@type": "Organization", "name": "Example Inc."},
  "jobLocation": {
    "@type": "Place",
    "address": {"addressRegion": "東京都", "addressLocality": "港区"}
  },
  "baseSalary": {
    "@type": "MonetaryAmount",
    "currency": "JPY",
    "value": {"minValue": 6000000, "maxValue": 9000000, "unitText": "YEAR"}
  }
}
</script>
"""


def test_extract_and_apply_schema_org_job_posting():
    posting = extract_job_posting(HTML)
    assert posting is not None

    job = Job(
        id="id",
        source="test",
        source_id="source-id",
        url="https://example.com/job",
        title="",
        company="",
    )
    assert apply_job_posting(job, posting)
    assert job.title == "Platform Engineer"
    assert job.company == "Example Inc."
    assert job.description_snippet.startswith("Build reliable systems")
    assert job.date_posted == "2026-07-21"
    assert job.employment_type == "fulltime"
    assert job.prefecture == "tokyo"
    assert job.wage.min == 6000000
    assert job.wage.max == 9000000
    assert job.wage.unit == "annual"


def test_extract_handles_comment_wrapped_jsonld():
    wrapped = HTML.replace('{\n  "@context"', '//<!--\n{\n  "@context"').replace(
        "\n}\n</script>", "\n}\n-->\n</script>"
    )
    assert extract_job_posting(wrapped)["title"] == "Platform Engineer"
