"""Load the active CV and extract supported LaTeX source as Markdown."""
import json
import re

FORMATS = ("md", "tex")
MAX_LENGTH = 100_000
ARGUMENTS = re.compile(r"\s*(\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\})")


def load(root):
    saved = root / "cv-source.json"
    if saved.is_file():
        return json.loads(saved.read_text(encoding="utf-8"))
    return {"format": "md", "source": (root / "cv.md").read_text(encoding="utf-8")}


def as_markdown(source, format):
    if not isinstance(source, str) or not source.strip() or len(source) > MAX_LENGTH:
        raise ValueError("CV must contain between 1 and 100,000 characters.")
    if format not in FORMATS:
        raise ValueError("Choose Markdown or LaTeX.")
    if format == "md":
        return source

    source = re.sub(r"(?<!\\)%[^\n]*", "", source)
    document = re.search(r"\\begin\s*\{document\}([\s\S]*?)\\end\s*\{document\}", source)
    if not document:
        raise ValueError("Upload a complete LaTeX document with a document environment.")
    text = document[1]
    if re.search(r"\\(?:input|include|subfile|import|bibliography|includegraphics)\b", text):
        raise ValueError("Use a self-contained LaTeX CV. External files and images are unsupported.")
    text = re.sub(r"\\(?:begin|end)\{[^{}]*\}(?:\[[^\]]*\])?", "\n", text)
    text = re.sub(r"\\\\(?:\[[^\]]*\])?", "\n", text)
    text = re.sub(r"\\item(?:\[[^\]]*\])?\s*", "\n- ", text)
    commands = {
        "section": (1, lambda args: "\n## " + args[0] + "\n"),
        "subsection": (1, lambda args: "\n### " + args[0] + "\n"),
        "resumeSubheading": (4, lambda args: "\n### " + " | ".join((args[2], args[0], args[3], args[1])) + "\n"),
        "resumeProjectHeading": (2, lambda args: "\n### " + " | ".join(args) + "\n"),
        "resumeItem": (1, lambda args: "\n- " + args[0] + "\n"),
        "cventry": (6, lambda args: "\n### " + " | ".join(filter(None, args[:5])) + "\n" + args[5]),
        "href": (2, lambda args: args[1]),
        "url": (1, lambda args: args[0]),
    }
    # Process from the outside in so nested text formatting stays readable.
    cursor, parts = 0, []
    pattern = re.compile(r"\\([A-Za-z]+)\*?")
    while match := pattern.search(text, cursor):
        parts.append(text[cursor:match.start()])
        cursor = match.end()
        rule = commands.get(match[1])
        if rule:
            count, render = rule
            args = []
            end = cursor
            for _ in range(count):
                argument = ARGUMENTS.match(text, end)
                if not argument:
                    break
                args.append(argument[1][1:-1])
                end = argument.end()
            if len(args) == count:
                parts.append(render(args))
                cursor = end
                continue
        parts.append(match[0])
    parts.append(text[cursor:])
    text = "".join(parts)
    text = re.sub(r"\\(?:vspace|hspace|setlength|fontsize)\*?\{[^{}]*\}(?:\{[^{}]*\})?", "", text)
    text = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?", "", text)
    text = re.sub(r"\\([%&#_$])", r"\1", text)
    text = text.replace("{", "").replace("}", "").replace("~", " ")
    text = text.replace("$|$", " | ").replace("&", " ")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines or sum(char.isalnum() for char in "".join(lines)) < 20:
        raise ValueError("Could not extract readable text from this LaTeX CV.")
    if not lines[0].startswith("#") and len(lines[0]) < 100:
        lines[0] = "# " + lines[0]
    return "\n".join(lines)


def active_markdown(root):
    cv = load(root)
    return as_markdown(cv["source"], cv["format"])
