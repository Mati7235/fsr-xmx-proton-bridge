# XMX 4.1.2: model selection (4.0.2X / 4.1.2X / Lite / Hybrid)

Static analysis only, CPU-only. The DLL was not executed, and no GPU/Wine was used.
Games, prefixes, drivers or `artifacts/original` were not touched. The DLL was opened in
Ghidra 12.2 headless (local project in `/tmp/opencode/ghidra-xmx412`) and the
disassembly/decompilation was reviewed. Addresses are VAs with
`ImageBase = 0x180000000`; the file offset is obtained from the PE section table.

Artifact:

- `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll`
- SHA-256 `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`
- PE32+ x86-64, 45 558 272 bytes.

Facts pinned by `tests/test_xmx412_model_strings.py` (7 tests, fail-closed):
SHA, literals, `CreateModel` branches, provider table, the
`fsr-original.dll` contract and label generation.

## Executive summary

| Variable (process) | Value | Resulting model | Native entry (index) | Weights required |
|---|---|---|---|---|
| `FSR4_XMX_INT8` | `1` | **4.1.2X** (INT8 model, kind 2) | 8 | `fsr-original.dll`: INT8 pair |
| `FSR4_XMX_LITE` | `1` | **4.1.2X Lite** (Lite model, kind 1) | 12 | `fsr-original.dll`: Lite pair |
| `FSR4_XMX_PRE41` | `1` | **4.0.2X Hybrid** (kind 0, hybrid flag) | 4 | embedded 4.0.2 (not external) |
| none | — | game's choice; default **4.0.2X** | 0 | embedded |
| `FSR4_XMX_DLSSK/M/E` | `1`/`E`/`F`/`A` | DLSS-KX / MX / LX / EX / FX / EFX | per table | `nvngx_dlss.dll` |

The "Native entry" column is the index of the provider entry that represents
that model. The environment override changes the model that `CreateModel` runs,
but **does not** change the provider entry already chosen by the game; to also
change the reported label/version, use the dropdown or `FSR4_XMX_PROVIDER_INDEX`.

Direct conclusions:

- **4.1.2X is not selected with `FSR4_XMX_PRE41`.** `PRE41=1` selects
  **4.0.2X Hybrid**. 4.1.2X is selected with `FSR4_XMX_INT8=1`.
- **Lite** is selected with `FSR4_XMX_LITE=1`. If `FSR4_XMX_INT8=1` is also set,
  INT8 (4.1.2X) wins when its weights are available; otherwise it falls back to
  Lite and then to PRE41.
- **Hybrid** is requested with `FSR4_XMX_PRE41=1`: it uses the embedded 4.0.2
  weights, but enables the model/hybrid flag (`+0x207`) that changes the scratch
  size and dispatch bits. It does not load external weights.
- The **4.0.2** that OptiScaler shows comes from the fixed label `4.0.2X` of the
  base provider entry (`FUN_180065920`) and/or the fixed VERSIONINFO `4.0.2.1`.
  It does not depend on `FSR4_XMX_*`. The 4.1.2 labels do depend on
  `fsr-original.dll` (they are generated with `%u.%u.%uX` from the version marker
  of the official DLL).
- For the caller/overlay to see **4.1.2X**, you must select the 4.1.2X provider
  entry (dropdown or `FSR4_XMX_PROVIDER_INDEX=8`); `FSR4_XMX_INT8=1` alone is not
  enough: the environment override changes the model, not the version label of the
  provider already chosen by the game.
- `fsr-original.dll` is the **official AMD FidelityFX Upscaler DX12 DLL of FSR 4.1.2**,
  renamed, placed next to the mod DLL (or next to the EXE, or via
  `FSR4_XMX_LITE_DLL`). It is not `amdxcffx64.dll`, it is not the 4.0.2 DLL, and it
  is not the modified 4.1.2 DLL itself (the last three do not contain the blobs
  the loader requires).

## 1. `CreateModel`: who reads what, and in what order

`CreateModel` is at `0x1800617C0` (the symbol string at `0x180321F70` reads
`unsigned int __cdecl CreateModel(struct InternalFsr4Context *,enum
fsr4_shaders::Preset)`). The reading and decision order is:

1. `FSR4_XMX_DLSSK` (`lea` at `0x180061900`)
2. `FSR4_XMX_DLSSM` (`0x180061933`)
3. `FSR4_XMX_DLSSE` (`0x18006195C`)
4. `FSR4_XMX_INT8` (`0x180061985`)
5. `FSR4_XMX_LITE` (`0x1800619A7`)
6. `FSR4_XMX_PRE41` (`0x1800619D4`)
7. if nothing applies: state of the provider entry chosen by the
   game/OptiScaler (fallback at `0x180061BFB`).

Each variable is read with `GetEnvironmentVariableA(..., 8)` and only the first
byte is compared with `'1'`; `0`, empty or any other text disables the branch.

### 1.1 INT8 -> 4.1.2X

At `0x180061AE3` the value read from `FSR4_XMX_INT8` is checked (the `lea` of the
name is at `0x180061985`); if it is `1`, `FUN_180027c00()` is called and
`byte [rax+0x68] != 0` is required:

```asm
180061AEA  call 0x180027c00              ; estructura de pesos fsr-original.dll
180061AEF  cmp  byte ptr [rax+0x68], 0   ; INT8 disponible
180061AF3  je   0x180061B08              ; si no, probar LITE
180061AF7  lea  r14, [rip+0x2C08A2]      ; 0x1803223A0 = "4.1.2X"
180061B00  movzx r9d, sil                ; flag INT8 para FUN_180061020
```

The branch fixes `pcVar8 = "4.1.2X"` (`0x1803223A0`) and calls `FUN_180061020`
at `0x180061B66` with the INT8 flag. `FUN_180061020` writes:

- `provider+0x209 = INT8`
- `provider+0x208 = LITE || INT8`
- `provider+0x207 = PRE41 || LITE || INT8` (model/hybrid flag)

Afterwards `FUN_1800625B0` translates the state into a model:
`+0x209 ? 2 : (+0x208 ? 1 : 0)`, and calls `FUN_18004A9D0` (the model loader).
That is why 4.1.2X is `kind=2` (INT8).

Nuance: `4.1.2X` is the literal label of this branch, but the label that the
provider list shows is generated from the official DLL (§3). With a 4.0.2
`fsr-original.dll` this branch would still be the INT8 one, but the generated text
would be `4.0.2X`; to actually get `4.1.2X` the 4.1.2 weights are needed.

### 1.2 LITE -> 4.1.2X Lite

At `0x180061B08` `FSR4_XMX_LITE` is checked; if it is `1`,
`byte [FUN_180027c00()] != 0` is required:

```asm
180061B0F  call 0x180027c00
180061B14  cmp  byte ptr [rax], 0        ; Lite disponible
180061B17  je   0x180061B2F              ; si no, probar PRE41
180061B1B  lea  r14, [rip+0x2C0886]      ; 0x1803223A8 = "4.1.2X Lite"
180061B29  movzx r8d, sil                ; flag LITE
```

Label `0x1803223A8`, LITE flag. `FUN_1800625B0` translates it to `kind=1`.
The Lite model uses the same embedded XMX pack as INT8, but a different set of
weights (blobs of `0x6B00` bytes, not `0x20000`).

### 1.3 PRE41 -> 4.0.2X Hybrid

At `0x180061B2F` the stored value of `FSR4_XMX_PRE41` is checked:

```asm
180061B2F  cmp  byte ptr [rbp+0x3F0], 0x31   ; '1'
180061B36  jne  0x180061BFB                   ; fallback del proveedor
180061B3C  lea  r14, [rip+0x2C031D]           ; 0x180321E60 = "4.0.2X Hybrid"
180061B43  movzx edx, sil                     ; flag PRE41
```

Label `0x180321E60`, PRE41 flag. It does not touch `+0x208`/`+0x209`, so
`FUN_1800625B0` calls `FUN_18004A9D0(..., 0, ...)`: it does not load external
weights and the model stays on the embedded 4.0.2 weights. The `+0x207` flag
enables the model/hybrid path; in `FUN_180063830` it changes the scratch size
(`FUN_180073FB0` versus `FUN_1800695C0`) and adds `0x1000`/`0x2000` bits to the
dispatch constants. The exact runtime semantics of "Hybrid" have not been
validated here; only the flag and its static effects are pinned.

### 1.4 Priority and interaction

Actual order of the branches (the first ones have priority):

```text
DLSSK > DLSSM > DLSSE > INT8 > LITE > PRE41 > elección del proveedor/juego
```

Consequences:

- `INT8=1` + `LITE=1` -> INT8 wins if `[0x68]` is available; otherwise Lite.
- `INT8=1` + `PRE41=1` -> INT8 wins if there are weights; otherwise Hybrid.
- `LITE=1` + `PRE41=1` -> Lite wins if there are weights; otherwise Hybrid.
- Any active `FSR4_XMX_DLSS*` with weights beats the three FSR4 branches.
  To test FSR4, do not define DLSS variables.
- If a 4.1.2 branch finds no weights, it does **not** choose 4.1.2: it falls to
  the next branch. The explicit error appears later if the model is forced by
  another route (provider entry or an already-started load):
  `Lite/INT8 model requested without verified fsr-original.dll weights.`
  (`0x18030E2E0`).

## 2. Two different lists (do not confuse them)

### 2.1 Plugin "Model"/"Version list"

`FUN_180001230` builds two parallel vectors of 10 entries. The labels are in
`.rdata`; the associated environment variables are the `...=1` strings:

| Label | Associated variable | Addresses |
|---|---|---|
| `The game's choice` | — | — |
| `4.0.2X Hybrid` | `FSR4_XMX_PRE41=1` | `0x180321E60`, `0x180323290` |
| `4.1.2X` | `FSR4_XMX_INT8=1` | `0x1803223A0`, `0x1803232A8` |
| `4.1.2X Lite` | `FSR4_XMX_LITE=1` | `0x1803223A8`, `0x1803232B8` |
| `DLSS-EX` | `FSR4_XMX_DLSSE=E` | `0x180321D08`, `0x1803232C8` |
| `DLSS-FX` | `FSR4_XMX_DLSSE=F` | `0x180321D30`, `0x1803232E0` |
| `DLSS-EFX` | `FSR4_XMX_DLSSE=A` | `0x180321D58`, `0x1803232F8` |
| `DLSS-KX` | `FSR4_XMX_DLSSK=1` | `0x180321DE0`, `0x180323310` |
| `DLSS-MX` | `FSR4_XMX_DLSSM=1` | `0x18031B978`, `0x180323328` |
| `DLSS-LX` | `FSR4_XMX_DLSSM=L` | `0x18031B970`, `0x180323340` |

This list is what the plugin host shows as "Model"/"Version list" (in
`OptiPluginInit`, `0x18006FC20`, the `Model` setting at `0x180F57A10`).
Selecting an entry ends up applying the corresponding environment variable;
`CreateModel` is the one that reads it. `FSR4_XMX_DEV=1` unlocks the Developer tab,
the "Version list" (`FUN_18006D040`), `HiddenEntries` and `Profile`; the `Model`
setting is read separately and does not change the model by itself.

### 2.2 FFX provider version table (what OptiScaler sees)

Independently of the list above, the DLL exposes 32 provider entries at
`0x180F2D970` (32 pointers; `FUN_180074600` walks up to `0x100`). Each entry
points to a state record whose first qwords are:

```text
+0x00  vtable 0x18031F088 (proveedor FSR4)
+0x08  estado byte 0 = "híbrido" (+0x207)
+0x09  estado byte 1 = Lite
+0x0A  estado byte 2 = INT8
+0x0B..+0x11  skip / DLSS / 3.1.5
```

The vtable `0x18031F088` contains, among others:

| Vtable offset | Function | Role |
|---:|---|---|
| `+0x08` | `0x1800614C0` | availability (weights) |
| `+0x20` | `0x180065920` | name/version shown |
| `+0x28` | `0x1800617C0` | `CreateModel` |
| `+0x48` | `0x180063830` | dispatch/config |

Relevant FSR4 entries (index = position in `0x180F2D970`; this is the value
that `FSR4_XMX_PROVIDER_INDEX` accepts):

| Index | State `+0x08` | Label | Model |
|---:|---|---|---|
| 0 | `0x0000000000000000` | `4.0.2X` | base, no hybrid |
| 4 | `0x0000000000000001` | `4.0.2X Hybrid` | 4.0.2 + hybrid flag |
| 8 | `0x0000000000010101` | `4.1.2X` | hybrid + Lite + INT8 (kind 2) |
| 12 | `0x0000000000000101` | `4.1.2X Lite` | hybrid + Lite (kind 1) |
| 31 | `0x0000000000000000`, `+0x10=0x100` | `3.1.5` | FSR 3.1.5 fallback |

`FUN_1800614C0` checks that the entry is available: for `+0x09` (Lite) it requires
`FUN_180027C00()[0] != 0`; for `+0x0A` (INT8) it requires
`FUN_180027C00()[0x68] != 0`. If not, the entry is hidden/degraded
("Greyed: its file is missing." at `0x180323813`). `FUN_180065920` returns the
label: for the all-zero state it returns the literal `4.0.2X`
(`0x180065ADF` -> `0x180321E70`); for INT8/Lite it returns the strings generated
from `FUN_180027C00()` at `+0x69`/`+1` (see §4).

`FSR4_XMX_PROVIDER_INDEX` is read in `FUN_180074600` (string at `0x180F2DA90`,
log at `0x180F2DAD0`). It accepts a decimal 0..31 and, if the entry is available
and compatible, forces it. Log:

```text
[FSR4 XMX] FSR4_XMX_PROVIDER_INDEX=%zu -> %s (requested version id 0x%llx)
```

If it is not available: `not available here, usual choice kept`. It is the route
to force the 4.1.2X label (`=8`) or the 4.1.2X Lite label (`=12`) without relying
on the dropdown; it requires the weights and a process restart (it is cached once).

## 3. Which version is reported to the caller

There are two sources, and neither depends on `FSR4_XMX_*`:

1. **Provider label**: `FUN_180065920` (`vtable+0x20`). For the base entry
   (state 0) it returns the literal **`4.0.2X`** (`0x180321E70`); for `+0x8` it
   returns `4.0.2X Hybrid` (`0x180321E60`). It is the label that appears in the
   provider version list (OptiScaler shows `FSR 4.0.2X`/`4.0.2`, consistent with
   that literal).
2. **PE VERSIONINFO**: resource `16/1`, `FileVersion 4.0.2.1`,
   `ProductVersion 4.0.2.1` (fixed; see `docs/xmx412-static-inventory.md`).
   It does not change with the environment.

The 4.1.2 labels are different: they are generated from the official weights DLL
in `FUN_180049950` and stored in the structure of `FUN_180027C00()`; they are not
literals in `.rdata`. If the official DLL is 4.1.2, the generated label is
`4.1.2X`/`4.1.2X Lite`; if it is 4.0.2, it would be `4.0.2X`/`4.0.2X Lite`. That
is why the correct `fsr-original.dll` is the one that carries the 4.1.2 blobs
(§4); simply renaming any DLL is not enough.

**Important nuance for the test**: `FSR4_XMX_INT8=1` changes the model that runs,
but it does not rewrite bytes `+0x08..+0x11` of the provider entry that the game
already chose. The overlay may keep showing `FSR 4.0.2` even though the log
confirms `INT8 model ...`. For the caller to see `4.1.2X`, select entry 8/12 in
the dropdown or force `FSR4_XMX_PROVIDER_INDEX=8`/`12`. The model log is the
authoritative evidence of what ran.

## 4. Contract of `fsr-original.dll`

### 4.1 Name and paths

- Exact name: **`fsr-original.dll`**. It appears in ASCII at `0x180323778`
  (UI "Model files") and in UTF-16 at `0x18008A018` (appended to the path).
  The UI says: `Missing? Place next to this DLL, restart.` (`0x180323790`).
- `FUN_180005AC0` resolves the file in this order:
  1. `FSR4_XMX_LITE_DLL` (UTF-16, `0x180089FF0`), if it is defined and valid. It
     is a full **Windows** path (e.g. `Z:\...`), because it is passed to
     `CreateFileW`. Although the name says LITE, `FUN_180005AC0` uses it as the
     path of the weights DLL for Lite **and** INT8 (the weights structure is
     shared). If the path fails, it continues with the next two.
  2. Directory of the mod's own DLL + `\fsr-original.dll`
     (`GetModuleHandleExW(6, FUN_180027C00, ...)` + `GetModuleFileNameW` +
     `FUN_180043130`, which cuts at the last `\`).
  3. Directory of the host EXE + `\fsr-original.dll`
     (`FUN_180043130(..., 0)`).
- It is not searched in `System32`, DriverStore, or next to `amdxcffx64.dll`.

### 4.2 What is verified (not a hash of the whole file)

`FUN_180049950` maps the file read-only and scans offsets aligned to 16 bytes. It
does not check name, exports, signature or PE; it checks content:

1. Size >= `0x6B01` (`0x1800499F6`).
2. At each candidate offset, the qwords at `+0x440..+0x478` must be zero
   (`0x180049B02`).
3. In the first `0x200` UTF-16 words, indices `7,15,23,...` must be zero, and there
   must be more than 400 non-null words (`0x180049B50`).
4. FNV-1a64 over `0x6B00` bytes and over `0x20000` bytes from the same offset,
   comparing four constants (`0x180049C1F`, `0x180049C51`, `0x180049C7C`,
   `0x180049CA6`):

   | Constant | Blob | Destination | Use |
   |---|---|---|---|
   | `0x0CA02A3581DE817F` | `0x6B00` | `+0x38` | Lite preset |
   | `0x2DD74EE29ECB9705` | `0x6B00` | `+0x50` | Lite ultraperf |
   | `0x29CE14ECDF23D42B` | `0x20000` | `+0xD8` | INT8 preset |
   | `0x0DFCFD62036F9E391` | `0x20000` | `+0xF0` | INT8 ultraperf |

5. Version marker: it looks for a pair of dwords where the second one is
   `0xF5A5CA1E` (`cmp [rcx+4], 0xf5a5ca1e` at `0x180049D60`), takes the first
   positive one, the largest, and extracts:
   - major = `v >> 22`
   - minor = `(v >> 12) & 0x3FF`
   - patch = `v & 0xFFF`

   to generate `%u.%u.%uX Lite` (`0x180089F80`) and `%u.%u.%uX`
   (`0x180089FA8`). For 4.1.2 the packed value would be
   `0x01001002` (4.1.2).
6. Availability:
   - `struct[0] = 1` only if **both** Lite blobs are present and the version is
     non-zero (`0x180049E07`).
   - `struct[0x68] = 1` only if **both** INT8 blobs are present and the version is
     non-zero (`0x180049E26`).

`FUN_180028560` re-checks the sizes (`0x6B00` Lite, `0x20000` INT8) and
copies/parses the weights into the model. `FUN_18004A9D0` requires:

- kind 2 (INT8): `FUN_180027C00()[0x68] != 0`;
- kind 1 (Lite): `FUN_180027C00()[0] != 0`;
- otherwise, `Lite/INT8 model requested without verified fsr-original.dll
  weights.` (`0x18030E2E0`) and `HRESULT 0x8000000A`.

The file name is not validated, nor is it checked that it is a PE: any file that
contains exactly those blobs would pass. In practice the expected origin is
AMD's official DLL.

### 4.3 Which official DLL it is

The expected DLL is the **official AMD FidelityFX Upscaler DX12 of FSR 4.1.2**
(`amd_fidelityfx_upscaler_dx12.dll`, unmodified), renamed to
`fsr-original.dll`. Evidence:

- The mod is called `amd_fidelityfx_upscaler_dx12.dll`; its PDB is
  `F:\xmx_probe\fsr4_402\Kits\FidelityFX\upscalers\dx12\x64\Release\amd_fidelityfx_upscaler_dx12.pdb`
  (string at `0x180F4DF28`), i.e. the base is the FidelityFX Upscaler DX12 library.
- The model files UI lists `fsr-original.dll` next to the DLL and says
  "Place next to this DLL, restart." (`0x180323778`, `0x180323790`).
- The loader looks for the FSR4 weights blobs (tables of `0x6B00`/`0x20000`), not
  for exports of a driver.

**It is not `amdxcffx64.dll`.** That string does not appear in the binary; the
only `amdxc*` string is `amdxc64.dll` (`0x180F2DA80`), which is a provider name
in the version table, not the weights file. The loader is content-based, so it
cannot be statically proven that `amdxcffx64.dll` fails without having it, but
there is no reference supporting it, and the expected layout is that of the
FidelityFX library.

**It is not the modified 4.1.2 DLL nor the local 4.0.2.** The exact scan of
`FUN_180049950` (C, read-only) was reimplemented over:

- `artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll` (4.0.2,
  `3eb08656…`): 0 version pairs, 0 matching blobs.
- `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll` (mod
  4.1.2, `fadbcb50…`): 0 version pairs, 0 matching blobs.

Therefore, copying/renaming the mod's own DLL as `fsr-original.dll` does not work
for 4.1.2X. The official 4.1.2 DLL is not in the repository; its SHA-256 is not
invented. The practical verification is the loader log (§5).

## 5. Recipe for Spider-Man (per process)

### 5.1 Files

1. Use the 4.1.2 mod DLL (`fadbcb50…`) and OptiScaler as before.
2. Obtain the official AMD FidelityFX Upscaler DX12 DLL of FSR 4.1.2
   (do not redistribute it in the repo) and rename it **`fsr-original.dll`**.
3. Place it:
   - next to the mod DLL (same folder as `amd_fidelityfx_upscaler_dx12.dll`), or
   - next to the game's EXE, or
   - at an explicit path with `FSR4_XMX_LITE_DLL=Z:\ruta\amd_fidelityfx_upscaler_dx12.dll`
     (Windows path; `Z:` is `/` in Proton).
4. Delete/rename any old `fsr-original.dll` (4.0.2) so the two are not mixed.
   Restart the game after changing files.

### 5.2 Variables (Steam: `VAR=1 %command%`; or wrapper `env VAR=1 ...`)

For **4.1.2X** (INT8):

```text
FSR4_XMX_INT8=1
```

For **4.1.2X Lite**:

```text
FSR4_XMX_LITE=1
```

Do not set both; if both are set, INT8 takes priority when weights are available.
For **4.0.2X Hybrid**:

```text
FSR4_XMX_PRE41=1
```

To leave the choice to the game (4.0.2X by default), do not define any of the
three. Do not define `FSR4_XMX_DLSSK/M/E` during the FSR4 test (they take
priority).

Example Steam launch options for a 4.1.2X test:

```text
FSR4_XMX_INT8=1 FSR4_XMX_DEV=1 PROTON_LOG=1 %command%
```

For 4.1.2X Lite, replace `FSR4_XMX_INT8=1` with `FSR4_XMX_LITE=1`.

Useful optional settings:

```text
FSR4_XMX_DEV=1                 # pestaña Developer, Version list/HiddenEntries/Profile
FSR4_XMX_PROVIDER_INDEX=8      # fuerza la etiqueta/entrada 4.1.2X (requiere pesos)
FSR4_XMX_PROVIDER_INDEX=12     # fuerza 4.1.2X Lite
FSR4_XMX_DPAS=16               # fuerza Xe2 SIMD16 (B-series); =8 fuerza DG2 SIMD8
FSR4_XMX_FS_DIAG=2             # skip rules como colores (0/2/4; bit 8 = stats)
MLSR-PROFILE=1                 # perfil por frame
FSR4_XMX_NO_DIALOG=1           # sin MessageBox en GPU sin XMX
FSR4_XMX_SHARPNESS=0.0         # 0..max; no afecta a la selección de modelo
```

`FSR4_XMX_DPAS` is read with `getenv_s` in `FUN_18004DC90`; if it is not set, it is
auto-detected via `INTC_D3D12_CheckFeatureSupport`. `FSR4_XMX_FS_DIAG` is read
with `atoi` in `FUN_180068CF0`; there is **no** `FS_DIAG` variable in this DLL
(if OptiScaler has its own, that is something else). `FSR4_XMX_DEV` is only
activated with a first byte of `'1'` (`0x18006FD90`).

### 5.3 How to know which model was used

Search stderr/`OutputDebugStringA` (Proton: `PROTON_LOG=1`, or the OptiScaler log):

- 4.1.2X (INT8):

  ```text
  [FSR4 XMX] INT8 model: preset weights from Z:\...\fsr-original.dll, bucket 0, Xe2 SIMD16-DPAS kernels.
  [FSR4 XMX] INT8 network kernels ready (bucket 0, preset weights).
  ```

- 4.1.2X Lite:

  ```text
  [FSR4 XMX] Lite model: preset weights from Z:\...\fsr-original.dll, bucket 0, Xe2 SIMD16-DPAS kernels.
  [FSR4 XMX] Lite network kernels ready (bucket 0, preset weights).
  ```

  (`preset`/`ultraperf` varies with the quality preset; `bucket` 0..2.)
- 4.0.2X/Hybrid does not go through `FUN_18004A9D0` (kind 0), so it does not print
  `INT8/Lite model`. It is recognized by the chosen provider entry
  (`4.0.2X`/`4.0.2X Hybrid`), by the GPU log
  `[FSR4 XMX] GPU GTGeneration=... -> ... kernels ...` and by the hybrid flag;
  there is no specific "model" line.
- If the provider was forced:

  ```text
  [FSR4 XMX] FSR4_XMX_PROVIDER_INDEX=8 -> 4.1.2X (requested version id 0x...)
  ```

- If the file/weights are missing:

  ```text
  Lite/INT8 model requested without verified fsr-original.dll weights.
  %s weights are unavailable (fsr-original.dll).
  ```

  and the model is not loaded.

**Overlay**: if the game chose the base entry, the overlay may keep showing
`FFX -> FSR 4.0.2` even though the log says `INT8 model`. That is expected:
`FSR4_XMX_INT8=1` does not change the provider version label. To see `4.1.2X` in
the list/overlay, select the 4.1.2X entry (requires weights) or use
`FSR4_XMX_PROVIDER_INDEX=8`; for Lite, `12`.

### 5.4 What to check if it fails

1. Does the log show `FSR4_XMX_PROVIDER_INDEX=8 -> 4.1.2X`? If it says
   `not available here, usual choice kept`, the weights are missing or the entry
   is not compatible.
2. Do `INT8 model`/`Lite model` appear? If not, `CreateModel` did not choose 4.1.2:
   check the spelling and the value `=1`, that there is no `FSR4_XMX_DLSS*`, and
   that the file is in the path being searched.
3. Is the log path the expected one? The loader tries `FSR4_XMX_LITE_DLL`, then the
   DLL's directory, then the EXE's. A mistyped `Z:\...` path fails silently and
   falls through to the next one.
4. Is the official DLL's version 4.1.2? If the generated marker gave `4.0.2X`, that
   file is not the official 4.1.2 (and its blobs do not match the constants of
   §4.2 either); it does not enable the 4.1.2 entries.
5. If the model loads but dispatch fails, the errors are no longer about selection:
   `Lite network pass %u XMX initialization/dispatch failed.`,
   `Lite ScratchBuffer too small`, `embedded Lite XMX resource pack is
   missing or invalid.`, etc.

### 5.5 Quick checklist

- [ ] `fsr-original.dll` is the official 4.1.2 DLL, not the 4.0.2 one nor the mod.
- [ ] It is next to the mod DLL (or next to the EXE, or in `FSR4_XMX_LITE_DLL`).
- [ ] There is no old `fsr-original.dll` at another path that gets tried first.
- [ ] Only one of `FSR4_XMX_INT8=1` / `FSR4_XMX_LITE=1` / `FSR4_XMX_PRE41=1`.
- [ ] No `FSR4_XMX_DLSSK/M/E` during the FSR4 test.
- [ ] The log shows `INT8 model` or `Lite model` with the correct path.
- [ ] If `FSR4_XMX_PROVIDER_INDEX` is used, the log shows the expected name
      (`4.1.2X`/`4.1.2X Lite`), not `not available here`.
- [ ] The overlay may stay on `4.0.2`; the log decides.

## 6. Limits

- Nothing was executed; there is no evidence of injection, GPU dispatch or
  readback. `S_OK`, a PSO or the overlay do not certify the model.
- The exact runtime semantics of "Hybrid" (+0x207) are not demonstrated; only the
  flag, the scratch change and the dispatch bits are pinned.
- The official 4.1.2 DLL is not available in the repository; its SHA-256 is not
  pinned. The verifiable contract is the blob/version scan and the log.
- The exact correspondence between the provider label and OptiScaler's text
  "FSR 4.0.2" is inferred from `FUN_180065920` and the VERSIONINFO; OptiScaler
  was not instrumented.
- `amdxcffx64.dll` could not be tested (it is not local); it is only asserted that
  the binary does not reference it and that the expected layout is that of the
  FidelityFX library.

## 7. Reproducible evidence

- `tests/test_xmx412_model_strings.py` (7 tests, CPU-only, read-only):
  SHA, literals, `INT8/LITE/PRE41` branches, priority, table of 32 providers,
  vtable, labels, FNV constants, version marker, `%u.%u.%uX` generation and the
  path/name of `fsr-original.dll`.
- `python3 -m unittest tests.test_xmx412_model_strings -v`
- Disassembly: `llvm-objdump -d --start-address=... --stop-address=...`;
  decompilation: Ghidra 12.2 headless (`analyzeHeadless`), local project, not
  versioned.
- Related documents: `docs/xmx412-static-inventory.md`,
  `docs/xmx412-variants.md`, `docs/compatibility.md`.
