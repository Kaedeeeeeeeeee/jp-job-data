"""Shared normalization for fields emitted by source adapters."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

from jpjobs.location import PREFECTURES, normalize as normalize_prefecture
from jpjobs.schema import Job


DATE_FORMATS = (
    "%Y-%m-%d",
    "%B %d, %Y",
    "%b %d, %Y",
    "%Y/%m/%d",
    "%Y年%m月%d日",
)

REMOTE_RE = re.compile(
    r"remote|work\s*from\s*home|telecommut|リモート|在宅勤務|在宅ワーク",
    re.I,
)
HYBRID_RE = re.compile(r"hybrid|ハイブリッド", re.I)
ENGLISH_RE = re.compile(r"\benglish\b|英語|英会話", re.I)
BILINGUAL_RE = re.compile(r"\bbilingual\b|バイリンガル|日英", re.I)
JAPANESE_RE = re.compile(r"\bjapanese\b|日本語|JLPT|N[1-5]\b", re.I)

EMPLOYMENT_PATTERNS = (
    ("parttime", re.compile(r"part[ -]?time|アルバイト|パート", re.I)),
    ("contract", re.compile(r"contract|契約社員|有期雇用", re.I)),
    ("dispatch", re.compile(r"dispatch|派遣", re.I)),
    ("freelance", re.compile(r"freelance|業務委託|フリーランス", re.I)),
    ("intern", re.compile(r"intern|インターン", re.I)),
    ("fulltime", re.compile(r"full[ -]?time|正社員", re.I)),
)


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "")).strip()


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    candidate = clean_text(value)
    try:
        return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(candidate, date_format).date()
        except ValueError:
            continue
    return None


def normalize_date(value: str | None) -> str | None:
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else None


def normalize_company(value: str | None) -> str:
    text = clean_text(value)
    text = re.sub(r"\s*[・|]\s*[^|・]{5,80}$", "", text)
    return text


def canonical_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = re.sub(
        r"株式会社|合同会社|有限会社|incorporated|corporation|"
        r"\binc\.?\b|\bltd\.?\b|\bco\.?\s*,?\s*ltd\.?\b",
        "",
        text,
    )
    return re.sub(r"[^0-9a-zぁ-んァ-ン一-龥]+", "", text)


def infer_employment_type(text: str) -> str | None:
    for employment_type, pattern in EMPLOYMENT_PATTERNS:
        if pattern.search(text):
            return employment_type
    return None


def infer_languages(text: str) -> list[str]:
    signals: list[str] = []
    if BILINGUAL_RE.search(text):
        signals.append("bilingual")
    if ENGLISH_RE.search(text):
        signals.append("english")
    if JAPANESE_RE.search(text):
        signals.append("japanese")
    return signals


def _prefecture_name(slug: str | None) -> str | None:
    if not slug:
        return None
    for _, (candidate, english, _) in PREFECTURES.items():
        if candidate == slug:
            return english
    return None


def normalize_job(job: Job) -> Job:
    """Normalize a source job in place while preserving raw source text."""
    job.title = clean_text(job.title)
    job.company = normalize_company(job.company)
    job.description = clean_text(job.description)
    job.description_snippet = clean_text(
        job.description_snippet or job.description[:400]
    )[:400]
    job.workplace = clean_text(job.workplace)
    job.date_posted = normalize_date(job.date_posted)

    detected_prefecture, _ = normalize_prefecture(job.workplace)
    if detected_prefecture:
        # Workplace text is more authoritative than the HelloWork office code.
        job.prefecture = detected_prefecture
    if job.prefecture:
        job.prefecture_name = _prefecture_name(job.prefecture)

    combined = " ".join(
        part
        for part in (
            job.title,
            job.description_snippet,
            job.workplace,
            job.wage.raw,
        )
        if part
    )
    if job.remote is None:
        job.remote = bool(REMOTE_RE.search(combined) or HYBRID_RE.search(combined))
    if not job.employment_type:
        job.employment_type = infer_employment_type(combined)

    inferred_languages = infer_languages(combined)
    job.language = list(dict.fromkeys([*job.language, *inferred_languages]))

    if not job.source_urls:
        job.source_urls = {job.source: job.url}
    if not job.source_ids:
        job.source_ids = {job.source: job.source_id}

    managed_flags = {
        "missing_company",
        "missing_description",
        "missing_date",
        "missing_prefecture",
    }
    flags = set(job.quality_flags) - managed_flags
    if not job.company:
        flags.add("missing_company")
    if not job.description_snippet:
        flags.add("missing_description")
    if not job.date_posted:
        flags.add("missing_date")
    if not job.prefecture:
        flags.add("missing_prefecture")
    job.quality_flags = sorted(flags)
    return job


def job_fingerprint(job: Job) -> str | None:
    """Return a conservative cross-source fingerprint."""
    company = canonical_text(job.company)
    title = canonical_text(job.title)
    if not company or not title:
        return None
    return f"{company}|{title}"
