from __future__ import annotations

from html import escape
from pathlib import Path
import re

from .models import Claim, Contradiction, Evaluation, Evidence, ResearchProgram, RunMetrics


def write_html(path: Path, title: str, markdown: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _markdown_to_html(markdown)
    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #18202a;
      --muted: #5b6573;
      --line: #d9dee7;
      --panel: #f7f9fc;
      --accent: #1f6feb;
    }}
    body {{
      margin: 0;
      font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: #ffffff;
    }}
    main {{
      max-width: 980px;
      margin: 0 auto;
      padding: 44px 24px 64px;
    }}
    h1, h2, h3 {{
      line-height: 1.2;
      margin: 28px 0 12px;
    }}
    h1 {{
      font-size: 34px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 18px;
    }}
    h2 {{
      font-size: 22px;
      color: #111827;
    }}
    h3 {{
      font-size: 17px;
    }}
    p, li {{
      color: var(--ink);
    }}
    ul {{
      padding-left: 22px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 16px 0 24px;
      font-size: 14px;
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 9px 10px;
      vertical-align: top;
    }}
    th {{
      background: var(--panel);
      text-align: left;
    }}
    a {{
      color: var(--accent);
    }}
    code {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 4px;
      padding: 1px 4px;
    }}
  </style>
</head>
<body>
<main>
{body}
</main>
</body>
</html>
""",
        encoding="utf-8",
    )


def write_research_html(
    path: Path,
    program: ResearchProgram,
    claims: list[Claim],
    evidence: list[Evidence],
    contradictions: list[Contradiction],
    open_questions: list[str],
    evaluation: Evaluation,
    metrics: RunMetrics,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    evidence_by_id = {item.source_id: item for item in evidence}
    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AutoResearch OS Grounded Legal Research Report</title>
  <style>{_report_css()}</style>
</head>
<body>
<main>
  <header class="report-header">
    <p class="eyebrow">AutoResearch OS Legal Runtime</p>
    <h1>Grounded Legal Research Report</h1>
    <p class="lede">{escape(_executive_summary(claims, evaluation))}</p>
    <div class="artifact-links">
      <a href="final_report.md">Markdown</a>
      <a href="final_report.pdf">PDF</a>
      <a href="metrics.json">Metrics JSON</a>
    </div>
  </header>

  <section>
    <h2>Research Objective</h2>
    <p>{escape(program.objective)}</p>
    <div class="meta-grid">
      {_metric_card("Final confidence", f"{metrics.final_confidence:.0%}")}
      {_metric_card("Agents spun off", str(metrics.agents_spun_off))}
      {_metric_card("Hypotheses", str(metrics.hypotheses_count))}
      {_metric_card("Runtime", f"{metrics.total_runtime_seconds:.3f}s")}
      {_metric_card("Contradictions", f"{metrics.resolved_contradictions_count}/{metrics.contradictions_count} resolved")}
      {_metric_card("Open questions", str(metrics.open_questions_count))}
    </div>
  </section>

  <section>
    <h2>How The Answer Was Deduced</h2>
    <p class="section-note">The diagram shows the legal reasoning path from user goal to final answer. Each stage includes agent count and measured runtime.</p>
    {_reasoning_svg(metrics, evaluation)}
  </section>

  <section>
    <h2>Convergence Progress</h2>
    <p class="section-note">The system continues researching until objective completion, citation grounding, contradiction resolution, and open-question thresholds are satisfied.</p>
    {_iteration_history_table(metrics)}
  </section>

  <section>
    <h2>Component Metrics</h2>
    {_component_table(metrics)}
  </section>

  <section>
    <h2>Agent Tool Loops</h2>
    {_agent_trace_table(metrics)}
  </section>

  <section>
    <h2>Live Retrieval</h2>
    {_retrieval_table(metrics)}
  </section>

  <section>
    <h2>Hypotheses And Claim Rationale</h2>
    {_claims_table(claims, evidence_by_id)}
  </section>

  <section>
    <h2>Contradiction Analysis</h2>
    {_contradiction_block(contradictions)}
  </section>

  <section>
    <h2>Legal Metadata</h2>
    <table>
      <tbody>
        <tr><th>Jurisdiction</th><td>{escape(program.legal_metadata.jurisdiction)}</td></tr>
        <tr><th>Practice area</th><td>{escape(program.legal_metadata.practice_area)}</td></tr>
        <tr><th>Risk posture</th><td>{escape(program.legal_metadata.risk_posture)}</td></tr>
        <tr><th>Authority hierarchy</th><td>{escape(", ".join(program.legal_metadata.authority_hierarchy))}</td></tr>
        <tr><th>Required source types</th><td>{escape(", ".join(program.legal_metadata.required_source_types))}</td></tr>
      </tbody>
    </table>
  </section>

  <section>
    <h2>Open Questions</h2>
    {_list_block(open_questions or ["None."])}
  </section>

  <section>
    <h2>Sources</h2>
    <ol class="sources">
      {"".join(_source_item(item) for item in evidence)}
    </ol>
  </section>
</main>
</body>
</html>
""",
        encoding="utf-8",
    )


def _report_css() -> str:
    return """
:root {
  --ink: #17202a;
  --muted: #647080;
  --line: #d9e0ea;
  --panel: #f7f9fc;
  --accent: #1f6feb;
  --accent-2: #0f766e;
  --warn: #a16207;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--ink);
  background: #fff;
}
main {
  max-width: 1120px;
  margin: 0 auto;
  padding: 44px 24px 72px;
}
.report-header {
  border-bottom: 1px solid var(--line);
  padding-bottom: 22px;
  margin-bottom: 30px;
}
.eyebrow {
  margin: 0 0 8px;
  color: var(--accent-2);
  font-weight: 700;
  letter-spacing: .02em;
  text-transform: uppercase;
  font-size: 12px;
}
h1, h2, h3 { line-height: 1.2; }
h1 { margin: 0 0 12px; font-size: 36px; }
h2 { margin: 34px 0 12px; font-size: 22px; }
h3 { margin: 22px 0 8px; font-size: 17px; }
.lede { max-width: 900px; color: #293241; font-size: 17px; }
.section-note { color: var(--muted); margin-top: -4px; }
.artifact-links { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
.artifact-links a, .cite {
  color: var(--accent);
  text-decoration: none;
  font-weight: 650;
}
.artifact-links a {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 6px 10px;
  background: var(--panel);
}
.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
  margin: 18px 0 4px;
}
.metric-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  background: var(--panel);
}
.metric-card strong { display: block; font-size: 22px; }
.metric-card span { color: var(--muted); font-size: 13px; }
table {
  width: 100%;
  border-collapse: collapse;
  margin: 14px 0 24px;
}
th, td {
  border: 1px solid var(--line);
  padding: 9px 10px;
  vertical-align: top;
  text-align: left;
}
th { background: var(--panel); }
.status-supported { color: var(--accent-2); font-weight: 700; }
.status-contested, .status-weak { color: var(--warn); font-weight: 700; }
.sources li { margin-bottom: 12px; }
.source-meta { color: var(--muted); display: block; font-size: 13px; }
.diagram-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; background: #fbfcfe; padding: 12px; }
svg text { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
"""


def _metric_card(label: str, value: str) -> str:
    return f'<div class="metric-card"><strong>{escape(value)}</strong><span>{escape(label)}</span></div>'


def _component_table(metrics: RunMetrics) -> str:
    rows = []
    for name, values in metrics.component_metrics.items():
        rows.append(
            "<tr>"
            f"<td>{escape(name.replace('_', ' ').title())}</td>"
            f"<td>{values.get('agents', 0)}</td>"
            f"<td>{values.get('seconds', 0):.4f}s</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>Component</th><th>Agents</th><th>Time</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def _agent_trace_table(metrics: RunMetrics) -> str:
    rows = []
    for trace in metrics.agent_traces:
        rows.append(
            "<tr>"
            f"<td>{escape(str(trace.get('name', 'agent')))}</td>"
            f"<td>{escape(', '.join(trace.get('tools', [])))}</td>"
            f"<td>{escape(' -> '.join(trace.get('steps', [])))}</td>"
            f"<td>{'yes' if trace.get('used_llm') else 'no'}</td>"
            f"<td>{escape(str(trace.get('output_count', 0)))}</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>Agent</th><th>Tools</th><th>Loop Steps</th><th>LLM</th><th>Outputs</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def _retrieval_table(metrics: RunMetrics) -> str:
    retrieval = metrics.retrieval_metrics
    rows = [
        ("Live retrieval", "enabled" if retrieval.get("enabled") else "disabled"),
        ("URLs attempted", retrieval.get("attempted_urls", 0)),
        ("URLs retrieved", retrieval.get("successful_urls", 0)),
        ("URLs failed", retrieval.get("failed_urls", 0)),
        ("Fallback evidence used", retrieval.get("fallback_used", False)),
    ]
    url_rows = "".join(f"<li>{escape(url)}</li>" for url in retrieval.get("retrieved_urls", []))
    table = "<table><tbody>" + "".join(f"<tr><th>{escape(str(left))}</th><td>{escape(str(right))}</td></tr>" for left, right in rows) + "</tbody></table>"
    if url_rows:
        table += f"<h3>Retrieved Sources</h3><ul>{url_rows}</ul>"
    return table


def _iteration_history_table(metrics: RunMetrics) -> str:
    rows = []
    for item in metrics.iteration_history:
        rows.append(
            "<tr>"
            f"<td>{item['iteration']}</td>"
            f"<td>{item['overall_confidence']:.0%}</td>"
            f"<td>{item['objective_completion']:.0%}</td>"
            f"<td>{item['citation_grounding']:.0%}</td>"
            f"<td>{item['contradiction_resolution']:.0%}</td>"
            f"<td>{item['open_questions']}</td>"
            f"<td>{escape(str(item['status']))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Iteration</th><th>Confidence</th><th>Objective</th>"
        "<th>Citations</th><th>Contradictions</th><th>Open Questions</th><th>Status</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _claims_table(claims: list[Claim], evidence_by_id: dict[str, Evidence]) -> str:
    rows = []
    for claim in claims:
        sources = " ".join(_citation(source_id, evidence_by_id) for source_id in claim.supporting_sources) or "None"
        contradicts = " ".join(_citation(source_id, evidence_by_id) for source_id in claim.contradicting_sources) or "None"
        rows.append(
            "<tr>"
            f"<td>{escape(claim.claim_id)}</td>"
            f"<td>{escape(claim.claim)}</td>"
            f'<td class="status-{escape(claim.status)}">{escape(claim.status)}</td>'
            f"<td>{claim.confidence:.0%}</td>"
            f"<td>{sources}</td>"
            f"<td>{contradicts}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>ID</th><th>Hypothesis / Claim</th><th>Status</th><th>Confidence</th>"
        "<th>Supporting citations</th><th>Contradicting citations</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _citation(source_id: str, evidence_by_id: dict[str, Evidence]) -> str:
    source = evidence_by_id.get(source_id)
    label = _citation_label(source_id)
    title = source.title if source else source_id
    return f'<a class="cite" href="#{escape(source_id)}" title="{escape(title)}">[{escape(label)}]</a>'


def _source_item(item: Evidence) -> str:
    label = _citation_label(item.source_id)
    return (
        f'<li id="{escape(item.source_id)}">'
        f'<strong>[{escape(label)}] <a href="{escape(item.url)}">{escape(item.title)}</a></strong>'
        f'<span class="source-meta">{escape(item.source_type)} | reliability {item.reliability:.0%}</span>'
        f"{escape(item.excerpt)}"
        "</li>"
    )


def _citation_label(source_id: str) -> str:
    if source_id.startswith("source_"):
        return str(int(source_id.removeprefix("source_")))
    return source_id


def _contradiction_block(contradictions: list[Contradiction]) -> str:
    if not contradictions:
        return "<p>No contradictions detected.</p>"
    return _list_block([f"{item.claim}: {item.resolution_status}. {item.note}" for item in contradictions])


def _list_block(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>"


def _executive_summary(claims: list[Claim], evaluation: Evaluation) -> str:
    supported = [claim.claim for claim in claims if claim.status == "supported"]
    if not supported:
        return "The runtime did not reach a well-supported conclusion yet."
    return (
        f"The research state supports {len(supported)} legal findings with {evaluation.overall_confidence:.0%} "
        f"overall confidence. Core rationale: {supported[0]}"
    )


def _reasoning_svg(metrics: RunMetrics, evaluation: Evaluation) -> str:
    nodes = [
        ("Goal", "Legal question", "program_generation"),
        ("Program", f"{metrics.tasks_count} tasks", "planning"),
        ("Hypotheses", f"{metrics.hypotheses_count} candidates", "hypothesis_generation"),
        ("Evidence", f"{metrics.evidence_count} records", "evidence_collection"),
        ("Critique", f"{metrics.contradictions_count} contradictions", "critique"),
        ("Evaluation", f"{evaluation.overall_confidence:.0%} confidence", "evaluation"),
        ("Report", "HTML / PDF / MD", "report_generation"),
    ]
    width = 980
    height = 230
    box_w = 126
    box_h = 76
    gap = 18
    y = 58
    svg_nodes = []
    svg_edges = []
    for index, (title, subtitle, component) in enumerate(nodes):
        x = 18 + index * (box_w + gap)
        data = metrics.component_metrics.get(component, {})
        agents = data.get("agents", 0)
        seconds = data.get("seconds", 0)
        agent_label = "agent" if agents == 1 else "agents"
        svg_nodes.append(
            f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" rx="8" fill="#ffffff" stroke="#d9e0ea"/>'
            f'<text x="{x + 12}" y="{y + 24}" font-size="13" font-weight="700" fill="#17202a">{escape(title)}</text>'
            f'<text x="{x + 12}" y="{y + 44}" font-size="11" fill="#4b5563">{escape(subtitle)}</text>'
            f'<text x="{x + 12}" y="{y + 62}" font-size="10" fill="#0f766e">{agents} {agent_label} | {seconds:.4f}s</text>'
        )
        if index < len(nodes) - 1:
            x1 = x + box_w
            x2 = x + box_w + gap
            svg_edges.append(
                f'<line x1="{x1}" y1="{y + box_h / 2:.0f}" x2="{x2}" y2="{y + box_h / 2:.0f}" stroke="#1f6feb" stroke-width="2" marker-end="url(#arrow)"/>'
            )
    return (
        '<div class="diagram-wrap">'
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Legal reasoning flow">'
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">'
        '<path d="M0,0 L0,6 L6,3 z" fill="#1f6feb"/></marker></defs>'
        '<text x="18" y="28" font-size="15" font-weight="700" fill="#17202a">Reasoning and rationale path</text>'
        + "".join(svg_edges)
        + "".join(svg_nodes)
        + "</svg></div>"
    )


def _markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    html: list[str] = []
    in_list = False
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        if not line:
            if in_list:
                html.append("</ul>")
                in_list = False
            index += 1
            continue
        if line.startswith("| ") and index + 1 < len(lines) and lines[index + 1].startswith("| ---"):
            if in_list:
                html.append("</ul>")
                in_list = False
            table_lines = [line]
            index += 2
            while index < len(lines) and lines[index].startswith("| "):
                table_lines.append(lines[index].rstrip())
                index += 1
            html.append(_table_to_html(table_lines))
            continue
        if line.startswith("# "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("### "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("- "):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{_inline(line[2:])}</li>")
        else:
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<p>{_inline(line)}</p>")
        index += 1
    if in_list:
        html.append("</ul>")
    return "\n".join(html)


def _table_to_html(lines: list[str]) -> str:
    rows = [_split_table_row(line) for line in lines]
    head = "".join(f"<th>{_inline(cell)}</th>" for cell in rows[0])
    body_rows = []
    for row in rows[1:]:
        body_rows.append("<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row) + "</tr>")
    return "<table><thead><tr>" + head + "</tr></thead><tbody>" + "".join(body_rows) + "</tbody></table>"


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _inline(text: str) -> str:
    safe = escape(text)
    safe = re.sub(r"`([^`]+)`", r"<code>\1</code>", safe)
    safe = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', safe)
    return safe
