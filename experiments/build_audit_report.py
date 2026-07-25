#!/usr/bin/env python3
"""Build a self-contained browser review page from a jpjobs JSON result."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


EXPECTED_SOURCES = (
    "hellowork",
    "linkedin",
    "tokyodev",
    "japandev",
    "daijob",
    "gaijinpot",
    "jobsinjapan",
    "green",
    "forkwell",
    "wantedly",
)


def _sample_evenly(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Select deterministic samples across the full date-ordered source result."""
    if len(rows) <= count:
        return rows
    if count == 1:
        return [rows[0]]
    indexes = {
        round(position * (len(rows) - 1) / (count - 1)) for position in range(count)
    }
    return [rows[index] for index in sorted(indexes)]


def build_sample(
    payload: dict[str, Any], per_source: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_source: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for job in payload.get("jobs") or []:
        by_source[job.get("source") or "unknown"].append(job)

    reported_sources = [
        row.get("name") for row in payload.get("per_source") or [] if row.get("name")
    ]
    sources = list(
        dict.fromkeys([*EXPECTED_SOURCES, *reported_sources, *sorted(by_source)])
    )
    source_summary: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    for source in sources:
        rows = by_source.get(source, [])
        selected = _sample_evenly(rows, per_source)
        source_summary.append(
            {
                "source": source,
                "available": len(rows),
                "sampled": len(selected),
            }
        )
        for job in selected:
            samples.append(job)
    return samples, source_summary


def render_html(
    *,
    payload: dict[str, Any],
    samples: list[dict[str, Any]],
    source_summary: list[dict[str, Any]],
    source_path: str,
) -> str:
    data = {
        "scanned_at": payload.get("scanned_at"),
        "total_kept": payload.get("total_kept", len(payload.get("jobs") or [])),
        "source_path": source_path,
        "sources": source_summary,
        "jobs": samples,
    }
    embedded = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>jpjobs 数据抽检</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17211b;
      --muted: #657169;
      --line: #dce4de;
      --paper: #fbfcf8;
      --panel: #ffffff;
      --green: #146c43;
      --green-soft: #e4f4ea;
      --amber: #936214;
      --amber-soft: #fff3d6;
      --red: #a33a32;
      --red-soft: #fde8e5;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.55;
    }}
    button, input, textarea, select {{ font: inherit; }}
    .shell {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; }}
    header {{
      position: sticky;
      top: 0;
      z-index: 20;
      border-bottom: 1px solid var(--line);
      background: rgba(251, 252, 248, .96);
      backdrop-filter: blur(12px);
    }}
    .header-inner {{ padding: 18px 0 14px; }}
    h1 {{ margin: 0; font-size: clamp(24px, 4vw, 38px); letter-spacing: -.03em; }}
    .subtitle {{ color: var(--muted); margin-top: 4px; }}
    .toolbar {{
      display: grid;
      grid-template-columns: minmax(180px, 1fr) minmax(170px, 240px) auto auto;
      gap: 10px;
      margin-top: 14px;
    }}
    select, .action {{
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel);
      color: var(--ink);
      padding: 8px 12px;
    }}
    .action {{ cursor: pointer; font-weight: 650; }}
    .action.primary {{ background: var(--ink); color: white; border-color: var(--ink); }}
    .progress-track {{
      height: 7px;
      margin-top: 12px;
      overflow: hidden;
      border-radius: 999px;
      background: #e8ece8;
    }}
    .progress-bar {{ height: 100%; width: 0; background: var(--green); transition: width .2s; }}
    .source-tabs {{ display: flex; gap: 8px; overflow-x: auto; padding: 18px 0 8px; }}
    .source-tab {{
      flex: 0 0 auto;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: white;
      padding: 7px 11px;
      cursor: pointer;
    }}
    .source-tab.active {{ color: white; background: var(--ink); border-color: var(--ink); }}
    .source-tab small {{ opacity: .72; }}
    main {{ padding: 12px 0 70px; }}
    .empty {{
      padding: 48px 24px;
      border: 1px dashed var(--line);
      border-radius: 16px;
      color: var(--muted);
      text-align: center;
    }}
    .card {{
      margin: 16px 0;
      padding: 20px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--panel);
      box-shadow: 0 8px 24px rgba(23, 33, 27, .04);
    }}
    .card[data-status="correct"] {{ border-left: 5px solid var(--green); }}
    .card[data-status="issue"] {{ border-left: 5px solid var(--red); }}
    .card[data-status="unsure"] {{ border-left: 5px solid var(--amber); }}
    .eyebrow {{ color: var(--muted); font-size: 13px; font-weight: 700; text-transform: uppercase; }}
    .title-row {{ display: flex; gap: 16px; align-items: start; justify-content: space-between; }}
    h2 {{ margin: 3px 0 2px; font-size: 21px; line-height: 1.3; }}
    .company {{ color: var(--muted); font-weight: 600; }}
    .source-link {{
      flex: 0 0 auto;
      border-radius: 9px;
      background: var(--ink);
      color: white;
      padding: 8px 11px;
      text-decoration: none;
      font-weight: 700;
    }}
    .facts {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin: 16px 0;
    }}
    .fact {{ padding: 10px 12px; border-radius: 10px; background: #f4f6f2; }}
    .fact span {{ display: block; color: var(--muted); font-size: 12px; }}
    .description {{ color: #3e4842; font-size: 14px; }}
    .review {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(260px, .7fr);
      gap: 16px;
      margin-top: 18px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
    }}
    .status-buttons {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .status {{
      border: 1px solid var(--line);
      border-radius: 9px;
      background: white;
      padding: 8px 11px;
      cursor: pointer;
    }}
    .status.selected[data-value="correct"] {{ background: var(--green-soft); border-color: var(--green); }}
    .status.selected[data-value="issue"] {{ background: var(--red-soft); border-color: var(--red); }}
    .status.selected[data-value="unsure"] {{ background: var(--amber-soft); border-color: var(--amber); }}
    .issues {{ display: flex; flex-wrap: wrap; gap: 7px 12px; margin-top: 12px; }}
    .issues label {{ font-size: 13px; }}
    textarea {{
      width: 100%;
      min-height: 90px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
    }}
    .hidden {{ display: none !important; }}
    @media (max-width: 800px) {{
      .toolbar {{ grid-template-columns: 1fr 1fr; }}
      .facts {{ grid-template-columns: 1fr 1fr; }}
      .review {{ grid-template-columns: 1fr; }}
      .title-row {{ display: block; }}
      .source-link {{ display: inline-block; margin-top: 12px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="shell header-inner">
      <h1>岗位数据抽检</h1>
      <div class="subtitle" id="summary"></div>
      <div class="toolbar">
        <select id="sourceFilter" aria-label="平台"></select>
        <select id="statusFilter" aria-label="审核状态">
          <option value="all">全部状态</option>
          <option value="unreviewed">只看未检查</option>
          <option value="correct">正确</option>
          <option value="issue">有问题</option>
          <option value="unsure">无法判断</option>
        </select>
        <button class="action primary" id="exportButton">导出审核结果</button>
        <button class="action" id="resetButton">清空审核</button>
      </div>
      <div class="progress-track"><div class="progress-bar" id="progressBar"></div></div>
    </div>
  </header>
  <div class="shell">
    <nav class="source-tabs" id="sourceTabs" aria-label="按平台筛选"></nav>
    <main id="cards"></main>
  </div>
  <script id="audit-data" type="application/json">{embedded}</script>
  <script>
    const data = JSON.parse(document.getElementById("audit-data").textContent);
    const storageKey = `jpjobs-audit:${{data.scanned_at || "unknown"}}`;
    const issueLabels = {{
      title: "标题", company: "公司", date_posted: "日期", workplace: "地点",
      wage: "薪资", employment_type: "雇佣类型", description: "描述",
      duplicate: "疑似重复", inactive: "已失效"
    }};
    let reviews = JSON.parse(localStorage.getItem(storageKey) || "{{}}");
    let activeSource = "all";

    const escapeText = value => value === null || value === undefined || value === "" ? "—" : String(value);
    const wageText = job => {{
      const wage = job.wage || {{}};
      return wage.raw || [wage.min, wage.max, wage.unit].filter(Boolean).join(" / ") || "—";
    }};
    const jobKey = job => `${{job.source}}:${{job.source_id || job.id}}`;
    const save = () => localStorage.setItem(storageKey, JSON.stringify(reviews));

    function sourceOptions() {{
      const select = document.getElementById("sourceFilter");
      select.innerHTML = "";
      const all = document.createElement("option");
      all.value = "all";
      all.textContent = `全部平台（${{data.jobs.length}} 条样本）`;
      select.appendChild(all);
      for (const source of data.sources) {{
        const option = document.createElement("option");
        option.value = source.source;
        option.textContent = `${{source.source}}（抽 ${{source.sampled}} / 共 ${{source.available}}）`;
        select.appendChild(option);
      }}
    }}

    function renderTabs() {{
      const tabs = document.getElementById("sourceTabs");
      tabs.innerHTML = "";
      const items = [{{source: "all", sampled: data.jobs.length}}, ...data.sources];
      for (const source of items) {{
        const button = document.createElement("button");
        button.className = "source-tab" + (activeSource === source.source ? " active" : "");
        button.dataset.source = source.source;
        button.innerHTML = `${{source.source === "all" ? "全部" : source.source}} <small>${{source.sampled}}</small>`;
        button.onclick = () => {{
          activeSource = source.source;
          document.getElementById("sourceFilter").value = activeSource;
          render();
        }};
        tabs.appendChild(button);
      }}
    }}

    function setStatus(job, value) {{
      const key = jobKey(job);
      reviews[key] ||= {{issues: [], notes: ""}};
      reviews[key].status = value;
      reviews[key].reviewed_at = new Date().toISOString();
      save();
      render();
    }}

    function updateIssue(job, issue, checked) {{
      const key = jobKey(job);
      reviews[key] ||= {{status: "issue", issues: [], notes: ""}};
      const issues = new Set(reviews[key].issues || []);
      checked ? issues.add(issue) : issues.delete(issue);
      reviews[key].issues = [...issues];
      if (checked && !reviews[key].status) reviews[key].status = "issue";
      reviews[key].reviewed_at = new Date().toISOString();
      save();
      updateProgress();
    }}

    function updateNotes(job, value) {{
      const key = jobKey(job);
      reviews[key] ||= {{issues: []}};
      reviews[key].notes = value;
      reviews[key].reviewed_at = new Date().toISOString();
      save();
    }}

    function cardFor(job) {{
      const key = jobKey(job);
      const review = reviews[key] || {{}};
      const card = document.createElement("article");
      card.className = "card";
      card.dataset.status = review.status || "unreviewed";

      const titleRow = document.createElement("div");
      titleRow.className = "title-row";
      const heading = document.createElement("div");
      const eyebrow = document.createElement("div");
      eyebrow.className = "eyebrow";
      eyebrow.textContent = `${{job.source}} · ${{job.source_id || job.id}}`;
      const title = document.createElement("h2");
      title.textContent = escapeText(job.title);
      const company = document.createElement("div");
      company.className = "company";
      company.textContent = escapeText(job.company);
      heading.append(eyebrow, title, company);
      const link = document.createElement("a");
      link.className = "source-link";
      link.href = job.url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "打开原岗位 ↗";
      titleRow.append(heading, link);

      const facts = document.createElement("div");
      facts.className = "facts";
      const values = [
        ["发布日期", job.date_posted],
        ["工作地点", job.workplace || job.prefecture_name],
        ["薪资", wageText(job)],
        ["雇佣类型", job.employment_type],
        ["远程", job.remote === true ? "是" : job.remote === false ? "否" : "—"],
        ["语言", (job.language || []).join(", ")],
        ["详情状态", job.detail_status],
        ["来源", (job.found_on || [job.source]).join(", ")]
      ];
      for (const [label, value] of values) {{
        const fact = document.createElement("div");
        fact.className = "fact";
        const caption = document.createElement("span");
        caption.textContent = label;
        fact.append(caption, document.createTextNode(escapeText(value)));
        facts.appendChild(fact);
      }}

      const description = document.createElement("div");
      description.className = "description";
      description.textContent = job.description_snippet || "没有描述摘要";

      const reviewPanel = document.createElement("div");
      reviewPanel.className = "review";
      const controls = document.createElement("div");
      const statusButtons = document.createElement("div");
      statusButtons.className = "status-buttons";
      for (const [value, label] of [["correct", "✓ 正确"], ["issue", "! 有问题"], ["unsure", "? 无法判断"]]) {{
        const button = document.createElement("button");
        button.className = "status" + (review.status === value ? " selected" : "");
        button.dataset.value = value;
        button.textContent = label;
        button.onclick = () => setStatus(job, value);
        statusButtons.appendChild(button);
      }}
      const issues = document.createElement("div");
      issues.className = "issues";
      for (const [value, label] of Object.entries(issueLabels)) {{
        const wrapper = document.createElement("label");
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = (review.issues || []).includes(value);
        input.onchange = event => updateIssue(job, value, event.target.checked);
        wrapper.append(input, document.createTextNode(" " + label));
        issues.appendChild(wrapper);
      }}
      controls.append(statusButtons, issues);
      const notes = document.createElement("textarea");
      notes.placeholder = "可选：记录具体哪里不对……";
      notes.value = review.notes || "";
      notes.oninput = event => updateNotes(job, event.target.value);
      reviewPanel.append(controls, notes);

      card.append(titleRow, facts, description, reviewPanel);
      return card;
    }}

    function filteredJobs() {{
      const status = document.getElementById("statusFilter").value;
      return data.jobs.filter(job => {{
        if (activeSource !== "all" && job.source !== activeSource) return false;
        const current = (reviews[jobKey(job)] || {{}}).status || "unreviewed";
        return status === "all" || current === status;
      }});
    }}

    function updateProgress() {{
      const reviewed = data.jobs.filter(job => (reviews[jobKey(job)] || {{}}).status).length;
      const percent = data.jobs.length ? Math.round(reviewed / data.jobs.length * 100) : 0;
      document.getElementById("summary").textContent =
        `源文件：${{data.source_path}} · 共 ${{data.total_kept}} 条 · 抽样 ${{data.jobs.length}} 条 · 已检查 ${{reviewed}} 条（${{percent}}%）`;
      document.getElementById("progressBar").style.width = percent + "%";
    }}

    function render() {{
      renderTabs();
      updateProgress();
      const cards = document.getElementById("cards");
      cards.innerHTML = "";
      const jobs = filteredJobs();
      if (!jobs.length) {{
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = activeSource === "all" ? "当前筛选下没有岗位。" : "这个平台没有可抽检的岗位。";
        cards.appendChild(empty);
        return;
      }}
      for (const job of jobs) cards.appendChild(cardFor(job));
    }}

    document.getElementById("sourceFilter").onchange = event => {{
      activeSource = event.target.value;
      render();
    }};
    document.getElementById("statusFilter").onchange = render;
    document.getElementById("exportButton").onclick = () => {{
      const output = {{
        exported_at: new Date().toISOString(),
        scanned_at: data.scanned_at,
        source_path: data.source_path,
        sample_size: data.jobs.length,
        reviews
      }};
      const blob = new Blob([JSON.stringify(output, null, 2)], {{type: "application/json"}});
      const anchor = document.createElement("a");
      anchor.href = URL.createObjectURL(blob);
      anchor.download = `jpjobs-audit-${{(data.scanned_at || "result").slice(0, 10)}}.json`;
      anchor.click();
      URL.revokeObjectURL(anchor.href);
    }};
    document.getElementById("resetButton").onclick = () => {{
      if (!confirm("确定清空这份抽检结果吗？")) return;
      reviews = {{}};
      save();
      render();
    }};

    sourceOptions();
    render();
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--per-source", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.per_source < 1:
        parser.error("--per-source must be at least 1")

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    samples, source_summary = build_sample(payload, args.per_source)
    html = render_html(
        payload=payload,
        samples=samples,
        source_summary=source_summary,
        source_path=str(args.input),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    print(
        f"wrote {len(samples)} samples from {len(source_summary)} sources "
        f"to {args.output}"
    )


if __name__ == "__main__":
    main()
