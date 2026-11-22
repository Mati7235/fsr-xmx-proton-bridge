#!/usr/bin/env python3
import os
import re
import sys
import tempfile

VALUE_RE = re.compile(r"^(?P<head>[^=]*=)(?P<pre>[ \t]*)(?P<val>.*?)(?P<post>[ \t]*)$")

USAGE = (
    "uso: ini_edit.py get <archivo> <seccion> <clave>\n"
    "     ini_edit.py plan <archivo>   (claves por stdin: seccion<TAB>clave<TAB>valor)\n"
    "     ini_edit.py set <archivo>\n"
)


def split_end(line):
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def section_name(body):
    text = body.strip()
    if len(text) >= 2 and text.startswith("[") and text.endswith("]"):
        return text[1:-1].strip().lower()
    return None


def key_name(body):
    text = body.strip()
    if not text or text[0] in ";#" or "=" not in text:
        return None
    return text.split("=", 1)[0].strip().lower()


def load(path):
    with open(path, "rb") as handle:
        data = handle.read()
    text = data.decode("utf-8", "surrogateescape")
    return text.splitlines(True)


def locate(lines):
    current = None
    hits = []
    for index, line in enumerate(lines):
        body, _ = split_end(line)
        name = section_name(body)
        if name is not None:
            current = name
            continue
        key = key_name(body)
        if key is not None:
            hits.append((current, key, index))
    return hits


def default_end(lines):
    for line in lines:
        _, end = split_end(line)
        if end:
            return end
    return "\n"


def find_value(lines, section, key):
    for current, found, index in locate(lines):
        if current != section.lower() or found != key.lower():
            continue
        body, _ = split_end(lines[index])
        return VALUE_RE.match(body).group("val").strip()
    return None


def compute_changes(lines, sets):
    changes = []
    for section, key, value in sets:
        old = find_value(lines, section, key)
        if old is None:
            changes.append((section, key, None, value))
        elif old.lower() != value.strip().lower():
            changes.append((section, key, old, value))
    return changes


def insert_key(lines, section, key, value, nl):
    header = None
    for index, line in enumerate(lines):
        body, _ = split_end(line)
        if section_name(body) == section.lower():
            header = index
            break
    if header is None:
        if lines:
            last_body, last_end = split_end(lines[-1])
            if not last_end:
                lines[-1] = last_body + nl
        lines.append("[%s]%s" % (section, nl))
        lines.append("%s = %s%s" % (key, value, nl))
        return
    end = header + 1
    while end < len(lines):
        body, _ = split_end(lines[end])
        if section_name(body) is not None:
            break
        end += 1
    lines.insert(end, "%s = %s%s" % (key, value, nl))


def apply_key(lines, section, key, value, nl):
    for current, found, index in locate(lines):
        if current != section.lower() or found != key.lower():
            continue
        body, line_end = split_end(lines[index])
        match = VALUE_RE.match(body)
        if match.group("val").strip().lower() == value.strip().lower():
            return False
        lines[index] = "%s%s%s%s%s" % (match.group("head"), match.group("pre"),
                                       value, match.group("post"), line_end)
        return True
    insert_key(lines, section, key, value, nl)
    return True


def read_sets():
    sets = []
    for raw in sys.stdin.read().splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        if len(parts) != 3:
            sys.stderr.write("entrada invalida: %r\n" % raw)
            raise SystemExit(2)
        sets.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return sets


def write_lines(path, lines):
    data = "".join(lines).encode("utf-8", "surrogateescape")
    directory = os.path.dirname(os.path.abspath(path))
    handle, tmp = tempfile.mkstemp(prefix=".ini-edit-", dir=directory)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv):
    if not argv or argv[0] not in ("get", "plan", "set"):
        sys.stderr.write(USAGE)
        return 2
    mode = argv[0]
    if len(argv) < 2:
        sys.stderr.write(USAGE)
        return 2
    path = argv[1]
    if not os.path.isfile(path):
        sys.stderr.write("no existe el archivo: %s\n" % path)
        return 2

    if mode == "get":
        if len(argv) < 4:
            sys.stderr.write(USAGE)
            return 2
        lines = load(path)
        value = find_value(lines, argv[2], argv[3])
        if value is None:
            return 3
        sys.stdout.write(value + "\n")
        return 0

    sets = read_sets()
    lines = load(path)
    changes = compute_changes(lines, sets)

    if mode == "plan":
        for section, key, old, new in changes:
            if old is None:
                sys.stdout.write("[%s] %s: (no estaba) -> %s\n" % (section, key, new))
            else:
                sys.stdout.write("[%s] %s: %s -> %s\n" % (section, key, old, new))
        return 0

    if not changes:
        return 0

    nl = default_end(lines)
    for section, key, value in sets:
        apply_key(lines, section, key, value, nl)
    write_lines(path, lines)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
