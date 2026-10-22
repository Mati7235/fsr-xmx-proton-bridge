# Reconstrucción de opciones y recursos del PRE

## En pocas palabras

PRE es la etapa inicial que prepara los datos antes del reescalado. Reconstruimos
su pedido al controlador y el orden de sus casilleros de recursos, sin ejecutar
el mod. Encontramos un desfase de un casillero en el mapeo automático del puente
al compararlo con el código de referencia de VKD3D. Todavía no es una prueba en GPU.

También corregimos una sospecha anterior: las opciones encontradas junto al kernel
viajan **dentro del bloque de bytecode**. Los dos punteros de opciones de la API
son NULL en el PRE inspeccionado. No hay evidencia de que el filtro de opciones
externas del helper elimine estas opciones embebidas.

## Avance posterior

La [compilación offline del PRE](offline-pre-compilation.md) ya confirmó los BTIs
y el consumo de las opciones embebidas. Existe un perfil y un lector candidato
CMK3, todavía no instalados ni validados en GPU. Las secciones de pendientes de
este documento describen el estado previo a esa compilación.

## Alcance y revisiones

- DLL SHA-256: `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53`.
- xess-xmx-linux: `ef39559d26e083ce1bd1353b2e8c86f33c3c264c`.
- VKD3D de referencia: `ef9a02e873715c9e2da0d6db8a236aca8380b303`, clonado localmente
  en `upstream/vkd3d-proton`. **No es identificación del Proton instalado**.
- Solo se reconstruyó el PRE normal. Las otras etapas requieren su propio análisis.
- Todos los datos siguientes son estáticos; no se cargó la DLL con Wine/LoadLibrary.

## 1. Los bloques CM tienen un pie con longitudes verificables

Formato recuperado, sin incluir padding de alineación del pack:

```text
SPIR-V [N bytes]
cadena A terminada en NUL
cadena B terminada en NUL
u64 little-endian: N
u64 little-endian: tamaño del pie completo
11 bytes: "-vc-payload"
```

El pie completo empieza en A e incluye el marcador final. No es necesario
adivinar el fin del SPIR-V recorriendo instrucciones: el pie declara su longitud.
Las cadenas son ASCII y cada pie tiene exactamente dos terminadores NUL.

Valores observados:

| Pack | Cadena A | Cadena B | Pie |
|---|---|---|---:|
| 40101 | `-vc-payload` | ` -target-features=+ocl_runtime` | 70 bytes |
| 40102 | `-vc-payload -Xfinalizer '-noDPASMacro'` | la misma | 97 bytes |
| 40103 | ambas variantes según registro | la misma | 70 o 97 bytes |

El espacio inicial de B y las comillas simples de A se preservan. No normalizarlos
ni reconstruir una línea de shell a partir de ellos.

`tools/parse_cm_payloads.py` valida la coherencia de cada pie con el magic inicial,
los límites del buffer y ambas cadenas. Recupera **252 + 252 + 186 = 690 bloques**.
Todos los IR extraídos se desensamblaron con `spirv-dis`, sin errores. Esto **no**
equivale a `spirv-val`, compilación IGC o corrección GPU.

El pack 40101 contiene además 18 contenedores DXBC detectados por magic y tamaño,
y seis huecos adicionales con contenido no nulo aún no clasificado. No se afirma
haber decodificado todo el formato del pack.

### Los seis módulos que faltaban

Son POST reales y recuperables. El carver anterior interpretaba los primeros bytes
de `-vc-payload` como una instrucción: word `0x2d63762d`, count falso 11619. Cuando
había un hueco grande después del POST podía seguir avanzando por datos ajenos al
SPIR-V. No era evidencia de corrupción de los kernels. El parser nuevo usa los
pies y recupera las 18 variantes POST de 40101.

## 2. Qué envía realmente la DLL a la API

Función PRE: `0x18002bb60..0x18002d447`.

- `0x18002c8cf..0x18002c914`: construye el descriptor INTC.
- Bytecode pointer en descriptor `+8`; longitud en `+16`.
- ShaderInputType en `+24` = **2, CM_SPIRV**.
- CompileOptions `+32` = **NULL**.
- InternalOptions `+40` = **NULL**.
- `0x18002cb00`: llamada indirecta a CreateComputePipelineState.

La longitud se copia de la tabla de la variante seleccionada, sin recorte posterior.
Se leyeron las tablas directamente de la DLL y se contrastaron con los pies:

| PRE native_1080 | IR | Pie | BytecodeLength real |
|---|---:|---:|---:|
| Pack 40101 | 329008 | 70 | **329078** |
| Pack 40102 | 330108 | 97 | **330205** |

Las **18 variantes de ambos packs** coinciden exactamente con `IR + pie`, sin
padding. Evidencia de tablas: RVA `0x56160`, stride `0x4f0`, PRE en `+0xd8`,
offset en `+8` y longitud en `+0x10` del registro PRE; tabla alternativa RVA
`0x613b0`, stride `0xf0`, offset `+0`, longitud `+8`.

El shim persiste todos los bytes de `CS.BytecodeLength` en DynKernelId
(`shim/src/dll/D3D12Api.cpp:43-81`). Por tanto, en esta ruta no hay recorte explícito
del pie. **Pendiente:** comprobar con IGC/ocloc que se interpreten las opciones
embebidas y qué binario generan. No pasar al compilador el `.spv` recortado pensando
que reproduce exactamente el pedido original: usar el `.cmspv` completo para esa comparación.

### Selección del pack Xe2

La función de selección en `0x1800329d0` consulta OPTIONS2 y escribe el flag de
contexto `+0x834` según `SIMD16Required` y éxito de la consulta (`0x180032d07..29`).
El flag no es una comparación directa de GTGeneration. El valor de entorno
`FSR4_XMX_DPAS`, si se procesa la ruta de override, lo reemplaza según sea 16 o no.
Flag no nulo selecciona pack 40102; el diagnóstico de fallo lo llama pack Xe2.
El loader `0x18001a450` relaciona selectores 0/1/2 con RCDATA 40101/40102/40103.

No fijar esos overrides para ocultar una detección incorrecta durante las pruebas.

## 3. Mapa de recursos: qué casillero es cada cosa

Una *root signature* es el listado de casilleros que el shader espera. Un
*descriptor* es la ficha que apunta al recurso real. Un *sampler* indica cómo leer
una textura (por ejemplo, interpolar y limitar coordenadas a los bordes).

Construcción de root signature: `0x18002c13f..0x18002c4bd`.

- Root 0: una constante de 32 bits, b0, espacio 0.
- Roots 1..11: once tablas de recursos, un descriptor por tabla.
- Root 12: tabla de sampler, un descriptor s0.
- Visibilidad ALL; espacio 0; offset de rango 0; flags 0.
- Root signature 1.0; **cero samplers estáticos**.

Ruta normal de dispatch, `0x1800163c0..0x180017b6e`, branch `dil == 0`:
`SetComputeRootDescriptorTable` en `0x180017428` asigna roots 1..11 usando el array
RVA `0x68988`; la asignación final en `0x180017543` usa root 12 para el heap sampler.
La rama alternativa `dil != 0` usa otro esquema y no está cubierta por este mapa.

| Root | Registro | Tipo de parámetro esperado en PRE | Slot relativo en heap de recursos | Offset push de referencia |
|---:|---|---|---:|---:|
| 0 | b0 | constante de un DWORD | — | 0 |
| 1 | u0 | BufferSurface ReadWrite | 7 | 4 |
| 2 | u1 | Image2D ReadWrite | 8 | 8 |
| 3 | t0 | Image2D ReadOnly | 0 | 12 |
| 4 | t1 | Image2D ReadOnly | 1 | 16 |
| 5 | t2 | Image2D ReadOnly | 2 | 20 |
| 6 | t3 | Image2D ReadOnly | 3 | 24 |
| 7 | t4 | Image2D ReadOnly | 4 | 28 |
| 8 | t5 | Image2D ReadOnly | 5 | 32 |
| 9 | t6 | Image2D ReadOnly | 6 | 36 |
| 10 | t7 | BufferSurface ReadWrite | 9 | 40 |
| 11 | t8 | BufferSurface ReadWrite | 10 | 44 |
| 12 | s0 | sampler (heap separado) | 0 del heap sampler | 48 |

**Límite:** el orden y los slots de las tablas están reconstruidos. La columna de
tipos corresponde al orden de parámetros del entry point; no es todavía una
comprobación de BTIs del zebin compilado. No identificamos aún cada textura como
'color', 'profundidad', 'vectores de movimiento', etc. No inventar esos nombres.
Tampoco confundir acceso ReadWrite del tipo CM con rango UAV: t7/t8 son rangos SRV
según la root signature, aunque su tipo SPIR-V se declare ReadWrite.

Slots relativos = base GPU G + incremento S * slot. No son direcciones físicas
reales ni índices absolutos de la sesión del usuario.

## 4. Desfase concreto al compararlo con el puente

En VKD3D de referencia, `libs/vkd3d/state.c:670-731,891-919`:

- La constante aporta 4 bytes.
- Todas las tablas, incluida la del sampler, aportan un DWORD cada una.
- Tamaño push total = **4 + 12*4 = 52 bytes**.
- Las tablas de recursos ocupan `[4,48)`; el sampler ocupa `[48,52)`.

`libs/vkd3d/command.c:7711-7717,7760-7766` repackea las tablas por orden y emite esos
DWORDs en el rango. La cuenta de tablas no excluye samplers.

El parche ANV actual usa (`patches/0001-anv-cm-kernel-injection.patch:700-720`):

```text
base = push_size - 4 * nsurf
     = 52 - 4*11
     = 8
```

Por eso leería offsets `[8,12,...,48]`, correspondientes a roots **2..12**, en vez
de `[4,8,...,44]`, roots **1..11**. Se omite u0 y se trata el índice de la tabla s0
como si apuntara al heap de recursos.

Es una incompatibilidad estática concreta **bajo este layout de referencia y el
orden de superficies asumido por el packer**. Falta corroborar el layout de la
versión real de Proton y el orden de BTIs antes de considerarla demostrada en runtime.

### Sampler: coincidencia parcial, no otro bloqueo demostrado

Template en RVA `0x72a20`: Filter `0x15` = MIN_MAG_MIP_LINEAR y AddressU/V/W `3` = CLAMP.
Creación en `0x18002cc23..0x18002cc8b`; LOD bias 0, anisotropía 1, comparación ALWAYS,
border 0, MinLOD 0, MaxLOD FLT_MAX según asignaciones del descriptor.

ANV no toma ese sampler dinámico: sin sampler estático usa fallback linear/clamp.
Coinciden filtro y modos de borde, pero no es soporte general de samplers dinámicos
ni equivalencia completa del estado (por ejemplo ANV MaxLOD=14). Falta contrastar
qué instrucciones de muestreo usa PRE y cómo interpreta sus coordenadas.

## 5. Adaptación mínima propuesta (no aplicada)

1. Canal explícito de metadata por kernel/layout para que el helper/packer indique
   dónde empieza la tabla de superficies y su orden; **no** cambiar globalmente
   todos los kernels XeSS a base 4.
2. Para este PRE de referencia, base esperada 4 y once superficies; excluir el
   DWORD de sampler. Confirmar orden `arg_index -> BTI` con IGC primero.
3. Separar selección de heap/slot de recursos y tratamiento de sampler. No usar
   el índice sampler para acceder al heap de recursos.
4. Mantener el blob CM completo con sus opciones embebidas al compilar offline.
5. Corregir de forma independiente la información de GPU que no se copia al
   llamador en CreateDeviceExtensionContext/Context1.

No basta con copiar DLLs. El siguiente hito útil es compilar este PRE offline y
examinar su zebin: argumentos, BTIs, GRFs, payloads y efectos de las opciones.
No requiere ejecutar Cyberpunk ni la DLL del mod.

## Reproducción de esta etapa

```bash
# Requiere los packs ya descomprimidos de la primera investigación.
for n in 0000 0001 0002; do
  python tools/parse_cm_payloads.py \
    analysis/fsr-resources/resource-$n.raw analysis/cm-payloads-$n
done
python tools/reconstruct_pre.py \
  artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll \
  > analysis/pre-reconstruction.json
python -m unittest discover -s tests -v
```

El parser conserva dos archivos por registro: `.spv` para desensamblado y `.cmspv`
con el pie completo para reproducir la entrada al compilador. Reportes generados:
`analysis/cm-payloads-*/manifest.json`, `analysis/cm-payloads-verification.json`,
`analysis/pre-reconstruction.json`, `analysis/recovered-six.json`.
Los archivos de terceros y derivados no se incorporan a Git.
