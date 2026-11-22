#!/usr/bin/env python3
"""Check that a translated Markdown file kept every code block, inline code
span, link target, hash and number of its committed version (git HEAD)."""
import re
import subprocess
import sys
from collections import Counter

FENCE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1", re.S | re.M)
INLINE = re.compile(r"`[^`]+`")
LINK = re.compile(r"\]\(([^)]+)\)")
TOKEN = re.compile(r"0x[0-9A-Fa-f]+|\b[0-9a-f]{7,64}\b|\d+(?:[.,]\d+)*")


def norm_number(token):
    return token.replace(".", "").replace(",", "") if not token.startswith("0x") else token.lower()


def facts(text):
    fences = FENCE.findall(text)
    blocks = ["\n".join(line.strip() for line in m.group(0).splitlines()) for m in FENCE.finditer(text)]
    rest = FENCE.sub("", text)
    paragraphs = re.split(r"\n\s*\n", rest)
    inline = [" ".join(span.split()) for para in paragraphs for span in INLINE.findall(para)]
    prose = "\n\n".join(INLINE.sub("", para) for para in paragraphs)
    return {
        "code blocks": Counter(blocks),
        "inline code": Counter(inline),
        "links": Counter(LINK.findall(rest)),
        "numbers/hashes": Counter(norm_number(t) for t in TOKEN.findall(prose)),
    }, len(fences)


def main():
    status = 0
    for path in sys.argv[1:]:
        old = subprocess.run(["git", "show", f"HEAD:{path}"], capture_output=True, text=True)
        if old.returncode != 0:
            print(f"SKIP {path}: not in HEAD")
            continue
        new = open(path, encoding="utf-8").read()
        before, _ = facts(old.stdout)
        after, _ = facts(new)
        problems = []
        for key in before:
            missing = before[key] - after[key]
            extra = after[key] - before[key]
            if missing or extra:
                problems.append((key, missing, extra))
        if problems:
            status = 1
            print(f"FAIL {path}")
            for key, missing, extra in problems:
                for item, n in list(missing.items())[:8]:
                    print(f"  missing {key}: {item[:120]!r} x{n}")
                for item, n in list(extra.items())[:8]:
                    print(f"  extra   {key}: {item[:120]!r} x{n}")
        else:
            print(f"OK   {path}")
    return status


if __name__ == "__main__":
    sys.exit(main())
