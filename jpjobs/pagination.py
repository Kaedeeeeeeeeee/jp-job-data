"""Shared pagination policy for fixed-depth and date-complete scans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from jpjobs.normalize import parse_date


COMPLETE_REASONS = {
    "date_boundary",
    "source_end",
    "server_filtered_end",
    "single_page_source",
}


def page_budget(opts: dict[str, Any]) -> int:
    """Return the request budget for one source/query combination."""
    if opts.get("auto_pages"):
        return max(1, int(opts.get("max_pages") or 50))
    return max(1, int(opts.get("pages") or 2))


@dataclass(frozen=True)
class PageDecision:
    stop: bool
    reason: str | None = None
    coverage_complete: bool | None = None
    oldest_date: str | None = None


class PaginationController:
    """Make and report conservative stop decisions after each fetched page."""

    def __init__(
        self,
        *,
        opts: dict[str, Any],
        ctx,
        source: str,
        keyword: str = "",
        context: dict[str, Any] | None = None,
    ):
        self.auto = bool(opts.get("auto_pages"))
        self.limit = page_budget(opts)
        self.ctx = ctx
        self.source = source
        self.keyword = keyword
        self.context = context or {}
        cutoff = opts.get("cutoff_date")
        self.cutoff = date.fromisoformat(cutoff) if cutoff else None
        self._reported = False

    def _report(self, page: int, decision: PageDecision) -> None:
        if self._reported or not decision.stop:
            return
        self._reported = True
        self.ctx.emit(
            "source.pagination_stop",
            source=self.source,
            keyword=self.keyword or None,
            page=page,
            reason=decision.reason,
            coverage_complete=decision.coverage_complete,
            cutoff_date=self.cutoff.isoformat() if self.cutoff else None,
            oldest_date=decision.oldest_date,
            **self.context,
        )

    def decide(
        self,
        *,
        page: int,
        rows: int,
        added: int,
        dates: Iterable[str | None] = (),
        has_next: bool | None = None,
        total_pages: int | None = None,
        date_ordered: bool = False,
        server_date_filtered: bool = False,
        stop_on_no_new: bool = False,
    ) -> PageDecision:
        """Return whether to stop after the current page.

        Date stopping is deliberately conservative: every supplied page date
        must be known and older than the inclusive cutoff. Adapters with a
        strict newest-first order may pass only the final (oldest) row date.
        """
        parsed_dates = []
        raw_dates = list(dates)
        for raw in raw_dates:
            parsed = parse_date(raw)
            if parsed:
                parsed_dates.append(parsed)
        oldest = min(parsed_dates).isoformat() if parsed_dates else None

        if rows == 0:
            reason = "server_filtered_end" if server_date_filtered else "source_end"
            decision = PageDecision(True, reason, True, oldest)
        elif has_next is False:
            reason = "server_filtered_end" if server_date_filtered else "source_end"
            decision = PageDecision(True, reason, True, oldest)
        elif total_pages is not None and page >= total_pages:
            decision = PageDecision(True, "source_end", True, oldest)
        elif stop_on_no_new and added == 0:
            decision = PageDecision(True, "repeated_page", False, oldest)
        elif (
            self.auto
            and date_ordered
            and self.cutoff
            and raw_dates
            and len(parsed_dates) == len(raw_dates)
            and max(parsed_dates) < self.cutoff
        ):
            decision = PageDecision(True, "date_boundary", True, oldest)
        elif page >= self.limit:
            reason = "safety_cap" if self.auto else "page_limit"
            decision = PageDecision(True, reason, False, oldest)
        else:
            decision = PageDecision(False, oldest_date=oldest)

        self._report(page, decision)
        return decision

    def single_page(self, rows: int) -> None:
        """Report a source that returns its whole inventory in one response."""
        self._report(
            1,
            PageDecision(
                True,
                "single_page_source",
                True,
            ),
        )

    def abort(self, page: int, reason: str = "request_error") -> None:
        """Report an abnormal stop that cannot establish complete coverage."""
        self._report(page, PageDecision(True, reason, False))
