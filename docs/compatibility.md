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

## Bloqueos pendientes

1. Extraer los packs RCDATA comprimidos del mod, preservando originales y verificando hashes si es posible.
2. Documentar un kernel real: entrada, tamaño local, argumentos y opciones.
3. Reconstruir root signature y asignación SurfaceIndex/sampler del mod.
4. Comparar los requisitos con packer y parche ANV; evitar generalizar por nombres compartidos.
5. Determinar si basta configuración o si hacen falta cambios en el shim, packer o driver.
6. Revisar compatibilidad de compilador IGC y dispositivo Xe2/Large-GRF.

## Hitos de implementación

- [x] Crear workspace separado, copias y hashes.
- [x] Clonar e identificar revisión upstream.
- [x] Inventario estático reproducible de la DLL.
- [x] Mapa inicial de APIs y riesgos ABI.
- [ ] Extractor de recursos/CM-SPIR-V (sin ejecutar DLL).
- [ ] Fixture y pruebas CPU para metadatos/ABI.
- [ ] Diseñar adaptación mínima con evidencia del kernel real.
- [ ] Con autorización, microtest en prefijo descartable con salida GPU conocida.
- [ ] Solo después, integración reversible por juego en Cyberpunk.

## Criterio de éxito y seguridad

No modificar el driver de la sesión ni prefijos del usuario durante el análisis.
Un experimento runtime deberá usar un prefijo descartable y variables por proceso,
mantener el canary del driver y comprobar readback GPU determinista más logs de
inyección. No considerar suficiente el overlay, S_OK, o que desaparezca el magenta.

Build upstream según documentación inspeccionada: shim MSVC/Windows SDK/CMake;
ANV Mesa parcheado y toolchain IGC/ocloc fijado por upstream. No se instaló ni
compiló ninguno. No se ha demostrado aún que los kernels FSR compilen o funcionen.
