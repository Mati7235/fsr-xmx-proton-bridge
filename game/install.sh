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
. "$(dirname "$CLI")/lib/common.sh"

PROFILE_ID=cyberpunk2077

case "${1-}" in
  -h|--help)
    cat <<'EOF'
Usage: ./install.sh [<game-folder>] [options]

Run it in the folder that holds the game's .exe (for Cyberpunk 2077 that is
.../bin/x64) after putting the files from PUT-THE-FILES-HERE.txt there. It
checks them, sets the game up and prints the line for the Steam launch options.

Options, passed to the fsr-xmx command:
  --fsr4 lite              use the Lite model instead of INT8
  --fg anr --anr <zip>     use ANR frame generation (the add-on zip is needed
                           the first time)

Undo with ./uninstall.sh in this folder.
EOF
    exit 0
    ;;
esac

game_arg=""
if [ $# -gt 0 ]; then
  case "$1" in
    -*) ;;
    *) game_arg="$1"; shift ;;
  esac
fi

if [ -n "$game_arg" ]; then
  if [ ! -d "$game_arg" ]; then
    fail "Game folder not found: $game_arg"
  fi
  game_dir="$(cd "$game_arg" && pwd -P)"
else
  game_dir="$(cd "$PWD" && pwd -P)"
fi

load_profile "$(profile_path "$PROFILE_ID")"
exe="$(prof_get GAME_EXE)"
if [ -z "$exe" ] || [ ! -f "$game_dir/$exe" ]; then
  fail "$exe is not in $game_dir; run ./install.sh from the folder with the game's .exe, or pass that folder: ./install.sh <game-folder>"
fi

mod_name="$(prof_get MOD_DLL)"
check_pinned_file "$game_dir/$mod_name" "$(prof_get MOD_SHA256)" "$(prof_get MOD_SIZE)" \
  "nitec's FSR4 XMX 4.1.2 mod ($mod_name)" \
  "Put the mod in $game_dir; where to get it is in PUT-THE-FILES-HERE.txt."

orig_name="$(prof_get FSR_ORIGINAL_DLL)"
check_pinned_file "$game_dir/$orig_name" "$(prof_get FSR_ORIGINAL_SHA256)" "$(prof_get FSR_ORIGINAL_SIZE)" \
  "AMD's official FSR 4.1.2 DLL ($orig_name)" \
  "Put the official 4.1.2 DLL in $game_dir; where to get it is in PUT-THE-FILES-HERE.txt."

opti_dll="$(prof_get OPTISCALER_DLL)"
opti_ini="$(prof_get OPTISCALER_INI)"
if [ ! -f "$game_dir/$opti_dll" ]; then
  if [ -f "$game_dir/OptiScaler.dll" ]; then
    fail "$opti_dll is not in $game_dir, but OptiScaler.dll is. The release ships the file under that name, so rename it in the game folder with: mv OptiScaler.dll $opti_dll"
  fi
  fail "$opti_dll is not in $game_dir; put the OptiScaler release files there, see PUT-THE-FILES-HERE.txt"
fi
if [ ! -f "$game_dir/$opti_ini" ]; then
  fail "$opti_ini is not in $game_dir; put the OptiScaler release files there, see PUT-THE-FILES-HERE.txt"
fi

if [ ! -f "$(release_dir)/igdext64.dll" ] || [ ! -f "$(release_dir)/cabinet.dll" ]; then
  fail "The driver step has not run on this machine yet (nothing at $(release_dir)); run driver/install.sh --from <bundle folder> first."
fi

enable_status=0
"$CLI" enable "$game_dir" --fsr4 "$(prof_get FSR4_DEFAULT int8)" --fg "$(prof_get FG_DEFAULT xefg)" "$@" ||
  enable_status=$?
if [ "$enable_status" -ne 0 ]; then
  exit "$enable_status"
fi

steam_cli="$CLI"
case "$CLI" in
  *[[:space:]]*) steam_cli="\"$CLI\"" ;;
esac
profile_name="$(basename "$PROF_FILE" .conf)"

say "Paste this line into Steam, in $(prof_get GAME_NAME "$PROFILE_ID") → Properties → General → Launch Options:"
say ""
say "  $steam_cli run --profile $profile_name -- %command%"
say ""
say "To undo, run ./uninstall.sh in this folder."
