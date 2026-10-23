# Primera prueba manual: DPAS y mapa de recursos

**Primera ejecución manual positiva en B580:** ver
[resultado y límites](first-synthetic-gpu-result.md). No prueba FSR,
Proton, OptiScaler ni Cyberpunk: usa un kernel sintético propio.

## Antes de ejecutarla

- Guardá tu trabajo y cerrá juegos/cargas GPU. Un fallo puede colgar la GPU o la
  sesión de escritorio. El timeout no garantiza recuperación.
- No uses `sudo`, no copies archivos a Steam y no cambies drivers del sistema.
- Ejecutá el comando solo si aceptás iniciar este experimento GPU. El agente no
  lo ejecutó por vos.

Desde cualquier directorio, en este equipo:

```bash
python3 /home/matias/Proyectos/fsr-xmx-proton-bridge/build/lab-test-v02/run-manual.py --run-gpu
```

Sin `--run-gpu`, el lanzador se niega a ejecutar el harness. No hay instalación
ni cambios persistentes de entorno. El comando prepara HOME, caché y directorios
nuevos dentro de `build/lab-test-v02/runs/`, fija solo el ICD local y deshabilita
layers. Reserva un `WINEPREFIX` vacío nuevo para cumplir el aislamiento del
laboratorio: el harness es nativo, no inicializa Wine ni usa prefijos existentes.
**Esto no aísla el hardware ni el driver del kernel.**

## Qué comprueba

Antes de crear el proceso, el lanzador verifica SHA-256 del harness, driver,
ICD y archivos del probe. Si cambiaron, aborta: no edites el manifiesto para
saltarte el control. La preparación también reprodujo la auditoría restringida
del payload y comparó todo el CMK3 con el paquete esperado.

En GPU, el harness exige PCI `8086:e20b`, canary, layout DIRECT con stride no
cero, logs de inyección/despacho y 128 resultados por cada uno de los once
recursos. Comprueba además que los cinco slots restantes no cambien. No se
considera éxito solo crear el pipeline o ver un marcador.

Si termina correctamente, el harness imprime:

```text
GPU probe passed its gating, canary, injection-log, deterministic readback, and untouched-buffer checks.
```

El lanzador imprime el código de salida y el directorio de la ejecución. Los
resultados se guardan en `build/lab-test-v02/runs/<ejecución>/evidence/`:

- `icd-selection.txt`: configuración solicitada del loader.
- `anv_canary`, `canary-driver.log`, `canary-evidence.txt`: control del driver.
- `probe-driver.log`: evidencia de inyección y despacho.
- `probe-readback.txt`: valores y slots intactos comprobados.

Mandame la salida de la terminal y esos logs, incluso si parece funcionar. Un
archivo parcial de readback no demuestra éxito; revisar el código de salida y
la evidencia completa. Si falla o se cuelga, no lo pruebes directamente en
Cyberpunk ni cambies las comprobaciones para forzarlo a pasar.

## Repreparación offline

Si recompilás o cambian hashes, podés generar una preparación nueva sin ejecutar
GPU, desde la raíz del repositorio:

```bash
python3 tools/prepare_lab_test.py
```

Usará Mesa local, harness local y `build/lab-probe-v10`. El directorio de salida
es nuevo y el programa imprime el comando manual correspondiente. No instala ni
redistribuye binarios. Esta preparación no valida la resolución dinámica de
dependencias ni el runtime: esas comprobaciones siguen formando parte del
experimento.
