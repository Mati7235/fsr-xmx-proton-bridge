#!/usr/bin/env python3
import os
import re
import sys

USAGE = "uso: vdf.py <carpeta-ge-proton> <nombre-interno> <nombre-visible>\n"

KEY_LINE = re.compile(r'^(\s*)"([^"]+)"(\s+)"(.*)"\s*$')
BARE_LINE = re.compile(r'^(\s*)"([^"]+)"\s*$')


def render(name, display):
    lines = [
        '"compatibilitytool.vdf"',
        "{",
        '\t"install"',
        "\t{",
        '\t\t"%s"' % name,
        "\t\t{",
        '\t\t\t"from_oslist"  "windows"',
        '\t\t\t"to_oslist"    "linux"',
        '\t\t\t"display_name" "%s"' % display,
        '\t\t\t"installpath"  "."',
        "\t\t}",
        "\t}",
        "}",
        "",
    ]
    return "\n".join(lines)


def find_block_name(lines):
    seen_install = False
    for index, line in enumerate(lines):
        bare = BARE_LINE.match(line)
        if bare is None:
            continue
        if bare.group(2) == "install":
            seen_install = True
            continue
        if seen_install:
            return index
    return None


def rewrite(text, name, display):
    lines = text.splitlines()
    nl = "\r\n" if "\r\n" in text else "\n"
    block = find_block_name(lines)
    if block is None:
        return render(name, display)
    out = []
    displayed = False
    for index, line in enumerate(lines):
        bare = BARE_LINE.match(line)
        key_line = KEY_LINE.match(line)
        if index == block:
            out.append('%s"%s"' % (bare.group(1), name))
            continue
        if key_line and key_line.group(2) == "display_name":
            out.append('%s"%s"%s"%s"' % (key_line.group(1), key_line.group(2),
                                         key_line.group(3), display))
            displayed = True
            continue
        out.append(line)
    if not displayed:
        out.insert(block + 1, '\t\t\t"display_name" "%s"' % display)
    return nl.join(out) + nl


def main(argv):
    if len(argv) < 3:
        sys.stderr.write(USAGE)
        return 2
    ge_dir, name, display = argv[0], argv[1], argv[2]
    path = os.path.join(ge_dir, "compatibilitytool.vdf")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8", errors="surrogateescape") as handle:
            new_text = rewrite(handle.read(), name, display)
    else:
        new_text = render(name, display)
    tmp = path + ".fsr-xmx.tmp"
    with open(tmp, "w", encoding="utf-8", errors="surrogateescape", newline="") as handle:
        handle.write(new_text)
    os.replace(tmp, path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
