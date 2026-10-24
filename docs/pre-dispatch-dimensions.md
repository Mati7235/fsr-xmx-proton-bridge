# PRE native_1080: dimensiones locales y gate de máscara

## Resultado

El análisis estático **no determina el tamaño local requerido** de
`fsr4_pre_xmx`. Para preparar un launcher PRE, el local size/runtime dispatch
sigue siendo un gate: no sustituirlo por `1×1×1`, por `SubgroupSize 1`, ni por
el selector Vulkan de workgroup usado para escoger un kernel.

La herramienta reproducible es:

```sh
python tools/inspect_pre_dispatch.py \
  analysis/offline-pre/full/ze_info.yaml \
  analysis/pre-payload/disasm/.text.fsr4_pre_xmx.asm \
  analysis/offline-pre/full/pre_bmg.bin \
  --spirv-assembly analysis/fsr-resources/xe2-first.spvasm
python -m unittest discover -s tests -p test_pre_dispatch.py -v
```

El inspector solo acepta los tres artefactos completos fijados por SHA-256; falla
con archivos truncados o modificados. `.ze_info` SHA-256:
`5546d5172c3094110fe25fd34922bcf1d4842fb1b0e97b9a42afc32c2ffe8f7c`;
zebin SHA-256: `3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2`;
desensamblado IGA SHA-256:
`a9c82bbfccc535959e73ddd6b80fb209ed8a12bf8607927f62078b43b6215660`.
El origen, compilador/target y hashes de input constan en
[`offline-pre-compilation.md`](offline-pre-compilation.md) y
[`pre-payload-audit.md`](pre-payload-audit.md).

Con `--spirv-assembly`, el inspector también fija el hash del IR textual
`7ed1d81b8127e9dbb1e0c5befa621060cf7ab47cd82f98f789099b7968db6a9e`.
Solo aparece `BuiltIn WorkgroupId` en las declaraciones (`:120`), cargado en
`:5166,5172`; los modos del entry no incluyen `LocalSize`. No aparecen builtins
de invocación local declarados. Esto no demuestra que el payload por thread del
binario nativo esté sin uso ni establece por sí solo un tamaño local válido.

## No confundir las magnitudes

| Magnitud | Evidencia fijada | Conclusión permitida |
|---|---|---|
| Tamaño local requerido del workgroup (X,Y,Z) | `.ze_info` completo del kernel, comprobado para los nombres de atributo locales conocidos por el inspector; IR/SPIR-V revisado | No se encontró atributo de tamaño local requerido en los datos revisados; no queda establecido. El inspector usa un lector restringido, no un parser YAML general, y la ausencia no prueba lo que una ruta runtime específica eligió. |
| SIMD size del compilador | `ze_info.yaml`, `execution_env.simd_size: 1` | El campo de metadata vale 1. No es una dimensión local ni el número total de lanes del workgroup Vulkan. |
| Lanes/anchos de instrucciones nativas | Desensamblado IGA fijado; contiene operaciones con texto `simd16` | Confirma operaciones SIMD16 representadas por ese disassembler; no fija workgroup size ni contradice por sí solo `simd_size: 1` del entorno CM. |
| Hardware threadcount / dispatch SIMD del driver | No hay atributo equivalente fijado en `.ze_info` ni evidencia de dispatch PRE observado | Desconocido para el lanzamiento real. La política SIMD32 del driver mencionada por la auditoría no demuestra por sí sola el threadcount ni la máscara del runtime PRE; la compilación local de Mesa y los probes sintéticos tampoco lo establecen. |
| Selector Vulkan de workgroup/kernel | Placeholder de selección generado por el packer | Un selector `1,1,1` no es contrato del shader ni geometría de dispatch. No usarlo como local size. |
| Workgroupcount (grid) | Guardas de `WorkgroupId.x >= 120` y `y >= 540` en IR fijado (SHA-256 `7ed1d81b8127e9dbb1e0c5befa621060cf7ab47cd82f98f789099b7968db6a9e`; véase `pre-controlled-test-contract.md`) | `120×540×1` cubre el rectángulo permitido por esas guardas; es solo candidato mínimo derivado de límites. No prueba el grid que despacha la DLL/host ni cobertura por píxel. |

En particular, el `packed_local_ids` de seis bytes en offset 0 de payload por
thread, `simd_size: 1`, las anchuras de instrucciones IGA y la cantidad de
threads físicos son conceptos distintos. No hay conversión demostrada entre
ellos que permita obtener las dimensiones locales.

## Configuración estática que construiría el driver local

Hay una configuración del driver que sí se puede derivar, sin confundirla con
un requisito del PRE. En `build/mesa-26.1.2/src/intel/vulkan/anv_shader_compile.c`
`:1725-1734`, el lector CMK transforma `lws` en
`cs->local_size = (32*lws.x, lws.y, lws.z)` y fija `prog_mask = 1 << 2`.
Para un paquete con `lws=(1,1,1)`, la representación interna es `(32,1,1)`.

`src/intel/compiler/brw/brw_shader.cpp:993-1027` calcula SIMD32, group size 32,
un thread y `right_mask=0xffffffff` para esos valores sin override. La ruta
de compute usa `brw_cs_get_dispatch_info(..., NULL)`; el `COMPUTE_WALKER` Xe2
recibe `ExecutionMask = dispatch.right_mask` en
`src/intel/vulkan/genX_cmd_compute.c:638-647`. La máscara inferior del antiguo
`GPGPU_WALKER` no es la evidencia pertinente para Xe2.

Esta es una derivación del código local y una configuración **condicional** al
paquete y ruta indicados. No prueba que `lws=1` sea el contrato correcto del PRE,
que el binario del driver en otro entorno sea el mismo, ni que la máscara efectiva
permanezca completa durante toda la ejecución del kernel. El inspector de
artefactos no verifica esas fuentes de Mesa ni observa registros de hardware.

## Gate de máscara del payload

`pre-payload-audit.md` y `analysis/pre-payload/report.json` muestran que los
cuatro campos extra del payload no se leen antes de sobrescritura/fin **bajo la
suposición** de máscara de ejecución completa y constante. Esta es una certeza
condicionada del análisis estático del zebin fijado, no una prueba de la máscara
que usará el dispatch real. El informe conserva el supuesto explícito; este
inspector no reaudita instrucciones ni lo eleva a hecho runtime.

Gate pendiente: establecer local size, threadcount/modo de dispatch y máscara
efectiva de la ruta PRE real con evidencia del driver/launcher y confirmar que
la ejecución satisface el supuesto de la auditoría. Hasta entonces, la máscara
requerida no está validada y no se autoriza rellenar campos ni despachar PRE
basándose en este análisis. El estado del perfil sigue
`experimental-offline-only` / `runtime_approved=false`.

## Límites y siguiente evidencia útil

Este trabajo no ejecutó GPU, DLL, Wine ni herramientas de instalación. Los
guards del shader determinan límites de WorkgroupId, no tamaño local, dimensiones
de imagen, grid observado ni resultado funcional. Para resolver el gate del
launcher se necesita registrar/capturar por una ruta autorizada el local size y
workgroupcount efectivos, la política SIMD/thread dispatch y evidencia que
valide la máscara completa y constante; comprobar además el readback PRE contra
un oracle, tal como exige el [contrato controlado](pre-controlled-test-contract.md).

Los tests son de CPU. Comprueban fijación de hashes, rechazo de truncamiento y
que la salida preserve como desconocidas las geometrías/máscara no demostradas;
no validan ejecución ni semántica general de zebin/IGA.
