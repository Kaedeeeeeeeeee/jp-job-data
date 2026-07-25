from jpjobs.sources.daijob import _parse_page


def test_daijob_listing_parses_activation_date_and_description():
    html = """
    <article class="job-card">
      <div class="job-card__header-info">
        <a href="/en/jobs/detail/12345">Example Company</a>
      </div>
      <h2 class="job-card__title">
        <a href="/en/jobs/detail/12345?from=list">Platform Engineer</a>
      </h2>
      <dl class="job-card__detail">
        <dt>Location</dt>
        <dd><a>Asia</a><a>Japan</a><a>Tokyo</a></dd>
        <dt>Job Description</dt>
        <dd>Build and operate a reliable cloud platform.</dd>
      </dl>
      <p class="text-end text-secondary">Activated: 2026-07-23</p>
    </article>
    """

    rows, added, jobs = _parse_page(html, "", {})

    assert rows == 1
    assert added == 1
    assert jobs[0].date_posted == "2026-07-23"
    assert jobs[0].description_snippet == (
        "Build and operate a reliable cloud platform."
    )
    assert jobs[0].workplace == "Asia, Japan, Tokyo"
