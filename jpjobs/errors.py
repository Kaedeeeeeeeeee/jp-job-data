"""Typed errors so callers (and AI agents) can react predictably."""


class JPJobsError(Exception):
    """Base error for jpjobs."""


class SchemaDriftError(JPJobsError):
    """A source's DOM/API changed in a way that breaks parsing."""


class MabaSchemaError(SchemaDriftError):
    """HelloWork's Maba framework version drifted."""


class RateLimitError(JPJobsError):
    """A source returned 429 / Cloudflare challenge."""


class LoginRequiredError(JPJobsError):
    """A source requires authentication we don't have."""
