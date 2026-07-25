"""Shared pagination policy for fixed-depth and date-complete scans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from jpjobs.normalize import parse_date


COMPLETE_REASONS = {
    "checkpoint_complete",
    "date_boundary",
    "source_end",
    "server_filtered_end",
    "single_page_source",
}


def page_budget(opts: dict[str, Any], source: str | None = None) -> int:
    """Return the request budget for one source/query combination."""
    if opts.get("auto_pages"):
        source_limits = opts.get("source_max_pages") or {}
        if source and source in source_limits:
            return max(1, int(source_limits[source]))
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
        self.limit = page_budget(opts, source)
        self.ctx = ctx
        self.source = source
        self.keyword = keyword
        self.context = context or {}
        self.checkpoint = opts.get("_checkpoint")
        checkpoint_start = 1
        self.checkpoint_complete = False
        if self.checkpoint:
            checkpoint_start, self.checkpoint_complete = self.checkpoint.resume_state(
                source, keyword, self.context
            )
        manual_start = int((opts.get("start_pages") or {}).get(source, 1))
        self.start_page = max(1, checkpoint_start, manual_start)
        if not self.checkpoint_complete and self.start_page > self.limit:
            raise ValueError(
                f"{source} resume page {self.start_page} exceeds its "
                f"maximum page {self.limit}"
            )
        cutoff = opts.get("cutoff_date")
        self.cutoff = date.fromisoformat(cutoff) if cutoff else None
        self._reported = False

    def page_numbers(self) -> range:
        """Return the one-based pages that still need to be requested."""
        if self.checkpoint_complete:
            completed_page = max(0, self.start_page - 1)
            self._report(
                completed_page,
                PageDecision(True, "checkpoint_complete", True),
            )
            return range(0)
        return range(self.start_page, self.limit + 1)

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
        no_new_tolerance: int = 1,
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
        if added == 0:
            self._consecutive_no_new = getattr(self, "_consecutive_no_new", 0) + 1
        else:
            self._consecutive_no_new = 0

        if rows == 0 and not (stop_on_no_new and has_next is True):
            reason = "server_filtered_end" if server_date_filtered else "source_end"
            decision = PageDecision(True, reason, True, oldest)
        elif has_next is False:
            reason = "server_filtered_end" if server_date_filtered else "source_end"
            decision = PageDecision(True, reason, True, oldest)
        elif total_pages is not None and page >= total_pages:
            decision = PageDecision(True, "source_end", True, oldest)
        elif (
            self.auto
            and date_ordered
            and self.cutoff
            and raw_dates
            and len(parsed_dates) == len(raw_dates)
            and max(parsed_dates) < self.cutoff
        ):
            decision = PageDecision(True, "date_boundary", True, oldest)
        elif stop_on_no_new and self._consecutive_no_new >= max(1, no_new_tolerance):
            decision = PageDecision(True, "repeated_page", False, oldest)
        elif page >= self.limit:
            reason = "safety_cap" if self.auto else "page_limit"
            decision = PageDecision(True, reason, False, oldest)
        else:
            decision = PageDecision(False, oldest_date=oldest)

        if self.checkpoint:
            self.checkpoint.record(
                source=self.source,
                keyword=self.keyword,
                context=self.context,
                page=page,
                reason=decision.reason,
                coverage_complete=decision.coverage_complete,
            )
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
        decision = PageDecision(True, reason, False)
        if self.checkpoint:
            self.checkpoint.record(
                source=self.source,
                keyword=self.keyword,
                context=self.context,
                page=page,
                reason=reason,
                coverage_complete=False,
            )
        self._report(page, decision)
