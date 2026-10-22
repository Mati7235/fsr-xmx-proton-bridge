#!/usr/bin/env python3
"""Generate a reviewable patch-of-patches for a LOCAL CMK3 prototype reader.

Does not apply patches, build Mesa, install anything, or modify upstream. Keep
legacy CMK2 behavior. CMK3 preserves explicit table base and requires an exact
push-range size plus per-surface range coverage. Full Mesa compilation is pending.
"""
import argparse
import difflib
from pathlib import Path
import re


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Upstream context changed or is ambiguous')
    return text.replace(old, new, 1)


def recount(text):
    lines = text.splitlines(keepends=True)
    delta = 0
    for i, line in enumerate(lines):
        if line.startswith('diff --git '):
            delta = 0
        match = re.match(r'@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@(.*)', line)
        if not match:
            continue
        end = i+1
        while end < len(lines) and not lines[end].startswith(('@@ ', 'diff --git ', '-- \n')):
            if lines[end][:1] not in (' ', '+', '-', '\\'):
                break
            end += 1
        old = sum(l.startswith((' ', '-')) for l in lines[i+1:end])
        new = sum(l.startswith((' ', '+')) for l in lines[i+1:end])
        start = int(match.group(1))
        lines[i] = f'@@ -{start},{old} +{start+delta},{new} @@{match.group(2)}\n'
        delta += new-old
    return ''.join(lines)


def adapt(text):
    text = once(text,
        '+   if (fread(&h, sizeof(h), 1, f) != 1 || memcmp(h.magic, "CMK2", 4) != 0 ||\n',
        '+   if (fread(&h, sizeof(h), 1, f) != 1 ||\n'
        '+       (memcmp(h.magic, "CMK2", 4) != 0 && memcmp(h.magic, "CMK3", 4) != 0) ||\n')
    text = once(text,
        '+   void *code = ralloc_size(mem_ctx, h.code_size);\n',
        '+   /* LOCAL CMK3 prototype: two extra u32 fields precede native code.\n'
        '+    * Old CMK2 readers reject its magic; CMK2 behavior remains unchanged. */\n'
        '+   const bool explicit_table_base = memcmp(h.magic, "CMK3", 4) == 0;\n'
        '+   uint32_t mapping[2] = {0, 0}; /* flags, expected push-range size */\n'
        '+   if (explicit_table_base &&\n'
        '+       (fread(mapping, sizeof(mapping), 1, f) != 1 || mapping[0] != 1 ||\n'
        '+        mapping[1] == 0 || (mapping[1] & 3) || h.nsurf == 0 || h.nsurf > 24 ||\n'
        '+        (h.table_pc_base & 3))) {\n'
        '+      fprintf(stderr, "ANV CM: invalid CMK3 mapping in %s\\n", path);\n'
        '+      fclose(f);\n'
        '+      return ANV_CM_FAILED;\n'
        '+   }\n'
        '+   void *code = ralloc_size(mem_ctx, h.code_size);\n')
    marker = '+   const struct vk_shader_compile_info *ci = shader_data->info;\n+   if (cs->cm_has_sampler) {'
    validation = '''+   const struct vk_shader_compile_info *ci = shader_data->info;
+   if (explicit_table_base) {
+      uint64_t push_size = 0;
+      for (uint32_t r = 0; r < ci->push_constant_range_count; r++) {
+         const uint64_t end = (uint64_t)ci->push_constant_ranges[r].offset +
+                              ci->push_constant_ranges[r].size;
+         if (end > push_size)
+            push_size = end;
+      }
+      bool valid = push_size == mapping[1];
+      for (uint32_t k = 0; k < h.nsurf && valid; k++) {
+         const uint64_t off = (uint64_t)h.table_pc_base + 4ull * h.table_idx[k];
+         bool covered = false;
+         for (uint32_t r = 0; r < ci->push_constant_range_count; r++) {
+            const uint64_t begin = ci->push_constant_ranges[r].offset;
+            const uint64_t end = begin + ci->push_constant_ranges[r].size;
+            covered |= off >= begin && off + 4 <= end;
+         }
+         valid &= covered && off + 4 <= push_size;
+      }
+      if (!valid) {
+         fprintf(stderr, "ANV CM: CMK3 push layout mismatch in %s\\n", path);
+         *cs = saved;
+         return ANV_CM_FAILED;
+      }
+   }
+   if (cs->cm_has_sampler) {'''
    text = once(text, marker, validation)
    text = once(text,
        '+      if (auto_heap) {\n+         /* vkd3d push constants end with',
        '+      if (auto_heap && !explicit_table_base) {\n+         /* vkd3d push constants end with')
    return recount(text)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('upstream', type=Path)
    a = p.parse_args()
    for relative in ['patches/0001-anv-cm-kernel-injection.patch',
                     'patches/mesa-26.3/0001-anv-cm-kernel-injection.patch']:
        original = (a.upstream/relative).read_text()
        modified = adapt(original)
        print(''.join(difflib.unified_diff(original.splitlines(True), modified.splitlines(True),
                                          fromfile='a/'+relative, tofile='b/'+relative)), end='')


if __name__ == '__main__':
    main()
