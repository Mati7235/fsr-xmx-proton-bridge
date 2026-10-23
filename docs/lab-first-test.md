# Primera prueba del laboratorio: preflight y límites

Este hito prepara un inventario reproducible, no un launcher. El preflight lee
archivos locales, extrae metadata Meson y calcula SHA-256 de un conjunto acotado
de artefactos. No invoca Mesa, el probe, `vulkaninfo`, Vulkan, el driver ni
herramientas de compilación; no modifica prefijos, Steam, el entorno ni archivos
del sistema.

## Crear el manifiesto

Después de compilar Mesa y generar el probe por separado, ejecutar desde la raíz
del repositorio, cambiando rutas si corresponde:

```sh
python tools/lab_preflight.py \
  --mesa-build build/mesa-26.1.2/out \
  --probe-dir build/lab-probe-v09 \
  --out analysis/lab-preflight.json
```

El JSON se escribe incluso si faltan entradas. Código de salida `2` y estado
`blocked` significan que falta evidencia o que el contrato sintético no coincide;
no se debe saltar el bloqueo. Código `0` solo significa que el inventario
requerido está presente y pasa sus comprobaciones estáticas. El estado
`inventory-complete-review-required` **no** certifica que la build de Mesa sea
correcta ni que el driver se haya cargado. El manifiesto conserva rutas, tamaños
y hashes; no copia ni empaqueta binarios.

Es un **inventario**, no una validación semántica de binarios: el preflight no
desensambla ni interpreta el contenido de Mesa, SPIR-V, CMK o zebin. Comprueba
metadata JSON y algunos valores declarados, exige CMK3 con heap explícito y
compara la identidad del zebin con la auditoría registrada. No vuelve a ejecutar
esa auditoría. Registra hashes para identificar bytes. La búsqueda textual de
`dpas.` en un archivo de desensamblado tampoco
certifica la ejecución o corrección de DPAS.

La compilación local produjo un `.so` de ANV y metadata Meson en
`build/mesa-26.1.2/out`, pero la mera presencia no acredita máscara/dimensiones,
parche correcto o prueba de carga. `build/lab-probe-v09` contiene el probe con
auditoría restringida y heap explícito; ver [evidencia](lab-probe.md). Las salidas
anteriores pueden estar incompletas o usar el heap automático incompatible.
No reutilizar salidas parciales como si fueran un probe terminado.

El probe identificado por `kind` es una **prueba sintética DPAS/mapa de recursos**,
no contiene el kernel FSR. `gpu_validated` debe permanecer `false` hasta una
prueba GPU independiente. Ni compilación, desensamblado DPAS, PSO, `S_OK`, overlay
ni salida de preflight son evidencia de inyección o readback. El manifiesto marca
explícitamente `fsr.complete_kernel_present=false`, `fsr.bridge_ready=false` y
`runtime_test_authorized=false`.

## Antes de cualquier prueba manual aislada

No hay todavía un harness validado en runtime. `lab/bridge_probe.c` compila
localmente y `lab/README.md` describe sus controles e invocación futura. Su
compilación CPU no demuestra inyección ni readback GPU.
**No ejecutar una prueba runtime basándose en este documento o en el manifiesto.**
Hace falta una autorización explícita separada y completar/revisar todos estos
puntos primero:

1. La validación de `docs/lab-mesa-build.md` debe confirmar el parche y build de
   Mesa, la máscara de ejecución y dimensiones locales; registrar revisión,
   opciones relevantes y hashes de los artefactos. El preflight no deduce estos
   hechos de `libvulkan_intel.so`.
2. Completar y auditar todos los entregables del probe. Mantener el canary activo;
   no ocultar errores de compilación ni sustituir DPAS real con una constante.
3. Revisar el harness con buffers conocidos, comprobación de
   los 11 resultados y de los slots intactos, readback determinista y evidencia
   inequívoca de que se llamó al kernel CM inyectado. El probe solo es un control
   de ABI, no FSR completo.
4. Para runtime, pedir autorización explícita. Usar exclusivamente un prefijo
   descartable nuevo, nunca el prefijo de Cyberpunk/Steam; aislar variables de
   entorno en el proceso de prueba, usar únicamente los artefactos Mesa locales
   identificados por hash, conservar el canary y registrar logs/readback. No
   instalar drivers, cambiar servicios ni modificar configuración global.
5. Detenerse ante falta de inyección, discrepancia de readback, fallo de compilación,
   canary o cualquier diferencia con los valores esperados. No escalar a FSR ni a
   integración por juego hasta explicar el fallo y revisar evidencia.

Este documento no autoriza los comandos de lanzamiento descritos en `lab/README.md`.
El siguiente paso es revisar juntos los artefactos y controles, registrar hashes
del harness/ICD y acordar explícitamente el experimento aislado antes de ejecutar
una prueba GPU. El timeout del harness no garantiza recuperar una GPU colgada.
