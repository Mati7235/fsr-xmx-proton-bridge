# XMX 4.1.2 model selection: 4.0.2X, 4.1.2X, Lite, DLSS

Static analysis only, CPU-only. No DLL, pack or game binary was executed, and no GPU, Wine,
Steam, prefix or `artifacts/original` was touched. The 4.1.2 DLL was opened in Ghidra 12.2
headless (local project in `/tmp/opencode/ghidra-xmx412`), and the packs were decoded
read-only with the local tools. Addresses are VAs with `ImageBase = 0x180000000`; the file
offset comes from the PE section table.

Artifact:

- `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll`
- SHA-256 `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`
- PE32+ x86-64, 45 558 272 bytes.

Three fail-closed, CPU-only test files pin this document:
`tests/test_xmx412_model_strings.py` (7 tests: SHA, literals, `CreateModel` branches,
provider table, weights contract, labels), `tests/test_xmx412_variants.py` (16 tests, pack
40102) and `tests/test_xmx412_dlss.py` (21 tests, packs 40104 to 40106).

## Executive summary

| Variable (process) | Value | Resulting model | Native entry (index) | Weights required |
|---|---|---|---|---|
| `FSR4_XMX_INT8` | `1` | **4.1.2X** (INT8 model, kind 2) | 8 | `fsr-original.dll`: INT8 pair |
| `FSR4_XMX_LITE` | `1` | **4.1.2X Lite** (Lite model, kind 1) | 12 | `fsr-original.dll`: Lite pair |
| `FSR4_XMX_PRE41` | `1` | **4.0.2X Hybrid** (kind 0, hybrid flag) | 4 | embedded 4.0.2 (not external) |
| none | - | game's choice; default **4.0.2X** | 0 | embedded |
| `FSR4_XMX_DLSSK` / `DLSSM` / `DLSSE` | `1` / `1` or `L` / `E`, `F` or `A` | DLSS-KX / MX / LX / EX / FX / EFX | per table | `nvngx_dlss.dll` |

The Native entry column is the index of the provider entry that represents that model. The
environment override changes the model that `CreateModel` runs, but it does not change the
provider entry the game already chose. To also change the reported label or version, use the
dropdown or `FSR4_XMX_PROVIDER_INDEX`.

Direct conclusions:

- `FSR4_XMX_PRE41=1` selects 4.0.2X Hybrid, not 4.1.2X. Use `FSR4_XMX_INT8=1` for 4.1.2X
  and `FSR4_XMX_LITE=1` for Lite. With both set, INT8 wins when its weights exist, then Lite,
  then PRE41.
- Hybrid uses the embedded 4.0.2 weights and sets the model/hybrid flag `+0x207`, which
  changes the scratch size and dispatch bits. It loads no external weights.
- The `4.0.2X` label that OptiScaler shows comes from the base provider and the fixed VERSIONINFO
  `4.0.2.1`, not from `FSR4_XMX_*`. The 4.1.2 labels are generated with `%u.%u.%uX` from the
  version marker of the official DLL.
- The caller sees `4.1.2X` only when the 4.1.2X entry is selected (dropdown or
  `FSR4_XMX_PROVIDER_INDEX=8`). The environment override changes the model, not the label of
  the entry the game chose.
- `fsr-original.dll` is the official AMD FidelityFX Upscaler DX12 DLL of FSR 4.1.2, renamed.
  Place it next to the mod DLL, next to the EXE, or point `FSR4_XMX_LITE_DLL` at it. It is not
  `amdxcffx64.dll`, not the 4.0.2 DLL and not the modified 4.1.2 DLL, which lack the blobs
  the loader requires.

## 1. `CreateModel`: who reads what, and in what order

`CreateModel` is at `0x1800617C0` (the symbol string at `0x180321F70` reads
`unsigned int __cdecl CreateModel(struct InternalFsr4Context *,enum fsr4_shaders::Preset)`).
The reading and decision order is:

1. `FSR4_XMX_DLSSK` (`lea` at `0x180061900`)
2. `FSR4_XMX_DLSSM` (`0x180061933`)
3. `FSR4_XMX_DLSSE` (`0x18006195C`)
4. `FSR4_XMX_INT8` (`0x180061985`)
5. `FSR4_XMX_LITE` (`0x1800619A7`)
6. `FSR4_XMX_PRE41` (`0x1800619D4`)
7. if nothing applies: state of the provider entry chosen by the game or OptiScaler
   (fallback at `0x180061BFB`).

Each variable is read with `GetEnvironmentVariableA(..., 8)` and only the first byte is
compared with `'1'`. `0`, empty or any other text disables the branch.

### 1.1 INT8 to 4.1.2X

At `0x180061AE3` the value read from `FSR4_XMX_INT8` is checked (the `lea` of the name is at
`0x180061985`); if it is `1`, `FUN_180027c00()` is called and `byte [rax+0x68] != 0` is
required:

```asm
180061AEA  call 0x180027c00              ; fsr-original.dll weights structure
180061AEF  cmp  byte ptr [rax+0x68], 0   ; INT8 available
180061AF3  je   0x180061B08              ; if not, try LITE
180061AF7  lea  r14, [rip+0x2C08A2]      ; 0x1803223A0 = "4.1.2X"
180061B00  movzx r9d, sil                ; INT8 flag for FUN_180061020
```

The branch fixes `pcVar8 = "4.1.2X"` (`0x1803223A0`) and calls `FUN_180061020` at
`0x180061B66` with the INT8 flag. `FUN_180061020` writes:

- `provider+0x209 = INT8`
- `provider+0x208 = LITE || INT8`
- `provider+0x207 = PRE41 || LITE || INT8` (model/hybrid flag)

Afterwards `FUN_1800625B0` translates the state into a model:
`+0x209 ? 2 : (+0x208 ? 1 : 0)`, and calls `FUN_18004A9D0` (the model loader). That is why
4.1.2X is `kind=2` (INT8).

### 1.2 LITE to 4.1.2X Lite

At `0x180061B08` `FSR4_XMX_LITE` is checked; if it is `1`, `byte [FUN_180027c00()] != 0` is
required:

```asm
180061B0F  call 0x180027c00
180061B14  cmp  byte ptr [rax], 0        ; Lite available
180061B17  je   0x180061B2F              ; if not, try PRE41
180061B1B  lea  r14, [rip+0x2C0886]      ; 0x1803223A8 = "4.1.2X Lite"
180061B29  movzx r8d, sil                ; LITE flag
```

Label `0x1803223A8`, LITE flag. `FUN_1800625B0` translates it to `kind=1`. The Lite model
uses the same embedded XMX pack as INT8, but different weights (blobs of `0x6B00` bytes,
not `0x20000`).

### 1.3 PRE41 to 4.0.2X Hybrid

At `0x180061B2F` the stored value of `FSR4_XMX_PRE41` is checked:

```asm
180061B2F  cmp  byte ptr [rbp+0x3F0], 0x31   ; '1'
180061B36  jne  0x180061BFB                   ; provider fallback
180061B3C  lea  r14, [rip+0x2C031D]           ; 0x180321E60 = "4.0.2X Hybrid"
180061B43  movzx edx, sil                     ; PRE41 flag
```

Label `0x180321E60`, PRE41 flag. It does not touch `+0x208`/`+0x209`, so `FUN_1800625B0`
calls `FUN_18004A9D0(..., 0, ...)`: it loads no external weights and the model stays on the
embedded 4.0.2 weights. The `+0x207` flag enables the model/hybrid path; in
`FUN_180063830` it changes the scratch size (`FUN_180073FB0` versus `FUN_1800695C0`) and
adds `0x1000`/`0x2000` bits to the dispatch constants.

### 1.4 Priority and interaction

- `INT8=1` + `LITE=1` gives INT8 if `[0x68]` is available; otherwise Lite.
- `INT8=1` + `PRE41=1` gives INT8 if there are weights; otherwise Hybrid.
- `LITE=1` + `PRE41=1` gives Lite if there are weights; otherwise Hybrid.
- Any active `FSR4_XMX_DLSS*` with weights beats the three FSR4 branches. To test FSR4, do
  not define the DLSS variables.
- If a 4.1.2 branch finds no weights, it does not choose 4.1.2: it falls to the next
  branch. The explicit error appears later if another route forces the model:
  `Lite/INT8 model requested without verified fsr-original.dll weights.` (`0x18030E2E0`).

## 2. Two different lists (do not confuse them)

### 2.1 Plugin Model/Version list

`FUN_180001230` builds two parallel vectors of 10 entries. The labels are in `.rdata`; the
associated environment variables are the `...=1` strings:

| Label | Associated variable | Addresses |
|---|---|---|
| `The game's choice` | - | - |
| `4.0.2X Hybrid` | `FSR4_XMX_PRE41=1` | `0x180321E60`, `0x180323290` |
| `4.1.2X` | `FSR4_XMX_INT8=1` | `0x1803223A0`, `0x1803232A8` |
| `4.1.2X Lite` | `FSR4_XMX_LITE=1` | `0x1803223A8`, `0x1803232B8` |
| `DLSS-EX` | `FSR4_XMX_DLSSE=E` | `0x180321D08`, `0x1803232C8` |
| `DLSS-FX` | `FSR4_XMX_DLSSE=F` | `0x180321D30`, `0x1803232E0` |
| `DLSS-EFX` | `FSR4_XMX_DLSSE=A` | `0x180321D58`, `0x1803232F8` |
| `DLSS-KX` | `FSR4_XMX_DLSSK=1` | `0x180321DE0`, `0x180323310` |
| `DLSS-MX` | `FSR4_XMX_DLSSM=1` | `0x18031B978`, `0x180323328` |
| `DLSS-LX` | `FSR4_XMX_DLSSM=L` | `0x18031B970`, `0x180323340` |

This list is what the plugin host shows as Model/Version list (in `OptiPluginInit`,
`0x18006FC20`, the `Model` setting at `0x180F57A10`). Selecting an entry applies the
corresponding environment variable, and `CreateModel` reads it. `FSR4_XMX_DEV=1` unlocks
the Developer tab, the Version list (`FUN_18006D040`), `HiddenEntries` and `Profile`. The
`Model` setting is read separately and does not change the model by itself.

### 2.2 FFX provider version table (what OptiScaler sees)

Independently of the list above, the DLL exposes 32 provider entries at `0x180F2D970`
(32 pointers; `FUN_180074600` walks up to `0x100`). Each entry points to a state record
whose first qwords are:

```text
+0x00  vtable 0x18031F088 (FSR4 provider)
+0x08  state byte 0 = "hybrid" (+0x207)
+0x09  state byte 1 = Lite
+0x0A  state byte 2 = INT8
+0x0B..+0x11  skip / DLSS / 3.1.5
```

The vtable `0x18031F088` contains, among others:

| Vtable offset | Function | Role |
|---:|---|---|
| `+0x08` | `0x1800614C0` | availability (weights) |
| `+0x20` | `0x180065920` | name/version shown |
| `+0x28` | `0x1800617C0` | `CreateModel` |
| `+0x48` | `0x180063830` | dispatch/config |

Relevant FSR4 entries (index = position in `0x180F2D970`; this is the value that
`FSR4_XMX_PROVIDER_INDEX` accepts):

| Index | State `+0x08` | Label | Model |
|---:|---|---|---|
| 0 | `0x0000000000000000` | `4.0.2X` | base, no hybrid |
| 4 | `0x0000000000000001` | `4.0.2X Hybrid` | 4.0.2 + hybrid flag |
| 8 | `0x0000000000010101` | `4.1.2X` | hybrid + Lite + INT8 (kind 2) |
| 12 | `0x0000000000000101` | `4.1.2X Lite` | hybrid + Lite (kind 1) |
| 31 | `0x0000000000000000`, `+0x10=0x100` | `3.1.5` | FSR 3.1.5 fallback |

`FUN_1800614C0` checks that the entry is available: for `+0x09` (Lite) it requires
`FUN_180027C00()[0] != 0`; for `+0x0A` (INT8) it requires `FUN_180027C00()[0x68] != 0`. If
not, the entry is hidden or degraded ("Greyed: its file is missing." at `0x180323813`).
`FUN_180065920` returns the label: for the all-zero state it returns the literal `4.0.2X`
(`0x180065ADF` to `0x180321E70`); for INT8/Lite it returns the strings generated from
`FUN_180027C00()` at `+0x69`/`+1` (section 4).

`FSR4_XMX_PROVIDER_INDEX` is read in `FUN_180074600` (string at `0x180F2DA90`, log at
`0x180F2DAD0`). It accepts a decimal 0..31 and, if the entry is available and compatible,
forces it. Log:

```text
[FSR4 XMX] FSR4_XMX_PROVIDER_INDEX=%zu -> %s (requested version id 0x%llx)
```

If it is not available: `not available here, usual choice kept`. This forces the 4.1.2X
label (`=8`) or the 4.1.2X Lite label (`=12`) without the dropdown. It requires the weights
and a process restart, because the choice is cached once.

## 3. Which version is reported to the caller

There are two sources, and neither depends on `FSR4_XMX_*`:

1. The provider label comes from `FUN_180065920` (`vtable+0x20`). For the base entry
   (state 0) it returns the literal **`4.0.2X`** (`0x180321E70`); for `+0x8` it returns
   `4.0.2X Hybrid` (`0x180321E60`). This is the label in the provider version list, and
   OptiScaler shows `FSR 4.0.2X`/`4.0.2`, consistent with that literal.
2. The PE VERSIONINFO resource is `16/1`, with `FileVersion 4.0.2.1` and
   `ProductVersion 4.0.2.1` (fixed; see `docs/xmx412-toolchain.md`). Neither field changes
   with the environment.

The 4.1.2 labels are generated from the official weights DLL in `FUN_180049950` and stored
in the structure of `FUN_180027C00()`; they are not literals in `.rdata`. If the official
DLL is 4.1.2, the labels are `4.1.2X`/`4.1.2X Lite`; if it is 4.0.2, they are
`4.0.2X`/`4.0.2X Lite`. That is why `fsr-original.dll` must carry the 4.1.2 blobs
(section 4); renaming any DLL is not enough.

`FSR4_XMX_INT8=1` changes the model that runs, but not the bytes `+0x08..+0x11` of the
provider entry the game already chose, so the overlay may keep showing `FSR 4.0.2`. The model
log is the authoritative evidence of what ran.

## 4. Contract of `fsr-original.dll`

### 4.1 Name and paths

- Exact name: **`fsr-original.dll`**. It appears in ASCII at `0x180323778` (UI "Model files")
  and in UTF-16 at `0x18008A018` (appended to the path). The UI says:
  `Missing? Place next to this DLL, restart.` (`0x180323790`).
- `FUN_180005AC0` resolves the file in this order:
  1. `FSR4_XMX_LITE_DLL` (UTF-16, `0x180089FF0`), if it is defined and valid. It is a full
     **Windows** path (e.g. `Z:\...`) passed to `CreateFileW`. Despite the name, it is the
     weights DLL path for Lite **and** INT8, which share the weights structure. If it fails,
     the next two are tried.
  2. Directory of the mod's own DLL + `\fsr-original.dll`
     (`GetModuleHandleExW(6, FUN_180027C00, ...)` + `GetModuleFileNameW` + `FUN_180043130`,
     which cuts at the last `\`).
  3. Directory of the host EXE + `\fsr-original.dll` (`FUN_180043130(..., 0)`).
- It is not searched in `System32`, DriverStore or next to `amdxcffx64.dll`.

### 4.2 What is verified (not a hash of the whole file)

`FUN_180049950` maps the file read-only and scans offsets aligned to 16 bytes. It does not
check name, exports, signature or PE; it checks content:

1. Size >= `0x6B01` (`0x1800499F6`).
2. At each candidate offset, the qwords at `+0x440..+0x478` must be zero (`0x180049B02`).
3. In the first `0x200` UTF-16 words, indices `7,15,23,...` must be zero, and there must be
   more than 400 non-null words (`0x180049B50`).
4. FNV-1a64 over `0x6B00` bytes and over `0x20000` bytes from the same offset, comparing
   four constants (`0x180049C1F`, `0x180049C51`, `0x180049C7C`, `0x180049CA6`):

   | Constant | Blob | Destination | Use |
   |---|---|---|---|
   | `0x0CA02A3581DE817F` | `0x6B00` | `+0x38` | Lite preset |
   | `0x2DD74EE29ECB9705` | `0x6B00` | `+0x50` | Lite ultraperf |
   | `0x29CE14ECDF23D42B` | `0x20000` | `+0xD8` | INT8 preset |
   | `0x0DFCFD62036F9E391` | `0x20000` | `+0xF0` | INT8 ultraperf |

5. Version marker: it looks for a pair of dwords where the second one is `0xF5A5CA1E`
   (`cmp [rcx+4], 0xf5a5ca1e` at `0x180049D60`), takes the first positive one, the
   largest, and extracts major = `v >> 22`, minor = `(v >> 12) & 0x3FF`, patch = `v & 0xFFF`
   to generate `%u.%u.%uX Lite` (`0x180089F80`) and `%u.%u.%uX` (`0x180089FA8`). For 4.1.2
   the packed value is `0x01001002` (4.1.2).
6. Availability:
   - `struct[0] = 1` only if **both** Lite blobs are present and the version is non-zero
     (`0x180049E07`).
   - `struct[0x68] = 1` only if **both** INT8 blobs are present and the version is non-zero
     (`0x180049E26`).

`FUN_180028560` re-checks the sizes (`0x6B00` Lite, `0x20000` INT8) and copies/parses the
weights into the model. `FUN_18004A9D0` requires kind 2 (INT8) with
`FUN_180027C00()[0x68] != 0`, kind 1 (Lite) with `FUN_180027C00()[0] != 0`, and otherwise
fails with `Lite/INT8 model requested without verified fsr-original.dll weights.`
(`0x18030E2E0`) and `HRESULT 0x8000000A`.

The file name is not validated, nor is it checked that the file is a PE: any file that
contains exactly those blobs would pass. In practice the expected origin is AMD's official
DLL.

### 4.3 Which official DLL it is

The expected DLL is the **official AMD FidelityFX Upscaler DX12 of FSR 4.1.2**
(`amd_fidelityfx_upscaler_dx12.dll`, unmodified), renamed to `fsr-original.dll`. Evidence:

- The mod is called `amd_fidelityfx_upscaler_dx12.dll`; its PDB is
  `F:\xmx_probe\fsr4_402\Kits\FidelityFX\upscalers\dx12\x64\Release\amd_fidelityfx_upscaler_dx12.pdb`
  (string at `0x180F4DF28`), so the base is the FidelityFX Upscaler DX12 library.
- The model files UI lists `fsr-original.dll` next to the DLL and says "Place next to this
  DLL, restart." (`0x180323778`, `0x180323790`).
- The loader looks for the FSR4 weights blobs (tables of `0x6B00`/`0x20000`), not for
  exports of a driver.

It is not `amdxcffx64.dll`. That string does not appear in the binary; the only `amdxc*`
string is `amdxc64.dll` (`0x180F2DA80`), a provider name in the version table, not the
weights file. The loader is content-based, so a static test cannot prove that
`amdxcffx64.dll` fails, but nothing in the binary references it, and the expected layout is
that of the FidelityFX library.

It is not the modified 4.1.2 DLL nor the local 4.0.2. The exact scan of `FUN_180049950`
(C, read-only) was reimplemented over:

- `artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll` (4.0.2, `3eb08656...`):
  0 version pairs, 0 matching blobs.
- `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll` (mod 4.1.2,
  `fadbcb50...`): 0 version pairs, 0 matching blobs.

Copying or renaming the mod's own DLL as `fsr-original.dll` therefore does not work. The
official 4.1.2 DLL is not in the repository; `installer/profiles/cyberpunk2077.conf` pins it
as `FSR_ORIGINAL_SHA256` `aad4fccccb29084a655f9a4f9f613bd22c8c03fb4a0f8840148cc6543b4ccace`
and `FSR_ORIGINAL_SIZE` `57664272`. The practical verification is the loader log (section
7.3).

## 5. Xe2 PRE variants (pack 40102)

Pack 40102 carries 252 CM envelopes, 18 of them PRE variants with `fsr4_pre_xmx` in the IR.
The pack is `analysis/fsr-xmx-412/pack-40102.raw` (23 682 325 B, SHA-256 `d88aa9d6...995e491`).
`tools/parse_cm_payloads.py` verified every footer: trailer 97 B, options
`"-vc-payload -Xfinalizer '-noDPASMacro'"` plus `" -target-features=+ocl_runtime"`.

The 18 PREs sit at CM indices
`[0,14,28,42,56,70,84,98,112,126,140,154,168,182,196,210,224,238]`, step 14. They share
`ir_size 358776`, `trailer 97`, `envelope 358873`, the same two strings, entry
`%11173 "fsr4_pre_xmx"`, 12 ordered args, a single `WorkgroupId`, 4 ExecutionModes without
`LocalSize`, counts `78/85/1`, and store `typed_quad_bti (0,0,7)` with surface `%10694` from
arg 1.

The `grid` column is the guard on `WorkgroupId.x/y` (`OpUGreaterThanEqual %uint_X/Y`, one
occurrence each; Z is unused). The `factor` column is `[1,2,4]` repeated six times from the
older census (`analysis/pre-reconstruction.json`, `test_pre_resources.py:96`,
`table_dword_at_0x24`), correlated with suffix and grid. `min Width = factor^2 * 0x7e9000`
comes from the old DLL; the IR is 358 776 B.

| # | Variant (assumed) | `rec_idx` | `offset` | grid guards | factor / min Width | `ir_sha256` | `envelope_sha256` | zebin / code (offline `0xe20b`) |
|---:|---|---|---:|---|---|---|---|---|
| 1 | `native_1080` | 0 | 0 | 120×540 | 1 / 8 294 400 | `49e069fd…21f9f568` | `ce372719…b85ab` | `b1781bb4…13751c2` / `68b962b5…28f8792c` |
| 2 | `native_2160` | 14 | 1315712 | 240×1080 | 2 / 33 177 600 | `20096eef…83d7ebb29` | `ee5553e3…027597` | `6a8f0fe6…bca2e6` / `ba7f966a…697b87` |
| 3 | `native_4320` | 28 | 2631424 | 480×2160 | 4 / 132 710 400 | `b4eacd68…0efc5e` | `281e11fc…efe616` | `dede3aed…7a62fa` / `0ad99755…1930f09` |
| 4 | `quality_1080` | 42 | 3947072 | 120×540 | 1 / 8 294 400 | `4516209c…7979722` | `bc2b0cf3…13a558` | `35fe9a6e…6999f4` / `88ccb2ff…05426a` |
| 5 | `quality_2160` | 56 | 5262784 | 240×1080 | 2 / 33 177 600 | `781497a6…83a7e35` | `c7af3e98…fa66` | `05e99861…0eeed` / `cce6dbab…7fadb` |
| 6 | `quality_4320` | 70 | 6578496 | 480×2160 | 4 / 132 710 400 | `530315c6…0940950` | `3414bc91…2333d4` | `1d747d50…a043d8` / `a5ba59b0…8d55` |
| 7 | `balanced_1080` | 84 | 7894144 | 120×540 | 1 / 8 294 400 | `58681903…a394a1f3` | `a6673041…a84a1` | `4fe17d55…e4275` / `46c43ce5…323638` |
| 8 | `balanced_2160` | 98 | 9209856 | 240×1080 | 2 / 33 177 600 | `fdd506a0…cffe9f` | `0dc3e2dd…f12d` | `096a231f…fac5c` / `83e1bc5c…aaf29` |
| 9 | `balanced_4320` | 112 | 10525568 | 480×2160 | 4 / 132 710 400 | `0d02fd9f…6be9c8` | `457c98b4…08da` | `5921d268…17718` / `ec826861…e1630` |
| 10 | `performance_1080` | 126 | 11841216 | 120×540 | 1 / 8 294 400 | `13d79716…21b7d2` | `00239bc0…a954e` | `2580f661…5cd89` / `5daf0d65…34c4b65` |
| 11 | `performance_2160` | 140 | 13156928 | 240×1080 | 2 / 33 177 600 | `44ddd92c…937aa4` | `5ffb99bb…10ddf` | `f4d93730…4632a` / `0bb8b07d…03599` |
| 12 | `performance_4320` | 154 | 14472640 | 480×2160 | 4 / 132 710 400 | `cc0d724a…64d313` | `4d6437df…2414` | `250ddd1a…832d` / `1437b715…60d6` |
| 13 | `ultraperf_1080` | 168 | 15788288 | 120×540 | 1 / 8 294 400 | `9fdea8f9…4386f` | `4f16b9c1…9c1b` | `e7640611…3176` / `67ad3899…48d81` |
| 14 | `ultraperf_2160` | 182 | 17103984 | 240×1080 | 2 / 33 177 600 | `6f2805c2…81ad4` | `50a9da87…8aaa3` | `cb80102b…30b6` / `679b9162…ad584` |
| 15 | `ultraperf_4320` | 196 | 18419680 | 480×2160 | 4 / 132 710 400 | `ae23ffef…ebf3f8` | `87a6d240…3634e` | `503f1269…26f7` / `46c84cb9…e7af65` |
| 16 | `drs_1080` | 210 | 19735312 | 120×540 | 1 / 8 294 400 | `1692bc85…964f64` | `e1bb7ba5…63c6` | `e481a5f8…4c2e5` / `04268212…1c68` |
| 17 | `drs_2160` | 224 | 21051008 | 240×1080 | 2 / 33 177 600 | `b289069b…694cd` | `436e5cb0…3440` | `243f845f…b535` / `5a589d02…680a` |
| 18 | `drs_4320` | 238 | 22366704 | 480×2160 | 4 / 132 710 400 | `c674bc37…eb27` | `ed03b05e…d05e` | `4c7b2796…83cd` / `b3c63d8f…52c1` |

Full 64-hex hashes are in `tests/test_xmx412_variants.py` (`VARIANTS`, `OFFLINE_BUILDS`);
IR and envelope SHAs come from the exact slice and footer, zebin/code SHAs from
`tools/inspect_zebin.py --kernel fsr4_pre_xmx`.

Disassembly of the 18 confirms the guard cycle `[(120,540),(240,1080),(480,2160)]` repeated
six times in `rec_idx` order, so the groups are interleaved. Each `_1080` guards `120×540`,
`_2160` guards `240×1080` and `_4320` guards `480×2160`, matching the census
(`docs/xmx412-dispatch.md`) and the dispatch formula
(`x=(w+15)>>4; x+=x&1; y=h>>1`; `1920×1080` gives `120×540` with factor 1,
`docs/xmx412-dispatch.md`). The rest is bit-identical to the older census except PRE and
pass 6: the 18 new PREs share 358 776 B of IR (old 330 108 B) with 18 distinct `ir_sha256`,
and the other 216 envelopes match by index.

Offline compilation used `profiles/intel-toolchain.json` (IGC `2.10.10+18926`, ocloc
`25.18.33578.6`), target `0xe20b` (B580) and `-options '-vc-codegen'`, into ignored
`analysis/offline-pre-412-variants/`. Each input is the `.cmspv` file (IR plus footer),
never a trimmed `.spv`:

```bash
LD_LIBRARY_PATH="$PWD/artifacts/extracted/intel-toolchain/igc/usr/local/lib:$PWD/artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu" \
XDG_CACHE_HOME="$PWD/analysis/compiler-cache" \
artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1 compile \
  -spirv_input -file "$PWD/analysis/offline-pre-412-variants/module-00-rec0000.cmspv" \
  -device 0xe20b -out_dir "$PWD/analysis/offline-pre-412-variants/out-00-rec0000" \
  -output pre -options '-vc-codegen'
python tools/inspect_zebin.py analysis/offline-pre-412-variants/out-00-rec0000/pre_bmg.bin \
  --kernel fsr4_pre_xmx
```

All 18 exited 0 with `Build succeeded`, with the mismatched-LLVM-triple warning left visible.
All share `grf_count 128`, `simd_size 1`, `has_dpas true`, `has_sample true`,
`has_fence_for_image_access true`, `has_no_stateless_write true` and
`offset_to_skip_per_thread_data_load 128`. BTI order is `[8,9,1,2,3,4,5,6,7,10,11]` for
`arg_index 0…10` plus a separate sampler, as in the older census
(`docs/xmx412-toolchain.md`). `code_size` is 30464 on all 18 (old `native_1080` 29 376),
the zebin/code SHAs differ across the 18 and from the old pin (`zebin 3e974d...`, `code
2e42d33c...`), and per-thread data is `packed_local_ids size 6` with cross-thread `arg0@8`,
`arg9@16`, `arg10@24` (8 B each) and `private_base_stateless@0` (8 B).

Variant names are an inherited hypothesis, not proof of the 4.1.2 table order. Do not
rename by them or use them for profiling or caching without review. `Unknown` in
`OpTypeImage` means no format, channels or space are inferred; the counts are
`OpFunctionCall` calls, not pixels. Offline compilation says nothing about GPU correctness,
dispatch, injection or readback.

## 6. DLSS packs 40104 to 40106

The three DLSS packs use the same igdext CM-SPIRV path as FSR: Kernel plus
`SPV_INTEL_vector_compute`, `BufferSurfaceINTEL` ReadWrite, DPAS/BTI, and no samplers. They
are not classic CUDA or NGX, and share the loader `FUN_180029640` with FSR.

| RCDATA (idx) | Bucket (loader) | Verified kernels | Execution path | Relevance for the bridge |
|---|---|---|---|---|
| 40104 (3) | DLSS K (DG2 + Xe2/Xe3) | 716: `k_gemm`×174, `k_linear`×160, `k_attn`×126, `k_mlp`×126, `k_block`×50, `k_stage`×48, `k_adapt`×32 | CM-SPIRV Kernel, `SPV_INTEL_vector_compute`, `BufferSurfaceINTEL` ReadWrite in 716/716, 64/716 with one `OpTypeImage` 2D Unknown, 0 samplers, DPAS2/DPASW plus `lsc.load.bti`/`oword` | Same path as FSR: the buffer, DPAS and BTI reader is reused, and there are no samplers to port. The blocker is the weights in `nvngx_dlss.dll`, plus `ScratchBuffer` and `token grid`, not `fsr-original.dll` or PRE magenta. |
| 40105 (4) | DLSS E / F | 312: `e_conv`×240, `e_stage`×64, `e_adapt`×8 | Same: 312/312 `BufferSurface` ReadWrite, 40/312 with one 2D Unknown image, 0 samplers, `dpas2` plus `lsc.store/load.bti`, and `scatter4.typed`/`3d.load` in a minority | Same. Convolutional `e_conv` plus typed stores, with no `sampler_t` and no `3d.sample`. Buffers and one Unknown image cover E/F without a dynamic sampler. |
| 40106 (5) | DLSS-MX (DG2) | 67: `k_gemm`×19, `m_layer`×18, `k_mlp`×10, `m_stage`×10, `m_attn`×8, `m_adapt`×2 | Same: 67/67 `BufferSurface` ReadWrite, 3/67 with one 2D Unknown image, 0 samplers, `dpas2`/`dpasw` | Mixed `k_` and `m_` kernels, same conclusion. At 5.4 MB it is the cheapest reader test case. |

Total DLSS: 1 095 envelopes (716 + 312 + 67). The six packs together hold 1 977.

Verified sizes (compressed, raw, raw SHA-256):

- 40104: 8 031 050 B, 42 477 193 B, `a9ea6724…7054ea`
- 40105: 3 421 152 B, 19 590 261 B, `7ac547ee…57d246fa`
- 40106: 1 001 522 B, 5 443 681 B, `03c18858…5a331ac3`

`raw.count(SPIRV_MAGIC) == cm_envelopes` in all three (716/312/67). The gaps are 712/307/66,
all zero, with zero DXBC candidates. The FSR packs 40102/40103 also have zero gaps; only
40101 has 18 DXBC and 24 non-zero gaps. DLSS is pure CM plus zero padding.

### 6.1 How the packs are found and verified

`tools/decompress_xmx412.EXPECTED` pins `index = rid - 40101` for 40101 to 40106, so the
DLSS packs are indices 3, 4 and 5. It also pins exact
`res_size`/`raw_size`/SHA-256/`cm_envelopes`, the loader immediates `MOV ESI 0x9CA5…0x9CAA`,
the sizes `0x21B5796…0x531061` and the clamp above 5 to 0.

The loader `FUN_180029640` resolves the pack with `GetModuleHandleExW`,
`FindResourceW(h, id, 10)`, `LoadResource`, `SizeofResource` and `LockResource`, then calls
`Cabinet.dll` ordinals 40, 43 and 45 (`ECX=5` selects LZMS with 64 KiB blocks). It verifies a
one-shot `BCryptHash(0x41)` SHA-256 plus `strcmp` against the compiled digest, and caches by
index under a mutex. There is no AES or ChaCha. The three DLSS packs verify through the same
`packs_from_resdir` + `decode_and_verify` path as FSR (`docs/xmx412-pack-envelope.md`).

### 6.2 Names, arguments and types

Entry points come from `tools/carve_spirv.py` (`OpEntryPoint`, `model=6` Kernel in
1 095/1 095); the distribution sums to the envelope count and fails closed if it does not.

The input interface is one or two `v3i64` `Input` values, a cross-thread payload and not
descriptors: 40104 has 282×1 and 434×2, 40105 has 272×1 and 40×2, 40106 has 23×1 and 44×2.
`BufferSurface` and `Image` never appear directly in the interface; the surfaces go through
BTI/internal stateless immediates plus `BufferSurface` state.

Each module has one `OpTypeBufferSurfaceINTEL` (opcode 6086, `access=2` ReadWrite) in
1 095/1 095, as a function parameter type (`OpTypeFunction` with `(i32, BufferSurface)`),
same as FSR. `OpTypeImage` (`dim=1` 2D, `depth=0`, `arrayed=0`, `ms=0`, `sampled=0`,
`format=0` Unknown) appears in 64/716, 40/312 and 3/67; FSR 40101 has 36/252 with two
images, and the Unknown format matches the PRE. `OpTypeSampler` (26) and
`OpTypeSampledImage` (27) are absent in 1 095/1 095; FSR has 18 to 36 modules with a
sampler. The IR has no `p2opencl.sampler_t` and no `3d.sample`, only `3d.load` (64/16/2),
`scatter4.typed` plus `lsc.store.quad.typed.bti` in the minority with an image, and
`address.convert ...p1opencl.image2d_{ro,rw}_t`. The rest is `lsc.load.bti`, `oword.ld/st`,
`vload/vstore`, `rdregion/wrregion`, `dpas2` (`v128f32…`, `v64f32…`), `dpasw`, `fence` and
`lsc.*.slm`. `dpas2`/`dpasw` are `llvm.genx.*` names inside the IR, not in the gaps.

Execution modes per module are `31`, `35(1)`, `5618` and `6417` in 100%, same as FSR
40101/40103. `5618(0)` is the majority (390/716, 272/312, 38/67) plus variants
`8192/4096/2048/3072/…`. Extensions are `SPV_INTEL_vector_compute`,
`SPV_KHR_no_integer_wrap_decoration` and `OpenCL.std` in 1 095/1 095 each, with no CUDA or
NGX extensions. The B trailer is always ` -target-features=+ocl_runtime` (716/312/67). The
A trailer is `…'-noDPASMacro'` 442 times plus `…-ze-exp-register-file-size=256…` 274 times
for 40104, 192 + 120 for 40105 and 49 + 18 for 40106. FSR 40101 has only `-vc-payload`, and
`register-file-size=256` appears only in DLSS.

### 6.3 What a failure looks like

A bad pack fails verification before any kernel runs:

```text
embedded pack %u invalid: ...
```

A verified pack logs its bucket: `embedded %s pack loaded: ... SHA256 verified`, with
`bucket=%s` set to `DLSS K (DG2 + Xe2/Xe3)`, `DLSS E / F` or `DLSS-MX (DG2)`. A load failure
or a mismatch on the weights side then shows as `DLSS K/E-F/MX ... initialization/output
dispatch failed`, `ScratchBuffer too small`, or `requested without verified nvngx_dlss.dll
weights`. A successful startup logs `DLSS K ready: %u kernels, %zu params bytes, token grid
%ux%u` and `DLSS %s ready: %u kernels…`. The MX leg also needs the depth buffer.

None of those lines proves dispatch. `S_OK`, a created PSO or an overlay label proves
nothing; injection evidence and deterministic readback are required, as in
`docs/compatibility.md`.

### 6.4 Contrast with the DLL strings

The FSR leg logs per-kernel failures such as `Failed to load P6 N32…`, `P7 FullFusion…` and
`P1 H1 DPAS…` (35 `Failed to load…`, 6 `FullFusion`). There is no `Failed to load k_*` or
`e_*`: DLSS does not log per kernel. It logs the 68 `DLSS…` lines, 34 `ScratchBuffer` lines,
19 `weights` lines and 4 `token grid` lines. `k_gemm`, `e_conv` and the other DLSS names
exist only in the packs, not in the DLL. The DLL contains no `CUDA`, no `NVNGX`/`NGX` and no
literal `40104`/`40105`/`40106`; the only weight-file reference is lowercase
`nvngx_dlss.dll`.

There is no CUDA or NGX backend to bridge. If the shim and ANV already create
`CreateDeviceExtensionContext 4.20.0` and `CreateComputePipelineState` for CM-SPIRV with
`BufferSurface`, DPAS, BTI and Unknown images without samplers, the 1 095 DLSS kernels
travel the same path as the PRE/FSR passes. FSR stays the priority. The parts to isolate are
the external weights, the per-bucket `ScratchBuffer`, the `token grid %ux%u` dispatch in
place of FSR's `baseDispatch`, the presets `KX/MX/LX/EX/FX`, the variables
`FSR4_XMX_DLSSK/DLSSM/DLSSE`, and the absence of `sampler_t`/`3d.sample`.

## 7. Recipe for Spider-Man (per process)

### 7.1 Files

1. Use the 4.1.2 mod DLL (`fadbcb50…`) and OptiScaler as before.
2. Obtain the official AMD FidelityFX Upscaler DX12 DLL of FSR 4.1.2, do not redistribute it
   in the repo, and rename it **`fsr-original.dll`**.
3. Place it next to the mod DLL (the folder with `amd_fidelityfx_upscaler_dx12.dll`), next
   to the game's EXE, or at an explicit path with
   `FSR4_XMX_LITE_DLL=Z:\path\amd_fidelityfx_upscaler_dx12.dll` (a Windows path; `Z:` is
   `/` in Proton).
4. Delete or rename any old 4.0.2 `fsr-original.dll` so the two are not mixed, then restart
   the game.

### 7.2 Variables (Steam: `VAR=1 %command%`; or a wrapper with `env VAR=1 ...`)

- For 4.1.2X, set `FSR4_XMX_INT8=1`.
- For 4.1.2X Lite, set `FSR4_XMX_LITE=1`. Do not set both; INT8 wins when weights exist.
- For 4.0.2X Hybrid, set `FSR4_XMX_PRE41=1`.
- To leave the choice to the game (4.0.2X by default), set none of the three. Do not set
  `FSR4_XMX_DLSSK`, `DLSSM` or `DLSSE` during an FSR4 test; they take priority.

Example Steam launch options for a 4.1.2X test:

```text
FSR4_XMX_INT8=1 FSR4_XMX_DEV=1 PROTON_LOG=1 %command%
```

For 4.1.2X Lite, replace `FSR4_XMX_INT8=1` with `FSR4_XMX_LITE=1`.

Useful optional settings:

| Setting | Effect |
|---|---|
| `FSR4_XMX_DEV=1` | Developer tab, Version list, `HiddenEntries` and `Profile`. |
| `FSR4_XMX_PROVIDER_INDEX=8` | Forces entry and label 4.1.2X (needs weights). |
| `FSR4_XMX_PROVIDER_INDEX=12` | Forces entry and label 4.1.2X Lite. |
| `FSR4_XMX_DPAS=16` | Forces Xe2 SIMD16 (B-series); `=8` forces DG2 SIMD8. |
| `FSR4_XMX_FS_DIAG=2` | Skip rules shown as colors (0, 2 or 4; bit 8 adds stats). |
| `MLSR-PROFILE=1` | Per-frame profile. |
| `FSR4_XMX_NO_DIALOG=1` | No MessageBox on a GPU without XMX. |
| `FSR4_XMX_SHARPNESS=0.0` | 0 to max; does not affect model selection. |

`FSR4_XMX_DPAS` is read with `getenv_s` in `FUN_18004DC90`; when unset, it is auto-detected
through `INTC_D3D12_CheckFeatureSupport`. `FSR4_XMX_FS_DIAG` is read with `atoi` in
`FUN_180068CF0`; this DLL has no `FS_DIAG` variable, so an OptiScaler variable of that name
is a different setting. `FSR4_XMX_DEV` activates only when the first byte is `'1'`
(`0x18006FD90`).

### 7.3 How to know which model ran

Search stderr or `OutputDebugStringA` (Proton: `PROTON_LOG=1`, or the OptiScaler log).

For 4.1.2X (INT8):

```text
[FSR4 XMX] INT8 model: preset weights from Z:\...\fsr-original.dll, bucket 0, Xe2 SIMD16-DPAS kernels.
[FSR4 XMX] INT8 network kernels ready (bucket 0, preset weights).
```

For 4.1.2X Lite:

```text
[FSR4 XMX] Lite model: preset weights from Z:\...\fsr-original.dll, bucket 0, Xe2 SIMD16-DPAS kernels.
[FSR4 XMX] Lite network kernels ready (bucket 0, preset weights).
```

`preset`/`ultraperf` varies with the quality preset, and `bucket` is 0..2.

4.0.2X/Hybrid does not go through `FUN_18004A9D0` (`kind 0`), so it prints no
`INT8/Lite model` line. Recognize it by the chosen provider entry (`4.0.2X`/`4.0.2X
Hybrid`), the GPU log `[FSR4 XMX] GPU GTGeneration=... -> ... kernels ...`, and the hybrid
flag.

A forced provider logs `[FSR4 XMX] FSR4_XMX_PROVIDER_INDEX=8 -> 4.1.2X (requested version
id 0x...)`.

If the file or weights are missing:

```text
Lite/INT8 model requested without verified fsr-original.dll weights.
%s weights are unavailable (fsr-original.dll).
```

The model is not loaded in that case. The overlay can stay on `FFX -> FSR 4.0.2` even when
the log says `INT8 model`, because `FSR4_XMX_INT8=1` does not change the provider version
label. To see `4.1.2X` in the list or overlay, select the 4.1.2X entry (needs weights) or set
`FSR4_XMX_PROVIDER_INDEX=8`; for Lite, use `12`.

### 7.4 What to check if it fails

1. Does the log show `FSR4_XMX_PROVIDER_INDEX=8 -> 4.1.2X`? If it says `not available here,
   usual choice kept`, the weights are missing or the entry is not compatible.
2. Do `INT8 model`/`Lite model` appear? If not, `CreateModel` did not choose 4.1.2: check
   the spelling and the value `=1`, confirm there is no `FSR4_XMX_DLSS*`, and confirm the
   file is in a searched path.
3. Is the path the expected one? The loader tries `FSR4_XMX_LITE_DLL`, the DLL's directory,
   then the EXE's. A mistyped `Z:\...` path fails silently and falls through.
4. Is the official DLL version 4.1.2? A generated `4.0.2X` means the file is not the official
   4.1.2, its blobs do not match section 4.2, and it does not enable the 4.1.2 entries.
5. If the model loads but dispatch fails, the errors are no longer about selection:
   `Lite network pass %u XMX initialization/dispatch failed.`, `Lite ScratchBuffer too
   small`, `embedded Lite XMX resource pack is missing or invalid.`

### 7.5 Quick checklist

- [ ] `fsr-original.dll` is the official 4.1.2 DLL, not the 4.0.2 one and not the mod, and
      no older copy sits at a path that is tried first.
- [ ] It is next to the mod DLL, next to the EXE, or in `FSR4_XMX_LITE_DLL`.
- [ ] Only one of `FSR4_XMX_INT8=1`, `FSR4_XMX_LITE=1`, `FSR4_XMX_PRE41=1`.
- [ ] No `FSR4_XMX_DLSSK/M/E` during the FSR4 test.
- [ ] The log shows `INT8 model` or `Lite model` with the correct path.
- [ ] If `FSR4_XMX_PROVIDER_INDEX` is used, the log shows the expected name
      (`4.1.2X`/`4.1.2X Lite`), not `not available here`.
- [ ] The overlay may stay on `4.0.2`; the log decides.

## 8. Limits

- Nothing was executed. There is no evidence of injection, GPU dispatch or readback. `S_OK`,
  a PSO or the overlay do not certify the model.
- The runtime meaning of Hybrid (`+0x207`) is not demonstrated; only the flag, the scratch
  change and the dispatch bits are pinned.
- The official 4.1.2 DLL is not in the repository. The installer profile pins its SHA-256
  and size, but the blob and version scan plus the log remain the verifiable contract here.
- The link between the provider label and OptiScaler's text `FSR 4.0.2` is inferred from
  `FUN_180065920` and the VERSIONINFO; OptiScaler was not instrumented.
- `amdxcffx64.dll` is not local and was not tested. The binary does not reference it, and
  the expected layout is that of the FidelityFX library.
- The DLSS pack work is static and CPU-only. Kernel names come from `carve_spirv` plus
  verified footers, not from a full pack parser; the bytes between envelopes are classified
  only as zero gaps. `OpTypeImage Unknown` carries no format, and concrete BTIs and runtime
  `ScratchBuffer` need a trace. The patched game DLL (`nvngx_dlssd_xmx.7z`, one
  `nvngx_dlssd.dll` of 179 233 280 B, dated `2026-11-10 09:17:17`) was only listed
  read-only, so no Proton or GPU compatibility is claimed for it.

## 9. Reproducible evidence

- `tests/test_xmx412_model_strings.py` (7 tests), `tests/test_xmx412_variants.py` (16 tests)
  and `tests/test_xmx412_dlss.py` (21 tests) are CPU-only, read-only and fail closed.
- `python3 -m unittest tests.test_xmx412_model_strings tests.test_xmx412_variants
  tests.test_xmx412_dlss -v`
- Disassembly: `llvm-objdump -d --start-address=... --stop-address=...`; decompilation:
  Ghidra 12.2 headless (`analyzeHeadless`), local project, not versioned.
- Related documents: `docs/xmx412-dispatch.md`, `docs/xmx412-toolchain.md`,
  `docs/xmx412-pack-envelope.md`, `docs/compatibility.md`.
