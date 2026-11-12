# Checklist de usuario: traza Spider-Man 4.1.2 (una página)

Solo ejecución manual del usuario, en prefijo descartable. Nada aquí autoriza
nada por sí mismo; cada paso lo haces tú a mano. No tocar Steam, prefijos
reales, drivers ni servicios.

## 0. Leer antes (no copiar: referenciar)

- Runbook completo y comandos exactos: [spiderman-trace-runbook.md](spiderman-trace-runbook.md)
  (§0 rutas/versiones, §1 re-verificación, §2 DLL, §3 preparación, §4 comando
  Proton, §5 RenderDoc opcional, §6 `evidence/versions/`).
- Qué registrar del dispatch PRE `native_1080`: [pre-trace-capture-spec.md](pre-trace-capture-spec.md)
  (§1–§8: creación, vistas/copias, `GetDesc`, bytes pre/post, handles/bases,
  sampler, secuencia/contexto, grid/transiciones).
- Qué fila de versiones guardar y con qué comando: [pre-trace-version-checklist.md](pre-trace-version-checklist.md)
  (la tabla del runbook §6 ya la adapta a 4.1.2: DLL `fadbcb50…`, sin zebin
  compilado, ICD explícito del sistema).

## 1. Preparar (solo lectura)

1. Re-verifica hashes de partida con el runbook §1 (DLL `fadbcb50…`, IR
   `49e069fd…`, envelope `ce372719…`; si difieren, parar).
2. Genera el run con `tools/prepare_trace_capture_412.py` (runbook §3);
   deja el `wineprefix-reserved-not-initialized` sin inicializar.

## 2. DLL del mod (manual)

1. Backup del archivo actual fuera del juego (es `d0dcccc7…`, no el mod).
2. Copia encima `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll`
   en el directorio del juego (ruta exacta en runbook §2).
3. `sha256sum` debe dar `fadbcb50…`; confirma en overlay/log de OptiScaler
   que el backend FSR/XMX 4.1.2 está en uso (runbook §2 paso 4).

## 3. Ejecutar (manual, una vez autorizado)

1. Comando Proton solo con `evidence/env.json` (entorno reemplazado) + log
   fuera del juego: ver runbook §4 (`VKD3D_DEBUG=trace` ya fijado).
2. Busca escena con entrada 1920×1080; anota resolución real y PCI real
   (`8086:e20b` esperado); grid esperado `(120,540,1)` (fórmula y modos en
   runbook §5 / spec §8).
3. Opcional: captura RenderDoc a `<run>/evidence/spiderman-412.rdc` y abre
   con `qrenderdoc` (runbook §5); localiza el `Dispatch` y los 11+1
   descriptores.

## 4. Evidencia (una fila por ítem, valor + fuente)

Llena `runs/<id>/evidence/versions/` con la tabla del runbook §6 (12 filas:
exe, versión PE, Proton, VKD3D, Wine, ICD manifiesto+librería, DLL
`fadbcb50…`, PRE IR+envelope, PCI, host). Guarda además log
`vkd3d-trace.log`, `.rdc` si aplica, y bytes pre/post (spec §4: header
128 B arg 10, 2.112 B arg 9, registro base+{0,16} y plano OWORD de arg 0;
volcado completo recomendado, sin inicializar como buffer vacío).

## 5. Criterio de cierre

La traza es evidencia de entrada, no oracle ni prueba funcional. Ninguna
fila sustituye al oracle; `S_OK`, overlay o magenta no acreditan nada
(runbook §6, spec §"Lo que esta captura no establece").
