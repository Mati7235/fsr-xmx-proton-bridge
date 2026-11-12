# XMX 4.1.2 DLSS packs (40104–40106) — vía de ejecución

Análisis estático, CPU-only, de los tres packs DLSS del build 4.1.2
(DLL SHA-256 `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`).
No se ejecutó código de la DLL ni de los packs; no se tocó driver, Steam,
prefijos, GPU, Wine ni `artifacts/original`. El 7z `nvngx_dlssd_xmx.7z`
solo se listó en solo-lectura (`7z l`: un `nvngx_dlssd.dll` de 179 233 280 B,
`2026-11-10 09:17:17`); no se extrajo ni ejecutó nada de él.
Herramientas: `tools/decompress_xmx412.py` + `tools/parse_cm_payloads.py` +
`tools/carve_spirv.py` (stdlib + libwim local, imagen nunca cargada).
Pins verificados en `tests/test_xmx412_dlss.py` (21 pruebas CPU, fail-closed).

Respuesta corta: **los kernels DLSS usan la misma vía igdext CM-SPIRV
que FSR (Kernel + `SPV_INTEL_vector_compute`, `BufferSurfaceINTEL`
ReadWrite, DPAS/BTI, sin samplers). No son CUDA/NGX clásicos.**
Comparten el loader `FUN_180029640` con los packs FSR.

## Tabla pack → kernels → vía → relevancia para el puente

| RCDATA (idx) | Bucket (loader) | Kernels verificados | Vía de ejecución | Relevancia para el puente |
|---|---|---|---|---|
| 40104 (3) | DLSS K (DG2 + Xe2/Xe3) | 716: `k_gemm`×174, `k_linear`×160, `k_attn`×126, `k_mlp`×126, `k_block`×50, `k_stage`×48, `k_adapt`×32 | CM-SPIRV Kernel, `SPV_INTEL_vector_compute`, `BufferSurfaceINTEL` ReadWrite en 716/716, 64/716 con 1 `OpTypeImage` 2D Unknown, 0 samplers, DPAS2/DPASW + `lsc.load.bti`/`oword` | Misma vía que FSR: el lector CMK3/ANV para buffers + DPAS + BTI se reutiliza. Sin samplers que portar. Bloqueante distinto: pesos `nvngx_dlss.dll` + `ScratchBuffer` + `token grid`, no `fsr-original.dll` ni magenta PRE. |
| 40105 (4) | DLSS E / F | 312: `e_conv`×240, `e_stage`×64, `e_adapt`×8 | Idem: 312/312 `BufferSurface` ReadWrite, 40/312 con 1 imagen 2D Unknown, 0 samplers, `dpas2` + `lsc.store/load.bti` + `scatter4.typed`/`3d.load` en minoría | Idem. Convolucional (`e_conv`) + typed stores; sin `sampler_t` ni `3d.sample`. Si el puente maneja buffers + una imagen Unknown, cubre E/F sin sampler dinámico. |
| 40106 (5) | DLSS-MX (DG2) | 67: `k_gemm`×19, `m_layer`×18, `k_mlp`×10, `m_stage`×10, `m_attn`×8, `m_adapt`×2 | Idem: 67/67 `BufferSurface` ReadWrite, 3/67 con 1 imagen 2D Unknown, 0 samplers, `dpas2`/`dpasw` | Variante mixta `k_`+`m_`; misma conclusión. Volumen pequeño (5,4 MB) útil como caso de prueba del lector. |

Total DLSS: **1 095** envelopes (716+312+67). Total seis packs: 1 977.

Tamaños verificados (comprimido → descomprimido, SHA-256 raw):

- 40104: 8 031 050 → 42 477 193, `a9ea6724…7054ea`
- 40105: 3 421 152 → 19 590 261, `7ac547ee…57d246fa`
- 40106: 1 001 522 → 5 443 681, `03c18858…5a331ac3`

`raw.count(SPIRV_MAGIC) == cm_envelopes` en los tres (716/312/67).
Gaps: 712/307/66 huecos, todos cero (`all_zero`), cero candidatos DXBC.
Los packs FSR 40102/40103 también tienen gaps cero; solo 40101 tiene
18 DXBC + 24 huecos no-cero. DLSS es CM puro + relleno cero.

## Nombres y args/tipos

- Entry points vía `tools/carve_spirv.py` (OpEntryPoint, `model=6` Kernel en
  1 095/1 095): distribuciones de arriba, suma == envelopes. Falla cerrado
  si difiere.
- Interfaz de entrada: **1–2 × `v3i64` `Input`** (payload cross-thread,
  no descriptores):
  - 40104: 282×1, 434×2; 40105: 272×1, 40×2; 40106: 23×1, 44×2.
  - Nunca `BufferSurface`/`Image` directo en la interfaz; las superficies
    van por BTI/stateless interno (inmediatos) + estado `BufferSurface`.
- Tipos internos por módulo:
  - `OpTypeBufferSurfaceINTEL` (opcode 6086, `access=2` ReadWrite): **1 por
    módulo en 1 095/1 095**, como tipo de parámetro de función
    (`OpTypeFunction` con `(i32, BufferSurface)`). Igual que FSR.
  - `OpTypeImage` (`dim=1` 2D, `depth=0`, `arrayed=0`, `ms=0`, `sampled=0`,
    `format=0` Unknown): 64/716, 40/312, 3/67. FSR 40101: 36/252 con 2
    imágenes. Formato Unknown idéntico al PRE.
  - `OpTypeSampler` (26) y `OpTypeSampledImage` (27): **0 en 1 095/1 095**.
    FSR tiene 18–36 módulos con sampler; DLSS ninguno. En IR: cero
    `p2opencl.sampler_t`, cero `3d.sample`; solo `3d.load` (64/16/2),
    `scatter4.typed` + `lsc.store.quad.typed.bti` en la minoría con imagen,
    más `address.convert ...p1opencl.image2d_{ro,rw}_t`.
  - Resto: `lsc.load.bti`, `oword.ld/st`, `vload/vstore`, `rdregion/wrregion`,
    `dpas2` (`v128f32…`, `v64f32…`), `dpasw` (`v64f32…`), `fence`, `lsc.*.slm`.
    `dpas2`/`dpasw` están en **nombres `llvm.genx.*` dentro del IR**, no en
    huecos (corrección al enunciado “gap strings” del envelope previo).
- Modos de ejecución por módulo: `31`, `35(1)`, `5618`, `6417` en 100 %,
  igual que FSR 40101/40103. `5618(0)` mayoritario (390/716, 272/312, 38/67)
  más variantes `8192/4096/2048/3072/…`; mismo perfil CM vector-compute.
- Extensiones por módulo: `SPV_INTEL_vector_compute` +
  `SPV_KHR_no_integer_wrap_decoration` en 1 095/1 095,
  `OpenCL.std` en 1 095/1 095. Sin extensiones CUDA/NGX.
- Trailers (`-vc-payload` + longitudes verificadas):
  - B siempre `␣-target-features=+ocl_runtime` (716/312/67).
  - A: 40104 `…'-noDPASMacro'`×442 + `…-ze-exp-register-file-size=256…`×274;
    40105 ×192+×120; 40106 ×49+×18. FSR 40101 es `-vc-payload` solo;
    40102/DLSS llevan `-noDPASMacro`. `register-file-size=256` solo en DLSS.

## ¿igdext/CM-SPIRV o CUDA/NGX clásicos?

CM-SPIRV vía igdext, evidencia:

1. Binario: SPIR-V Kernel + vector-compute + `BufferSurface` + DPAS/BTI en
   100 %; imágenes Unknown sin samplers; mismos modos que FSR; gaps cero sin
   DXBC/CUDA/NGX. Búsqueda `ngx/cuda/nvngx/dxbc` (minúsculas) en packs crudos:
   ausente (salvo `dxbc` omitido por ruido x86; marcador `DXBC` mayúsculas
   cero vía `gaps[].dxbc_candidates == []`).
2. DLL (solo-lectura, `artifacts/extracted/fsr-xmx-412/…dll`):
   cero `k_gemm/k_linear/e_conv/m_layer`, cero `CUDA`, cero `NVNGX/NGX`,
   cero `40104/40105/40106`. Solo referencias de fichero de pesos en
   minúsculas: `nvngx_dlss.dll` (8 cadenas: “requested without verified
   nvngx_dlss.dll weights … K/E-F/M”, “with the K weights (or reconstruction
   tables not bit-exact)”, presets L/M).
3. Misma DLL sí trae vía Intel: `igdext64.dll` (17), `INTC_D3D12_*`
   (`CreateDeviceExtensionContext`, `CheckFeatureSupport`,
   `CreateComputePipelineState`, `GetCachedBlob`), `CM-SPIRV` (29),
   `OPTIONS1/OPTIONS2`, `root signature`, `production ABI`.
4. Logs FSR vs DLSS: `Failed to load P6 N32…` / `P7 FullFusion…` /
   `P1 H1 DPAS…` / `P10 X1 Low128…` existen **solo para la pata FSR**
   (35 `Failed to load…`, 6 `FullFusion`). Ningún `Failed to load k_*` /
   `e_*`. La pata DLSS loguea distinto: `DLSS K/E-F/MX … initialization/
   output dispatch failed`, `ScratchBuffer too small`, `requested without
   verified nvngx…`, `DLSS K ready: %u kernels, %zu params bytes, token grid
   %ux%u`, `DLSS %s ready: %u kernels…`, `needs the depth buffer` (MX),
   perfiles `DLSS-KX/MX/LX/EX/FX`, `FSR4_XMX_DLSSK/DLSSM/DLSSE`, `[DLSSK PROFILE]
   …`, `[DLSSK ASKIP]…`. Es decir, misma vía de compilación, distinto
   dispatcher/pesos.

## ¿Comparten el loader `FUN_180029640`?

Sí. `tools/decompress_xmx412.EXPECTED` fija `index = rid-40101` para
40101–40106 (DLSS = 3,4,5), `res_size/raw_size/SHA-256/cm_envelopes` exactos,
`MOV ESI 0x9CA5…0x9CAA`, tamaños `0x21B5796…0x531061`, clamp `>5→0`,
`GetModuleHandleExW→FindResourceW(h,id,10)→LoadResource→SizeofResource→
LockResource`, `Cabinet.dll` ordinales 40/43/45 (`ECX=5` LZMS, 64 KiB),
`BCryptHash(0x41)` SHA-256 + `strcmp` contra digesto compilado, caché por
índice bajo mutex, logs `embedded pack %u invalid: …` /
`embedded %s pack loaded: … SHA256 verified` con `bucket=%s`
(`DLSS K (DG2 + Xe2/Xe3)`, `DLSS E / F`, `DLSS-MX (DG2)`). Sin AES/ChaCha.
Ver `docs/xmx412-pack-envelope.md`. Los tres packs DLSS verifican por esa
misma ruta (`packs_from_resdir` + `decode_and_verify` en pruebas).

## Contraste con strings de la DLL (resumen)

| Señal | FSR (40101–40103) | DLSS (40104–40106) |
|---|---|---|
| `Failed to load P6 N32…` / `P7 FullFusion…` / `P1…P12…` | Presente (35) | Ausente para `k_/e_/m_`; DLSS no loguea por kernel |
| `CM-SPIRV PSO creation failed` / `igdext64.dll for passN` | Presente por pase | Sin equivalente por kernel; `igdext` global + `CreateComputePipelineState` compartido |
| `DLSS K/E-F/MX … ScratchBuffer/token grid/kernels/weights` | N/A | Presente (68 `DLSS…`, 34 `ScratchBuffer`, 19 `weights`, 4 `token grid`) |
| `k_gemm/e_conv…` en DLL | N/A (solo en packs) | Ausente en DLL (solo en SPIR-V) |
| `CUDA/NVNGX/NGX` | Ausente | Ausente (solo `nvngx_dlss.dll` peso) |
| `embedded pack %u invalid` / `embedded %s pack loaded` / buckets | Compartido | Compartido (misma tabla 0–5) |

## Relevancia para el puente

- **No hay backend CUDA/NGX que puentear.** Si el shim + ANV ya crean
  `CreateDeviceExtensionContext 4.20.0` + `CreateComputePipelineState` para
  CM-SPIRV con `BufferSurface` + DPAS + BTI + `Unknown` images sin sampler,
  los 1 095 kernels DLSS viajan por el mismo camino que el PRE/pases FSR.
  Prioridad sigue en FSR (magenta/fail-stop, tablas por SurfaceIndex/sampler,
  `pre-resource-map.md`).
- **Diferencias a aislar:** pesos fuera del pack (`nvngx_dlss.dll` verificado,
  tablas de reconstrucción bit-exactas), `ScratchBuffer` por bucket, `token
  grid %ux%u` en vez de `baseDispatch` FSR, presets `KX/MX/LX/EX/FX` y env
  `FSR4_XMX_DLSSK/DLSSM/DLSSE`, sin `sampler_t`/`3d.sample` (menor superficie
  que FSR). No reutilizar el oracle PRE ni asumir mismos BTI/offsets.
- **Riesgos cerrados:** cadenas no prueban dispatch; `S_OK`/overlay no es
  éxito; se exige evidencia de inyección + readback determinista como en
  `docs/compatibility.md`. DLSS-MX (67 kernels, 5 MB) es el candidato más
  barato si algún día se prueba un dispatcher DLSS aislado, siempre en
  prefijo descartable y nunca en el juego (Spider-Man usa `nvngx_dlssd.dll`
  parcheada aparte, no analizada aquí más allá del `7z l`).

## Limitaciones

- Solo estático y CPU; sin Ghidra/REA con ejecución, sin IGC/ocloc, sin Wine.
- Nombres de kernels por `carve_spirv` + pies verificados; no parser completo
  del pack (pesos/params entre envelopes no clasificados, salvo gaps cero).
- `OpTypeImage Unknown` sin formato/dims; BTI concretos y `ScratchBuffer`
  runtime requieren traza (ver `pre-trace-capture-spec.md` para FSR).
- La DLL parcheada del juego (`nvngx_dlssd_xmx.7z`) queda fuera de alcance
  salvo el listado; no se afirma compatibilidad Proton/GPU.
