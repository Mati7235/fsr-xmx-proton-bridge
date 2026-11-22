#!/usr/bin/env bash

# Prints the fsr-xmx command for the folder that holds this file. The release
# keeps its own copy under fsr-xmx/, and a repository checkout has it under
# installer/. Returns non-zero when neither exists.

find_cli() {
  local self_dir="$1" candidate
  for candidate in "$self_dir/fsr-xmx/fsr-xmx" "$self_dir/../installer/fsr-xmx"; do
    if [ -x "$candidate" ]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}
