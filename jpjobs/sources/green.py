"""Green-Japan source — IT/startup jobs in Japan (Japanese site).

Note: green-japan.com is a Next.js/MUI app. The server response includes the
listing markup but with emotion-CSS noise inline. We strip <style> blocks and
extract semantic fields from the cleaned text + image alts.
"""

from __future__ import annotations

import re
from typing import Any

from selectolax.parser import HTMLParser

from jpjobs.schema import Job, make_job_id, now_iso
from jpjobs.util.fetch import make_client, fetch_html


name = "green"
description = "Green-Japan — IT/startup jobs in Japan"
status = "active"
requires_browser = False
supports = {
    "prefecture": False,
    "keywords": True,
    "category": False,
    "employment_type": False,
    "language": False,
}
default_rate_limit_ms = 1500

BASE = "https://www.green-japan.com/search"


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    keywords = opts.get("keywords") or [""]
    seen: dict[str, Job] = {}
    async with make_client() as client:
        for kw in keywords:
            url = BASE if not kw else f"{BASE}?keyword={kw}"
            html = await fetch_html(client, url)
            if not html:
                ctx.emit("source.error", source=name, keyword=kw, error="fetch failed")
                continue
            tree = HTMLParser(html)
            page_count = 0
            for a in tree.css('a[href^="/company/"]'):
                href = a.attributes.get("href") or ""
                m = re.match(r"^/company/(\d+)/job/(\d+)", href)
                if not m:
                    continue
                company_id, job_id = m.group(1), m.group(2)
                sid = f"{company_id}/{job_id}"
                if sid in seen:
                    continue
                # Strip <style> blocks before reading text
                for s in a.css("style"):
                    s.decompose()
                # Company name is the alt of the first image, minus the
                # "<company>のイメージ画像N" or similar suffix
                company = ""
                for img in a.css("img"):
                    alt = (img.attributes.get("alt") or "").strip()
                    if alt:
                        company = re.sub(r"のイメージ画像\d+$", "", alt)
                        company = re.sub(r"のロゴ$", "", company)
                        break
                tokens = [
                    t.strip() for t in a.text(separator="|").split("|") if t.strip()
                ]
                # Skip tokens that match CSS noise (.css-... etc.) — defensive
                tokens = [t for t in tokens if not t.startswith(".") and "{" not in t]
                # Heuristic: title = first token that's not the company name and
                # is reasonably long; otherwise pick the longest short token.
                title = ""
                for t in tokens:
                    if t == company:
                        continue
                    if 6 <= len(t) <= 120:
                        title = t
                        break
                if not title:
                    # Fallback to longest plausible token
                    candidates = [t for t in tokens if t != company and len(t) <= 200]
                    if candidates:
                        title = max(candidates, key=len)
                if not title:
                    continue
                # Workplace: look for a token that includes Japanese prefecture markers
                workplace = ""
                for t in tokens:
                    if re.search(
                        r"(東京都|大阪府|京都府|神奈川県|愛知県|福岡県|北海道|.+県)", t
                    ):
                        workplace = t[:120]
                        break
                if not workplace:
                    workplace = "Japan"
                seen[sid] = Job(
                    id=make_job_id(name, sid),
                    source=name,
                    source_id=sid,
                    url=f"https://www.green-japan.com{href}",
                    title=title[:200],
                    company=company[:120],
                    workplace=workplace,
                    matched_keyword=kw or None,
                    scraped_at=now_iso(),
                )
                page_count += 1
            ctx.emit(
                "source.page", source=name, keyword=kw, rows=page_count, total=len(seen)
            )
    return list(seen.values())
