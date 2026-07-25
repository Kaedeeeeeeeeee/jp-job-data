from experiments.build_audit_report import build_sample, render_html


def job(source, number):
    return {
        "id": f"{source}-{number}",
        "source": source,
        "source_id": str(number),
        "url": f"https://example.com/{source}/{number}",
        "title": f"Job {number}",
        "company": "Example",
    }


def test_audit_sample_is_source_balanced_and_self_contained():
    payload = {
        "scanned_at": "2026-07-23T00:00:00Z",
        "total_kept": 6,
        "jobs": [
            *[job("green", number) for number in range(5)],
            job("wantedly", 1),
        ],
    }

    samples, sources = build_sample(payload, per_source=2)
    html = render_html(
        payload=payload,
        samples=samples,
        source_summary=sources,
        source_path="jobs.json",
    )

    assert sum(row["source"] == "green" for row in samples) == 2
    assert sum(row["source"] == "wantedly" for row in samples) == 1
    assert "jpjobs 数据抽检" in html
    assert "导出审核结果" in html
    assert "https://example.com/green/" in html
