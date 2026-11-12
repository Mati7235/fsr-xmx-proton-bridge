# Spider-Man Remastered: runbook de traza manual con el mod XMX 4.1.2

Fase 1, CPU-only para quien prepara; **ejecución manual del usuario** para la
traza. Este documento no autoriza nada por sí mismo: cada paso de ejecución
lo realiza el usuario a mano, en un prefijo descartable, sin tocar Steam,
prefijos reales, drivers ni servicios.

Estado fijado por `tools/prepare_trace_capture_412.py` (verificado por
SHA-256 el 2026-11-12):

| Artefacto | SHA-256 |
|---|---|
| DLL `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll` | `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732` |
| PRE Xe2 `native_1080` IR (pack 40102, record 0, offset 0, 358776 B) | `49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568` |
| PRE Xe2 `native_1080` envelope (358873 B, también `analysis/offline-pre-412/module-0000.cmspv`) | `ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab` |
| Packs 40101–40106 raw | ver `profiles/xmx412-pins.json` (1977 envelopes CM en total) |

Contrato de captura: `docs/pre-trace-capture-spec.md` (qué registrar del
dispatch PRE `native_1080`); checklist de versiones:
`docs/pre-trace-version-checklist.md`.

## 0. Rutas y versiones de partida (solo lectura)

- Juego: `/home/matias/Juegos/Spiderman/Marvel's Spider-Man Remastered/`,
  ejecutable `Spider-Man.exe` (121.901.008 B observados; re-registrar el día
  de la traza, Steam puede actualizarlo).
- OptiScaler ya instalado: `dxgi.dll` + `D3D12_OptiScaler/D3D12Core.dll` +
  `OptiScaler.ini`. El `amd_fidelityfx_upscaler_dx12.dll` actual del juego
  (`d0dcccc7…`) **no** es el mod.
- Proton: `/home/matias/.steam/root/steamapps/common/Proton - Experimental`
  (`version`: `experimental-11.0-20261105c`; lanzador `proton`, uso
  `proton run <exe>`).
- ICD explícito: `/usr/share/vulkan/icd.d/intel_icd.x86_64.json`
  (`api_version 1.4.363`, librería `/usr/lib/libvulkan_intel.so`).
- RenderDoc disponible: `renderdoccmd` / `qrenderdoc` v1.46 (soporte
  Vulkan compilado).

## 1. Re-verificar hashes de partida (solo lectura, sin ejecutar nada)

```bash
cd /home/matias/Proyectos/fsr-xmx-proton-bridge
sha256sum artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll
# esperado: fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732
python3 -c "
import sys; sys.path.insert(0,'tools')
import parse_cm_payloads
from pathlib import Path
data = Path('analysis/fsr-xmx-412/pack-40102.raw').read_bytes()
r = parse_cm_payloads.parse(data)[0]
print(r)
assert r['ir_sha256'] == '49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568'
assert r['envelope_sha256'] == 'ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab'
print('PRE native_1080 OK')
"
sha256sum "/home/matias/Juegos/Spiderman/Marvel's Spider-Man Remastered/Spider-Man.exe"
cat "/home/matias/.steam/root/steamapps/common/Proton - Experimental/version"
sha256sum /usr/share/vulkan/icd.d/intel_icd.x86_64.json /usr/lib/libvulkan_intel.so
```

Si cualquier hash del mod difiere: parar, no continuar.

## 2. Colocar la DLL del mod (acción manual del usuario)

Lectura del `OptiScaler.ini` del juego (verificado por lectura directa):

- `[Upscalers] Dx12Upscaler = xess` (línea 14): OptiScaler intercepta el
  DX12 del juego por la ruta XeSS.
- `[Libraries] FfxDx12SRPath = auto` (línea 810-811, comentario
  `amd_fidelityfx_upscaler_dx12.dll`): en `auto`, OptiScaler resuelve esa
  DLL desde el directorio del juego.

Por tanto, la ruta exacta esperada del mod es:

```text
/home/matias/Juegos/Spiderman/Marvel's Spider-Man Remastered/amd_fidelityfx_upscaler_dx12.dll
```

Pasos manuales (el usuario, nunca automatizado):

1. Copia de seguridad del archivo actual fuera del juego (el actual es
   `d0dcccc7…`, no el mod; no tocar `.optiscaler-backup/`).
2. Copiar encima `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll`.
3. Re-verificar: `sha256sum` debe dar `fadbcb50…`.
4. Antes de capturar, confirmar en el overlay/menú de OptiScaler (Insert) y
   en su log qué backend atiende realmente el upscale: con
   `Dx12Upscaler=xess`, si la ruta activa es XeSS puro la traza del PRE no
   aplica; solo proceder si el backend FSR/XMX 4.1.2 está en uso. Registrar
   lo observado en `evidence/versions/` como nota, sin reinterpretarlo.

## 3. Andamiar la preparación y el run (CPU-only, sin ejecutar nada)

```bash
cd /home/matias/Proyectos/fsr-xmx-proton-bridge
python3 tools/prepare_trace_capture_412.py
# crea build/trace-412-<fecha>-<id>/ con manifest.json + run-manual.py
python3 build/trace-412-<fecha>-<id>/run-manual.py --run-trace \
  --icd-manifest /usr/share/vulkan/icd.d/intel_icd.x86_64.json
# crea runs/<run-id>/ con wineprefix-reserved-not-initialized VACÍO (0700)
# y evidence/{env.json,pinned-hashes.json,planned-command.txt,icd-manifest.json,versions/}
```

El lanzador exige **ambos** flags y nunca inicializa el prefijo ni genera
procesos hijo. El `WINEPREFIX` reservado solo se inicializa dentro del run
manual autorizado, nunca antes.

## 4. Comando Proton exacto (manual, una vez autorizado)

Solo con las variables de `evidence/env.json` (entorno reemplazado, no
heredado), más la redirección del log fuera del juego/Steam:

```bash
env -i \
  PATH=/usr/bin:/bin LANG=C LC_ALL=C \
  HOME='<run>/home' XDG_CACHE_HOME='<run>/cache' XDG_CONFIG_HOME='<run>/config' \
  XDG_DATA_HOME='<run>/data' XDG_STATE_HOME='<run>/state' TMPDIR='<run>/tmp' \
  WINEPREFIX='<run>/wineprefix-reserved-not-initialized' \
  VK_DRIVER_FILES=/usr/share/vulkan/icd.d/intel_icd.x86_64.json \
  VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/intel_icd.x86_64.json \
  VKD3D_DEBUG=trace \
  "/home/matias/.steam/root/steamapps/common/Proton - Experimental/proton" run \
  "/home/matias/Juegos/Spiderman/Marvel's Spider-Man Remastered/Spider-Man.exe" \
  > '<run>/evidence/vkd3d-trace.log' 2>&1
```

Notas:

- `VKD3D_DEBUG=trace` ya viene fijado en `evidence/env.json`; es la
  variable de captura API de VKD3D-Proton (log textual masivo, no frame).
- En el juego, buscar una escena con entrada de upscale 1920×1080
  (grid PRE `native_1080`); anotar resolución interna real observada en vez
  de suponerla.
- Device PCI esperado en B580: `8086:e20b`; registrar el ID real del log.

## 5. Captura del frame con RenderDoc (manual, opcional complementario)

El log `VKD3D_DEBUG=trace` da la secuencia API; el frame con descriptores
se captura con RenderDoc sobre el lado Vulkan:

```bash
renderdoccmd capture --capturefile '<run>/evidence/spiderman-412.rdc' \
  env -i <mismas variables de evidence/env.json> \
  "/home/matias/.steam/root/steamapps/common/Proton - Experimental/proton" run \
  "/home/matias/Juegos/Spiderman/Marvel's Spider-Man Remastered/Spider-Man.exe"
```

Abrir el `.rdc` con `qrenderdoc` (CPU, sin GPU del juego) y localizar el
evento `Dispatch(120, 540, 1)`. Cualquier variable extra de capa
(`VK_INSTANCE_LAYERS`, …) es una desviación documentada de
`evidence/env.json`, no parte del entorno fijado.

Qué buscar en el frame (criterio de la spec §2–§8):

- Un único `Dispatch` con grid `(120, 540, 1)` para `w=1920, h=1080`
  (fórmula `x=(w+15)>>4; x+=x&1; y=h>>1`); modos 2–3 no emiten PRE,
  4 → `(1,1,1)`, 5 → `(x,1,1)`, 6 → `(x,0x44,1)`.
- 11 tablas de descriptores efectivas (roots 1–11: u0, u1, t0–t6, t7, t8)
  + sampler en root 12; `SetComputeRoot32BitConstant(root 0) = 0`.
- Formatos: UAV/SRV `R8_UINT` (`0x3E`); arg 9 SRV `0x1688`, `0x840`
  (2.112 B); arg 10 SRV `0x1688`, `0x80` (128 B); arg 0 UAV
  `NumElements = Width` con `GetDesc.Dimension == 1` y
  `Width >= 8.294.400`.
- `Width` efectivo de arg 0 (dimensiona el UAV; no suponer asignación
  exacta), `GetDesc` por slot, aliasing entre slots, estados/transiciones
  `ResourceBarrier` (`0x40`/`0x400`/`0x800`).
- Bytes pre **y** post dispatch: header arg 10 (128 B), arg 9 (2.112 B),
  registro float4 en `base+{0,16}` y plano OWORD de arg 0
  (`índice = wg_y*960 + wg_x*8`); volcado completo recomendado, sin
  inicializar nada como buffer vacío.

## 6. Llenar `evidence/versions/` (una fila por ítem, valor + fuente)

Guía fila a fila del checklist (todos los comandos son de solo lectura;
guardar cada salida con el nombre indicado):

| # | Archivo | Comando de solo lectura |
|---|---|---|
| 1 | `exe.sha256` | `sha256sum "<juego>/Spider-Man.exe"` + tamaño en bytes |
| 2 | `exe.version.txt` | recurso de versión del PE (FileVersion/ProductVersion), leído sin ejecutar |
| 3 | `proton.version.txt` | `cat "<proton>/version"` + ruta del directorio Proton |
| 4 | `vkd3d.*.sha256` | `sha256sum <proton>/files/lib/wine/x86_64-windows/{d3d12,dxgi}.dll <proton>/files/lib/vkd3d/x86_64-windows/*.dll` de los binarios confirmados por el log de carga |
| 5 | `vkd3d.version.txt` | cadena de versión del build VKD3D en uso (archivo de versión o log), sin asumir número |
| 6 | `wine.version.txt` | `"<proton>/files/bin/wine" --version` (fuera de Steam, sin inicializar prefijos) |
| 7 | copia del manifiesto | `evidence/icd-manifest.json` ya la deja el lanzador; añadir `sha256sum` del manifiesto usado |
| 8 | `icd.library.sha256` | `sha256sum /usr/lib/libvulkan_intel.so` + `api_version` del manifiesto |
| 9 | `dll.sha256` | `sha256sum "<juego>/amd_fidelityfx_upscaler_dx12.dll"` → debe dar `fadbcb50…` (el checklist impreso aún muestra el hash viejo: anotar la desviación explícitamente) |
| 10 | `pre-412.hashes.txt` | IR `49e069fd…` + envelope `ce372719…` re-verificados con el comando del §1 (no hay zebin 4.1.2 compilado: `REQUIRED-TBD`, el runtime resuelve desde el pack 40102 de la DLL) |
| 11 | `device.pci.txt` | ID PCI real del log de selección (`8086:e20b` esperado en B580) |
| 12 | `host.context.txt` | `uname -r`, versión de CachyOS/Mesa (solo contexto) |

Reglas: si un ítem no aplica, anotarlo explícitamente; no reutilizar
valores de otra máquina o ejecución; ninguna fila sustituye al oracle de
salida ni acredita corrección funcional.
