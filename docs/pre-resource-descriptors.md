# PRE native_1080: reconstrucción estática de recursos

## Resultado

Análisis de la DLL fijada `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53`
y del PRE Xe2 `40102/native_1080`. Es estático: no se ejecutó la DLL, no hubo
captura nueva ni dispatch PRE. La prueba sintética de imagen/sampler reportada por
el usuario (64 valores correctos y 1.984 words centinela intactos) solo valida ese
probe; no proporciona descriptores ni datos de los recursos PRE.

**Conclusión acotada:** la ruta normal sí materializa vistas D3D12 para buffers
PRE y copia descriptores de imágenes. Los headers locales LLVM-MinGW fijados
permiten identificar los métodos COM y los layouts usados. Aun así, los formatos
y dimensiones de las imágenes fuente, el tamaño real de los backing resources y
los bytes iniciales no se deducen de estas vistas. La DLL contiene operaciones
D3D12 indirectas; la ausencia de imports directos no implicaba que no creara
vistas o copiara descriptores.

## Mapa exacto que sí se recupera

La ruta normal del dispatch es `0x1800163c0..0x180017b6e` (`dil == 0`); carga el
array RVA `0x68988` y enlaza roots 1–11 en `0x180017410..0x180017435`, y root 12
con el heap de sampler en `0x180017543`. El mapa de argumentos/BTIs se contrastó
con `analysis/offline-pre/full/ze_info.yaml` y el SPIR-V fijado:

| Recurso PRE | Arg | Root/register | Heap/slot relativo | Clase de descriptor en la firma | Formato/tamaño recuperado |
|---|---:|---|---|---|---|
| buffer mixto | 0 | 1 / u0 | recursos / 7 | UAV `BUFFER`, `R8_UINT`, `FirstElement=0`; `NumElements=resource.Width` | `GetDesc` exige `Dimension=BUFFER (1)` y `Width <= 0xffffffff`; el mínimo depende de un factor de la tabla de variante. Para native_1080, factor 1: `Width >= 8.294.400 bytes`. Width exacto es runtime. |
| imagen destino | 1 | 2 / u1 | recursos / 8 | Image2D ReadWrite | Se copia un descriptor de imagen a slot 8 mediante `CopyDescriptorsSimple`; source descriptor y formato no se recuperan en esta secuencia. |
| imagen t0 | 2 | 3 / t0 | recursos / 0 | Image2D ReadOnly | Descriptor fuente copiado por helper `0x180002df0`, source index recibido en el caller; formato/dimensiones de origen pendientes. |
| imagen t1 | 3 | 4 / t1 | recursos / 1 | Image2D ReadOnly | Descriptor fuente copiado por helper `0x180002df0`, source index recibido en el caller; formato/dimensiones de origen pendientes. |
| imagen t2 | 4 | 5 / t2 | recursos / 2 | Image2D ReadOnly | Descriptor fuente copiado por helper `0x180002df0`, source index recibido en el caller; formato/dimensiones de origen pendientes. |
| imagen t3 | 5 | 6 / t3 | recursos / 3 | Image2D ReadOnly | Descriptor fuente copiado por helper `0x180002df0`, source index recibido en el caller; formato/dimensiones de origen pendientes. |
| imagen t4 | 6 | 7 / t4 | recursos / 4 | Image2D ReadOnly | Descriptor fuente copiado por helper `0x180002df0`, source index recibido en el caller; formato/dimensiones de origen pendientes. |
| imagen t5 | 7 | 8 / t5 | recursos / 5 | Image2D ReadOnly | Descriptor fuente copiado por helper `0x180002df0`, source index recibido en el caller; formato/dimensiones de origen pendientes. |
| imagen t6 | 8 | 9 / t6 | recursos / 6 | Image2D ReadOnly | Descriptor fuente copiado por helper `0x180002df0`, source index recibido en el caller; formato/dimensiones de origen pendientes. |
| buffer | 9 | 10 / t7 | recursos / 9 | SRV `BUFFER`, `R8_UINT`, first element 0, 2.112 elementos / bytes | Recurso procede de contexto `+0xa80`; la vista cubre 2.112 B. Asignación backing y contenido inicial no deducidos. |
| buffer header | 10 | 11 / t8 | recursos / 10 | SRV `BUFFER`, `R8_UINT`, first element 0, 128 elementos / bytes | Recurso procede de contexto `+0xa98`; vista/header de 128 B. Asignación backing y bytes del header son runtime. |
| sampler | 11 | 12 / s0 | heap sampler / 0 | sampler | MIN/MAG/MIP linear; CLAMP U/V/W; bias 0, max anisotropy 1, comparison ALWAYS, MinLOD 0, MaxLOD FLT_MAX. |

Los números de slots son relativos al heap/tabla que usa la ruta normal, no
índices absolutos. `t7` y `t8` son SRV por la root signature aunque sus tipos CM
sean ReadWrite. La imagen destino es arg 1/u1/BTI 9, no arg 8/t6; el `7` de la
máscara `0,0,7` del store typed-quad habilita canales `.xyz`, no es un binding.

## Datos de buffers demostrables

### Arg 0 / u0

El PRE genera un write de 128 bytes por grupo, en unidades OWORD, con índice
`wg_y * 960 + wg_x * 8` (SPIR-V `:15977-15993`). Con el dominio aceptado por los
guards, `wg_x < 120`, `wg_y < 540`, el extremo exclusivo del último write es:

```text
((539 * 960) + (119 * 8) + 8) OWORD * 16 bytes/OWORD
= 518400 * 16
= 8,294,400 bytes
```

El store final tiene esa cobertura si se despacha grid completa 120×540 y los
grupos pasan su guard. Además, la DLL hace `ID3D12Resource::GetDesc` del buffer
seleccionado como arg 0 y compara `Dimension` con `edx=1`, es decir
`D3D12_RESOURCE_DIMENSION_BUFFER`. **El factor en `eax` es otro valor:** se
carga del campo `+0x24` de `tabla[selector - 1]`, con stride `0x4f0` y selector
en el DWORD `contexto+0x830`, o vale 1
por defecto (`0x180016984..0x1800169df`). No confundir los dos registros.
Después comprueba `Width >= factor² * 0x7e9000` y
`Width <= 0xffffffff` (`0x180016973..0x180016a0e`; el `GetDesc` indirecto está en
`+0x50`). La extracción directa de la tabla fijada identifica `native_1080`
como selector 1, con factor 1, por lo que su límite inferior es **8.294.400 B**.
Las variantes 2160/4320 tienen factores 2/4, no otras dimensiones de recurso.
Luego usa `Width` como `NumElements` de un UAV
`R8_UINT` en heap slot 7 (`0x180017184..0x1800171ff`). Esto sí demuestra una
restricción de capacidad del recurso en esta ruta, pero no su Width exacto de
runtime; no implica RGBA8. Arg 0 también tiene lecturas y scratch seleccionados
por arg 10. No inicializarlo como readback vacío.

### Arg 10 / t8

El shader carga 128 bytes desde arg 10 como header. Los campos usados incluyen
DWORDs en offsets 8–84, campos de dirección/bytes en 64–80, flags en byte 100 y
base en byte 104 (SPIR-V `:5190-5325`, `:5573-5602`). Bit `0x400` de flags es
guard; bit `0x2000` decide entre `base` y `base+16` para la lectura float4. Un
float4 de 16 bytes se lee desde arg 0 usando como byte offset `base` o
`base+16` (`:5573-5614`, particularmente el `oword.ld.unaligned` en
`:5606-5612`). Por tanto, en este camino del IR, `base` **no se consume como VA**:
es desplazamiento relativo al buffer arg 0, condicionado por el flag `0x2000`.
Esto identifica una relación entre recursos, no la longitud/alineación asignada
de arg 0 ni la validez de los datos que el host coloque allí. Los otros offsets
del header tampoco deben recibir nombres semánticos sin ABI del caller.

### Arg 9 / t7 y arg 10 / t8

`ID3D12Device::CreateShaderResourceView` se llama con recurso desde estado
`+0xa80` para slot 9 y `+0xa98` para slot 10 (`0x1800172e1..0x180017367`). Ambas
descripciones son `Format=0x3e` (`DXGI_FORMAT_R8_UINT`),
`ViewDimension=1` (`D3D12_SRV_DIMENSION_BUFFER`),
`Shader4ComponentMapping=0x1688` (`D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING`),
`FirstElement=0`, `StructureByteStride=0`, `Flags=0`. `NumElements` es 0x840
(2.112 bytes) para arg 9 y 0x80 (128 bytes) para arg 10. El primer elemento es
typed, no `RAW` (los flags son cero). Los SRV limitan el rango visible, pero no
informan el Width de cada backing resource ni su contenido inicial. Arg 10
contiene al menos los 128 bytes que el kernel carga; los DWORDs de ese header son
entradas del caller, no valores inicializados por este descriptor.

## Caller graph: APIs, handle tables y creación de vistas

El dump fijado (`analysis/fsr-xmx-disassembly.txt`, SHA-256
`4007779c416772def4eecdd20acefb5d52deb6c8d0f0f895473761653f4e66b0`) da un
call-xref directo a `0x1800163c0`: `0x1800058be` dentro de la ruta de contexto en
`0x1800058a1..0x1800058e6`. Esa función es un wrapper interno, no una frontera
exportada. El límite público FFX incluye `ffxCreateContext` (`0x180001290`),
`ffxDispatch` (`0x1800013b0`) y `ffxQuery` (`0x180001400`); el wrapper llama al
setup/dispatch PRE con `rcx=estado`, `rdx=registro` y `r8=interfaz D3D12`
(convención x64). Los descriptores de imagen fuente se leen/copian desde el heap
de origen del contexto; este bloque de copia no muestra quién creó esas imágenes.

La atribución de vtable se contrasta con `ID3D12Device`/`ID3D12DescriptorHeap`
de los headers locales fijados (SHA más abajo): `+0x48` en descriptor heap es
`GetCPUDescriptorHandleForHeapStart`; `+0x90`, `+0x98` y `+0xc0` en device son
`CreateShaderResourceView`, `CreateUnorderedAccessView` y
`CopyDescriptorsSimple`. El `0x3e` que se escribe en `0x1800171c2`/`0x1800172fd`
es el campo `Format` D3D12, no un tipo de callback ni una solicitud FFX.

- El buffer arg 0 recibe un UAV `R8_UINT` tipo `BUFFER`, `FirstElement=0`,
  `NumElements=resource.Width`, stride/counter/flags cero, en el heap slot 7.
  La ruta llama `GetDesc`, exige dimensión BUFFER y aplica el límite de capacidad
  dependiente del factor de variante documentado arriba.
- Arg 9 / t7: `CreateShaderResourceView` con recurso `[context+0xa80]`, SRV
  `R8_UINT BUFFER`, `NumElements=0x840`, destinado a heap slot 9.
- Arg 10 / t8: análogo con `[context+0xa98]`, `NumElements=0x80`, slot 10.
- Args 2–8 / t0–t6: en `0x18001711b..0x18001717f` se invoca siete veces al
  helper `0x180002df0`, con destino 0..6 y source indices seleccionados en
  `r8d`: slot0 toma `[rsp+0x78]`, slot1 `[rsp+0x7c]`, slot2 `esi`, slot3
  `[rbp-0x80]`, slot4 `[rbp-0x7c]`, slot5 `edi` y slot6 `ebx`. Esos valores
  se seleccionan en el dispatch desde el registro de recursos (`r13`), no son
  constantes de formato. El helper obtiene el
  CPU-handle inicial del heap de origen en `[context+0x1b40]`, suma
  `sourceIndex * descriptorIncrement` y llama `ID3D12Device::CopyDescriptorsSimple`
  (`+0xc0`) para copiarlo al heap PRE interno. Así se establece procedencia por
  descriptor, no el formato o las dimensiones de la textura fuente.
- Arg 1 / u1, heap slot 8: la rama normal llama también a
  `CopyDescriptorsSimple` (`0x18001727e`) con índice de destino 8; el origen es
  otro descriptor de imagen. La fuente no se materializa como `D3D12_*_VIEW_DESC`
  en este bloque, por lo que el formato de la imagen no se deriva aquí.

El loop `0x180017410..0x180017435` enlaza las 11 tablas; root 12 enlaza sampler.
El único call-xref directo a `0x1800163c0` sigue siendo `0x1800058be`. La DLL
selecciona recursos guardados en contexto y crea/copia sus vistas, pero no se
recupera de este dump quién creó los recursos origen ni los bytes iniciales de
imágenes/buffers. La reconstrucción no ha completado la cadena desde la entrada
pública hasta cada creador/handle; no demuestra que esa cadena esté ausente de
la DLL. Un registro de los valores efectivos del dispatch requeriría captura.

El extractor `tools/reconstruct_pre_resources.py` fija hashes de DLL, dump y
headers, recupera los SRV/UAV, la relación contexto/heap slots y ventanas de las
copias de descriptores, sin cargar la DLL:

```bash
python tools/reconstruct_pre_resources.py \
  artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll \
  analysis/fsr-xmx-disassembly.txt
python -m unittest discover -s tests -p test_pre_resources.py -v
```

Los tests opcionales con artefactos locales contrastan la tabla de las 18
variantes y compilan assertions contra los headers Windows reales: offsets de
vtables y estructuras, `R8_UINT=62`, `BUFFER=1` y component mapping `0x1688`.
Es compilación sintáctica, no ejecución de una DLL. El reporte local completo
se conserva en `analysis/pre-resource-descriptors.json`.

## Qué bloquea dimensiones y formatos de imagen

El IR fija imágenes 2D y el guard de grid `120×540×1`; no fija ancho/alto de las
imágenes, DXGI/Vulkan format, número de canales físicos, mip/layer, sample count,
permisos concretos del descriptor ni bytes asignados. `native_1080` es selector
de variante del kernel, no una descripción D3D12 de cada recurso. Las
operaciones sample/load del IR demuestran uso, no la descripción elegida por el
host. El descriptor dinámico que apunta al recurso no aparece materializado en
la root signature ni en la tabla constante de slots.

La investigación estática de la DLL localiza la creación de la root signature
en `0x18002c13f..0x18002c4bd`, sampler en `0x18002cc23..0x18002cc8b`, y el
dispatch normal arriba indicado. La inspección de imports PE (`llvm-objdump -p`)
no encuentra imports directos de `CreateCommittedResource`,
`CreateShaderResourceView` ni `CreateUnorderedAccessView`. Eso solo describe la
tabla de imports. El dump sí muestra llamadas directas mediante vtables D3D12
para crear vistas y copiar descriptores. No resuelve una llamada de asignación
`CreateCommittedResource` ni descarta otros caminos de creación. «No localicé un
import» no equivale a «la DLL no asigna recursos».

## Oracle requerido y captura mínima

Queda pendiente seguir los índices de origen hasta las rutinas que crean y
llenan cada vista/recurso; no se ha demostrado que sea imposible resolverlo
estáticamente. Una alternativa es una traza autorizada del host en el mismo
camino `native_1080`, antes del primer dispatch PRE. Debe registrar, correlacionado por
ID de recurso/descriptor:

1. `CreateCommittedResource` / placed/reserved resource o importación, con
   `D3D12_RESOURCE_DESC` completo (dimension, width, height, depth/array, mip,
   format, sample count, layout, flags), heap properties y tamaño/offset de
   asignación cuando aplique.
2. Cada `CreateShaderResourceView`/`CreateUnorderedAccessView` y
   `CopyDescriptors*`: resource asociado, `D3D12_*_VIEW_DESC`, formato,
   mip/layer/rango, slot final y heap. También seguir aliases/copies, no solo
   direcciones de handles.
3. `GetDesc`/identidad de los recursos enlazados a heapslots 0–10 justo antes
   del dispatch; valores/bytes de entrada de buffers args 0/9/10. Para arg 10,
    conservar el header de 128 bytes y los bytes de arg 0 referenciados por el
    offset del byte 104, con límites legibles y flags originales; no tratarlo
    como una dirección virtual.
4. Root-table GPU handles, heap bases/incremento, sampler desc, grid de
   `Dispatch` y estado/transiciones de recursos. El tamaño local CM/hardware
   requiere evidencia separada: no es un argumento de `ID3D12GraphicsCommandList::Dispatch`.
   Volcar datos pre y
   post dispatch sin modificar el estado observado.

Una traza D3D12 instrumentada en un **prefijo desechable** o documentación
verificable del llamador puede completar las descripciones/identidades que los
descriptores copiados no transportan. Esa traza es evidencia de entrada, no un
oracle de corrección funcional ni prueba de que Proton/VKD3D haya implementado
correctamente PRE. Registrar ejecutable/versiones/hashes, correlacionar IDs y
handles con roots/slots, guardar bytes pre/post y preservar la captura original;
el resultado del probe sintético no es sustituto.

Una vez identificados los recursos origen, se pueden fijar tamaños/layouts y
crear un input reproducible. Aún hará falta comparar salida PRE con una
implementación de referencia independiente (o CPU oracle validado contra ella)
para afirmar corrección funcional; una captura de descriptores, inyección,
no-corrupción de guards o ausencia de errores no lo sustituye.

## Reproducción y evidencia fijada

```bash
sha256sum artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll \
  analysis/fsr-xmx-disassembly.txt
llvm-objdump -p artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll
```

Resultados al redactar: DLL SHA-256 `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53`;
disassembly SHA-256 `4007779c416772def4eecdd20acefb5d52deb6c8d0f0f895473761653f4e66b0`.
Referencias adicionales: `docs/pre-resource-map.md:123-150`,
`docs/pre-controlled-test-contract.md:20-65,88-108`,
`analysis/offline-pre/full/ze_info.yaml:15-160`,
`analysis/fsr-resources/xe2-first.spvasm:5166-5185,5190-5325,5573-5634,15977-15993`,
`analysis/pre-dispatch-snippet.txt:76-89`. Headers contrastados: `artifacts/extracted/llvm-mingw-20261020-ucrt/llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64/generic-w64-mingw32/include/d3d12.h` SHA-256 `23935395fe8939ac0ca71c5b34cd7b21a689ff5e9641846563613f24bc0dd85e` y `dxgiformat.h` SHA-256 `8a4e770d3022aff667b7d4f03f0cf5a068ecde87f357c9791f275954c1461c48`. El SHA del disassembly identifica
el archivo usado para las direcciones, no acredita independientemente la
corrección de su decodificación.
