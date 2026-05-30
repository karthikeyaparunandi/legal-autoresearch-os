from __future__ import annotations

from pathlib import Path
import textwrap


def write_pdf(path: Path, title: str, markdown: str) -> None:
    lines = _markdown_to_lines(title, markdown)
    pages = _paginate(lines)
    objects: list[bytes] = []

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{index + 3} 0 R" for index in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii"))

    content_object_start = 3 + len(pages)
    for index in range(len(pages)):
        content_ref = content_object_start + index
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {content_object_start + len(pages)} 0 R >> >> "
                f"/Contents {content_ref} 0 R >>"
            ).encode("ascii")
        )

    for page in pages:
        stream = _page_stream(page)
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream")

    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_assemble_pdf(objects))


def _markdown_to_lines(title: str, markdown: str) -> list[str]:
    lines = [title, ""]
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        if line.startswith("### "):
            line = line[4:]
        elif line.startswith("## "):
            line = line[3:].upper()
        elif line.startswith("# "):
            line = line[2:].upper()
        elif line.startswith("- "):
            line = "  - " + line[2:]
        line = line.replace("|", "  ")
        lines.extend(textwrap.wrap(line, width=92) or [""])
    return lines


def _paginate(lines: list[str]) -> list[list[str]]:
    page_size = 48
    return [lines[index : index + page_size] for index in range(0, len(lines), page_size)] or [[]]


def _page_stream(lines: list[str]) -> bytes:
    chunks = ["BT", "/F1 10 Tf", "50 750 Td", "14 TL"]
    for line in lines:
        chunks.append(f"({_escape(line)}) Tj")
        chunks.append("T*")
    chunks.append("ET")
    return "\n".join(chunks).encode("latin-1", errors="replace")


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _assemble_pdf(objects: list[bytes]) -> bytes:
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")

    xref_start = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            "startxref\n"
            f"{xref_start}\n"
            "%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)
