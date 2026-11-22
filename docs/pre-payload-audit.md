# Static audit of the four PRE payload fields

## Conclusion in plain terms

The four fields that looked like missing addresses **are not read before being
overwritten or before the kernel ends**, according to the analysis of the reviewed
native code, **assuming a full and constant execution mask**.

For this compiled PRE there is no evidence that we must invent GPU addresses and place
them in those fields. Keeping them at zero is consistent with this conditional static
result. This **does not authorize a runtime test** nor generalize to other kernels,
compilers, variants or execution masks.

Before, we only knew that the compiler declared them and that upstream left them at
zero. That was a research item to follow up, **not a demonstrated functional failure**.

## Scope and identities

Same input, options and compiler as in [the offline compilation](offline-pre-compilation.md):
PRE Xe2 40102 native_1080, B580 target 0xe20b, IGC 2.10.10+18926.

- Complete CM: `76942f6cff52b09ea8fef63adfce8b4119fcd45c8c0586c913eedb9e35fe773b`.
- Zebin: `3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2`.
- Native code: `2e42d33c13d6c93bfe86fa81b1427c92aa2980df1af0100e011753a067f8ed5f`.
- IGA disassembly emitted by ocloc:
  `a9c82bbfccc535959e73ddd6b80fb209ed8a12bf8607927f62078b43b6215660`.
- Textual SPIR-V of the embedded `.spv`:
  `7ed1d81b8127e9dbb1e0c5befa621060cf7ab47cd82f98f789099b7968db6a9e`.

The association of the disassemblies with the binary was established by running only the
offline disassemblers on the pinned zebin. The auditor rejects hash changes; it does not
aim to verify by itself a general ISA decoder. It also checks that the embedded `.spv`
matches the start of the CM input byte for byte. It does not load the DLL nor dispatch on
the GPU.

## IR and native code evidence

### 1. The three buffer arguments are opaque surfaces

In SPIR-V, the parameters of arguments 0, 9 and 10 have type
`OpTypeBufferSurfaceINTEL ReadWrite`, not a generic 64-bit pointer. The entry wrapper
passes them in the same order to the main function. In that function, each one has
**a single direct use**: `llvm.genx.address.convert.i32.p1intel.buffer_rw_t`.

That conversion produces a SurfaceIndex. **This does not mean the resources are useless:**
the kernel does access them through BTIs 8, 10 and 11. The audit does not confuse the
resource argument with the eight extra bytes declared by the backend.
`private_base_stateless` is an implicit field, not another parameter of the entry point.

### 2. The prologue loads the 32 bytes, but seeing that load is not enough

According to the disassembly, the prologue loads the cross-thread block into GRF `r2`.
The relative offsets and sizes are:

| Field | Bytes of the block |
|---|---|
| private_base_stateless | 0..7 |
| extra pointer of arg 0 | 8..15 |
| extra pointer of arg 9 | 16..23 |
| extra pointer of arg 10 | 24..31 |

The first message loads local IDs into `r1` from base + 32 + thread*64; the second loads
the eight cross-thread DWORDs into `r2` from the base. That layout matches the payload
code of the upstream ANV patch. It does not prove an observed execution.

### 3. Byte tracking and branches

`tools/audit_pre_payload.py` keeps the set of original bytes still present in `r2`. For
each instruction:

1. It checks the reads **before** applying writes.
2. It removes only bytes unconditionally overwritten under the assumed mask.
3. It does not remove bytes for a predicated `mov`/`send`.
4. For `sel`, the predicate selects the value; it does not suppress the write to the destination.
5. It takes the **union** of the live bytes of all branches; it accepts backedges up to a fixed point.
6. It ends a path at EOT or when no original byte remains.

Result: **160 instructions visited with some original byte still live; zero possible
reads of those bytes** under the declared assumptions. Paths that leave the kernel early
may end with bytes still present, but not read.

Some overwrite points recorded in the pinned ASM:

- Lines 20 and 23: replacement of bytes 0..3 via selects.
- Line 143: a four-DWORD write replaces the remaining bytes 4..15 on that path.
- Line 179: a vector write replaces the remaining bytes on a later path.
- Line 379: a sampler response replaces the remaining bytes on another path.

The analysis does not only look for register names or stateless messages. If it detected
an original use as arithmetic data, it would also mark it as a possible read. A possible
read would be an open item, not proof that it affects the result.

### 4. Do not confuse send padding with data that is read

A transposed message `d32x4t.a32` uses a scalar 32-bit address and four data components.
That the payload reserves a 64-byte GRF does not mean it reads all of its positions. The
auditor models those real sizes; for sampler/typed send sources it uses the physical range
as a conservative approximation.

Semantic basis, Intel sources pinned to the same version:

- [SEL](https://github.com/intel/intel-graphics-compiler/blob/v2.10.10/documentation/visa/instructions/SEL.md):
  `dst[i] = Pred[i] ? src0[i] : src1[i]` for channels with EM enabled.
- [LSC_UNTYPED](https://github.com/intel/intel-graphics-compiler/blob/v2.10.10/documentation/visa/instructions/LSC_UNTYPED.md):
  transpose consumes one address and successive components; requires SIMD1.

## Conditions still open

- **Execution mask:** the result assumes all relevant channels are active, with no EM
  changes during the kernel. A disabled channel could preserve bytes that a later read
  under another mask would reach. The upstream driver forces SIMD32 dispatch and scales
  local_size.x by 32; the real path still needs to be compiled and validated.
- **Decoding:** message sizes and operation come from the IGA included in the pinned
  toolchain. The auditor does not independently verify every bit of the descriptor.
- **GRF size:** only the 64 bytes of this Xe2 target are modeled.
- **IR:** the direct use of the parameters is verified, not a complete semantic analysis
  of every function; the proof of the extra bytes relies on native code.
- **Scope:** a single reviewed kernel/input/output. Other outputs are rejected.
- Dynamic sampler, local dimensions, VKD3D runtime layout and context copy remain
  pending. Mesa was not installed nor compiled, and no game files were changed.

The profile keeps its experimental status and `runtime_approved=false`. No patch was
added to fill unused addresses, and the canaries were not relaxed.

## Reproduction

From the root, with the zebin and local toolchain already verified:

```bash
mkdir -p analysis/pre-payload
LD_LIBRARY_PATH="$PWD/artifacts/extracted/intel-toolchain/igc/usr/local/lib:$PWD/artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu" \
artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1 disasm \
  -file "$PWD/analysis/offline-pre/full/pre_bmg.bin" \
  -dump "$PWD/analysis/pre-payload/disasm" -device bmg-g21

python - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, 'tools')
from inspect_zebin import sections
p = Path('analysis/offline-pre/full/pre_bmg.bin')
Path('analysis/pre-payload/embedded.spv').write_bytes(sections(p.read_bytes())['.spv'])
PY
spirv-dis analysis/pre-payload/embedded.spv -o analysis/pre-payload/embedded.spvasm
python tools/audit_pre_payload.py analysis/cm-payloads-0001/module-0000.cmspv \
  analysis/offline-pre/full/pre_bmg.bin \
  analysis/pre-payload/disasm/.text.fsr4_pre_xmx.asm \
  analysis/pre-payload/embedded.spvasm > analysis/pre-payload/report.json
cmp profiles/fsr4-pre-native1080-payload-audit.json analysis/pre-payload/report.json
python -m unittest discover -s tests -v
```

The disassembler reported `Warnings: unexpected padding at end of kernel` and exit 0.
The log was kept. There are `illegal` padding instructions after the EOT, with no path
reachable from the prologue. The auditor refuses to reach them with live bytes.

The tests include real reads, partial and predicated writes, branch unions, loops,
read-before-write, short load responses and message padding. Those tests verify the
limited analyzer, not the GPU image output.
