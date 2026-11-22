#!/usr/bin/env bash
set -euo pipefail

say() { printf '%s\n' "$*"; }
fail() {
  printf 'fsr-xmx driver: %s\n' "$*" >&2
  exit 1
}

resolve_self() {
  local path="$1" dir target
  case "$path" in
    */*) ;;
    *) path="$(command -v -- "$path" 2>/dev/null || printf '%s' "$path")" ;;
  esac
  while [ -L "$path" ]; do
    dir="$(cd "$(dirname "$path")" && pwd -P)"
    target="$(readlink "$path")"
    case "$target" in
      /*) path="$target" ;;
      *) path="$dir/$target" ;;
    esac
  done
  dir="$(cd "$(dirname "$path")" && pwd -P)"
  printf '%s/%s' "$dir" "$(basename "$path")"
}

sha256_of() { sha256sum "$1" | cut -d' ' -f1; }

SELF="$(resolve_self "${BASH_SOURCE[0]}")"
SELF_DIR="$(dirname "$SELF")"

case "${1-}" in
  -h|--help)
    cat <<'EOF'
Usage: sudo ./uninstall.sh [--test-root <folder>]

Removes the files that install.sh wrote, using the list and the checksums in
/opt/fsr-xmx/created.tsv. It refuses when a file changed since the install, and
it never deletes a path that is not in that list.

It also undoes the per-user part with the fsr-xmx command, which refuses while a
game is still set up. Run game/uninstall.sh in each game folder first.
EOF
    exit 0
    ;;
esac

test_root=""
while [ $# -gt 0 ]; do
  case "$1" in
    --test-root) test_root="${2-}"; shift 2 ;;
    --test-root=*) test_root="${1#*=}"; shift ;;
    *) fail "Unknown option: $1 (see --help)" ;;
  esac
done

if [ -n "$test_root" ]; then
  if [ "${FSR_XMX_DRIVER_TEST_ROOT:-}" != "1" ]; then
    fail "--test-root exists only for the test suite; set FSR_XMX_DRIVER_TEST_ROOT=1 to use it."
  fi
  case "$test_root" in
    /*) ;;
    *) fail "--test-root needs an absolute path." ;;
  esac
  if [ ! -d "$test_root" ]; then
    fail "--test-root folder not found: $test_root"
  fi
fi

ROOT_DIR="$test_root"
OPT_DIR="$ROOT_DIR/opt/fsr-xmx"
MANIFEST="$OPT_DIR/created.tsv"

if [ -z "$test_root" ] && [ "$(id -u)" -ne 0 ]; then
  fail "This removes files under /usr, /opt and /etc, so it needs root; run it with sudo."
fi

. "$SELF_DIR/find-cli.sh"
CLI="$(find_cli "$SELF_DIR")" ||
  fail "This download is incomplete: fsr-xmx/ has to sit next to install.sh."
CLI="$(resolve_self "$CLI")"

if [ ! -f "$MANIFEST" ]; then
  say "Nothing from the driver step is installed under ${ROOT_DIR:-/}."
  exit 0
fi

mapfile -t entries <"$MANIFEST"

changed=()
for entry in "${entries[@]}"; do
  IFS=$'\t' read -r kind first second <<<"$entry"
  if [ "$kind" = "file" ] && [ -f "$second" ]; then
    if [ "$(sha256_of "$second")" != "$first" ]; then
      changed+=("$second")
    fi
  fi
done

if [ "${#changed[@]}" -gt 0 ]; then
  printf 'ERROR   these files changed since the install, so nothing was removed:\n' >&2
  printf '  %s\n' "${changed[@]}" >&2
  printf 'ERROR   Check them and run ./uninstall.sh again, or delete them by hand if you are sure.\n' >&2
  exit 1
fi

rm -f "$MANIFEST"

index="${#entries[@]}"
while [ "$index" -gt 0 ]; do
  index=$((index - 1))
  IFS=$'\t' read -r kind first second <<<"${entries[$index]}"
  case "$kind" in
    file) rm -f "$second" ;;
    dir) rmdir "$first" 2>/dev/null || true ;;
  esac
done

say "Removed every path the driver step created."

if "$CLI" uninstall; then
  say "The per-user part in your home is gone too."
else
  say "The per-user part is still installed. Undo each game with its own uninstall.sh, then run: $CLI uninstall"
fi

say ""
say "Log out and back in so the removed settings stop applying to your session."
