from __future__ import annotations

from html import escape
from pathlib import Path
import re


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
