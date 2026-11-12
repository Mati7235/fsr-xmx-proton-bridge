# XMX 4.1.2: dispatch PRE equivalente (estático, CPU-only)

Solo análisis estático de la DLL fijada
`fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`
(45.558.272 bytes). Sin ejecutar la DLL, sin GPU/Wine, sin tocar
`artifacts/original`, juegos o prefijos. Sin Ghidra/REA: el proveedor REA
estaba no disponible (`GHIDRA_INSTALL_DIR` sin configurar); la evidencia
viene de parsing PE con stdlib + `llvm-objdump -d` (solo desensamblado).
Los nombres `FUN_*` de la vieja son sintetizados de Ghidra; aquí se usan
RVAs `0x…` (VA = `0x180000000` + RVA).

Fijado en `tests/test_xmx412_dispatch.py` (fail-closed).

## DLL y PE

| | vieja | 4.1.2 |
|---|---|---|
| SHA-256 | `3eb08656…08eba53` | `fadbcb50…37f44732` |
| tamaño | 25.779.712 | 45.558.272 |
| ImageBase | `0x180000000` | `0x180000000` |
| `.text` | vsize `0x52aff` vaddr `0x1000` | vsize `0x7762f` vaddr `0x1000` |
| `.rdata` | vaddr `0x54000` | vaddr `0x79000` |

## Dispatch PRE equivalente: `0x180024e00..0x18002666a`

Lógica equivalente a la vieja `FUN_1800163c0`
(`0x1800163c0..0x180017b6d`, 6.062 B):

- Entrada 4.1.2: RVA `0x24e00` (VA `0x180024e00`).
  Prólogo con cookie (`mov %rsp,%r11 … sub $0x270,%rsp`) y gate
  `ctx+0xa94==0 || ctx+0xa80==0 || ctx+0xa88==0` → fail-stop
  `PRE params are not ready` (salto a `0x2666a`).
  Rango lógico `0x24e00..0x2666a` = 6.250 B (+188 B vs vieja).
- `.pdata` lo parte en tres entradas (misma lógica, unwind separado):
  `[0x24e00,0x24e5a)` 90 B + `[0x24e5a,0x25147)` 749 B +
  `[0x25163,0x2666a)` 5.383 B (hueco `0x25147..0x25163` = epílogo/ret).
  La vieja era una sola entrada.
- Único llamante directo: `E8` en RVA `0x8e3a`
  (`e8 c1 bf 01 00` → `0x24e00`) dentro de la función
  `[0x8a1c,0x99b7)` (3.995 B). Análogo al viejo sitio `0x1800058be`
  en `FUN_1800052e`. Verificado por barrido de todos los `E8` en `.text`
  (1 solo hit).
- Segunda mitad contiene los 10 nombres stock, los gates de constantes/
  ABI/ScratchBuffer, la selección de slots vía tabla `+0x8efc`, los
  `GetDesc`/bounds, las barreras y el dispatch final.

LEAs RIP-relativas fijadas (sitio → cadena):

| sitio RVA | destino RVA | cadena |
|---|---|---|
| `0x25110` | `0x311790` | `PRE runtime-flag ABI mismatch…` |
| `0x26635` | `0x311890` | `PRE runtime geometry is unavailable.` |
| `0x26646` | `0x311840` | `PRE ScratchBuffer layout mismatch…` |
| `0x26652` | `0x311740` | `PRE constants are incomplete…` |
| `0x2665e` | `0x3116f0` | `PRE required stock binding missing…` |
| `0x2666a` | `0x3115a0` | `PRE params are not ready…` |
| `0x24ea9` | `0x3115e8` | `MLSR_Optimized_Constants` (tabla) |
| `0x24ef2` | `0x311620` | `ScratchBuffer` (tabla) |

Más 49 LEAs a la primera tabla (`0x3101e8..0x310410`) repartidas en
`0x19782..0x25232`, con el cluster PRE en `0x24ea9..0x25232`
(ver `test_lea_anchors_point_at_strings`).

## Geometría del dispatch (derivada, no observada en ejecución)

Idéntica a la vieja, byte a byte en intención:

```text
w = *(u32*)(ctx+0x840);  h = *(u32*)(ctx+0x844);
x = (w + 15) >> 4;  x += x & 1;  y = h >> 1;
```

Evidencia 4.1.2 (`llvm-objdump`, VA `0x180…`):

- `0x26094: add $15, %eax` (`83 C0 0F`), `0x26097: shr %edi`
  (`D1 EF`, `y = h>>1`), `0x26099: shr $4, %eax` (`C1 E8 04`).
- `0x2609c: mov %eax, %r15d` (`44 8B F8`),
  `and %r13d, %r15d` (`45 23 FD`), `add %eax, %r15d` (`44 03 F8`).
- `r13d == 1` fijado en `0x25d55: mov $1, %r13d` (`41 BD 01 00 00 00`)
  sin reescritura hasta el grid (verificado por grep de `r13` en
  `0x24e5a..0x26700`). Luego `x += x&1` usa `r13d` como inmediato `1`,
  igual que la vieja `x += x&1`.
- `ctx+0x849==0`, `w==0`, `h==0` → `PRE runtime geometry…`
  vía `0x02d710` (en `0x26062..0x2608e`), igual que la vieja
  (`ctx==0 || ctx+0x849==0 || w==0 || h==0`).

Para `w=1920,h=1080`: `(120,540,1)`. Las cadenas de la DLL lo confirman:
`PRE … baseDispatch=120x540x1` (también `60x270x1`, `30x135x1/2` para
otros passes, 13 ocurrencias de `baseDispatch`, igual que la vieja).

## Modos (equivalente a `FUN_18001c9c0`)

Modo = retorno de la función en RVA `0x2bed0`
(pdata `[0x2bed0,0x2bf61)`, 145 B — mismo tamaño que la vieja
`FUN_18001c9c0` en `[0x1c9c0,0x1ca51)`, 145 B; reubicada).

- Sitio de llamada: `0x25a3e: E8 8D 64 00 00` → `0x2bed0`,
  resultado en `0x68(%rsp)`, luego `0x25e7e: mov 0x68(%rsp), %esi`.
- `0x25e82: cmp $2, %esi; je 0x2662e` y
  `0x26055: cmp $3, %esi; je 0x2662e` → `2,3 → return 1`
  (`0x2662e: mov $1, %al; jmp …`), sin dispatch.
- `0x260a5: cmp $4, %esi; … mov %r13d,%r15d; mov %r13d,%edi`
  → `4 → (1,1,1)` (r13d=1).
- `0x260b2: cmp $5, %esi; … mov %r13d,%edi` → `5 → (x,1,1)`.
- `0x260bc: cmp $6, %esi; mov $0x44,%eax; cmove %eax,%edi`
  → `6 → (x,0x44,1)`.
- Defecto → `Dispatch(x,y,1)` en `0x26394` y `0x263c9`
  (`FF 50 70` = `call *0x70(%rax)`), con `b0=0` vía
  `SetComputeRoot32BitConstant` (`FF 90 08 01 00 00` = `*0x108`).

Idéntico a lo documentado en `docs/pre-dispatch-ghidra.md`.

## Tabla de nombres stock: los mismos 10

| nombre | wide count 4.1.2 | wide count vieja | ascii 4.1.2 | ascii vieja |
|---|---|---|---|---|
| `MLSR_Optimized_Constants` | 2 | 2 | 2 | 2 |
| `ScratchBuffer` | 3 | 3 | 51 | 48 |
| `rw_reprojected_color` | 2 | 2 | 0 | 0 |
| `r_history_color` | 2 | 2 | 0 | 0 |
| `r_velocity` | 2 | 2 | 1 | 1 |
| `r_input_color` | 2 | 2 | 1 | 1 |
| `r_recurrent_0` | 2 | 2 | 0 | 0 |
| `r_depth` | 2 | 2 | 0 | 0 |
| `r_input_exposure` | 2 | 2 | 2 | 2 |
| `r_auto_exposure_texture` | 2 | 2 | 2 | 2 |

Primer cluster wide (tabla) en offsets `0x3101e8..0x310410`
(RVAs `0x3115e8..0x311810`); segundo cluster disperso
(`0x31b444..0x31d4a4`); tercer `ScratchBuffer` aislado en
`0x320e32` (RVA `0x322232`). Misma disposición que la vieja
(`0x67a08..0x67c30`, `0x71a44..0x73620`, `0x77082`).
Reglas de selección por tabla `+0x8efc` y sustituciones
`depth/exposure/auto-exposure` preservadas (secuencia
`movslq …; mov %…; cmovne …` en `0x252b7..0x2538c`, igual que la vieja).
Cambio único: 3 ascii extra de `ScratchBuffer` (48→51) por nuevos passes;
el resto idéntico.

## Fail-stops: cadenas exactas y conteos

Todas ASCII, 1 ocurrencia cada una (igual que la vieja):

- `[FSR4 XMX] PRE params are not ready; XMX fail-stop will trigger.`
  (off `0x3101a0`, RVA `0x3115a0`)
- `[FSR4 XMX] PRE required stock binding missing; XMX fail-stop will trigger.`
  (off `0x3102f0`, RVA `0x3116f0`)
- `[FSR4 XMX] PRE constants are incomplete; XMX fail-stop will trigger.`
  (off `0x310340`, RVA `0x311740`)
- `[FSR4 XMX] PRE runtime-flag ABI mismatch; XMX fail-stop will trigger.`
  (off `0x310390`, RVA `0x311790`)
- `[FSR4 XMX] PRE ScratchBuffer layout mismatch; XMX fail-stop will trigger.`
  (off `0x310440`, RVA `0x311840`)
- `PRE runtime geometry is unavailable.`
  (off `0x310490`, RVA `0x311890`, NUL directo; el resto LF+NUL)
- `[FSR4 XMX PARITY] Ring full; capture frame skipped without waiting.`
  (off `0x30f280`, RVA `0x310680`)

Gates verificados en desensamblado:

- params: `0x24e2e/0x24e3e/0x24e4c` (`0xa94/0xa80/0xa88`), igual.
- bindings: `test %eax/%ecx/%ebx/%edx/%r8d/%r9d; je …` en
  `0x25303..0x2532f`, igual.
- constates: `test %rax; je` + `cmp $0x20,(%rcx)` en
  `0x250e9..0x250f5`, igual (`<0x20`).
- ABI: `mov 0x64(%rax),%ecx; and $0xffff0000,%eax; cmp $0x50580000`
  en `0x250fb..0x25109`, igual (`consts+100`, altos `0x5058`).
- ScratchBuffer: `GetDesc` (`*0x50`), `Dimension==1`,
  `Width >= factor²*0x7e9000`, `Width <= 0xffffffff` en
  `0x253b7..0x2544f` (`imul $0x7e9000`), igual.

Anclas pedidas, ya presentes en la vieja (retención, no novedad):

- `[FSR4 XMX 0028ZR] PRE production ABI: one table per SurfaceIndex/sampler; ZB physical heap slots retained.`
  (off `0x30f660`, RVA `0x310a60`, count 1 en ambas; ref en `0x4174b`).
- `[FSR4 XMX] Failed to load PRE CM-SPIRV; XMX fail-stop will trigger.`
  (off `0x30f400`, RVA `0x310800`, count 1 en ambas; refs en
  `0x40f2e/0x41016/0x42786`).

## Helper de copia: no es el mismo

Vieja: `0x180002df0`, 164 B, 1 bloque:
`GetCPUDescriptorHandleForHeapStart(heap en ctx+0x1b40)` + 1 descriptor
vía `CopyDescriptorsSimple` (dispositivo `+0xC0`).

4.1.2 en el PRE:

- `0x18000bbd0`, 198 B (`[0xbbd0,0xbc96)`): traductor de índices
  (`movslq (%rdx),%r14; shl $6; add 0x4920…; shl $5…; …; call 0x274a0…`),
  llamado ~9 veces con `r8d = 2/4` y `rdx = 0x48/0x58/0x74/0x78/0x7c(%rsp)…`
  (en `0x25632..0x256ee`), más llamadas posteriores para `0x44/0x70`.
  No usa `ctx+0x1b40`.
- `0x180027bc0`, 57 B (`[0x27bc0,0x27bf9)`): barrera
  (`call *0xD0(%rax)` + `movl $0,0x4910(%rbx)`), llamado antes de las
  copias (en `0x256fe`, `0x26340`…).
- `ctx+0x1b40` solo aparece 1 vez en toda la DLL (en `0x2a71e`,
  dispatcher `0x2a670` con offsets `0x100/0xa00/0x1200/0x1a00/0x1a40/0x1b40`),
  fuera del PRE. El heap del PRE ahora sale de
  `0x38f0/0xa78/0x4920/0x4910/0x3910…` (ver `0x25d…/0x25e…`).

Conclusión: helper reescrito y desdoblado (barrera + traductor);
firma y heap distintos. No reutilizar el de 164 B.

## Vtables verificados contra headers LLVM-MinGW fijados

Headers fijados (hashes iguales a los viejos):

- `d3d12.h` SHA-256 `23935395…0dd85e`, `dxgiformat.h` `8a4e770d…461c48`.
- `static_assert` de compilación (clang del toolchain) en el test:
  `CreateSRV==0x90`, `CreateUAV==0x98`, `CopyDescriptorsSimple==0xC0`,
  `GetCPUDescriptorHandleForHeapStart==0x48`,
  `GetGPUDescriptorHandleForHeapStart==0x50`, `GetDesc==0x50`,
  `Dispatch==0x70`, `ResourceBarrier==0xD0`, `SetDescriptorHeaps==0xE0`,
  `SetPipelineState==0xC8`, `SetComputeRootDescriptorTable==0xF8`,
  `SetComputeRoot32BitConstant==0x108`, más `R8_UINT==0x3e`,
  `BUFFER==1`, `0x1688`, offsets de `D3D12_*_DESC`.

Opcodes crudos en el rango PRE `0x24e00..0x2666a` (conteos fijados):

| patrón | slot | count 4.1.2 | count vieja |
|---|---|---|---|
| `FF 50 48` | heap `+0x48` | 2 | 2 |
| `FF 50 50` | recurso `+0x50` GetDesc | 4 | 4 |
| `FF 50 58` | heap GPU `+0x58` | 1 | 1 |
| `FF 50 70` | command-list `+0x70` Dispatch | 2 | 2 |
| `FF 50 78` | `+0x78` | 9 | 8 |
| `FF 90 90 00 00 00` | dispositivo `+0x90` CreateSRV | 2 | 2 |
| `FF 90 C0 00 00 00` | dispositivo `+0xC0` CopyDescriptorsSimple | 1 | 1 |
| `FF 90 C8 00 00 00` | `+0xC8` SetPipelineState | 1 | 1 |
| `FF 90 D0 00 00 00` | `+0xD0` ResourceBarrier | 12 | 12 |
| `FF 90 E0 00 00 00` | `+0xE0` SetDescriptorHeaps | 1 | 1 |
| `FF 90 E8 00 00 00` | `+0xE8` | 1 | 1 |
| `FF 90 F8 00 00 00` | `+0xF8` SetComputeRootDescriptorTable | 3 | 3 |
| `FF 90 08 01 00 00` | `+0x108` SetComputeRoot32BitConstant | 1 | 1 |
| `FF 90 A8 01 00 00` | `+0x1A8` | 7 | 7 |

`CreateUAV (+0x98)` no aparece como `FF 90 98…` sino cargado en `r10`
(`mov 0x98(%rdx),%r10; call *%r10` en `0x25d04` y `0x25ddd`), igual que
la vieja (`0x171f3`). `GetDesc`, `SetComputeRoot32BitConstant(0,0,0)`
→ `b0=0`, `NumElements=0x840/0x80`, `ComponentMapping=0x1688`,
`Format=0x3e (R8_UINT)`, estados `0x40/0x400/0x800` preservados.

Diferencia única: un `*0x78` extra en `0x255b4` (9 vs 8). Resto idéntico.

## Qué cambió vs la vieja (resumen)

1. Tamaño y layout: 25,7→45,5 MB; `.text` `0x52aff→0x7762f`;
   PRE `0x163c0 (6.062 B, 1 pdata)` → `0x24e00 (6.250 B, 3 pdata)`.
2. Entrada y llamante reubicados: `0x163c0←0x58be (FUN_52e0)`
   → `0x24e00←0x8e3a ([0x8a1c,0x99b7))`; modo `0x1c9c0 (145 B)`
   → `0x2bed0 (145 B)`, mismo tamaño, misma semántica 2..6.
3. Grid y modos idénticos (incluido truco `r13d=1` en `0x25d55`,
   `(x+15)>>4`, `x+=x&1`, `y=h>>1`, `(1,1,1)/(x,1,1)/(x,0x44,1)`).
4. Stock: mismos 10 nombres, mismas multiplicidades wide
   (`ScratchBuffer` 3, resto 2); ascii idénticos salvo
   `ScratchBuffer` 48→51.
5. Fail-stops: mismas 7 cadenas, count 1, mismos gates
   (params/bindings/`<0x20`/ABI `0x5058`/ScratchBuffer/geometría/paridad).
6. Anclas `0028ZR` y `Failed to load PRE CM-SPIRV` ya existían
   (count 1 en ambas); retención, no novedad.
7. Helper: 164 B `0x2df0 (ctx+0x1b40)` → `0xbbd0 (198 B)` +
   `0x27bc0 (57 B)`, heap por `0x38f0/0xa78/0x4920`, firma distinta.
8. Vtables: mismos slots y conteos, salvo `+0x78` 8→9.

## Límites

- Estático y derivado; 51 llamadas indirectas y tablas runtime
  (`+0x8efc`, `0x9608/0x9400`, `0x2a30/0x2ab8…`) siguen sin resolver
  valores. Los slots identifican el método, no prueban el driver.
- Sin Ghidra/REA (proveedor no disponible); sin traza de valores,
  contenido inicial, local size/máscara ni oracle de salida.
  No autoriza dispatch PRE.
