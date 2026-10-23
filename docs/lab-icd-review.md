# Revisión offline del ICD para la prueba manual

Se inspeccionaron los ELF con `readelf`, sin cargar el driver ni ejecutar el
harness. ANV exporta `vk_icdGetInstanceProcAddr` y
`vk_icdNegotiateLoaderICDInterfaceVersion`. Sus 22 dependencias directas y las
dos del harness tienen archivos presentes en las rutas locales del sistema.
Esto no verifica resolución dinámica de símbolos/versiones, dependencias
transitivas, selección efectiva del ICD ni funcionamiento GPU.

Artefactos locales revisados:

| Artefacto | SHA-256 |
|---|---|
| `build/mesa-26.1.2/out/src/intel/vulkan/libvulkan_intel.so` | `3fc482d67725f417a5194a7d68dc69ffbb29d0795ca354c65c84cd38050843fb` |
| `build/lab-harness/bridge_probe` | `e9ad923a51fdeec10c94ec9e2011e7367a694fe8a1e845dfa34710410b0ac749` |

El inventario detallado local está en `analysis/lab-elf-review.json`. No se usó
`ldd`, `vulkaninfo` ni el ejecutable de prueba para esta inspección. Los hashes
identifican estas builds, no un resultado de ejecución.

El candidato de probe es `build/lab-probe-v10`. Conserva exactamente el zebin,
CMK3 y auditoría de payload de v09, pero corrige los shaders Vulkan de marcador:
solo escribe la invocación local cero. Los dos marcadores pasan
`spirv-val --target-env vulkan1.1`. No usar los marcadores históricos que
escribían concurrentemente el mismo DWORD.

Para la prueba manual, el manifiesto ICD debe apuntar mediante ruta absoluta a
este ANV local; no reemplazar manifiestos de `/usr/share/vulkan` ni instalar el
driver. El lanzador debe volver a comparar los hashes, usar un HOME/caché y
directorio de evidencia nuevos, y pasar un entorno acotado solo al proceso hijo.
El harness exige además canary, evidencia DIRECT/inyección y readback conocido.

## Riesgo residual

El experimento usa la misma GPU y el mismo driver del kernel que la sesión de
escritorio. **No es aislamiento de hardware**: un fallo puede colgar la GPU o la
sesión. Guardar el trabajo antes de ejecutarlo. El fence de 20 segundos solo
limita una espera del harness; no garantiza recuperación ni acota todas las
llamadas al driver. No ejecutar con `sudo` ni con Cyberpunk/Steam como banco de
pruebas. Una prueba sintética correcta no validaría FSR completo ni Proton.
