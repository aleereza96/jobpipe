"""Build a tailored CV from the base CV and a saved job draft."""
import io
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def section(text, name):
    lines = []
    active = False
    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading:
            if active:
                break
            active = heading[2].strip("*").rstrip(":").casefold() == name
        elif active:
            lines.append(line)
    return "\n".join(lines).strip()


def tailored_lines(cv, draft):
    summary = section(draft, "tailored summary")
    if not summary:
        raise ValueError("This job needs a tailored summary before it can be exported.")
    cv = re.sub(r"<!--.*?-->", "", cv, flags=re.S)
    original = section(cv, "summary")
    if original:
        cv = cv.replace(original, summary, 1)
    else:
        heading = re.search(r"^##\s", cv, re.M)
        index = heading.start() if heading else len(cv)
        cv = cv[:index].rstrip() + "\n\n## Summary\n" + summary + "\n\n" + cv[index:]

    preferred = [line[2:].strip() for line in section(draft, "bullets to move up").splitlines()
                 if line.startswith(("- ", "* "))]
    rank = {line: index for index, line in enumerate(preferred)}
    lines = cv.splitlines()
    index = 0
    while index < len(lines):
        if not lines[index].startswith("- "):
            index += 1
            continue
        end = index + 1
        while end < len(lines) and lines[end].startswith("- "):
            end += 1
        # Only move exact matches within their original section or role.
        lines[index:end] = sorted(lines[index:end],
                                  key=lambda line: rank.get(line[2:].strip(), len(rank)))
        index = end
    return lines


def render(cv, draft=None):
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=47, rightMargin=47,
                            topMargin=42, bottomMargin=44, title="Tailored CV" if draft is not None else "CV")
    body = ParagraphStyle("Body", fontName="Helvetica", fontSize=10, leading=14,
                          textColor=colors.HexColor("#202b27"), spaceAfter=4)
    name = ParagraphStyle("Name", parent=body, fontName="Helvetica-Bold",
                          fontSize=23, leading=28, spaceAfter=6, keepWithNext=True)
    section_style = ParagraphStyle("Section", parent=body, fontName="Helvetica-Bold",
                                   fontSize=13, leading=16, spaceBefore=9, spaceAfter=5,
                                   textColor=colors.HexColor("#204a3a"), keepWithNext=True)
    role = ParagraphStyle("Role", parent=body, fontName="Helvetica-Bold",
                          spaceBefore=5, keepWithNext=True)
    bullet = ParagraphStyle("Bullet", parent=body, leftIndent=12, bulletIndent=1)
    story = []
    lines = tailored_lines(cv, draft) if draft is not None else re.sub(r"<!--.*?-->", "", cv, flags=re.S).splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        heading = HEADING.match(line)
        if heading:
            style = {1: name, 2: section_style}.get(len(heading[1]), role)
            story.append(Paragraph(escape(heading[2]), style))
        elif line.startswith(("- ", "* ")):
            story.append(Paragraph(escape(line[2:]), bullet, bulletText="•"))
        else:
            story.append(Paragraph(escape(line), body))

    def page_number(canvas, document):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#59655f"))
        canvas.drawRightString(A4[0] - 47, 25, str(document.page))

    doc.build(story, onFirstPage=page_number, onLaterPages=page_number)
    return output.getvalue()
