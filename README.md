# FSR XMX / Proton bridge lab

Laboratorio para investigar la compatibilidad entre el mod FSR4 XMX de nitec y
[xess-xmx-linux](https://github.com/HHHHanasak1/xess-xmx-linux).

**Estado: análisis estático inicial. No existe todavía un puente funcional ni se ha probado en GPU.**
Equipo objetivo informado: Intel Arc B580 (Xe2), CachyOS, Steam nativo, Cyberpunk 2077.

## Hipótesis

El mod envía kernels CM-SPIR-V mediante las extensiones D3D12 de Intel.
xess-xmx-linux implementa un shim IGDEXT y Mesa ANV modificado que pueden servir
como base. Compartir APIs no garantiza compartir la ABI de recursos y argumentos.

## Contenido

- `docs/compatibility.md`: hallazgos, limitaciones y plan de trabajo.
- `tools/inspect_dll.py`: inventario estático reproducible de cadenas y SHA-256.
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

## Próximo hito

Extraer de forma estática un kernel CM-SPIR-V representativo y documentar sus
argumentos, opciones de compilación y root signature. Compararlos con la ABI del
shim/ANV antes de intentar un microtest de GPU con resultado determinista.

No se instalaron drivers ni se modificaron Steam, Cyberpunk o prefijos Proton.
No ejecutar los instaladores de upstream como parte del análisis.

## Procedencia

Fecha de preparación: 2026-10-22.
Upstream inicial: `ef39559d26e083ce1bd1353b2e8c86f33c3c264c`.
Los binarios de terceros no se redistribuyen. Este repositorio no concede derechos
sobre los modelos, DLLs o el código upstream; consultar sus licencias respectivas.
