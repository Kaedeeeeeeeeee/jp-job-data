"""HelloWork (Japan MHLW government job board) source.

Reverse-engineered from the Maba framework — see the README for the form-trick
write-up. HelloWork's search button is locked behind a JavaScript form whose
naïve POST returns empty results because the `action` field gets cleared by
modal overlays. This module sets the leaf checkboxes via page.evaluate(),
hides the modal overlays with display:none, then force-clicks the submit button.
"""

from __future__ import annotations

import re
from typing import Any

from jpjobs.schema import Job, Wage, make_job_id, now_iso
from jpjobs.location import PREFECTURES


name = "hellowork"
description = "Japan MHLW government job board (公開求人)"
status = "active"
requires_browser = True
supports = {
    "prefecture": True,
    "keywords": True,
    "category": True,
    "employment_type": True,
    "language": False,
    "date": True,
    "pagination": True,
}
default_rate_limit_ms = 2000

ENTRY_URL = (
    "https://www.hellowork.mhlw.go.jp/kensaku/GECA110010.do"
    "?action=initDisp&screenId=GECA110010"
)
BASE = "https://www.hellowork.mhlw.go.jp/kensaku"

# Default IT (大分類11) subcategory leaf codes. Setting only the parent box
# doesn't propagate the filter — leaves must be checked directly.
IT_LEAVES_PREFIX = "11"

# English-signal keyword bundle (used when language='english')
ENGLISH_KEYWORDS = [
    "英語",
    "外資",
    "外資系",
    "バイリンガル",
    "グローバル",
    "英文",
    "English",
    "英会話",
]


def _parse_job_row(text: str, kjno: str) -> dict:
    """Extract structured fields from a single table.kyujin inner text."""
    clean = re.sub(r"\s+", " ", text).strip()

    def get(
        label: str,
        stops: tuple[str, ...] = (
            "職種",
            "仕事の内容",
            "仕事内容",
            "事業所名",
            "就業場所",
            "賃金",
            "就業時間",
            "休日",
            "求人番号",
            "画像あり",
            "受付年月日",
            "紹介期限日",
        ),
    ) -> str:
        idx = clean.find(label)
        if idx < 0:
            return ""
        after = clean[idx + len(label) :]
        end = len(after)
        for s in stops:
            if s == label:
                continue
            i = after.find(s)
            if 0 < i < end:
                end = i
        return after[:end].strip()

    title = re.sub(r"\s*職種解説\s*$", "", get("職種"))[:200]
    company = get("事業所名")[:200]
    workplace = get("就業場所")[:200]

    date_match = re.search(
        r"受付年月日\s*[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日", clean
    )
    date_posted = (
        f"{date_match.group(1)}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
        if date_match
        else None
    )

    wage_match = re.search(
        r"賃金[^円]*?([\d,]+\s*円(?:\s*[〜～~]\s*[\d,]+\s*円)?)", clean
    ) or re.search(
        r"(月給|時給|日給|年俸)[^円]*?[\d,]+\s*円(?:[^円]*?[\d,]+\s*円)?", clean
    )
    wage_raw = ""
    wage_min = wage_max = None
    wage_unit = None
    if wage_match:
        wage_raw = re.sub(
            r"\s+",
            "",
            wage_match.group(1) if wage_match.lastindex else wage_match.group(0),
        )
        nums = [int(n.replace(",", "")) for n in re.findall(r"[\d,]+", wage_raw)]
        if nums:
            wage_min = nums[0]
            wage_max = nums[-1] if len(nums) > 1 else nums[0]
        if "月給" in clean or wage_min and wage_min > 100000:
            wage_unit = "monthly"
        elif "時給" in clean:
            wage_unit = "hourly"
        elif "年俸" in clean:
            wage_unit = "annual"
        else:
            wage_unit = "monthly"

    pref_code = kjno[:2] if kjno else None
    pref_slug, pref_name = None, None
    if pref_code and pref_code in PREFECTURES:
        pref_slug, pref_name = PREFECTURES[pref_code][0], PREFECTURES[pref_code][1]

    job_number_fmt = (
        f"{kjno[:5]}-{kjno[5:11]}-{kjno[11:]}"
        if kjno and len(kjno) >= 13
        else kjno or ""
    )

    return {
        "title": title,
        "company": company,
        "workplace": workplace,
        "prefecture": pref_slug,
        "prefecture_name": pref_name,
        "wage": Wage(min=wage_min, max=wage_max, unit=wage_unit, raw=wage_raw),
        "date_posted": date_posted,
        "snippet": clean[:400],
        "job_number_fmt": job_number_fmt,
    }


async def _extract_from_page(page) -> tuple[list[dict], int, bool]:
    """Pull job rows from the current results page."""
    raw = await page.evaluate("""
        () => {
            const tables = document.querySelectorAll('table.kyujin');
            const jobs = [];
            for (const tbl of tables) {
                const detail = tbl.querySelector('a[href*="dispDetailBtn"]');
                if (!detail) continue;
                const href = detail.getAttribute('href') || '';
                const kjno = (href.match(/kJNo=(\\d+)/) || [])[1] || '';
                jobs.push({ kjno, href: href.replace(/^\\.?\\//, ''), text: tbl.innerText || '' });
            }
            const m = document.body.innerText.match(/(\\d+)件中\\s*\\d+/);
            const total = m ? parseInt(m[1]) : jobs.length;
            const nextBtn = document.querySelector(
                'input[name="fwListNaviBtnNext"], a[id*="forwardBtn"], button[id*="forward"]'
            );
            return { jobs, total, hasNext: !!nextBtn };
        }
    """)
    return raw["jobs"], raw["total"], raw["hasNext"]


async def _setup_search(
    page, keyword: str, prefecture: str | None, employment_types: list[str]
) -> None:
    await page.goto(ENTRY_URL, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(700)

    ft = "fulltime" in employment_types
    pt = "parttime" in employment_types

    await page.evaluate(
        """
        ({kw, ft, pt, prefCode, leafPrefix}) => {
            // Employment type
            const ftBox = document.getElementById('ID_ippanCKBox1');
            const ptBox = document.getElementById('ID_ippanCKBox2');
            if (ftBox) ftBox.checked = !!ft;
            if (ptBox) ptBox.checked = !!pt;
            // IT subcategory leaves
            document.querySelectorAll('input[name="easyShokusyuBox"]').forEach(cb => {
                if (cb.value.startsWith(leafPrefix)) cb.checked = true;
            });
            // Parent IT category (UI consistency)
            const dai = document.getElementById('ID_daiEasyShokusyuBox11');
            if (dai) dai.checked = true;
            // Prefecture hidden field
            if (prefCode) {
                const h = document.getElementById('ID_todohukenHidden');
                if (h) h.value = prefCode;
            }
            // Freeword
            if (kw) {
                const fw = document.getElementById('ID_freeWordInput');
                if (fw) fw.value = kw;
            }
        }
    """,
        {
            "kw": keyword,
            "ft": ft,
            "pt": pt,
            "prefCode": prefecture,
            "leafPrefix": IT_LEAVES_PREFIX,
        },
    )

    # Hide modal overlays so they don't intercept the submit click
    await page.evaluate(
        "document.querySelectorAll('.modal_wrap, .mom').forEach(el => el.style.display = 'none')"
    )

    await page.locator("#ID_searchBtn").click(force=True)
    await page.wait_for_load_state("domcontentloaded", timeout=20000)
    await page.wait_for_timeout(1200)


async def scan(opts: dict[str, Any], ctx) -> list[Job]:
    """Run the HelloWork scan with given opts."""
    keywords: list[str] = opts.get("keywords") or [""]
    if opts.get("language") == "english":
        keywords = ENGLISH_KEYWORDS
    prefecture: str | None = opts.get(
        "prefecture_code"
    )  # '13' for Tokyo; pass code, not slug
    pages: int = opts.get("pages", 2)
    employment_types: list[str] = opts.get("employment_types") or ["fulltime"]
    english_filter: bool = opts.get("english_filter", opts.get("language") == "english")

    browser = await ctx.get_browser()
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    page = await context.new_page()

    eng_re = re.compile(
        r"英語|外資|ﾊﾞｲﾘﾝｶﾞﾙ|バイリンガル|グローバル|英文|英会話|English|english|Bilingual|bilingual|global|海外|外国"
    )

    seen: dict[str, Job] = {}
    try:
        for kw in keywords:
            try:
                await _setup_search(page, kw, prefecture, employment_types)
                for page_num in range(1, pages + 1):
                    rows, total, has_next = await _extract_from_page(page)
                    ctx.emit(
                        "source.page",
                        source=name,
                        keyword=kw,
                        page=page_num,
                        rows=len(rows),
                        total=total,
                    )
                    for r in rows:
                        parsed = _parse_job_row(r["text"], r["kjno"])
                        if (
                            prefecture
                            and parsed["prefecture"]
                            != PREFECTURES.get(prefecture, ("",))[0]
                        ):
                            if "東京" not in parsed["workplace"]:
                                continue
                        if english_filter and not eng_re.search(
                            parsed["title"] + parsed["snippet"]
                        ):
                            continue
                        sid = r["kjno"]
                        if sid in seen:
                            continue
                        seen[sid] = Job(
                            id=make_job_id(name, sid),
                            source=name,
                            source_id=sid,
                            url=f"{BASE}/{r['href']}",
                            title=parsed["title"],
                            company=parsed["company"],
                            description=parsed["snippet"],
                            description_snippet=parsed["snippet"],
                            workplace=parsed["workplace"],
                            prefecture=parsed["prefecture"],
                            prefecture_name=parsed["prefecture_name"],
                            wage=parsed["wage"],
                            employment_type="fulltime"
                            if "fulltime" in employment_types
                            else None,
                            date_posted=parsed["date_posted"],
                            matched_keyword=kw or None,
                            scraped_at=now_iso(),
                        )
                    if not has_next or page_num >= pages:
                        break
                    # next page
                    clicked = await page.evaluate("""
                        () => {
                            const b = document.querySelector(
                                'input[name="fwListNaviBtnNext"], a[id*="forwardBtn"], button[id*="forward"]'
                            );
                            if (b) { b.click(); return true; }
                            return false;
                        }
                    """)
                    if not clicked:
                        break
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(1200)
            except Exception as e:
                ctx.emit("source.error", source=name, keyword=kw, error=str(e))
    finally:
        await context.close()
    return list(seen.values())
