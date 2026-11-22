# macl + acc0 in fsr4_pre_xmx 4.1.2: semantics, flows and verdict

CPU-only, static. No DLLs executed, no GPU/Wine, no touching
`artifacts/original`, games or prefixes. IGA and zebin read-only.
REA/Ghidra does not disassemble EU ISA; the primary evidence is the pinned IGA
(`analysis/offline-pre-412/disasm/.text.fsr4_pre_xmx.asm`, 2390 lines,
sha `7773a88b…`) plus the public IGC/Mesa sources cited below.

## 1. Exact semantics of `macl` (line 444)

IGA (lines 441-444, file numbering):

```
L6024:                                                            // 441
(W)     mul (1|M0)               acc0.0<1>:d   r82.14<0;1,0>:d   r80.2<0;1,0>:uw  // 442
        shl (1|M0)               r1.1<1>:d     r80.0<0;1,0>:d    3:w               {Compacted}  // 443
        macl (1|M0)              r1.0<1>:d     r82.14<0;1,0>:d   r80.1<0;1,0>:d   {Compacted}  // 444
```

Breakdown:

- Opcode `macl`, width `(1|M0)`, no predicate, no `condmod`, no saturation.
  Unconditional execution under the assumed full mask.
- Explicit destination: `r1.0<1>:d` — 1 DWORD (GRF bytes 64..67).
- Explicit sources: `r82.14<0;1,0>:d` (bytes 5304..5307),
  `r80.1<0;1,0>:d` (bytes 5124..5127). Width 1, region `0;1,0`
  (vertical 0, span 1, horizontal 0): a single element.
  Does not overlap `r2` (bytes 128..159, seed at line 11).
- Implicit source: `acc0.0` (always `acc0.0`, 1 element `:d`).
  IGC: “`macl creates an implicit src using the supplied accType.
  AccWrCtrl is not set. acc0.0 is always used” (`visa/BuildIRImpl.cpp`,
  commit `66d1f97`, `createMach/createMacl wrapper`).
  IGA dependencies: “`mac/mach has implicitly read to acc0`” and the list
  includes `MACL` (`visa/iga/IGALibrary/IR/RegDeps.cpp`, `setInputsSrcDep`).
- Write: only the GRF destination `r1.0`. `macl` does **not** write `acc`
  in this model (conservative *no-kill*): IGC says `AccWrCtrl` is
  **not** set for `macl` (unlike `mach`, which creates
  “both implicit acc src and dst” and sets `AccWrCtrl`).
  `RegDeps.cpp` marks `MACL/MACH` as implicit writers of `acc`
  through dependency/SWSB over-approximation; assuming the write would
  clear `taint` and would be *unsound* (false negative). Not assuming it
  preserves `taint` (safe; at worst a false positive, which does not occur here).
  Mesa confirms the accumulator cost: “New on Xe2, this instruction
  enables faster 32x32 integer multiply at the cost of extra accumulator
  usage”, opcode 83, 2 src / 1 dst, `GFX_GE(XE2)`
  (commit `73701c3`, `brw: wire up MACL`).
- No modelable side effects: no `send`, no `null` with `condmod`,
  no indirect addressing (`r[`/`a0.` absent throughout the kernel),
  immediate descriptors. `{Compacted}` is a finalizer annotation,
  it does not change the footprint.
- Does not touch the bytes under analysis through explicit operands
  (disjoint from `r2.0..r2.7`, offsets 0..31). The only remaining channel would be
  the implicit `acc0`, which is clean on all live paths
  (§3). No predicate: there is no lane suppression.

Sources:

- IGC `createMach/createMacl`:
  `https://github.com/intel/intel-graphics-compiler/commit/66d1f97ea95492de78c400af9dba65a0b637460f`
- IGC `RegDeps.cpp` (`setInputsSrcDep`, `setDstRegion`, `acc0/acc1` pair):
  `https://github.com/intel/intel-graphics-compiler/blob/master/visa/iga/IGALibrary/IR/RegDeps.cpp`
- Mesa `MACL` Xe2:
  `https://github.com/maurossi/mesa/commit/73701c305e9ddc4087a3f68a372193a841cebed9`
- `AccWrCtrl`: “When set, the result is written to both destination and
  accumulator” (PRM Vol 2b, `AccWrCtrl`).

## 2. All `acc0` flows (`acc0/acc1` group)

Auditor model (`tools/audit_pre_payload.py`): explicit `accN` per
overlapping pair (`(n//2)*2`; `acc0/acc1` group 0, `acc2/acc3` group 1, …,
conservative per `RegDeps`: “we always mark them together”),
plus implicit group-0 read for `mac`/`macl`/`mach`.
`mac`/`macl` never write `acc` (no-kill); `mach` is still rejected
(`fail-closed`, not observed). Predicated non-`sel` writes do not kill
(they union); `sel` does kill (it selects a value). `send` with `acc` is rejected.
`acc` starts clean (the cross-thread payload is only in `r2`).

Static count in the 4.1.2 IGA (file, 2390 lines):

- Lines with `acc0`: 253 (old: 252; +1 due to the `mul acc0` on line 442
  that feeds `macl`; `macl` itself does not contain the string `acc0`).
- Explicit group-0 writes: 179 (`add`/`mad`/`mul`/`sel` to `acc0`,
  plus `acc1` of the same group). Explicit group-0 reads: 218
  (`mad`/`mul`/`cmp`/`sel`/`rnde`/`rndd`/`add` from `acc0/acc1`,
  incl. `(abs)acc0`; `-acc2` does not count here).
- Implicit group-0 reads: 9 (8× `mac` lines 2328-2354 + 1× `macl`
  line 444). `mach`: 0 observed.
- Remaining `acc`: group 2 (`acc2/acc3`) and high pairs for intermediate
  `mad`/`mul`/`sel` expansions; isolated from group 0.

`acc` writes (sample; `overlap_r2` = raw GRF footprint, without liveness):

- 174 `add acc0 = r99,-1.0`, 175 `mad acc0 = r80.7,acc0,r81.4`, …,
  212/214/216-220 (`add`/`mad` block in `f`), 236/251/273/… `sel acc0`,
  442 `mul acc0 = r82.14,r80.2` (feeds `macl`), 555… `mul acc0`,
  699/702/719/721…, 1022 `add acc0`, 1031… etc. None reads `r2`
  raw except those listed below.
- `acc` writes that **syntactically** read `r2` (wide vectors or broadcast;
  e.g. `r1.0<1;1,0>` width 32 overlaps `r1-r4` incl. `r2`,
  `r2.0<0;0>` broadcast 1 DWORD):
  278/300/330/358 `sel acc2 = r1,acc0` (width 32, overlaps `r2`),
  541 `mad acc0 = r2.0<0;0>,…` (1 DWORD 128..131),
  1027 `add acc2 = r2,…` (width 16, all of `r2`),
  1105 `mad acc0 = r2.0<0;0>,…`, 1590 `add acc1 = r2,…`,
  1701 `mad acc0 = …,r2`, 1740/1742/1744/1746 (`acc1/acc2/acc3 = …,r2`),
  1849 `add acc2 = r2,0.5`, 2329 `mul acc0 = r2,…`, etc.

`acc0` reads (sample):

- 176/179/182/185/189/… `rnde rX = acc0`, 238/253/281/303/333/361…
  `cmp null = …,acc0`, 244/259 `sel r61 = …,acc0`, 278/300…
  `sel acc2 = …,acc0`, 557 `mul acc0 = acc0,…` (self-accumulation),
  702/721 `sel acc0 = acc0,0.0`, 1024 `mul r6 = …, (abs)acc0`, …,
  2328-2354 `mac …` (implicit), 444 `macl` (implicit).

Does any path connect `acc0` with the bytes under analysis?

No. Flow-sensitive audit (`audit_native` extended, seed at line 11,
`r2` 32 B, union at joins, fixed point on backedges):

- State: `(grf_live, acc_live)`; `acc_live` maps group→set of original offsets.
  A read of `grf_live & usado` or `acc_taint & leído` ⇒
  `possible-read`. An unconditional write replaces; a predicated non-`sel` write
  unions. `macl`/`mac` read group 0 without writing it.
- Result 4.1.2: `unread-before-overwrite-or-end`, 160 visited,
  0 reads, overwrites at lines 20/23/143/179/379 — identical to the old one.
  `macl` (idx 415) is **not reachable with live bytes** (`states` empty);
  its explicit sources are disjoint from `r2` and its implicit `acc0` is
  clean on all live predecessors.
- All raw `acc` writes that read `r2` occur only where `grf_live`
  is already empty (after the kills at 20/23/143/179/379 on those paths): the
  `live`-pruned analysis never visits them with non-empty `live`,
  so they never introduce `taint` (`new_from_grf = live & usado`
  empty) and never report. No instruction that writes `acc`
  with non-empty `live` reads `r2`; therefore `acc_live` remains empty
  in all reachable states and all `acc0` reads
  (explicit + 8×`mac` + 1×`macl`) are clean.
- Group isolation verified by tests: a tainted `acc2` does not contaminate
  `macl` (group 0); `acc0→acc1` does contaminate (same pair).

## 3. Verdict

With the minimal and conservative model `macl`+`acc0` (relaxing nothing:
`mach` and unknown opcodes remain rejected, `send` with `acc`
rejected, unmodeled regions conservative or rejected):

- IGA 4.1.2 `fsr4_pre_xmx`: **no read before overwrite or end**,
  under a full and constant mask, 64 B GRFs, `send` descriptions
  from the IGA. 160 visited, 0 possible reads, overwrites
  20 (0..1), 23 (2..3), 143 (4..15), 179 (4..31), 379 (4..31).
- `macl` line 444 is benign: operands disjoint from `r2`, implicit `acc0`
  clean, unconditional, no side effects on `r2`.
- Profile `profiles/fsr4-pre-412-native1080-payload-audit.json`
  updated to `static-analysis-only` / `unread-before-overwrite-or-end`
  (was `static-analysis-blocked`); `runtime_approved=false` is kept.
  `build_report` still rejects because of the old pins (correct
  *fail-closed* identity checks, not a bug). `mach` is still rejected.
- This does **not** authorize runtime, nor generalize to other variants/stages/
  masks. Scope: one kernel/input/output reviewed.

Reproduction (CPU only):

```bash
python3 -m unittest tests.test_xmx412_payload_macl -v
python3 -m unittest tests.test_pre_payload_audit -v
python3 <<'PY'
import sys; sys.path.insert(0,'tools')
from audit_pre_payload import audit_native
print(audit_native(open('analysis/offline-pre-412/disasm/.text.fsr4_pre_xmx.asm').read(),11))
PY
```
