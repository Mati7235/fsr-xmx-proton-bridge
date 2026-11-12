# Checklist de versiones para la futura traza PRE autorizada

Fase 1, CPU-only: esta lista define **qué registrar**, no autoriza la traza.
Se completa a mano por el usuario en el momento de la ejecución manual, en un
prefijo descartable, sin tocar Steam, prefijos reales, drivers ni servicios.
Todos los comandos de obtención son de solo lectura.

## Cómo registrar

- Una fila por ítem: valor observado + fuente (ruta o archivo) + SHA-256
  cuando sea un archivo.
- Guardar la evidencia bajo `runs/<id>/evidence/versions/` junto a la captura
  ([spec](pre-trace-capture-spec.md)).
- Si un ítem no aplica o no se encuentra, anotarlo explícitamente en vez de
  omitirlo. No reutilizar valores de otra máquina o ejecución.

## Tabla de registro

| # | Ítem | Fuente / comando de solo lectura | Evidencia a guardar |
|---|---|---|---|
| 1 | Ejecutable del juego (ruta real usada) | ruta + `sha256sum <exe>` + tamaño en bytes | `exe.sha256`, ruta anotada |
| 2 | Versión del ejecutable | recurso de versión del PE (FileVersion/ProductVersion), leído sin ejecutar | `exe.version.txt` |
| 3 | Build de Proton en uso (directorio) | ruta del directorio Proton + contenido de su archivo de versión | `proton.version.txt` |
| 4 | Binarios D3D12/VKD3D realmente cargados | DLLs `d3d12`/VKD3D del build en uso confirmadas por el log de carga + `sha256sum` de cada una | `vkd3d.*.sha256` |
| 5 | Versión de VKD3D-Proton | cadena de versión del build en uso (archivo de versión o log), sin asumir número | `vkd3d.version.txt` |
| 6 | Versión de Wine del prefijo | `wine --version` del Wine que gestiona el prefijo descartable (solo lectura, fuera de Steam) | `wine.version.txt` |
| 7 | Manifiesto ICD local usado | `intel-local-icd.json` de la preparación (ruta + `sha256sum`) | copia en `evidence/` |
| 8 | Librería ICD local (`libvulkan_intel.so`) | ruta absoluta + `sha256sum` + `api_version` del manifiesto | `icd.library.sha256` |
| 9 | DLL del mod XMX | `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53` (re-verificar con `sha256sum`, no asumir) | `dll.sha256` |
| 10 | Blob PRE Xe2 native_1080 | `3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2` (re-verificar) | `pre-zebin.sha256` |
| 11 | Dispositivo PCI observado | `8086:e20b` esperado en B580; registrar el ID real del log de selección | `device.pci.txt` |
| 12 | Kernel y escritorio (contexto, no cambia el resultado) | `uname -r`, versión de CachyOS/Mesa del sistema solo como contexto | `host.context.txt` |

## Reglas

- El manifiesto de la preparación fija hashes de DLL, disassembly, headers y
  blob PRE; el lanzador los re-verifica antes de andamiar el run. Si alguno
  cambió, la traza no procede: no se edita el manifiesto para saltarse el
  control.
- El ICD debe ser un manifiesto local explícito (`VK_DRIVER_FILES` y
  `VK_ICD_FILENAMES` apuntando solo a él). Un ICD de sistema no es válido
  para esta captura.
- `WINEPREFIX` es un directorio fresco por run, reservado pero **no
  inicializado** por la preparación. La inicialización, si se autoriza, ocurre
  solo dentro del run manual futuro.
- Ningún resultado de esta lista sustituye al oracle de salida ni acredita
  corrección funcional (ver
  [contrato controlado](pre-controlled-test-contract.md)).
