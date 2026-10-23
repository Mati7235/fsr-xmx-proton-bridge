# PRE native_1080: contrato estático para prueba controlada

## Estado y alcance

Este documento especifica qué se puede preparar para **PRE Xe2 pack 40102,
native_1080**, no autoriza un dispatch ni declara compatible el puente. Se analizó
estáticamente la DLL fijada (`3eb086…eba53`), el blob CM completo fijado
(`76942f…773b`) y el PRE compilado para Xe2/B580 (`0xe20b`; zebin
`3e974d…e01b2`). No se ejecutó DLL, shader ni GPU en este trabajo.

La extracción repetible `python tools/inspect_pre_inputs.py
analysis/fsr-resources/xe2-first.spvasm` valida el SHA-256 del SPIR-V textual y
extrae tipos/guards sin asignar semántica de escena. Pruebas CPU:
`python -m unittest discover -s tests -p test_pre_inputs.py -v`.

## Contrato confirmado

### Shader/dispatch

- Entry: `fsr4_pre_xmx`; 12 argumentos en este orden:
  0 `BufferSurfaceINTEL ReadWrite`, 1 `Image2D ReadWrite`, 2–8 siete
  `Image2D ReadOnly`, 9–10 `BufferSurfaceINTEL ReadWrite`, 11 sampler. En el
  mapeo IGC fijado, BTIs respectivos: `8,9,1,2,3,4,5,6,7,10,11` y sampler
  index 0 (fuente: `analysis/offline-pre/full/ze_info.yaml:15-160`,
  `docs/offline-pre-compilation.md:54-76`). La root signature de la DLL contiene
  además b0 y la tabla s0 (`docs/pre-resource-map.md:123-150`).
- El shader compara `WorkgroupId.x >= 120` y `WorkgroupId.y >= 540` y retorna
  para cualquiera de esos casos (`analysis/fsr-resources/xe2-first.spvasm:5166-5185`).
  Por tanto, para cubrir toda la región admitida, el candidato mínimo de grid es
  **120×540×1 workgroups**; X/Y menores dejan grupos sin procesar, mayores se
  descartan por guard. Z no se usa en el entry inspeccionado. Esto es un límite
  derivado del código, **no** una prueba de que cada grupo cubra 16×2 píxeles ni
  de que el host runtime despache así. Las dimensiones locales correctas siguen
  sin establecerse (no inferirlas de `SubgroupSize 1` ni del packer provisional
  `1×1×1`).
- Hay llamadas GenX de image load/sample y un typed quad store. El `OpTypeImage`
  declara formato `Unknown`; las imágenes son 2D, pero no podemos derivar formato
  Vulkan, canales, espacio de color, escala, valores de profundidad/motion ni
  contenidos de prueba. El extractor registra 78 llamadas syntácticas `3d_load`,
  85 `3d_sample` y un `typed_quad_store`; esos conteos no equivalen a lecturas por
  píxel ni asignan cada operación a un recurso. No renombrar t0…t8 como
  color/depth/etc.
- **El store NO usa BTI 7.** La firma exacta en `xe2-first.spvasm:3057-3068` es
  `(predicate, i8, i8, i8, i32 surface, u, v, r, lod, data)`. En la llamada de
  `:15312`, los tres `i8` son `0,0,7`; el 7 es channel-enable mask `.xyz`, no
  superficie ni LOD. El `i32 surface` es `%9780`, con cadena SSA
  `%9780 <- %3391 <- %9774 <- %3397 <- %9769 <- %3460 <- %3749 <- %3656 <- %1687`,
  donde `%1687` convierte el **arg 1 Image2D ReadWrite** (`:3180-3181`,
  `:5152-5154`, `:5238-5250`, `:15278-15312`). El zebin confirma arg 1 → BTI 9
  (`ze_info.yaml:138-143`), y el IGA final emite dos
  `store_quad.tgm.d32.xyz.a32.bti[9]` con coordenadas `u,v,r,lod`
  (`analysis/pre-payload/disasm/.text.fsr4_pre_xmx.asm:1972-1973`). Coincide
  también con root 2 / u1, la imagen ReadWrite (`pre-resource-map.md:139-142`).
  **Resultado:** no hay conflicto con arg 8/t6; t6 (arg 8, BTI 7) no es destino
  de ese store. No reinterpretar el 7 como binding ni cambiar permisos.
- La root signature y el dispatch de la DLL conservan la separación D3D: u1 está
  en root 2, t6 en root 9; el loop normal llama `SetComputeRootDescriptorTable`
  con índices 1…11 y el array de handles (`0x180017410..0x180017435`,
  `pre-dispatch-snippet.txt:76-89`). En el mapa reconstruido u1 usa heap slot 8,
  t6 slot 6 (`pre-resource-map.md:136-150`). No hay una conversión de arg 8/t6 a
  UAV necesaria para explicar el store: el destino es el propio arg 1/u1, cuyo
  descriptor debe ser writable conforme a la firma. La DLL también crea vistas
  D3D en otras ramas; sin una traza del llamador no se atribuye una llamada
  concreta `CreateUnorderedAccessView`/`CreateShaderResourceView` a cada handle,
  pero esa atribución ya no cambia el binding del kernel.

### ABI y argumentos

- La DLL crea b0 como root constant de un DWORD y roots 1–11 como una tabla de
  descriptor por superficie más root 12 sampler (`pre-resource-map.md:123-150`).
  El orden/offset de push esperado según VKD3D de referencia es: b0 offset 0;
  superficies offsets 4,8,…,44; sampler offset 48; rango total 52 bytes. Es una
  referencia estática VKD3D, no una captura de Proton en uso. En el setup normal
  la DLL emite una llamada con los cuatro argumentos `rootIndex=0, value=0,
  destOffset=0` antes de las tablas (DLL `0x1800173e0`, vtable `+0x108`); el
  loop siguiente enlaza roots 1–11 en `0x180017410..0x180017435`. Por tanto **b0
  se fija a cero**, no es un campo de dimensiones/escala que el harness deba
  adivinar. No aparece como parámetro de los 12 argumentos del entry ni como
  argumento cross-thread de zebin. Para este kernel es un root-constant filler
  no consumido por el IR revisado; mantenerlo en cero.
- El ABI de PRE normal necesita 11 tablas en heap de recursos y s0 en heap de
  sampler separado. Perfil fijado: explícita base push 4 y correspondencia
  `arg_index -> BTI` anterior. El lector candidato CMK3 y el perfil siguen
  `experimental-offline-only`, no instalados ni integrados runtime.
- El sampler que la DLL crea usa MIN/MAG/MIP linear + CLAMP U/V/W; fallback ANV
  coincide parcialmente, pero no es equivalente general. No omitirlo en la prueba
  de imagen/sampler ni asumir exactitud bilineal sin comparar.
- Los buffers stateful sí tienen uso real; distinguirlos de sus ocho bytes extra
  de payload. `u0`/arg 0/BTI 8 (slot heap 7) es un buffer de acceso mixto: el IR
  hace un `oword.ld.unaligned.v4f32` de 16 bytes (`:5627-5634`) y stores de 16 y 128 bytes
  (`:5665`, `:15993`); el IGA incluye `load.ugm...bti[8]` y stores `bti[8]`
  (`.text.fsr4_pre_xmx.asm:139,146,2297`). El acceso float4 de `:5627` usa una
  dirección derivada del arg 10: su bloque inicial de 128 bytes se carga en
  `:5190-5220` y los campos leídos incluyen offsets 8–84, DWORD/byte offsets
  64–80, flags en byte 100 y dirección base en byte 104 (`:5261-5325`,
  `:5573-5602`). Hay guard por bit `0x400` de flags; bit `0x2000` selecciona
  entre `base` y `base+16` para leer float4, y el primer canal participa en la
  normalización/comparación. No se deducen nombres semánticos de esos campos.
  La ruta final escribe 128 bytes de salida por grupo en arg 0 en el índice
  OWORD `wg_y*960 + wg_x*8` (`:15977-15993`), cuando pasa su guard. Así que arg 0
  no debe inicializarse como un buffer vacío de readback: contiene regiones de
  entrada/scratch y salida cuyas relaciones exactas dependen del header arg 10.
- Los ocho bytes cross-thread extra de args 0/9/10 y `private_base_stateless`
  están estáticamente sin lectura antes de overwrite/fin **solo bajo máscara de
  ejecución completa y constante** para este zebin (`pre-payload-audit.md`). Esos
  son campos de payload, no los recursos de buffer: los buffers opacos siguen
  presentes en ABI. Mantener la máscara como gate abierta; no suministrar
  direcciones inventadas ni generalizar la auditoría.
- La DLL pasa CompileOptions e InternalOptions NULL para esta ruta; el blob CM
  completo preserva opciones embebidas consumidas por IGC. Input/kernel/hash/
  target deben seguir fijados como arriba.

## Preparación segura y criterio

La prueba controlada debe ser una futura prueba **aislada en prefijo descartable**,
con ICD/driver local escogido explícitamente y sin tocar Steam, prefijo real,
servicios o drivers del usuario. Reutilizar la barrera del harness sintético:
canary habilitado, log explícito de inyección real, perfil/cache identity fijados,
layout DIRECT verificado, sincronización/barriers correctos y readback GPU repetible.
El probe sintético DPAS positivo cubre solo su propio kernel/layout, no PRE.

Antes del primer dispatch PRE aún hacen falta:

1. **Después del probe de imágenes/sampler**, guardar evidencia exacta de formatos,
   filtros, coordenadas normalizadas/texel-space, límites, transición de imagen y
   readback de ese probe. No extrapolar sus resultados automáticamente a las ocho
   imágenes PRE.
2. Determinar de forma independiente el formato, tamaño, permisos/uso y contenido
   de cada imagen y el tamaño/layout completo de buffers arg 0/9/10 mediante una
   traza autorizada del llamador (o documentación verificable de su ABI). Arg 0
   requiere al menos que el registro de 16 bytes en `byte104 + {0,16}` y el plano
   de escritura por OWORD no aliasen regiones incompatibles; arg 10 debe cubrir
   el header de 128 bytes y sus offsets derivados. La ABI estática no da los
   tamaños asignados ni las direcciones/offsets de runtime.
3. Capturar/derivar la dimensión local del dispatch en la ruta real y confirmar
   que el grid efectivo cubre 120×540; además, verificar
   máscara de ejecución requerida por la auditoría del payload. El tamaño `native_1080`
   no establece por sí solo tamaños concretos de entrada ni local size.
4. Identificar las imágenes por procedencia/uso observados (no por intuición) y
   preparar valores deterministas que sean válidos para cada formato confirmado.
   Una captura exacta de los recursos antes del dispatch sería mejor oracle que
   patrones inventados.
5. Obtener oracle PRE independiente: salida del mismo input/recursos/ABI en la
   implementación de referencia, o una referencia de CPU validada contra ella.
   El shader contiene reducción/feature/modelo y constantes de pesos; no hay una
   regla estática simple que permita declarar esperado un buffer/image de salida.
   A falta de oracle, limitarse a verificar inyección, límites/guardas y ausencia
   de corrupción fuera de la salida no acredita corrección funcional.
6. Revisar con hashes la versión real de Proton/VKD3D, el layout push, heap/sampler,
   el mapa de bindings y el ciclo de vida/sincronización antes de autorizar runtime.

**Criterio de aprobación PRE:** todos los gates anteriores documentados; prueba
repetible de entrada fija en prefijo desechable; evidencia de la ruta de inyección y
del layout esperado; readback íntegro comparado con oracle (tolerancias justificadas
por formato/operación, no inventadas), sin diferencias en canarios/guard regions ni
lecturas/escrituras fuera de rango. `S_OK`, creación de PSO, etiqueta overlay o
desaparición de magenta no bastan.

## Evidencia estática y límites exactos

- `analysis/fsr-resources/xe2-first.spvasm`: types `OpTypeImage` Unknown en líneas
  2473–2477; guards en 5166–5185; firma/call typed store y SSA en 3057–3068,
  3180, 5152–5154, 5238–5250, 15278–15312. `7` es `.xyz`, superficie `%9780`
  deriva del arg 1.
- `analysis/offline-pre/full/ze_info.yaml`: payload/argumentos y BTIs; `profiles/`
  fija hashes de input y zebin. El disassembly IGA auditado tiene hash
  `a9c82bbfccc535959e73ddd6b80fb209ed8a12bf8607927f62078b43b6215660`; no es un
  decodificador ISA independiente.
- `analysis/pre-dispatch-snippet.txt` documenta asignación de roots 1..11 y root
  12 sampler en la DLL. `docs/pre-resource-map.md` advierte que el layout Proton
  real aún no se contrastó.
- La imagen sintética no es dato PRE real; los pesos/modelo y las entradas semánticas
  del llamador no se reconstruyen en este contrato. Ningún resultado aquí demuestra
  PRE funcional, compatibilidad Proton ni salida visual correcta.
