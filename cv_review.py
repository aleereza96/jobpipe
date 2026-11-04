"""Optional CV review using the configured model."""
import json
import re

from ai_provider import ask_ai
from cv_source import as_markdown

TEXT = {"type": "string"}


def object_schema(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


SCORE = object_schema({"score": {"type": "integer"}, "feedback": TEXT})
EDIT = object_schema({"before": TEXT, "after": TEXT, "reason": TEXT})
SUGGESTIONS = object_schema({"edits": {"type": "array", "items": EDIT}})
TEX_SYNTAX = re.compile(r"[\\{}%&_$#^~]")


def review(config, action, source, format):
    readable = as_markdown(source, format)
    if action == "score":
        system = ("Review this CV for clarity, structure, and evidence of impact. "
                  "Give a general writing-quality score from 0 to 100 and concise feedback with concrete examples. "
                  "Do not infer personal traits or assess suitability for any particular job. "
                  "Return JSON with score and feedback.")
        result = json.loads(ask_ai(config, system, readable, schema=SCORE))
        score, feedback = result.get("score"), result.get("feedback")
        if type(score) is not int or not 0 <= score <= 100 or not isinstance(feedback, str):
            raise ValueError("The review returned an invalid score. Try again.")
        return {"score": score, "feedback": feedback}
    if action != "suggest":
        raise ValueError("Choose a CV review action.")
    system = ("Suggest up to five small wording improvements as JSON edits with before, after, and reason. "
              "Each before must be an exact, unique, single-line prose excerpt from the original source. "
              "Preserve all facts, dates, names and numbers. Never invent metrics, skills or credentials. "
              "Keep formatting and LaTeX commands outside the edited excerpt. "
              "For LaTeX, neither excerpt may contain LaTeX syntax or special characters. "
              "Return an empty edits list if there are no safe improvements.")
    result = json.loads(ask_ai(config, system, source, schema=SUGGESTIONS))
    edits = []
    for item in result.get("edits", [])[:5]:
        if not isinstance(item, dict):
            continue
        before, after, reason = (item.get(key) for key in ("before", "after", "reason"))
        if not all(isinstance(value, str) and value.strip() for value in (before, after, reason)):
            continue
        if before == after or "\n" in before or "\n" in after or source.count(before) != 1:
            continue
        if format == "tex" and (TEX_SYNTAX.search(before + after) or before not in readable):
            continue
        edits.append({"before": before, "after": after, "reason": reason})
    return {"edits": edits}
