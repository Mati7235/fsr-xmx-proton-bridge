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

usage() {
  cat <<'EOF'
Usage: sudo ./install.sh [--from <bundle folder>] [--no-snapshot]

Installs the fsr-xmx driver bundle once for the whole machine. Without --from
it looks in the bundle folder next to this script.

It takes a snapper snapshot of the root config when snapper is installed, then
writes the driver to /usr/lib/fsr-xmx, an ICD file next to Mesa's own ICD files,
the two Windows stand-in DLLs to /opt/fsr-xmx, and the environment file to
/etc/environment.d/fsr-xmx.conf. Mesa's own ICD file is never replaced.

--no-snapshot skips the snapshot. Use it only when snapper cannot take one.

Undo with: sudo ./uninstall.sh
EOF
}

from=""
test_root=""
no_snapshot=0
while [ $# -gt 0 ]; do
  case "$1" in
    --from) from="${2-}"; shift 2 ;;
    --from=*) from="${1#*=}"; shift ;;
    --no-snapshot) no_snapshot=1; shift ;;
    --test-root) test_root="${2-}"; shift 2 ;;
    --test-root=*) test_root="${1#*=}"; shift ;;
    -h|--help) usage; exit 0 ;;
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
LIB_DIR="$ROOT_DIR/usr/lib/fsr-xmx"
ICD_DIR="$ROOT_DIR/usr/share/vulkan/icd.d"
OPT_DIR="$ROOT_DIR/opt/fsr-xmx"
ENV_DIR="$ROOT_DIR/etc/environment.d"
LIB_PATH="$LIB_DIR/libvulkan_intel.so"
ICD_PATH="$ICD_DIR/fsr-xmx-intel_icd.json"
ENV_FILE="$ENV_DIR/fsr-xmx.conf"
MANIFEST="$OPT_DIR/created.tsv"

if [ -z "$test_root" ] && [ "$(id -u)" -ne 0 ]; then
  fail "This step writes to /usr, /opt and /etc, so it needs root; run it with sudo."
fi

. "$SELF_DIR/find-cli.sh"
CLI="$(find_cli "$SELF_DIR")" ||
  fail "This download is incomplete: fsr-xmx/ has to sit next to install.sh."
CLI="$(resolve_self "$CLI")"

if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 is missing (package python), and this step needs it to write the ICD file; install it with sudo pacman -S python and run this again."
fi

if [ -z "$from" ]; then
  from="$SELF_DIR/bundle"
  if [ ! -d "$from" ]; then
    fail "No bundle folder given and $from does not exist; download the bundle and run ./install.sh --from <bundle folder>."
  fi
fi
if [ ! -d "$from" ]; then
  fail "Bundle folder not found: $from"
fi
from="$(cd "$from" && pwd -P)"
if [ ! -f "$from/SHA256SUMS" ]; then
  fail "$from has no SHA256SUMS file, so its files cannot be checked; nothing was written."
fi

for target in "$LIB_PATH" "$ICD_PATH" "$ENV_FILE" "$OPT_DIR/igdext64.dll" "$OPT_DIR/cabinet.dll"; do
  if [ -e "$target" ]; then
    fail "$target already exists; run ./uninstall.sh first, because this script does not overwrite files it did not create."
  fi
done

if [ -z "$test_root" ] && [ "$no_snapshot" = "0" ] && command -v snapper >/dev/null 2>&1; then
  if ! snap_out="$(snapper --config root create --description 'fsr-xmx driver install' --print-number 2>&1)"; then
    printf '%s\n' "$snap_out" >&2
    fail "snapper could not create a snapshot, so nothing was written; check snapper with sudo snapper --config root list, or run this again with --no-snapshot if you accept the risk."
  fi
  snap_number="$(printf '%s\n' "$snap_out" | grep -Eo '[0-9]+' | tail -1 || true)"
  if [ -n "$snap_number" ]; then
    say "snapper snapshot $snap_number created (config root). This script never deletes snapshots."
  else
    say "snapper ran but printed no number; check it with: sudo snapper --config root list"
  fi
elif [ -z "$test_root" ] && [ "$no_snapshot" = "1" ] && command -v snapper >/dev/null 2>&1; then
  say "Skipping the snapper snapshot because --no-snapshot was given."
fi

say "Checking the bundle and installing the per-user part with $CLI ..."
if ! "$CLI" install --from "$from"; then
  fail "The bundle failed its own check, so nothing was written to /usr, /opt or /etc."
fi

created_dirs=()
for dir in "$LIB_DIR" "$ICD_DIR" "$ENV_DIR" "$OPT_DIR"; do
  cur="$dir"
  while [ ! -d "$cur" ] && [ "$cur" != "/" ]; do
    created_dirs+=("$cur")
    cur="$(dirname "$cur")"
  done
done
for dir in "$LIB_DIR" "$ICD_DIR" "$ENV_DIR" "$OPT_DIR"; do
  mkdir -p "$dir"
done

: >"$MANIFEST"
if [ "${#created_dirs[@]}" -gt 0 ]; then
  printf '%s\n' "${created_dirs[@]}" | LC_ALL=C sort -u | while IFS= read -r dir; do
    printf 'dir\t%s\n' "$dir" >>"$MANIFEST"
  done
fi

put_file() {
  local src="$1" dst="$2" tmp hash
  if [ -e "$dst" ]; then
    fail "$dst already exists; run ./uninstall.sh first."
  fi
  tmp="$dst.fsr-xmx-new"
  cp -p "$src" "$tmp"
  hash="$(sha256_of "$tmp")"
  printf 'file\t%s\t%s\n' "$hash" "$dst" >>"$MANIFEST"
  mv -f "$tmp" "$dst"
}

put_text() {
  local dst="$1" tmp
  if [ -e "$dst" ]; then
    fail "$dst already exists; run ./uninstall.sh first."
  fi
  tmp="$dst.fsr-xmx-new"
  cat >"$tmp"
  printf 'file\t%s\t%s\n' "$(sha256_of "$tmp")" "$dst" >>"$MANIFEST"
  mv -f "$tmp" "$dst"
}

icd_tmp="$(mktemp "${TMPDIR:-/tmp}/fsr-xmx-icd.XXXXXX")"
if ! python3 - "$from/icd/intel_icd.json" "$LIB_PATH" >"$icd_tmp" <<'PY'
import json
import sys

source, library = sys.argv[1], sys.argv[2]
with open(source, encoding="utf-8") as handle:
    data = json.load(handle)
icd = data.get("ICD")
if not isinstance(icd, dict):
    raise SystemExit("the bundle ICD file has no ICD object")
icd["library_path"] = library
json.dump(data, sys.stdout, indent=4)
sys.stdout.write("\n")
PY
then
  rm -f "$icd_tmp"
  fail "The bundle's icd/intel_icd.json could not be read, so nothing was written to /usr, /opt or /etc."
fi

put_file "$from/lib/libvulkan_intel.so" "$LIB_PATH"
# This adds an ICD next to Mesa's own intel_icd file and never replaces or deletes
# it: Mesa's file stays, and only VK_DRIVER_FILES (the name fsr-xmx run uses) points here.
put_text "$ICD_PATH" <"$icd_tmp"
rm -f "$icd_tmp"

put_file "$from/igdext64.dll" "$OPT_DIR/igdext64.dll"
put_file "$from/cabinet.dll" "$OPT_DIR/cabinet.dll"

put_text "$ENV_FILE" <<EOF
# Written by fsr-xmx. Remove it with driver/uninstall.sh.
VK_DRIVER_FILES=$ICD_PATH
ANV_CM_HELPER=\${HOME}/.local/share/fsr-xmx/current/tools/cm-compile.sh
ANV_CM_KERNEL_DIR=\${HOME}/.cache/fsr-xmx/kernels
WINEDLLOVERRIDES=dxgi,cabinet=n,b
EOF

say ""
say "The driver is installed for the whole machine:"
say "  $LIB_PATH"
say "  $ICD_PATH"
say "  $OPT_DIR/igdext64.dll"
say "  $OPT_DIR/cabinet.dll"
say "  $ENV_FILE"
say "  $MANIFEST (the list uninstall.sh uses)"
say ""
say "Mesa's own ICD file was not touched: this adds one ICD next to it and points VK_DRIVER_FILES at the new file."
say ""
say "/etc/environment.d is only read when a login session starts, so log out and back in."
say "For the session you are in now, run:"
say "  export VK_DRIVER_FILES=$ICD_PATH"
say ""
say "Next: the game step, the separate fsr-xmx-game download."
say "That download has its own README, which explains what to do in the game folder."
say "Undo with: sudo ./uninstall.sh"
