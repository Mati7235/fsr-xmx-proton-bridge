# Build offline de Mesa 26.1.2 con LLVM 23

## Resultado

El checkout local de Mesa 26.1.2, con el lector CM adaptado del laboratorio y
LLVM 23.1.1, completó la compilación CPU. El log anterior registra los 575 pasos
y `analysis/lab-v0.1/mesa-result-llvm23.txt` contiene `0` (código de salida).
Luego `ninja -C build/mesa-26.1.2/out` terminó nueve objetivos incrementales
restantes, entre ellos `libblorp_elk.a`; no reportó errores. El artefacto ANV
construido es
`build/mesa-26.1.2/out/src/intel/vulkan/libvulkan_intel.so` (27.6 MB).

Esto solo verifica compilación local. No se ejecutó Vulkan/GPU, no se instaló el
driver y no se modificaron Steam, prefijos, servicios ni el entorno de sesión.
No constituye evidencia de inyección ni de readback correcto.

## Parche de compatibilidad LLVM

Se preservó `patches/mesa-26.1.2-llvm23.patch`, que ya estaba sin seguimiento
antes de esta revisión. Es una adaptación de cuatro líneas en
`src/compiler/clc/clc_helpers.cpp`: con LLVM 23 `TargetRegistry::lookupTarget`
recibe `llvm::Triple`; versiones anteriores conservan la llamada con `const
char *`. La fuente local ya contiene exactamente esa adaptación, por lo que el
parche inverso pasó `git -C build/mesa-26.1.2 apply --reverse --check`.
`git apply --check` en sentido normal no aplica sobre una fuente que ya contiene
el cambio; no se revirtió ni se volvió a aplicar.

Meson encontró LLVM 23.1.1 y LLVMSPIRVLib 23.1.0.0. El log muestra cuatro
warnings deprecados de Expat en `intel_decoder.c`; se conservaron. No se
suprimieron errores ni canaries.

## Revisión estática de máscara y dimensiones

La ruta del lector está en
`build/mesa-26.1.2/src/intel/vulkan/anv_shader_compile.c`:

1. Lee `h.lws[3]` del CMK y fija `prog_mask = 1 << 2`, `dispatch_width = 32`.
2. Fija `local_size` como `(32*h.lws[0], h.lws[1], h.lws[2])`.
3. El PRE inspeccionado tiene `simd_size: 1` en `analysis/offline-pre/full/ze_info.yaml`.
   El artefacto legado reproducido por el packer declara `lws 1x1x1`
   (`analysis/offline-pre/full/pack.log`). Para esos valores, el tamaño de grupo
   que Mesa calcula es `(32,1,1)`.

En `src/intel/compiler/brw/brw_shader.cpp`, `brw_cs_get_dispatch_info` toma
`simd_size = 8 << log2(prog_mask) = 32`, calcula
`group_size = local_size[0]*local_size[1]*local_size[2]` y usa máscara completa
cuando el residuo módulo SIMD es cero. Para cualquier `lws` positivo que quepa
en los tipos usados, el local size arriba da `group_size = 32*lws[0]*lws[1]*lws[2]`;
por tanto es múltiplo de 32 y `right_mask` resulta `0xffffffff`. La ruta Xe2
codifica ese valor en `COMPUTE_WALKER.ExecutionMask` en
`src/intel/vulkan/genX_cmd_compute.c`.

En `src/intel/vulkan/genX_shader.c`, la creación del payload reserva
`dispatch.threads` entradas y escribe los local IDs como `t % lx`,
`(t / lx) % ly`, `t / (lx*ly)`. Para el PRE empaquetado como `1x1x1`, la única
entrada lleva ID local `(0,0,0)` y el walker representa un grupo SIMD32.

### Límites de esta conclusión

- Es una deducción del código y de los metadatos/CMK locales; no observación de
  la máscara en hardware ni validación de la ruta de despacho en runtime.
- El lector no valida explícitamente que `lws` sea no-cero, ni todos los casos
  de overflow. La conclusión requiere valores positivos, representables y que
  el packer/probe y el lector interpreten las mismas dimensiones.
- `simd_size: 1` del zebin y `lws 1x1x1` del CMK documentan las entradas actuales;
  no prueban que el probe nuevo las emita correctamente. Su diagnóstico queda
  a cargo del agente que mantiene `tools/build_lab_probe.py`.
- Esto no confirma máscara constante durante ejecución ni releva la auditoría
  del payload de sus condiciones. Tampoco valida sampler, layout VKD3D,
  transferencia de contexto, inyección ni resultado de imagen.

## Reproducción limitada

La compilación original quedó registrada en
`analysis/lab-v0.1/mesa-build-llvm23.log` y su estado en
`analysis/lab-v0.1/mesa-result-llvm23.txt`. Para comprobar si quedan objetivos:

```sh
ninja -C build/mesa-26.1.2/out
```

Es una build local de CPU; no ejecutar el ICD generado como parte de esta
verificación.
