# Primera investigación: packs y ABI

## Actualización posterior

Ver [pre-resource-map.md](pre-resource-map.md). El parser por pies recupera **690**
bloques, incluidos los seis POST que el carver heurístico omitía. En PRE se
confirmaron CompileOptions/InternalOptions **NULL**: las cadenas viajan dentro
del bytecode y el shim las preserva. La hipótesis de pérdida de esas opciones
por el filtro del helper no está demostrada y queda corregida para este caso.
Este documento conserva los hallazgos iniciales como registro histórico.

## Resultado

Se extrajeron los recursos de la DLL sin cargarla ni ejecutarla, se descomprimieron
los tres packs LZMS y se recuperaron **684 candidatos CM-SPIR-V** que `spirv-dis`
pudo desensamblar. Esto demuestra que podemos inspeccionar kernels reales;
**no demuestra compilación IGC, ejecución ni compatibilidad GPU**.

## Recursos

| RCDATA / idioma | Bytes comprimidos | Bytes descomprimidos | Candidatos recuperados |
|---|---:|---:|---:|
| 40101 / 1033 | 6.454.442 | 36.151.282 | 246 |
| 40102 / 1033 | 3.777.348 | 23.164.789 | 252 |
| 40103 / 1033 | 2.229.762 | 13.528.965 | 186 |

La asociación exacta entre ID de recurso y selección de arquitectura/modelo
requiere seguir las referencias de la DLL; no se debe deducir solo por el orden.
El primer pack contiene 252 ocurrencias de magic SPIR-V pero solo 246 candidatos
pasaron el carving actual: faltan investigar seis casos. No llamar a este proceso
un parser completo del contenedor ni afirmar que extrajo todos los kernels.

SHA-256 de los packs descomprimidos:

- 40101: `486b16078b5f90f0b577d5eac3851f81c88f5b0b706444f0d908cdc320223b6c`
- 40102: `8b520078fd9457593d6cf726f79802634a4fcbd5372819f81c7e359ecec39d24`
- 40103: `f6d884bc26735c04ca2fa57d70ed31d3db3de48c3b0444121cf70a2937987999`

## Método y verificación

1. `extract_resources.py`: parser PE mínimo con biblioteca estándar, traducción RVA
   y recorrido acotado del árbol de recursos. No LoadLibrary ni Wine.
2. Cabecera de Compression API `0a51e5c0`, algoritmo 5 = LZMS, bloques de 65.536 bytes.
3. `binary-refinery==0.11.2` instalado en `.venv` aislado falló con errores de offset
   LZMS en los tres packs. No se aceptó salida parcial ni se usó modo lenient.
4. Se compiló **localmente**, sin `make install`, wimlib en revisión
   `cd5e231c348c255ae5088873b5a66ee0eb96fa07`.
5. `decompress_mscf.py` valida CRC de cabecera, límites de tamaño, tamaño exacto y
   ausencia de sobrantes; usa únicamente la API de descompresión de libwim local.
6. `carve_spirv.py` busca magic, recorre instrucciones acotadas y exige entry point
   y fin OpFunctionEnd. Conserva offsets, hashes y cadenas en los huecos.
7. Los 684 candidatos se desensamblaron sin error. El validador `spirv-val` falla en
   el primer módulo de 40102 con `TypeBufferSurfaceINTEL must appear in a block`.
   Por tanto, no afirmar validación semántica SPIR-V general. Debe contrastarse con
   las herramientas Intel/IGC para este dialecto CM.
8. Doce pruebas sintéticas de parsers y rechazo de entradas malformadas pasan.
   No cubren aún un round-trip de LZMS ni ejecución GPU.

Artefactos y reportes completos: `analysis/fsr-resources/`, `analysis/kernels-*`,
`analysis/disassembly-check.json`. Todo está excluido de Git.

## Kernel representativo

`analysis/kernels-0001/module-0000.spv`, offset 0 del pack 40102:

- Entry point `fsr4_pre_xmx`, modelo `Kernel`, SPIR-V 1.1.
- Extensiones `SPV_INTEL_vector_compute` y `SPV_KHR_no_integer_wrap_decoration`.
- Modelo de memoria Physical64/OpenCL.
- SubgroupSize = 1; no LocalSize literal observado en los modos de ejecución.
- Parámetros de entrada: **11 superficies y 1 sampler**:
  - 3 BufferSurfaceINTEL ReadWrite;
  - 1 Image 2D ReadWrite;
  - 7 Image 2D ReadOnly;
  - 1 Sampler.
- El pack 40102 incluye 18 variantes por nombre de las 14 familias PRE/P1..P12/POST.
- El pack 40103 contiene `lite_p1a`, `lite_p1b`, `lite_p2`, `lite_p3`, `i8_p6`,
  `i8_fnb64`, PRE y POST.

El tamaño de workgroup NO debe inferirse de los mensajes baseDispatch de la DLL.
La conversión de esos parámetros a zebin/BTI todavía no se ha verificado.

## Incompatibilidades y candidatos a adaptación

### 1. Información de GPU no propagada al llamador

En upstream `shim/src/dll/IgdextApiDll.cpp:343-500`, las variantes original y
Context1 crean `INTCExtensionInfo1` temporal, inicializan las extensiones y no copian
sus resultados al `INTCExtensionInfo` del llamador. Ambas reciben la estructura
antigua; **Context2**, no Context1, recibe la extendida.

El mod contiene diagnósticos/selección por GTGeneration y paquetes Xe2. El efecto
real de recibir ceros o información no inicializada todavía debe demostrarse,
pero es una incompatibilidad concreta de la implementación de la API.

Candidato: copiar explícitamente el subobjeto base de información de dispositivo y
los campos de driver tras éxito. No hacer memcpy de 200 bytes a la estructura de
192 bytes (tamaños derivados del ABI Windows x64, pendientes de static_assert).
Revisar también la devolución anticipada para contexto preexistente.

### 2. Opciones del compilador descartadas

En el hueco inmediatamente posterior al primer módulo 40102 aparece:

```text
-vc-payload -Xfinalizer '-noDPASMacro'
 -target-features=+ocl_runtime
```

Se repite el primer texto en los 252 candidatos de ese pack. Son cadenas adyacentes,
no una captura de los argumentos de la llamada: reconstruir aún el formato del
registro para establecer con certeza CompileOptions vs InternalOptions.

`tools/cm-compile.sh:42-54` solo conserva tokens con prefijos `-doubleGRF` o `-ze-`;
descartaría `-vc-payload` y la configuración de finalizer. `InternalOptions` tampoco
se persiste. Esto altera la solicitud de compilación respecto de las cadenas del
pack; no se ha determinado si provoca error o resultados incorrectos.

Candidato: preservar opciones relevantes y valores de manera explícita y probada,
incluirlos en cache identity y comparar el zebin antes de ampliar indiscriminadamente
las opciones admitidas.

### 3. Tabla de sampler y superficies

El PRE observado tiene **11 superficies + sampler**. La DLL incluye la cadena de
ABI 'one table per SurfaceIndex/sampler'. ANV asume que las últimas N palabras de
push constants son tablas de superficies, pero trata samplers aparte.

Una tabla de sampler al final o intercalada puede desplazar los índices. Esto es
un riesgo concreto de layout, no una incompatibilidad ya probada: falta reconstruir
la root signature real. El packer admite `--heap` y `--surf` explícitos, pero el
helper los fuerza a `auto`. Podría ser el canal mínimo de adaptación si confirmamos
el mapa.

### 4. Aspectos que no deben confundirse con soporte

- Contexto acepta 4.20.0 por comparación de versión, no porque implemente todo el SDK.
- ShaderInputType debe ser CM_SPIRV=2; SPIRV=4 es otra ruta.
- GetCachedBlob devuelve E_NOTIMPL; en el mod podría ser solo diagnóstico.
- S_OK puede corresponder a un placeholder/no-op. Se necesita evidencia de inyección
  y readback GPU para dar por válida la ruta.

## Próxima etapa

1. Reconstruir los límites/registros de los packs para extraer opciones exactas y
   explicar los seis candidatos no recuperados de 40101.
2. Mapear referencias a recursos de la DLL, selección Xe2 y creación de root signatures.
3. Preparar una corrección pequeña del contexto con pruebas de layout/copia.
4. Compilar un kernel representativo de forma offline con la toolchain Intel y
   comparar metadatos zebin con el packer (no requiere ejecutar la DLL ni GPU).
5. Solo después de autorización, microtest aislado de GPU; no Cyberpunk como primer test.

## Reproducción

Desde la raíz, con archivos originales ya presentes:

```bash
python tools/extract_resources.py \
  artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll \
  analysis/fsr-resources

# Compilar dependencia local; no instalar en el sistema.
git clone https://github.com/ebiggers/wimlib.git upstream/wimlib
git -C upstream/wimlib checkout cd5e231c348c255ae5088873b5a66ee0eb96fa07
(cd upstream/wimlib && ./bootstrap && \
 ./configure --without-ntfs-3g --without-fuse && make -j4)

for n in 0000 0001 0002; do
  python tools/decompress_mscf.py \
    analysis/fsr-resources/resource-$n.bin \
    analysis/fsr-resources/resource-$n.raw \
    --libwim upstream/wimlib/.libs/libwim.so
  python tools/carve_spirv.py \
    analysis/fsr-resources/resource-$n.raw analysis/kernels-$n
done
python -m unittest discover -s tests -v
```

Los extractores rechazan sobrescrituras; usar directorios nuevos al repetir.
Se necesita toolchain de compilación/autotools para wimlib y SPIRV-Tools para los
chequeos externos. No es necesario instalar binary-refinery para la ruta exitosa.

Fuentes de formato/API:
- https://wimlib.net/apidoc/group__G__compression.html
- https://github.com/ebiggers/wimlib
- https://github.com/binref/refinery/blob/master/refinery/units/compression/mscf.py
- https://github.com/KhronosGroup/SPIRV-Headers/blob/main/include/spirv/unified1/spirv.core.grammar.json
