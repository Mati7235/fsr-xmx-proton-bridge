# Compatibilidad inicial y plan

## Entradas y trazabilidad

Análisis estático del 2026-10-22. No se ejecutó código de los paquetes.

| Archivo | SHA-256 |
|---|---|
| amd_fidelityfx_upscaler_dx12_xmx.7z | `1364778b46ab3f0734305ad44d23e161d94cd75130e08683acd5ceed85d7155b` |
| OptiScaler_v10.0.0-pre_20261022.7z | `df1380aa37fc17b26524e783f12ccb2f59cb67f966af13240bca3d4cd608a25a` |
| DLL extraída del mod XMX | `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53` |

Upstream analizado: `ef39559d26e083ce1bd1353b2e8c86f33c3c264c`.
Las líneas siguientes son relativas a `upstream/xess-xmx-linux/`;
para parches se refieren al archivo del parche, no al archivo final de Mesa.

## Evidencia en el mod

La DLL de 25.779.712 bytes incluye cadenas de búsqueda de `igdext64.dll`,
las variantes INTC con y sin guion bajo, y mensajes de:

- `CreateDeviceExtensionContext`, contexto solicitado 4.20.0.
- `CheckFeatureSupport`: OPTIONS1/XMX y OPTIONS2/SIMD16Required.
- `CreateComputePipelineState`: kernels CM-SPIRV y packs Xe2 embebidos.
- `DestroyDeviceExtensionContext`.
- `GetCachedBlob`, asociado a diagnóstico de un blob PRE (su carácter obligatorio no está establecido).
- Modelos `4.0.2x`, `4.0.2xm`, y lectura de pesos desde `fsr-original.dll`.
- Fallo explícito con diagnóstico magenta; fallback convencional deshabilitado.
- Mensaje ABI PRE: una tabla por SurfaceIndex/sampler.

Son cadenas extraídas, no una traza observada ni una reconstrucción completa del flujo.

## Mapa del shim

| Área | Hallazgo | Evidencia upstream |
|---|---|---|
| Versión | Acepta 4.20.0 mediante comparación contra máximo 5.20.0; esto no prueba implementación completa | `shim/src/D3D12ExtensionContext.cpp:7-30`, `shim/src/ExtensionContextBase.h:42-45` |
| Contexto | Exporta `_INTC_D3D12_CreateDeviceExtensionContext`; variante sin sufijo usa información temporal que no devuelve completamente al llamador | `shim/src/dll/Igdext.def:33`, `shim/src/dll/IgdextApiDll.cpp:343-434` |
| Capacidades | OPTIONS1 y OPTIONS2 implementadas; respuestas basadas en GPU detectada, con overrides | `shim/src/dll/D3D12Api.cpp:397-426` |
| Detección GPU | Registro PCI de Wine, no necesariamente el dispositivo D3D12 recibido; default optimista si no detecta | `shim/src/dll/GpuInfo.cpp:12-42` |
| PSO CM-SPIR-V | Guarda kernels dinámicos; no requiere whitelist fija XeSS | `shim/src/dll/D3D12Api.cpp:218-249`, `shim/CMakeLists.txt:39-43` |
| Compilación | Filtra CompileOptions; no transmite InternalOptions; tamaño local depende de defines concretos o cae a 1,1,1 | `tools/cm-compile.sh:42-54`, `shim/src/dll/D3D12Api.cpp:202-245` |
| Entry point | Packer elige primera sección .text no interna; no selección general del entry point | `tools/cmk_pack.py:44-52` |
| Recursos | Asume una tabla por superficie y trailing DWORDs en push constants; no interpreta root signature general | `tools/cmk_pack.py:89-101`, `patches/0001-anv-cm-kernel-injection.patch:675-720` |
| Samplers | Primer sampler estático o fallback linear/clamp XeSS | mismo parche `:668-673,786-824` |
| Payload | Límite cross-thread de 128 bytes; tipos de argumentos no implementados; group count fijo en packer | `tools/cmk_pack.py:62-87`, `tools/cm-compile.sh:54` |
| CachedBlob | Export presente pero E_NOTIMPL; evaluar si solo afecta diagnóstico del mod | `shim/src/dll/D3D12Api.cpp:120-124` |
| Resultado | S_OK o un PSO creado no garantizan inyección; hay fallback no-op | `shim/src/dll/D3D12Api.cpp:247-256` |

La coincidencia de 'una tabla por superficie' es prometedora, pero no demuestra
que coincidan los offsets, samplers, argumentos, registros o el layout de vkd3d.

## Avance de investigación

Ver [pre-resource-map.md](pre-resource-map.md): **690 bloques** recuperados por
pies de longitud, mapa del PRE reconstruido y desfase de un DWORD identificado
bajo el layout VKD3D de referencia. En PRE las opciones de API son NULL y las
opciones embebidas se preservan. La [compilación offline](offline-pre-compilation.md)
confirmó que IGC las consume, compiló el PRE para B580 y verificó los BTIs. Se añadió
un perfil fijado por hashes y un lector CMK3 candidato, no instalado.
La [auditoría posterior del payload](pre-payload-audit.md) no encuentra lecturas de
los cuatro campos extra antes de sobrescribirlos o terminar, bajo una máscara de
ejecución completa y constante en este binario. No se necesitó inventar direcciones.

## Bloqueos pendientes

1. Completar el formato de los datos no CM de 40101 (18 DXBC y seis huecos no clasificados); los seis módulos faltantes ya se recuperaron.
2. Validar la máscara de ejecución completa y constante asumida por la auditoría: los campos cross-thread de args 0/9/10 y private_base_stateless no se leen bajo esa condición en el PRE revisado.
3. Confirmar sampler y layout del Proton que se use para la prueba; el mapa de superficies del PRE ya se contrastó con zebin.
4. Revisar la integración del lector ya compilado dentro de Mesa local e integrar selección de perfil/cache identity sin cambiar globalmente XeSS; ver [build local](lab-mesa-build.md).
5. Determinar si basta configuración o si hacen falta cambios en el shim, packer o driver.
6. Revisar compatibilidad de compilador IGC y dispositivo Xe2/Large-GRF.

## Hitos de implementación

- [x] Crear workspace separado, copias y hashes.
- [x] Clonar e identificar revisión upstream.
- [x] Inventario estático reproducible de la DLL.
- [x] Mapa inicial de APIs y riesgos ABI.
- [x] Extractor de recursos y carving inicial CM-SPIR-V (sin ejecutar DLL; no parser completo del pack).
- [x] Parser por pies CM: 690 bloques recuperados y desensamblados.
- [x] Opciones y root signature del PRE normal reconstruidas; tamaños de 36 variantes verificados.
- [x] 22 pruebas CPU sintéticas y 2 opcionales con artefactos locales, incluido modelo del desfase de tablas.
- [x] Compilación offline del PRE Xe2 native_1080 para B580; BTIs confirmados y control de opciones reproducido.
- [x] Perfil por hashes, adaptador CMK3 offline y parche candidato de lector ANV para ambas versiones.
- [x] 41 pruebas locales pasando, incluido bloque C de validación con layouts sintéticos.
- [x] Auditoría estática de bytes cross-thread y usos de superficies opacas; sin lecturas bajo máscara completa, con evidencia por hashes.
- [x] 68 pruebas locales pasando, incluidos casos de lectura, escrituras parciales/predicadas y ramas del auditor.
- [ ] Pruebas de layout/copia de información de contexto y validación de máscara y dimensiones locales.
- [x] Compilación CPU de Mesa local con LLVM 23 y lector candidato; sin instalar ni ejecutar en GPU.
- [x] Probe sintético DPAS compilado, payload auditado bajo supuestos estáticos y heap CMK3 explícito.
- [x] Harness Vulkan compilado sin ejecución y preflight de inventario; 96 pruebas CPU pasan.
- [x] Preparación manual con ICD local, hashes, entorno nuevo y lanzador opt-in; 102 pruebas CPU pasan, sin ejecutar GPU.
- [x] Usuario ejecutó el probe sintético en B580: inyección y 1.408 valores correctos, con slots restantes intactos; ver [evidencia](first-synthetic-gpu-result.md).
- [x] Probe de imagen/sampler compilado, auditado y preparado para prueba manual con referencia CPU y readback binario independiente; 133 pruebas CPU pasan.
- [x] Usuario ejecutó imagen/sampler en B580: revisión binaria independiente confirma 64 valores con error máximo 0 y 1.984 words centinela intactos; ver [resultado](first-image-gpu-result.md).
- [ ] Integración runtime del perfil y revisión del contrato del probe/harness.
- [ ] Con autorización, microtest en prefijo descartable con salida GPU conocida.
- [ ] Solo después, integración reversible por juego en Cyberpunk.

## Criterio de éxito y seguridad

No modificar el driver de la sesión ni prefijos del usuario durante el análisis.
Un experimento runtime deberá usar un prefijo descartable y variables por proceso,
mantener el canary del driver y comprobar readback GPU determinista más logs de
inyección. No considerar suficiente el overlay, S_OK, o que desaparezca el magenta.

Build upstream: shim MSVC/Windows SDK/CMake aún no compilado. ANV Mesa parcheado
compiló localmente con LLVM 23, sin instalar ni ejecutar el ICD.
IGC/ocloc oficiales se extrajeron localmente sin instalación y compilaron un PRE
para B580. Eso no demuestra corrección GPU ni compatibilidad del resto de etapas.
