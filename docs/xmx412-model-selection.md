# XMX 4.1.2: selección de modelo (4.0.2X / 4.1.2X / Lite / Hybrid)

Solo análisis estático, CPU-only. No se ejecutó la DLL, ni GPU/Wine, ni se
tocaron juegos, prefijos, drivers o `artifacts/original`. La DLL se abrió en
Ghidra 12.2 headless (proyecto local en `/tmp/opencode/ghidra-xmx412`) y se
revisó el desensamblado/decompilado. Las direcciones son VA con
`ImageBase = 0x180000000`; el offset de archivo se obtiene con la tabla de
secciones PE.

Artefacto:

- `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll`
- SHA-256 `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`
- PE32+ x86-64, 45 558 272 bytes.

Hechos fijados por `tests/test_xmx412_model_strings.py` (7 tests, fail-closed):
SHA, literales, ramas de `CreateModel`, tabla de proveedores, contrato de
`fsr-original.dll` y generación de etiquetas.

## Resumen ejecutivo

| Variable (proceso) | Valor | Modelo resultante | Entrada nativa (índice) | Pesos necesarios |
|---|---|---|---|---|
| `FSR4_XMX_INT8` | `1` | **4.1.2X** (modelo INT8, kind 2) | 8 | `fsr-original.dll`: par INT8 |
| `FSR4_XMX_LITE` | `1` | **4.1.2X Lite** (modelo Lite, kind 1) | 12 | `fsr-original.dll`: par Lite |
| `FSR4_XMX_PRE41` | `1` | **4.0.2X Hybrid** (kind 0, flag híbrido) | 4 | embebidos 4.0.2 (no externos) |
| ninguna | — | elección del juego; por defecto **4.0.2X** | 0 | embebidos |
| `FSR4_XMX_DLSSK/M/E` | `1`/`E`/`F`/`A` | DLSS-KX / MX / LX / EX / FX / EFX | según tabla | `nvngx_dlss.dll` |

La columna "Entrada nativa" es el índice de la entrada de proveedor que
representa ese modelo. El override por entorno cambia el modelo que ejecuta
`CreateModel`, pero **no** cambia la entrada de proveedor ya elegida por el
juego; para cambiar también la etiqueta/versión reportada hay que usar el
dropdown o `FSR4_XMX_PROVIDER_INDEX`.

Conclusiones directas:

- **4.1.2X no se selecciona con `FSR4_XMX_PRE41`.** `PRE41=1` selecciona
  **4.0.2X Hybrid**. 4.1.2X se selecciona con `FSR4_XMX_INT8=1`.
- **Lite** se selecciona con `FSR4_XMX_LITE=1`. Si también está
  `FSR4_XMX_INT8=1`, gana INT8 (4.1.2X) cuando sus pesos están disponibles;
  si no, cae a Lite y luego a PRE41.
- **Hybrid** se pide con `FSR4_XMX_PRE41=1`: usa los pesos 4.0.2 embebidos,
  pero activa el flag de modelo/híbrido (`+0x207`) que cambia el tamaño de
  scratch y bits de dispatch. No carga pesos externos.
- El **4.0.2** que muestra OptiScaler sale de la etiqueta fija `4.0.2X` de la
  entrada base de proveedor (`FUN_180065920`) y/o del VERSIONINFO fijo
  `4.0.2.1`. No depende de `FSR4_XMX_*`. Las etiquetas 4.1.2 sí dependen de
  `fsr-original.dll` (se generan con `%u.%u.%uX` a partir del marcador de
  versión del DLL oficial).
- Para que el llamador/overlay vea **4.1.2X**, hay que seleccionar la entrada
  de proveedor 4.1.2X (dropdown o `FSR4_XMX_PROVIDER_INDEX=8`), no basta con
  `FSR4_XMX_INT8=1`: el override de entorno cambia el modelo, no la etiqueta
  de versión del proveedor ya elegido por el juego.
- `fsr-original.dll` es el **DLL oficial AMD FidelityFX Upscaler DX12 de FSR
  4.1.2**, renombrado, colocado junto al DLL del mod (o junto al EXE, o vía
  `FSR4_XMX_LITE_DLL`). No es `amdxcffx64.dll`, no es el DLL 4.0.2 y no es el
  propio DLL modificado 4.1.2 (los tres últimos no contienen los blobs que el
  loader exige).

## 1. `CreateModel`: quién lee qué y en qué orden

`CreateModel` está en `0x1800617C0` (la cadena de símbolo en `0x180321F70`
dice `unsigned int __cdecl CreateModel(struct InternalFsr4Context *,enum
fsr4_shaders::Preset)`). El orden de lectura y decisión es:

1. `FSR4_XMX_DLSSK` (`lea` en `0x180061900`)
2. `FSR4_XMX_DLSSM` (`0x180061933`)
3. `FSR4_XMX_DLSSE` (`0x18006195C`)
4. `FSR4_XMX_INT8` (`0x180061985`)
5. `FSR4_XMX_LITE` (`0x1800619A7`)
6. `FSR4_XMX_PRE41` (`0x1800619D4`)
7. si nada aplica: estado de la entrada de proveedor elegida por el
   juego/OptiScaler (fallback en `0x180061BFB`).

Cada variable se lee con `GetEnvironmentVariableA(..., 8)` y se compara solo
el primer byte con `'1'`; `0`, vacío o cualquier otro texto desactiva la rama.

### 1.1 INT8 -> 4.1.2X

En `0x180061AE3` se comprueba el valor leído de `FSR4_XMX_INT8` (el `lea`
del nombre está en `0x180061985`); si vale `1`, se llama a
`FUN_180027c00()` y se exige `byte [rax+0x68] != 0`:

```asm
180061AEA  call 0x180027c00              ; estructura de pesos fsr-original.dll
180061AEF  cmp  byte ptr [rax+0x68], 0   ; INT8 disponible
180061AF3  je   0x180061B08              ; si no, probar LITE
180061AF7  lea  r14, [rip+0x2C08A2]      ; 0x1803223A0 = "4.1.2X"
180061B00  movzx r9d, sil                ; flag INT8 para FUN_180061020
```

La rama fija `pcVar8 = "4.1.2X"` (`0x1803223A0`) y llama a
`FUN_180061020` en `0x180061B66` con el flag INT8. `FUN_180061020` escribe:

- `provider+0x209 = INT8`
- `provider+0x208 = LITE || INT8`
- `provider+0x207 = PRE41 || LITE || INT8` (flag de modelo/híbrido)

Después `FUN_1800625B0` traduce el estado a modelo:
`+0x209 ? 2 : (+0x208 ? 1 : 0)` y llama a `FUN_18004A9D0` (loader del
modelo). Por eso 4.1.2X es `kind=2` (INT8).

Matiz: `4.1.2X` es la etiqueta literal de esta rama, pero la etiqueta que
muestra la lista de proveedores se genera desde el DLL oficial (§3). Con un
`fsr-original.dll` 4.0.2 esta rama seguiría siendo la de INT8, pero el texto
generado sería `4.0.2X`; para obtener realmente `4.1.2X` hacen falta los
pesos 4.1.2.

### 1.2 LITE -> 4.1.2X Lite

En `0x180061B08` se comprueba `FSR4_XMX_LITE`; si vale `1`, se exige
`byte [FUN_180027c00()] != 0`:

```asm
180061B0F  call 0x180027c00
180061B14  cmp  byte ptr [rax], 0        ; Lite disponible
180061B17  je   0x180061B2F              ; si no, probar PRE41
180061B1B  lea  r14, [rip+0x2C0886]      ; 0x1803223A8 = "4.1.2X Lite"
180061B29  movzx r8d, sil                ; flag LITE
```

Etiqueta `0x1803223A8`, flag LITE. `FUN_1800625B0` lo traduce a `kind=1`.
El modelo Lite usa el mismo pack XMX embebido que INT8, pero otro juego de
pesos (blobs de `0x6B00` bytes, no de `0x20000`).

### 1.3 PRE41 -> 4.0.2X Hybrid

En `0x180061B2F` se comprueba el valor guardado de `FSR4_XMX_PRE41`:

```asm
180061B2F  cmp  byte ptr [rbp+0x3F0], 0x31   ; '1'
180061B36  jne  0x180061BFB                   ; fallback del proveedor
180061B3C  lea  r14, [rip+0x2C031D]           ; 0x180321E60 = "4.0.2X Hybrid"
180061B43  movzx edx, sil                     ; flag PRE41
```

Etiqueta `0x180321E60`, flag PRE41. No toca `+0x208`/`+0x209`, así que
`FUN_1800625B0` llama a `FUN_18004A9D0(..., 0, ...)`: no carga pesos
externos y el modelo queda en los pesos 4.0.2 embebidos. El flag `+0x207`
activa el camino de modelo/híbrido; en `FUN_180063830` cambia el tamaño de
scratch (`FUN_180073FB0` frente a `FUN_1800695C0`) y añade bits `0x1000`/
`0x2000` a las constantes de dispatch. La semántica runtime exacta de
"Hybrid" no se ha validado aquí; solo se fija el flag y sus efectos estáticos.

### 1.4 Prioridad e interacción

Orden real de las ramas (las primeras tienen prioridad):

```text
DLSSK > DLSSM > DLSSE > INT8 > LITE > PRE41 > elección del proveedor/juego
```

Consecuencias:

- `INT8=1` + `LITE=1` -> INT8 gana si `[0x68]` está disponible; si no, Lite.
- `INT8=1` + `PRE41=1` -> INT8 gana si hay pesos; si no, Hybrid.
- `LITE=1` + `PRE41=1` -> Lite gana si hay pesos; si no, Hybrid.
- Cualquier `FSR4_XMX_DLSS*` activo y con pesos gana a las tres ramas FSR4.
  Para probar FSR4, no definir variables DLSS.
- Si una rama 4.1.2 no encuentra pesos, **no** elige 4.1.2: cae a la
  siguiente rama. El error explícito aparece más tarde si el modelo se fuerza
  por otra vía (entrada de proveedor o carga ya iniciada):
  `Lite/INT8 model requested without verified fsr-original.dll weights.`
  (`0x18030E2E0`).

## 2. Dos listas distintas (no confundirlas)

### 2.1 Lista "Model"/"Version list" del plugin

`FUN_180001230` construye dos vectores paralelos de 10 entradas. Las
etiquetas están en `.rdata`; las variables de entorno asociadas son las
cadenas `...=1`:

| Etiqueta | Variable asociada | Direcciones |
|---|---|---|
| `The game's choice` | — | — |
| `4.0.2X Hybrid` | `FSR4_XMX_PRE41=1` | `0x180321E60`, `0x180323290` |
| `4.1.2X` | `FSR4_XMX_INT8=1` | `0x1803223A0`, `0x1803232A8` |
| `4.1.2X Lite` | `FSR4_XMX_LITE=1` | `0x1803223A8`, `0x1803232B8` |
| `DLSS-EX` | `FSR4_XMX_DLSSE=E` | `0x180321D08`, `0x1803232C8` |
| `DLSS-FX` | `FSR4_XMX_DLSSE=F` | `0x180321D30`, `0x1803232E0` |
| `DLSS-EFX` | `FSR4_XMX_DLSSE=A` | `0x180321D58`, `0x1803232F8` |
| `DLSS-KX` | `FSR4_XMX_DLSSK=1` | `0x180321DE0`, `0x180323310` |
| `DLSS-MX` | `FSR4_XMX_DLSSM=1` | `0x18031B978`, `0x180323328` |
| `DLSS-LX` | `FSR4_XMX_DLSSM=L` | `0x18031B970`, `0x180323340` |

Esta lista es la que el host del plugin muestra como "Model"/"Version list"
(en `OptiPluginInit`, `0x18006FC20`, ajuste `Model` en `0x180F57A10`). La
selección de una entrada termina aplicando la variable de entorno
correspondiente; `CreateModel` es quien la lee. `FSR4_XMX_DEV=1` desbloquea
la pestaña Developer, la "Version list" (`FUN_18006D040`), `HiddenEntries` y
`Profile`; el ajuste `Model` se lee aparte y no cambia por sí solo el modelo.

### 2.2 Tabla de versiones del proveedor FFX (lo que ve OptiScaler)

Independientemente de la lista anterior, el DLL expone 32 entradas de
proveedor en `0x180F2D970` (32 punteros; `FUN_180074600` recorre hasta
`0x100`). Cada entrada apunta a un registro de estado cuyos primeros qwords
son:

```text
+0x00  vtable 0x18031F088 (proveedor FSR4)
+0x08  estado byte 0 = "híbrido" (+0x207)
+0x09  estado byte 1 = Lite
+0x0A  estado byte 2 = INT8
+0x0B..+0x11  skip / DLSS / 3.1.5
```

La vtable `0x18031F088` contiene, entre otros:

| Offset vtable | Función | Papel |
|---:|---|---|
| `+0x08` | `0x1800614C0` | disponibilidad (pesos) |
| `+0x20` | `0x180065920` | nombre/versión que se muestra |
| `+0x28` | `0x1800617C0` | `CreateModel` |
| `+0x48` | `0x180063830` | dispatch/config |

Entradas FSR4 relevantes (índice = posición en `0x180F2D970`; es el valor
que acepta `FSR4_XMX_PROVIDER_INDEX`):

| Índice | Estado `+0x08` | Etiqueta | Modelo |
|---:|---|---|---|
| 0 | `0x0000000000000000` | `4.0.2X` | base, sin híbrido |
| 4 | `0x0000000000000001` | `4.0.2X Hybrid` | 4.0.2 + flag híbrido |
| 8 | `0x0000000000010101` | `4.1.2X` | híbrido + Lite + INT8 (kind 2) |
| 12 | `0x0000000000000101` | `4.1.2X Lite` | híbrido + Lite (kind 1) |
| 31 | `0x0000000000000000`, `+0x10=0x100` | `3.1.5` | fallback FSR 3.1.5 |

`FUN_1800614C0` comprueba que la entrada esté disponible: para `+0x09`
(Lite) exige `FUN_180027C00()[0] != 0`; para `+0x0A` (INT8) exige
`FUN_180027C00()[0x68] != 0`. Si no, la entrada se oculta/degrada
("Greyed: its file is missing." en `0x180323813`). `FUN_180065920` devuelve
la etiqueta: para el estado todo-cero retorna el literal `4.0.2X`
(`0x180065ADF` -> `0x180321E70`); para INT8/Lite retorna las cadenas
generadas desde `FUN_180027C00()` en `+0x69`/`+1` (véase §4).

`FSR4_XMX_PROVIDER_INDEX` se lee en `FUN_180074600` (cadena en
`0x180F2DA90`, log en `0x180F2DAD0`). Acepta un decimal 0..31 y, si la
entrada está disponible y es compatible, la fuerza. Log:

```text
[FSR4 XMX] FSR4_XMX_PROVIDER_INDEX=%zu -> %s (requested version id 0x%llx)
```

Si no está disponible: `not available here, usual choice kept`. Es la vía
para forzar la etiqueta 4.1.2X (`=8`) o 4.1.2X Lite (`=12`) sin depender del
dropdown; requiere los pesos y reiniciar el proceso (se cachea una vez).

## 3. Qué versión se reporta al llamador

Hay dos fuentes y ninguna depende de `FSR4_XMX_*`:

1. **Etiqueta del proveedor**: `FUN_180065920` (`vtable+0x20`). Para la
   entrada base (estado 0) devuelve el literal **`4.0.2X`**
   (`0x180321E70`); para `+0x8` devuelve `4.0.2X Hybrid` (`0x180321E60`).
   Es la etiqueta que aparece en la lista de versiones del proveedor
   (OptiScaler muestra `FSR 4.0.2X`/`4.0.2`, coherente con ese literal).
2. **VERSIONINFO del PE**: recurso `16/1`, `FileVersion 4.0.2.1`,
   `ProductVersion 4.0.2.1` (fijo; ver `docs/xmx412-static-inventory.md`).
   No cambia con el entorno.

Las etiquetas 4.1.2 son distintas: se generan desde el DLL de pesos oficial
en `FUN_180049950` y se guardan en la estructura de `FUN_180027C00()`; no son
literales del `.rdata`. Si el DLL oficial es 4.1.2, la etiqueta generada es
`4.1.2X`/`4.1.2X Lite`; si es 4.0.2, sería `4.0.2X`/`4.0.2X Lite`. Por eso
el archivo `fsr-original.dll` correcto es el que lleva los blobs 4.1.2
(§4), no basta renombrar cualquier DLL.

**Matiz importante para la prueba**: `FSR4_XMX_INT8=1` cambia el modelo que
se ejecuta, pero no reescribe los bytes `+0x08..+0x11` de la entrada de
proveedor que el juego ya eligió. El overlay puede seguir mostrando
`FSR 4.0.2` aunque el log confirme `INT8 model ...`. Para que el llamador
vea `4.1.2X`, hay que elegir la entrada 8/12 en el dropdown o forzar
`FSR4_XMX_PROVIDER_INDEX=8`/`12`. El log del modelo es la evidencia
autoritativa de qué se ejecutó.

## 4. Contrato de `fsr-original.dll`

### 4.1 Nombre y rutas

- Nombre exacto: **`fsr-original.dll`**. Aparece en ASCII en
  `0x180323778` (UI "Model files") y en UTF-16 en `0x18008A018` (se añade a
  la ruta). La UI dice: `Missing? Place next to this DLL, restart.`
  (`0x180323790`).
- `FUN_180005AC0` resuelve el archivo en este orden:
  1. `FSR4_XMX_LITE_DLL` (UTF-16, `0x180089FF0`), si está definida y es
     válida. Es una ruta completa **Windows** (p. ej. `Z:\...`), porque se
     pasa a `CreateFileW`. Aunque el nombre diga LITE, `FUN_180005AC0` la usa
     como ruta del DLL de pesos para Lite **e** INT8 (la estructura de pesos
     es compartida). Si la ruta falla, continúa con las dos siguientes.
  2. Directorio del propio DLL del mod + `\fsr-original.dll`
     (`GetModuleHandleExW(6, FUN_180027C00, ...)` + `GetModuleFileNameW` +
     `FUN_180043130`, que corta en el último `\`).
  3. Directorio del EXE anfitrión + `\fsr-original.dll`
     (`FUN_180043130(..., 0)`).
- No se busca en `System32`, DriverStore ni junto a `amdxcffx64.dll`.

### 4.2 Qué se verifica (no es un hash del archivo completo)

`FUN_180049950` mapea el archivo en solo lectura y escanea offsets alineados
a 16 bytes. No comprueba nombre, exports, firma ni PE; comprueba contenido:

1. Tamaño >= `0x6B01` (`0x1800499F6`).
2. En cada offset candidato, qwords en `+0x440..+0x478` deben ser cero
   (`0x180049B02`).
3. En los primeros `0x200` words UTF-16, los índices `7,15,23,...` deben ser
   cero y debe haber más de 400 words no nulos (`0x180049B50`).
4. FNV-1a64 sobre `0x6B00` bytes y sobre `0x20000` bytes desde el mismo
   offset, comparando cuatro constantes (`0x180049C1F`, `0x180049C51`,
   `0x180049C7C`, `0x180049CA6`):

| Constante | Blob | Destino | Uso |
|---|---|---|---|
| `0x0CA02A3581DE817F` | `0x6B00` | `+0x38` | Lite preset |
| `0x2DD74EE29ECB9705` | `0x6B00` | `+0x50` | Lite ultraperf |
| `0x29CE14ECDF23D42B` | `0x20000` | `+0xD8` | INT8 preset |
| `0x0DFCFD62036F9E391` | `0x20000` | `+0xF0` | INT8 ultraperf |

5. Marcador de versión: busca un par de dwords donde el segundo sea
   `0xF5A5CA1E` (`cmp [rcx+4], 0xf5a5ca1e` en `0x180049D60`), toma el mayor
   primero positivo, y extrae:
   - major = `v >> 22`
   - minor = `(v >> 12) & 0x3FF`
   - patch = `v & 0xFFF`

   para generar `%u.%u.%uX Lite` (`0x180089F80`) y `%u.%u.%uX`
   (`0x180089FA8`). Para 4.1.2 el valor empaquetado sería
   `0x01001002` (4.1.2).
6. Disponibilidad:
   - `struct[0] = 1` solo si están los **dos** blobs Lite y la versión es
     distinta de cero (`0x180049E07`).
   - `struct[0x68] = 1` solo si están los **dos** blobs INT8 y la versión es
     distinta de cero (`0x180049E26`).

`FUN_180028560` vuelve a comprobar tamaños (`0x6B00` Lite, `0x20000` INT8) y
copia/parsea los pesos al modelo. `FUN_18004A9D0` exige:
- kind 2 (INT8): `FUN_180027C00()[0x68] != 0`;
- kind 1 (Lite): `FUN_180027C00()[0] != 0`;
- si no, `Lite/INT8 model requested without verified fsr-original.dll
  weights.` (`0x18030E2E0`) y `HRESULT 0x8000000A`.

No se valida el nombre del archivo ni que sea un PE: cualquier archivo que
contenga exactamente esos blobs y el marcador pasaría. En la práctica el
origen esperado es el DLL oficial de AMD.

### 4.3 Qué DLL oficial es

El DLL esperado es el **AMD FidelityFX Upscaler DX12 oficial de FSR 4.1.2**
(`amd_fidelityfx_upscaler_dx12.dll` sin modificar), renombrado a
`fsr-original.dll`. Evidencia:

- El mod se llama `amd_fidelityfx_upscaler_dx12.dll`; su PDB es
  `F:\xmx_probe\fsr4_402\Kits\FidelityFX\upscalers\dx12\x64\Release\amd_fidelityfx_upscaler_dx12.pdb`
  (cadena en `0x180F4DF28`), es decir, la base es la librería FidelityFX
  Upscaler DX12.
- La UI de archivos de modelo lista `fsr-original.dll` junto al DLL y dice
  "Place next to this DLL, restart." (`0x180323778`, `0x180323790`).
- El loader busca los blobs de pesos de la FSR4 (tablas de `0x6B00`/
  `0x20000`), no exports de un driver.

**No es `amdxcffx64.dll`.** Esa cadena no aparece en el binario; la única
cadena `amdxc*` es `amdxc64.dll` (`0x180F2DA80`), que es un nombre de
proveedor de la tabla de versiones, no el archivo de pesos. El loader es
content-based, así que no se puede demostrar estáticamente que
`amdxcffx64.dll` falle sin tenerlo, pero no hay ninguna referencia que lo
respalde y el layout esperado es el de la librería FidelityFX.

**No es el DLL 4.1.2 modificado ni el 4.0.2 local.** Se reimplementó el
escaneo exacto de `FUN_180049950` (C, solo lectura) sobre:
- `artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll` (4.0.2,
  `3eb08656…`): 0 pares de versión, 0 blobs coincidentes.
- `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll` (mod
  4.1.2, `fadbcb50…`): 0 pares de versión, 0 blobs coincidentes.

Por tanto, copiar/renombrar el propio DLL del mod como `fsr-original.dll` no
sirve para 4.1.2X. El DLL oficial 4.1.2 no está en el repositorio; no se
inventa su SHA-256. La verificación práctica es el log del loader (§5).

## 5. Receta para Spider-Man (por proceso)

### 5.1 Archivos

1. Usar el DLL del mod 4.1.2 (`fadbcb50…`) y OptiScaler como hasta ahora.
2. Obtener el DLL oficial AMD FidelityFX Upscaler DX12 de FSR 4.1.2
   (no redistribuirlo en el repo) y renombrarlo **`fsr-original.dll`**.
3. Colocarlo:
   - junto al DLL del mod (misma carpeta que `amd_fidelityfx_upscaler_dx12.dll`),
     o
   - junto al EXE del juego, o
   - en una ruta explícita con `FSR4_XMX_LITE_DLL=Z:\ruta\amd_fidelityfx_upscaler_dx12.dll`
     (ruta Windows; `Z:` es `/` en Proton).
4. Eliminar/renombrar cualquier `fsr-original.dll` viejo (4.0.2) para no
   mezclar. Reiniciar el juego tras cambiar archivos.

### 5.2 Variables (Steam: `VAR=1 %command%`; o wrapper `env VAR=1 ...`)

Para **4.1.2X** (INT8):

```text
FSR4_XMX_INT8=1
```

Para **4.1.2X Lite**:

```text
FSR4_XMX_LITE=1
```

No definir ambas; si se definen, INT8 tiene prioridad cuando hay pesos. Para
**4.0.2X Hybrid**:

```text
FSR4_XMX_PRE41=1
```

Para dejar la elección al juego (4.0.2X por defecto), no definir ninguna de
las tres. No definir `FSR4_XMX_DLSSK/M/E` durante la prueba FSR4 (tienen
prioridad).

Ejemplo de launch options de Steam para una prueba 4.1.2X:

```text
FSR4_XMX_INT8=1 FSR4_XMX_DEV=1 PROTON_LOG=1 %command%
```

Para 4.1.2X Lite, sustituir `FSR4_XMX_INT8=1` por `FSR4_XMX_LITE=1`.

Opcionales útiles:

```text
FSR4_XMX_DEV=1                 # pestaña Developer, Version list/HiddenEntries/Profile
FSR4_XMX_PROVIDER_INDEX=8      # fuerza la etiqueta/entrada 4.1.2X (requiere pesos)
FSR4_XMX_PROVIDER_INDEX=12     # fuerza 4.1.2X Lite
FSR4_XMX_DPAS=16               # fuerza Xe2 SIMD16 (B-series); =8 fuerza DG2 SIMD8
FSR4_XMX_FS_DIAG=2             # skip rules como colores (0/2/4; bit 8 = stats)
MLSR-PROFILE=1                 # perfil por frame
FSR4_XMX_NO_DIALOG=1           # sin MessageBox en GPU sin XMX
FSR4_XMX_SHARPNESS=0.0         # 0..max; no afecta a la selección de modelo
```

`FSR4_XMX_DPAS` se lee con `getenv_s` en `FUN_18004DC90`; si no está, se
autodetecta por `INTC_D3D12_CheckFeatureSupport`. `FSR4_XMX_FS_DIAG` se lee
con `atoi` en `FUN_180068CF0`; **no existe** una variable `FS_DIAG` en este
DLL (si OptiScaler tiene la suya, es otra cosa). `FSR4_XMX_DEV` solo se
activa con el primer byte `'1'` (`0x18006FD90`).

### 5.3 Cómo saber qué modelo se usó

Buscar en stderr/`OutputDebugStringA` (Proton: `PROTON_LOG=1`, o el log de
OptiScaler):

- 4.1.2X (INT8):
  ```text
  [FSR4 XMX] INT8 model: preset weights from Z:\...\fsr-original.dll, bucket 0, Xe2 SIMD16-DPAS kernels.
  [FSR4 XMX] INT8 network kernels ready (bucket 0, preset weights).
  ```
- 4.1.2X Lite:
  ```text
  [FSR4 XMX] Lite model: preset weights from Z:\...\fsr-original.dll, bucket 0, Xe2 SIMD16-DPAS kernels.
  [FSR4 XMX] Lite network kernels ready (bucket 0, preset weights).
  ```
  (`preset`/`ultraperf` varía con el preset de calidad; `bucket` 0..2.)
- 4.0.2X/Hybrid no pasa por `FUN_18004A9D0` (kind 0), así que no imprime
  `INT8/Lite model`. Se reconoce por la entrada de proveedor elegida
  (`4.0.2X`/`4.0.2X Hybrid`), por el log de GPU
  `[FSR4 XMX] GPU GTGeneration=... -> ... kernels ...` y por el flag híbrido;
  no hay una línea "model" específica.
- Si se forzó el proveedor:
  ```text
  [FSR4 XMX] FSR4_XMX_PROVIDER_INDEX=8 -> 4.1.2X (requested version id 0x...)
  ```
- Si falta el archivo/pesos:
  ```text
  Lite/INT8 model requested without verified fsr-original.dll weights.
  %s weights are unavailable (fsr-original.dll).
  ```
  y el modelo no se carga.

**Overlay**: si el juego eligió la entrada base, el overlay puede seguir
mostrando `FFX -> FSR 4.0.2` aunque el log diga `INT8 model`. Eso es esperado:
`FSR4_XMX_INT8=1` no cambia la etiqueta de versión del proveedor. Para ver
`4.1.2X` en la lista/overlay, seleccionar la entrada 4.1.2X (requiere pesos)
o usar `FSR4_XMX_PROVIDER_INDEX=8`; para Lite, `12`.

### 5.4 Qué mirar si falla

1. ¿El log muestra `FSR4_XMX_PROVIDER_INDEX=8 -> 4.1.2X`? Si dice
   `not available here, usual choice kept`, faltan los pesos o la entrada no
   es compatible.
2. ¿Aparece `INT8 model`/`Lite model`? Si no, `CreateModel` no eligió 4.1.2:
   revisar ortografía/valor `=1`, que no haya `FSR4_XMX_DLSS*` y que el
   archivo esté en la ruta buscada.
3. ¿El path del log es el esperado? El loader prueba `FSR4_XMX_LITE_DLL`,
   luego el directorio del DLL, luego el del EXE. Un path `Z:\...` mal escrito
   falla silenciosamente y cae al siguiente.
4. ¿La versión del DLL oficial es 4.1.2? Si el marcador generado diera
   `4.0.2X`, ese archivo no es el oficial 4.1.2 (y sus blobs tampoco
   coinciden con las constantes de §4.2); no habilita las entradas 4.1.2.
5. Si el modelo carga pero falla el dispatch, los errores ya no son de
   selección: `Lite network pass %u XMX initialization/dispatch failed.`,
   `Lite ScratchBuffer too small`, `embedded Lite XMX resource pack is
   missing or invalid.`, etc.

### 5.5 Checklist rápido

- [ ] `fsr-original.dll` es el DLL oficial 4.1.2, no el 4.0.2 ni el mod.
- [ ] Está junto al DLL del mod (o junto al EXE, o en `FSR4_XMX_LITE_DLL`).
- [ ] No hay un `fsr-original.dll` viejo en otra ruta que se pruebe antes.
- [ ] Solo una de `FSR4_XMX_INT8=1` / `FSR4_XMX_LITE=1` / `FSR4_XMX_PRE41=1`.
- [ ] Sin `FSR4_XMX_DLSSK/M/E` durante la prueba FSR4.
- [ ] El log muestra `INT8 model` o `Lite model` con el path correcto.
- [ ] Si se usa `FSR4_XMX_PROVIDER_INDEX`, el log muestra el nombre esperado
      (`4.1.2X`/`4.1.2X Lite`), no `not available here`.
- [ ] El overlay puede seguir en `4.0.2`; el log manda.

## 6. Límites

- No se ejecutó nada; no hay evidencia de inyección, dispatch GPU ni readback.
  `S_OK`, un PSO o el overlay no acreditan el modelo.
- La semántica runtime exacta de "Hybrid" (+0x207) no está demostrada; solo
  se fijan el flag, el cambio de scratch y los bits de dispatch.
- No se dispone del DLL oficial 4.1.2 en el repositorio; no se fija su
  SHA-256. El contrato verificable es el escaneo de blobs/versión y el log.
- La correspondencia exacta entre la etiqueta del proveedor y el texto
  "FSR 4.0.2" de OptiScaler es inferida de `FUN_180065920` y del VERSIONINFO;
  no se instrumentó OptiScaler.
- `amdxcffx64.dll` no se pudo probar (no está local); solo se afirma que el
  binario no lo referencia y que el layout esperado es el de la librería
  FidelityFX.

## 7. Evidencia reproducible

- `tests/test_xmx412_model_strings.py` (7 tests, CPU-only, lectura):
  SHA, literales, ramas `INT8/LITE/PRE41`, prioridad, tabla de 32
  proveedores, vtable, etiquetas, constantes FNV, marcador de versión,
  generación `%u.%u.%uX` y ruta/nombre de `fsr-original.dll`.
- `python3 -m unittest tests.test_xmx412_model_strings -v`
- Desensamblado: `llvm-objdump -d --start-address=... --stop-address=...`;
  decompilado: Ghidra 12.2 headless (`analyzeHeadless`), proyecto local no
  versionado.
- Documentos relacionados: `docs/xmx412-static-inventory.md`,
  `docs/xmx412-variants.md`, `docs/compatibility.md`.
