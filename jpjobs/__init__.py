"""jpjobs — unified scraper for Japan's major job boards."""

from jpjobs.schema import Job, ScanResult, Wage
from jpjobs.aggregate import scan, list_sources, register_source

__version__ = "0.1.0"
__all__ = ["scan", "list_sources", "register_source", "Job", "ScanResult", "Wage"]
