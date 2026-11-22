#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'fsr-xmx: %s\n' "$*" >&2
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

SELF="$(resolve_self "${BASH_SOURCE[0]}")"
SELF_DIR="$(dirname "$SELF")"

. "$SELF_DIR/find-cli.sh"
CLI="$(find_cli "$SELF_DIR")" ||
  fail "This download is incomplete: fsr-xmx/ has to sit next to install.sh."
CLI="$(resolve_self "$CLI")"

case "${1-}" in
  -h|--help)
    cat <<'EOF'
Usage: ./uninstall.sh [<game-folder>]

Puts back every file that install.sh replaced or added, using the backup in
.fsr-xmx-backup/<timestamp>/ and comparing sha256. Without an argument it uses
the current folder. If a file cannot be restored it names the file, keeps the
state pending and exits non-zero; run it again to retry.
EOF
    exit 0
    ;;
esac

game_arg="${1-}"
if [ -n "$game_arg" ]; then
  if [ ! -d "$game_arg" ]; then
    fail "Game folder not found: $game_arg"
  fi
  game_dir="$(cd "$game_arg" && pwd -P)"
else
  game_dir="$(cd "$PWD" && pwd -P)"
fi

"$CLI" disable "$game_dir"

printf '\n%s\n' "The backup in $game_dir/.fsr-xmx-backup stays there; delete it by hand when you are happy."
