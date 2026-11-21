"""Regenerate the settings reference in docs/USER_GUIDE.md from stepfable/help_text.py.

Run after editing help_text.py:  python scripts/build_docs.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from stepfable import help_text  # noqa: E402
from stepfable.app_spec import PARAM_GROUPS  # noqa: E402

START, END = "<!-- settings:start -->", "<!-- settings:end -->"


def build() -> str:
    out = []
    for title, names in PARAM_GROUPS:
        out.append(f"### {title.replace('  ', '. ', 1)}\n")
        out.append(help_text.STAGES.get(title, "") + "\n")
        out.append("| Setting | What it does | How to set it |")
        out.append("|---|---|---|")
        for n in names:
            label, what, how = help_text.PARAMS[n]
            out.append(f"| **{label}** | {what} | {how} |")
        out.append("")
    out.append("### Export settings\n")
    out.append("| Setting | What it does | How to set it |")
    out.append("|---|---|---|")
    for label, what, how in help_text.EXPORT.values():
        out.append(f"| **{label}** | {what} | {how} |")
    out.append("")
    out.append("### The Runs table\n")
    out.append("| Column | Meaning |")
    out.append("|---|---|")
    for k, v in help_text.RUNS_COLUMNS.items():
        out.append(f"| **{k}** | {v} |")
    return "\n".join(out)


def main():
    path = os.path.join(ROOT, "docs", "USER_GUIDE.md")
    text = open(path, encoding="utf-8").read()
    new = re.sub(re.escape(START) + ".*?" + re.escape(END),
                 lambda m: f"{START}\n{build()}\n{END}", text, flags=re.S)
    open(path, "w", encoding="utf-8", newline="\n").write(new)
    print("updated", path)


if __name__ == "__main__":
    main()
