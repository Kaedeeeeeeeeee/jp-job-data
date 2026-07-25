from datetime import date

import pytest

from jpjobs.checkpoint import PageCheckpoint
from jpjobs.cli import _page_mode, _source_page
from jpjobs.pagination import PaginationController, page_budget
from jpjobs.sources.jobsinjapan import _relative_date
from jpjobs.sources.wantedly import _page_job_posts


class Events:
    def __init__(self):
        self.rows = []

    def emit(self, event, **data):
        self.rows.append({"event": event, **data})


def options(*, auto=False, pages=2, max_pages=50):
    return {
        "auto_pages": auto,
        "pages": pages,
        "max_pages": max_pages,
        "cutoff_date": "2026-06-23",
    }


def test_page_mode_accepts_integer_or_auto():
    assert _page_mode("3") == 3
    assert _page_mode("AUTO") is None
    assert page_budget(options(auto=True, max_pages=12)) == 12
    assert _source_page("daijob=250") == ("daijob", 250)


def test_source_specific_page_budget_overrides_global_cap():
    opts = options(auto=True, max_pages=50)
    opts["source_max_pages"] = {"hellowork": 250}

    assert page_budget(opts, "hellowork") == 250
    assert page_budget(opts, "daijob") == 50


def test_auto_date_boundary_requires_every_supplied_date_to_be_old():
    events = Events()
    controller = PaginationController(
        opts=options(auto=True),
        ctx=events,
        source="example",
    )

    first = controller.decide(
        page=1,
        rows=2,
        added=2,
        dates=["2026-06-22", "2026-07-01"],
        date_ordered=True,
    )
    second = controller.decide(
        page=2,
        rows=2,
        added=2,
        dates=["2026-06-22", "2026-06-01"],
        date_ordered=True,
    )

    assert not first.stop
    assert second.reason == "date_boundary"
    assert second.coverage_complete is True
    assert events.rows[-1]["reason"] == "date_boundary"


def test_fixed_limit_and_auto_safety_cap_are_reported_as_incomplete():
    fixed = PaginationController(
        opts=options(pages=2),
        ctx=Events(),
        source="fixed",
    )
    auto = PaginationController(
        opts=options(auto=True, max_pages=3),
        ctx=Events(),
        source="auto",
    )

    fixed_decision = fixed.decide(page=2, rows=10, added=10)
    auto_decision = auto.decide(page=3, rows=10, added=10)

    assert fixed_decision.reason == "page_limit"
    assert fixed_decision.coverage_complete is False
    assert auto_decision.reason == "safety_cap"
    assert auto_decision.coverage_complete is False


def test_source_end_takes_precedence_over_repeated_page():
    controller = PaginationController(
        opts=options(auto=True),
        ctx=Events(),
        source="example",
    )
    decision = controller.decide(
        page=3,
        rows=5,
        added=0,
        has_next=False,
    )
    assert decision.reason == "source_end"
    assert decision.coverage_complete is True


def test_repeated_page_stop_is_explicitly_enabled():
    controller = PaginationController(
        opts=options(auto=True),
        ctx=Events(),
        source="example",
    )
    decision = controller.decide(
        page=2,
        rows=10,
        added=0,
        has_next=True,
        stop_on_no_new=True,
    )
    assert decision.reason == "repeated_page"
    assert decision.coverage_complete is False


def test_repeated_page_tolerance_allows_a_transient_overlap():
    controller = PaginationController(
        opts=options(auto=True),
        ctx=Events(),
        source="wantedly",
    )

    first = controller.decide(
        page=2,
        rows=10,
        added=0,
        has_next=True,
        stop_on_no_new=True,
        no_new_tolerance=3,
    )
    second = controller.decide(
        page=3,
        rows=10,
        added=5,
        has_next=True,
        stop_on_no_new=True,
        no_new_tolerance=3,
    )
    assert not first.stop
    assert not second.stop

    for page in (4, 5):
        decision = controller.decide(
            page=page,
            rows=10,
            added=0,
            has_next=True,
            stop_on_no_new=True,
            no_new_tolerance=3,
        )
        assert not decision.stop
    third = controller.decide(
        page=6,
        rows=10,
        added=0,
        has_next=True,
        stop_on_no_new=True,
        no_new_tolerance=3,
    )
    assert third.reason == "repeated_page"


def test_date_boundary_takes_precedence_over_repeated_page():
    controller = PaginationController(
        opts=options(auto=True),
        ctx=Events(),
        source="wantedly",
    )
    decision = controller.decide(
        page=4,
        rows=10,
        added=0,
        dates=["2026-06-22"] * 10,
        has_next=True,
        date_ordered=True,
        stop_on_no_new=True,
    )
    assert decision.reason == "date_boundary"
    assert decision.coverage_complete is True


def test_empty_page_with_claimed_next_page_uses_repeat_tolerance():
    controller = PaginationController(
        opts=options(auto=True),
        ctx=Events(),
        source="wantedly",
    )
    first = controller.decide(
        page=20,
        rows=0,
        added=0,
        has_next=True,
        stop_on_no_new=True,
        no_new_tolerance=3,
    )
    second = controller.decide(
        page=21,
        rows=0,
        added=0,
        has_next=True,
        stop_on_no_new=True,
        no_new_tolerance=3,
    )
    third = controller.decide(
        page=22,
        rows=0,
        added=0,
        has_next=True,
        stop_on_no_new=True,
        no_new_tolerance=3,
    )

    assert not first.stop
    assert not second.stop
    assert third.reason == "repeated_page"
    assert third.coverage_complete is False


def test_checkpoint_resumes_at_next_page_and_validates_parameters(tmp_path):
    path = tmp_path / "scan.checkpoint.json"
    parameters = {"days": 30, "as_of": "2026-07-25"}
    checkpoint = PageCheckpoint(path, parameters=parameters)
    opts = options(auto=True, max_pages=100)
    opts["_checkpoint"] = checkpoint
    controller = PaginationController(
        opts=opts,
        ctx=Events(),
        source="daijob",
    )
    controller.decide(page=50, rows=20, added=20)

    resumed_checkpoint = PageCheckpoint(path, parameters=parameters)
    resumed_opts = options(auto=True, max_pages=100)
    resumed_opts["_checkpoint"] = resumed_checkpoint
    resumed = PaginationController(
        opts=resumed_opts,
        ctx=Events(),
        source="daijob",
    )

    assert resumed.start_page == 51
    assert list(resumed.page_numbers())[:2] == [51, 52]
    with pytest.raises(ValueError, match="parameters do not match"):
        PageCheckpoint(
            path,
            parameters={"days": 7, "as_of": "2026-07-25"},
        )


def test_checkpoint_does_not_regress_when_session_replay_fails(tmp_path):
    path = tmp_path / "scan.checkpoint.json"
    checkpoint = PageCheckpoint(path, parameters={"days": 30})
    checkpoint.record(
        source="hellowork",
        keyword="",
        context={},
        page=250,
        reason="safety_cap",
        coverage_complete=False,
    )
    checkpoint.record(
        source="hellowork",
        keyword="",
        context={},
        page=1,
        reason="resume_replay_failed",
        coverage_complete=False,
    )

    assert checkpoint.resume_state("hellowork") == (251, False)


def test_jobs_in_japan_relative_date_uses_reproducible_as_of():
    as_of = date(2026, 7, 23)
    assert _relative_date("4 days ago", as_of) == "2026-07-19"
    assert _relative_date("2 hours ago", as_of) == "2026-07-23"


def test_wantedly_uses_only_requested_offset_page():
    first_ref = 'JobPost:{"id":"1"}'
    recommendation_ref = 'JobPost:{"id":"999"}'
    apollo = {
        "ROOT_QUERY": {
            "projectIndexPageJobPostIndex": {
                (
                    'searchedJobPostsUsingOffset({"input":{"pageNumber":2,'
                    '"pageSize":10,"searchParameters":null}})'
                ): {
                    "jobPosts": [{"jobPost": {"__ref": first_ref}}],
                    "totalCount": 25,
                }
            }
        },
        first_ref: {"id": "1", "title": "Requested result"},
        recommendation_ref: {"id": "999", "title": "Cached recommendation"},
    }

    rows, total, has_next = _page_job_posts(apollo, 2)

    assert [row[0] for row in rows] == ["1"]
    assert total == 25
    assert has_next is True
