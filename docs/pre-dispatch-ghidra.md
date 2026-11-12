# PRE: dispatch y procedencia reconstruidos con Ghidra 12.2

Solo análisis estático de la DLL fijada
`3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53`.
Sin ejecutar la DLL. El desensamblado es representación de Ghidra, no fuente
original; los nombres `FUN_*` son sintetizados (PDB referenciado pero no
disponible). Ideas verificadas por segunda vía se marcan como tales.

Función: `FUN_1800163c0`, rango `0x1800163c0..0x180017b6d` (6.062 bytes,
213 bloques, 1.407 instrucciones). Firma decompilada:
`(contexto, tabla_registro, command_list)`. Único llamante:
`FUN_1800052e0` (sitio `0x1800058be` dentro de su rango), coherente con el xref
del dump llvm-objdump.

## Fail-stops (cadenas ANSI, 1 ocurrencia cada una en el binario)

| Condición | Cadena |
|---|---|
| `ctx+0xa94==0 \|\| ctx+0xa80==0 \|\| ctx+0xa88==0` | `[FSR4 XMX] PRE params are not ready; XMX fail-stop will trigger.` |
| algún binding stock falta | `[FSR4 XMX] PRE required stock binding missing; XMX fail-stop will trigger.` |
| constantes nulas o tamaño `< 0x20` | `[FSR4 XMX] PRE constants are incomplete; XMX fail-stop will trigger.` |
| 16 bits altos de flags (`consts+100`) `!= 0x5058` | `[FSR4 XMX] PRE runtime-flag ABI mismatch; XMX fail-stop will trigger.` |
| `GetDesc.Dimension != 1` o `Width < factor²·0x7e9000` o `Width > 0xffffffff` | `[FSR4 XMX] PRE ScratchBuffer layout mismatch; XMX fail-stop will trigger.` |
| `ctx==0 \|\| ctx+0x849==0 \|\| w==0 \|\| h==0` | `PRE runtime geometry is unavailable.` (vía `FUN_18001dbf0`) |
| anillo de paridad lleno | `[FSR4 XMX PARITY] Ring full; capture frame skipped without waiting.` |

## Procedencia de las imágenes: bindings stock por nombre ancho

Los 7 índices fuente de `t0..t6` NO están en la DLL: se buscan por nombre
UTF-16LE en tablas que entrega el llamador (`param_2`), y se traducen por la
tabla `+0x8efc` a índices de recurso. Nombres fijados (2 ocurrencias UTF-16LE
cada uno: referencia + datos):

`MLSR_Optimized_Constants`, `ScratchBuffer`, `rw_reprojected_color`,
`r_history_color`, `r_velocity`, `r_input_color`, `r_recurrent_0`,
`r_depth`, `r_input_exposure`, `r_auto_exposure_texture`.

Reglas observadas: sin `r_depth` y con bit0 de flags, retorno 0. Con
`flags&0x18==0`, exige `r_input_exposure` (si bit2 limpio) o
`r_auto_exposure_texture` (si bit2 set). `depth/exposure/auto-exposure`
sustituyen fuentes por defecto. El orden exacto slot←nombre depende de esos
índices runtime: mecanismo establecido, tabla fija pendiente de traza de
valores. Esto delimita el "dato externo que falta": son estas tablas del host,
no un secreto dentro de la DLL.

## Geometría del Dispatch (derivada, no observada en ejecución)

```text
w = *(u32*)(ctx+0x840);  h = *(u32*)(ctx+0x844);
x = (w + 15) >> 4;  x += x & 1;  y = h >> 1;
modo = FUN_18001c9c0();
2,3 → return 1 (sin dispatch PRE); 4 → (1,1,1); 5 → (x,1,1); 6 → (x,0x44,1);
defecto → Dispatch(x, y, 1)  [slot command-list +0x70]
```

Para `w=1920, h=1080`: `(120, 540, 1)`, consistente con los guards del IR
(`WorkgroupId.x < 120`, `.y < 540`). Los valores `w/h` son runtime del
contexto; la fórmula es estática. El tamaño local CM y la máscara efectiva
siguen siendo gates separados.

## Llamadas verificadas contra `d3d12.h` (clang, headers LLVM-MinGW)

`ID3D12GraphicsCommandList`: `Dispatch=0x70`, `ResourceBarrier=0xd0`,
`SetDescriptorHeaps=0xe0`, `SetPipelineState=0xc8`,
`SetComputeRootDescriptorTable=0xf8`, `SetComputeRoot32BitConstant=0x108`;
heap `GetCPUDescriptorHandleForHeapStart=0x48`,
`GetGPUDescriptorHandleForHeapStart=0x50`. Dispositivo: `CreateSRV=0x90`,
`CreateUAV=0x98`, `CopyDescriptorsSimple=0xc0`; recurso `GetDesc=0x50`.

Observado y encajando: `SetComputeRoot32BitConstant(0, 0, 0)` → **b0=0**;
11 raíces `1..11` desde `DAT_180068988` (RVA `0x68988`) y raíz 12 sampler vía
handle GPU; barreras con estados `0x40/0x400/0x800`
(`NON_PIXEL_SHADER_RESOURCE`/`COPY_DEST`/`COPY_SOURCE`) alrededor de copias;
UAV arg0 con `NumElements=Width` tras `GetDesc`.

## Helper `FUN_180002df0` (0x180002df0, 164 bytes, 1 bloque)

```c
GetCPUDescriptorHandleForHeapStart(*(heap en ctx+0x1b40), &h);
h += incremento_origen * indice_origen;
CopyDescriptorsSimple(dispositivo, 1, base_destino + incremento_destino * slot_destino);
```

Confirma: heap origen en `ctx+0x1b40`, copia de 1 descriptor. Segundo
llamante: `FUN_180015920` (otra ruta de dispatch, fuera del PRE normal).

## Límites

Decompilador-derivado; 51 llamadas indirectas sin destino y 3 sitios de call
computado quedan desconocidos. Los slots de vtable identifican el método, no
prueban el comportamiento runtime del driver. No autoriza dispatch PRE: faltan
contenido inicial, local size/máscara y oracle de salida.
