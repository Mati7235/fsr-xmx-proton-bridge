# FSR XMX / Proton bridge lab

Laboratorio para investigar la compatibilidad entre el mod FSR4 XMX de nitec y
[xess-xmx-linux](https://github.com/HHHHanasak1/xess-xmx-linux).

**Estado: PRE y probe sintético compilados offline; Mesa adaptado compila localmente. No existe todavía un puente funcional ni se ha probado en GPU.**
Equipo objetivo informado: Intel Arc B580 (Xe2), CachyOS, Steam nativo, Cyberpunk 2077.

## Hipótesis

El mod envía kernels CM-SPIR-V mediante las extensiones D3D12 de Intel.
xess-xmx-linux implementa un shim IGDEXT y Mesa ANV modificado que pueden servir
como base. Compartir APIs no garantiza compartir la ABI de recursos y argumentos.

## Contenido

- `docs/compatibility.md`: hallazgos, limitaciones y plan de trabajo.
- `tools/inspect_dll.py`: inventario estático reproducible de cadenas y SHA-256.
- `tools/extract_resources.py`: extracción de recursos PE sin cargar la DLL.
- `tools/decompress_mscf.py`: descompresión LZMS con libwim local.
- `tools/carve_spirv.py`: recuperación heurística inicial (histórica).
- `tools/parse_cm_payloads.py`: extracción por pies y longitudes de los bloques CM.
- `tools/reconstruct_pre.py`: tablas del PRE y modelo de layout para la DLL fijada.
- `tools/inspect_zebin.py`, `tools/build_pre_profile.py`: inspección y perfil del PRE compilado.
- `tools/audit_pre_payload.py`: auditoría restringida del uso de bytes cross-thread en el PRE.
- `tools/apply_cmk_mapping.py`: adaptador offline experimental CMK2 → CMK3.
- `tools/build_anv_mapping_patch.py`: generador del lector candidato, sin aplicar cambios.
- `profiles/`, `patches/`: metadata revisada y parche experimental (no binarios).
- `tests/`: pruebas de CPU; algunas usan artefactos/checkouts locales opcionales.
- `artifacts/original/`: copias locales de los dos archivos descargados (ignoradas por Git).
- `artifacts/extracted/fsr-xmx/`: DLL del mod extraída sin ejecución.
- `upstream/xess-xmx-linux/`: clon independiente de upstream (ignorado por Git).
- `analysis/fsr-xmx-static.json`: reporte generado localmente.

```bash
python tools/inspect_dll.py \
  artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll \
  > analysis/fsr-xmx-static.json
```

El script no carga la DLL. Las cadenas son indicios de implementación, no una
prueba de funcionamiento ni una especificación completa.

## Investigación actual

Ver [reconstrucción del PRE](docs/pre-resource-map.md): **690 bloques CM**
recuperados por sus longitudes y desensamblados, opciones embebidas preservadas y
mapa de once recursos más sampler. La comparación estática encuentra un posible
desfase de un DWORD en el mapeo automático del puente para el layout de referencia.
Se confirmó la compilación del PRE Xe2 native_1080 para B580 y su orden de BTIs.
Ver [compilación offline y prototipo](docs/offline-pre-compilation.md): opciones
embebidas consumidas, perfil fijado por hashes y lector CMK3 candidato.
La [auditoría del payload](docs/pre-payload-audit.md) no encuentra lecturas de los
cuatro campos extra antes de sobrescribirlos o terminar, bajo una máscara de
ejecución completa y constante, solo para este binario fijado.
Ese hito quedó verificado con 68 pruebas (algunas requieren artefactos opcionales).
No equivale a corrección GPU; la compilación posterior de Mesa se detalla abajo.

La [primera investigación](docs/investigation-2026-10-22.md) se conserva como
registro histórico; su hipótesis de opciones perdidas en PRE fue corregida.

## Laboratorio aislado

La [build local de Mesa](docs/lab-mesa-build.md) terminó con LLVM 23, sin instalar
el driver. La revisión estática deriva máscara completa para el CMK `1x1x1`;
no demuestra la máscara durante la ejecución del kernel.
El [preflight CPU](docs/lab-first-test.md) inventaría artefactos y hashes, detecta
faltantes y no declara el runtime listo. Sus ocho pruebas sintéticas pasan.
El probe y el harness siguen en revisión de integración; compilar no demuestra
inyección ni resultados GPU correctos.

## Próximo hito

Completar la auditoría del payload del probe sintético y alinear su selección de
heap con el harness antes de preparar una prueba GPU autorizada. El lector ya
compila dentro de Mesa local, pero no está instalado. El orden de argumentos/BTIs
del PRE revisado y la metadata explícita están implementados; la auditoría del
PRE no se transfiere automáticamente al nuevo probe ni al resto de FSR.

No se instalaron drivers ni se modificaron Steam, Cyberpunk o prefijos Proton.
No ejecutar los instaladores de upstream como parte del análisis.

## Procedencia

Fecha de preparación: 2026-10-22.
Upstream inicial: `ef39559d26e083ce1bd1353b2e8c86f33c3c264c`.
Los binarios de terceros no se redistribuyen. Este repositorio no concede derechos
sobre los modelos, DLLs o el código upstream; consultar sus licencias respectivas.
