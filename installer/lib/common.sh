#!/usr/bin/env bash

COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER_DIR="$(cd "$COMMON_DIR/.." && pwd)"
PROFILES_DIR="${FSR_XMX_PROFILES:-$INSTALLER_DIR/profiles}"
ROOT="${FSR_XMX_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/fsr-xmx}"
CACHE="${FSR_XMX_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/fsr-xmx}"
SYSFS_DIR="${FSR_XMX_SYSFS:-/sys}"
MARKER=".fsr-xmx-root"
TOOL_NAME="GE-Proton-XMX"
declare -A PROF=()
PROF_FILE=""
FAIL_COUNT=0

say() { printf '%s\n' "$*"; }
info() { printf '       %s\n' "$*"; }
okl() { printf 'OK     %s\n' "$*"; }
warn() { printf 'AVISO  %s\n' "$*"; }
failmsg() { printf 'FALTA  %s\n' "$*"; FAIL_COUNT=$((FAIL_COUNT + 1)); }
die() { printf 'ERROR  %s\n' "$*" >&2; exit 1; }

need_python() {
  command -v python3 >/dev/null 2>&1 ||
    die "falta python3 (paquete python). Instalá: sudo pacman -S python"
}

sha256_of() { sha256sum "$1" | cut -d' ' -f1; }
size_of() { stat -c %s "$1"; }

steam_root() {
  if [ -n "${FSR_XMX_STEAM:-}" ]; then
    printf '%s' "$FSR_XMX_STEAM"
    return 0
  fi
  local candidate
  for candidate in "$HOME/.local/share/Steam" "$HOME/.steam/root" "$HOME/.steam/steam"; do
    if [ -d "$candidate" ]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  printf '%s' ""
}

flatpak_steam_dir() { printf '%s' "$HOME/.var/app/com.valvesoftware.Steam"; }

release_dir() { printf '%s' "$ROOT/current"; }

release_has() { [ -f "$ROOT/current/$1" ]; }

state_file() { printf '%s/profiles/%s/state.conf' "$ROOT" "$1"; }

profile_path() {
  local want="$1"
  case "$want" in
    /*) printf '%s' "$want" ;;
    *)
      if [ -f "$PROFILES_DIR/$want.conf" ]; then
        printf '%s' "$PROFILES_DIR/$want.conf"
      else
        printf '%s' "$PROFILES_DIR/$want"
      fi
      ;;
  esac
}

profile_ids() {
  local file
  for file in "$PROFILES_DIR"/*.conf; do
    [ -f "$file" ] || continue
    basename "$file" .conf
  done
}

load_profile() {
  local file="$1" line key val
  [ -f "$file" ] || die "no encuentro el perfil: $file"
  PROF=()
  PROF_FILE="$file"
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in
      ''|'#'*) continue ;;
    esac
    case "$line" in
      *=*) ;;
      *) continue ;;
    esac
    key="${line%%=*}"
    val="${line#*=}"
    key="${key//[[:space:]]/}"
    val="${val#"${val%%[![:space:]]*}"}"
    val="${val%"${val##*[![:space:]]}"}"
    case "$val" in
      \"*\") val="${val#\"}"; val="${val%\"}" ;;
    esac
    PROF["$key"]="$val"
  done <"$file"
}

prof_get() {
  local key="$1"
  printf '%s' "${PROF[$key]:-${2-}}"
}

key_get() {
  local file="$1" key="$2" line
  [ -f "$file" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in
      "$key="*) printf '%s' "${line#*=}"; return 0 ;;
    esac
  done <"$file"
  return 1
}

manifest_get() {
  local dir="$1" key="$2"
  [ -f "$dir/MANIFEST" ] || return 1
  sed -n "s/^${key}=//p" "$dir/MANIFEST" | head -1
}

hash_in_list() {
  local hash="$1" list="$2" item
  case ",$list," in
    *",$hash,"*) return 0 ;;
  esac
  return 1
}

verify_archive() {
  local path="$1" label="$2" allowed="$3" hint="$4" got
  [ -f "$path" ] || die "no existe el archivo: $path"
  got="$(sha256_of "$path")"
  if hash_in_list "$got" "$allowed"; then
    return 0
  fi
  say "El $label no es el esperado." >&2
  say "  archivo:  $path" >&2
  say "  sha256:   $got" >&2
  say "  esperaba: $allowed" >&2
  die "$hint"
}

check_pinned_file() {
  local path="$1" expected_sha="$2" expected_size="$3" label="$4" hint="$5" got size
  [ -f "$path" ] || die "falta $label: $path. $hint"
  got="$(sha256_of "$path")"
  size="$(size_of "$path")"
  if [ -n "$expected_size" ] && [ "$size" != "$expected_size" ]; then
    say "El $label tiene un tamaño distinto al esperado: $size bytes (esperaba $expected_size)." >&2
    die "$hint"
  fi
  if [ "$got" != "$expected_sha" ]; then
    say "El $label no coincide con el esperado." >&2
    say "  archivo:  $path" >&2
    say "  sha256:   $got" >&2
    say "  esperaba: $expected_sha" >&2
    die "$hint"
  fi
}

extract_archive() {
  local archive="$1" dest="$2" lower
  [ -f "$archive" ] || die "no existe el archivo: $archive"
  mkdir -p "$dest"
  lower="$(printf '%s' "$archive" | tr 'A-Z' 'a-z')"
  case "$lower" in
    *.7z)
      if command -v 7z >/dev/null 2>&1; then
        7z x -y -o"$dest" "$archive" >/dev/null || die "no pude abrir $archive con 7z"
      elif command -v 7za >/dev/null 2>&1; then
        7za x -y -o"$dest" "$archive" >/dev/null || die "no pude abrir $archive con 7za"
      else
        die "el archivo es .7z y falta el programa 7z. Instalá: sudo pacman -S p7zip"
      fi
      ;;
    *.zip)
      if command -v unzip >/dev/null 2>&1; then
        unzip -q -o "$archive" -d "$dest" || die "no pude abrir $archive con unzip"
      elif command -v bsdtar >/dev/null 2>&1; then
        bsdtar -xf "$archive" -C "$dest" || die "no pude abrir $archive con bsdtar"
      else
        die "el archivo es .zip y falta unzip. Instalá: sudo pacman -S unzip"
      fi
      ;;
    *.tar.xz|*.tar.gz|*.tar.zst|*.tgz)
      tar -xf "$archive" -C "$dest" || die "no pude abrir $archive con tar"
      ;;
    *)
      die "no sé abrir $archive (formatos: .7z, .zip, .tar.xz)"
      ;;
  esac
}

BK_DIR=""
BK_MANIFEST=""
BK_GAME=""

backup_begin() {
  local game="$1" stamp base n=1
  if [ -n "$BK_DIR" ] && [ "$BK_GAME" = "$game" ]; then
    return 0
  fi
  BK_GAME="$game"
  stamp="$(date +%Y%m%d-%H%M%S)"
  base="$game/.fsr-xmx-backup/$stamp"
  while [ -e "$base" ]; do
    n=$((n + 1))
    base="$game/.fsr-xmx-backup/$stamp-$n"
  done
  mkdir -p "$base/files"
  BK_DIR="$base"
  BK_MANIFEST="$base/manifest.tsv"
  printf 'FORMAT\t1\nGAME_DIR\t%s\nCREATED\t%s\n' "$game" "$stamp" >"$BK_MANIFEST"
}

backup_record() {
  local path="$1" rel
  [ -n "$BK_DIR" ] || return 0
  rel="${path#"$BK_GAME"/}"
  case "$rel" in
    ''|/*|..|../*) return 0 ;;
  esac
  if awk -F'\t' -v want="$rel" '$2 == want { found = 1 } END { exit !found }' "$BK_MANIFEST"; then
    return 0
  fi
  if [ -f "$path" ]; then
    mkdir -p "$BK_DIR/files/$(dirname "$rel")"
    cp -p "$path" "$BK_DIR/files/$rel"
    printf 'replaced\t%s\t%s\n' "$rel" "$(sha256_of "$path")" >>"$BK_MANIFEST"
  else
    printf 'added\t%s\n' "$rel" >>"$BK_MANIFEST"
  fi
}

backup_mkdir() {
  local dir="$1" rel cur rel_cur
  local -a missing=()
  [ -n "$BK_DIR" ] || return 0
  [ -d "$dir" ] && return 0
  cur="$dir"
  while [ "$cur" != "$BK_GAME" ] && [ "$cur" != "/" ] && [ ! -d "$cur" ]; do
    missing=("$cur" "${missing[@]}")
    cur="$(dirname "$cur")"
  done
  mkdir -p "$dir"
  for cur in "${missing[@]}"; do
    rel="${cur#"$BK_GAME"/}"
    rel="${rel%/}"
    case "$rel" in
      ''|/*|..|../*) continue ;;
    esac
    printf 'mkdir\t%s\n' "$rel" >>"$BK_MANIFEST"
  done
}

copy_with_backup() {
  local src="$1" dst="$2"
  [ -f "$src" ] || die "falta el archivo de origen: $src"
  if [ -f "$dst" ] && [ "$(sha256_of "$src")" = "$(sha256_of "$dst")" ]; then
    return 0
  fi
  backup_mkdir "$(dirname "$dst")"
  backup_record "$dst"
  cp -p "$src" "$dst"
}

tree_with_backup() {
  local src="$1" dst="$2" item rel
  [ -d "$src" ] || die "falta la carpeta de origen: $src"
  while IFS= read -r item; do
    rel="${item#"$src"}"
    rel="${rel#/}"
    backup_mkdir "$dst/$rel"
  done < <(find "$src" -type d | LC_ALL=C sort)
  while IFS= read -r item; do
    [ "$item" = "$src" ] && continue
    rel="${item#"$src"/}"
    copy_with_backup "$item" "$dst/$rel"
  done < <(find "$src" -type f | LC_ALL=C sort)
}

backup_has_entries() {
  [ -n "$(sed -n '4,$p' "$BK_MANIFEST")" ]
}

backup_discard_if_empty() {
  if [ -n "$BK_DIR" ] && ! backup_has_entries; then
    rm -rf "$BK_DIR"
    BK_DIR=""
    BK_MANIFEST=""
  fi
}

bundle_required() {
  printf '%s\n' \
    "MANIFEST" \
    "SHA256SUMS" \
    "icd/intel_icd.json" \
    "lib/libvulkan_intel.so" \
    "igdext64.dll" \
    "cabinet.dll" \
    "vkd3d-proton/x86_64-windows/d3d12.dll" \
    "vkd3d-proton/x86_64-windows/d3d12core.dll" \
    "tools/cm-compile.sh"
}

verify_bundle() {
  local dir="$1" file line hash rest got problems=0 count=0
  for file in $(bundle_required); do
    if [ ! -f "$dir/$file" ]; then
      failmsg "a la instalación le falta $file (en $dir)."
      problems=1
    fi
  done
  [ -f "$dir/SHA256SUMS" ] || return "$problems"
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in
      ''|'#'*) continue ;;
    esac
    hash="${line%% *}"
    rest="${line#* }"
    rest="${rest# }"
    rest="${rest#\*}"
    rest="${rest#./}"
    [ -n "$rest" ] || continue
    count=$((count + 1))
    if [ ! -f "$dir/$rest" ]; then
      failmsg "falta el archivo $rest que figura en SHA256SUMS."
      problems=1
      continue
    fi
    got="$(sha256_of "$dir/$rest")"
    if [ "$got" != "$hash" ]; then
      failmsg "el archivo $rest no coincide con SHA256SUMS (puede estar dañado o incompleto)."
      problems=1
    fi
  done <"$dir/SHA256SUMS"
  if [ "$count" -eq 0 ]; then
    failmsg "SHA256SUMS está vacío; no puedo verificar la instalación."
    problems=1
  fi
  local needed
  for needed in igdext64.dll cabinet.dll icd/intel_icd.json vkd3d-proton/x86_64-windows/d3d12.dll vkd3d-proton/x86_64-windows/d3d12core.dll; do
    if ! grep -q "  $needed\$" "$dir/SHA256SUMS" 2>/dev/null &&
       ! grep -q " \*$needed\$" "$dir/SHA256SUMS" 2>/dev/null; then
      failmsg "$needed no está listado en SHA256SUMS; no puedo confiar en esa instalación."
      problems=1
    fi
  done
  return "$problems"
}

intel_card_dir() {
  local vendor
  for vendor in "$SYSFS_DIR"/class/drm/card*/device/vendor; do
    [ -f "$vendor" ] || continue
    case "$(cat "$vendor")" in
      0x8086|8086) printf '%s' "${vendor%/device/vendor}"; return 0 ;;
    esac
  done
  return 1
}

card_driver() {
  local card="$1" link
  link="$(readlink -f "$card/device/driver" 2>/dev/null || true)"
  [ -n "$link" ] || return 1
  printf '%s' "$(basename "$link")"
}

has_vulkan_loader() {
  local path
  if [ -n "${FSR_XMX_VULKAN_LOADER:-}" ]; then
    [ -f "$FSR_XMX_VULKAN_LOADER" ] && return 0
    return 1
  fi
  for path in /usr/lib/libvulkan.so.1 /usr/lib64/libvulkan.so.1 \
              /usr/lib/x86_64-linux-gnu/libvulkan.so.1 /usr/local/lib/libvulkan.so.1; do
    [ -e "$path" ] && return 0
  done
  if command -v ldconfig >/dev/null 2>&1 && ldconfig -p 2>/dev/null | grep -q 'libvulkan\.so\.1'; then
    return 0
  fi
  return 1
}

dll_overridden() {
  local list="$1" want="$2" entry
  local IFS=','
  for entry in $list; do
    entry="$(printf '%s' "$entry" | tr 'A-Z' 'a-z' | tr -d ' ')"
    [ "${entry%%=*}" = "$want" ] && return 0
  done
  return 1
}

merge_dll_overrides() {
  local existing="$1" out="$1" dll
  shift
  for dll in "$@"; do
    if ! dll_overridden "$existing" "$dll"; then
      if [ -n "$out" ]; then
        out="$out,$dll=n,b"
      else
        out="$dll=n,b"
      fi
    fi
  done
  printf '%s' "$out"
}

ini_stream() {
  local spec="$1" item
  local IFS=';'
  for item in $spec; do
    [ -n "$item" ] || continue
    printf '%s\n' "${item//|/$'\t'}"
  done
}

game_running() {
  local exe="$1" game_dir="${2-}" pid entry cwd found=1
  [ -n "$exe" ] || return 1
  for pid in /proc/[0-9]*; do
    pid="${pid#/proc/}"
    [ "$pid" = "$$" ] && continue
    [ "$pid" = "$PPID" ] && continue
    [ -r "/proc/$pid/cmdline" ] || continue
    cwd=""
    while IFS= read -r -d '' entry; do
      [ "${entry##*/}" = "$exe" ] || continue
      case "$entry" in
        /*) found=0; break ;;
      esac
      if [ -z "$cwd" ]; then
        cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
      fi
      if [ -n "$game_dir" ] && [ "$cwd" = "$game_dir" ]; then
        found=0
        break
      fi
    done <"/proc/$pid/cmdline"
    [ "$found" = "0" ] && break
  done
  return "$found"
}
