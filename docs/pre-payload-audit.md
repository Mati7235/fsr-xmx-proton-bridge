# Auditoría estática de los cuatro campos de payload del PRE

## Conclusión sin jerga

Los cuatro campos que parecían direcciones faltantes **no se leen antes de ser
sobrescritos o de terminar el kernel**, según el análisis del código nativo
revisado, **suponiendo una máscara de ejecución completa y constante**.

Para este PRE compilado no hay evidencia de que debamos inventar direcciones GPU
y colocarlas en esos campos. Mantenerlos en cero es compatible con este resultado
estático condicionado. Esto **no autoriza una prueba runtime** ni generaliza a
otros kernels, compiladores, variantes o máscaras de ejecución.

Antes solo sabíamos que el compilador los declaraba y que upstream los dejaba en
cero. Eso era un pendiente de investigación, **no un fallo funcional demostrado**.

## Alcance e identidades

Mismos input, opciones y compilador que en [la compilación offline](offline-pre-compilation.md):
PRE Xe2 40102 native_1080, B580 target 0xe20b, IGC 2.10.10+18926.

- CM completo: `76942f6cff52b09ea8fef63adfce8b4119fcd45c8c0586c913eedb9e35fe773b`.
- Zebin: `3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2`.
- Código nativo: `2e42d33c13d6c93bfe86fa81b1427c92aa2980df1af0100e011753a067f8ed5f`.
- Disassembly IGA emitido por ocloc:
  `a9c82bbfccc535959e73ddd6b80fb209ed8a12bf8607927f62078b43b6215660`.
- SPIR-V textual del `.spv` embebido:
  `7ed1d81b8127e9dbb1e0c5befa621060cf7ab47cd82f98f789099b7968db6a9e`.

La asociación de los desensamblados con el binario se estableció ejecutando solo
los desensambladores offline sobre el zebin fijado. El auditor rechaza cambios de
hash; no pretende verificar por sí mismo un decodificador ISA general. También
comprueba que el `.spv` embebido coincida byte a byte con el comienzo del CM input.
No carga la DLL ni hace dispatch GPU.

## Evidencia IR y código nativo

### 1. Los tres argumentos de buffer son superficies opacas

En SPIR-V, los parámetros de argumentos 0, 9 y 10 tienen tipo
`OpTypeBufferSurfaceINTEL ReadWrite`, no un puntero genérico de 64 bits.
El entry wrapper los pasa en el mismo orden a la función principal. En esa función,
cada uno tiene **un único uso directo**: `llvm.genx.address.convert.i32.p1intel.buffer_rw_t`.

Esa conversión produce un SurfaceIndex. **No significa que los recursos sean
inútiles:** el kernel sí accede a ellos mediante BTIs 8, 10 y 11. La auditoría no
confunde el argumento de recurso con los ocho bytes extra declarados por el backend.
`private_base_stateless` es un campo implícito, no otro parámetro del entry point.

### 2. El prólogo carga los 32 bytes, pero no basta con ver esa carga

Según el desensamblado, el prólogo carga el bloque cross-thread en el GRF `r2`.
Los offsets relativos y tamaños son:

| Campo | Bytes del bloque |
|---|---|
| private_base_stateless | 0..7 |
| puntero extra de arg 0 | 8..15 |
| puntero extra de arg 9 | 16..23 |
| puntero extra de arg 10 | 24..31 |

El primer mensaje carga IDs locales en `r1` desde base + 32 + thread*64; el segundo
carga los ocho DWORDs cross-thread en `r2` desde la base. Esa disposición coincide
con el código de payload del parche ANV upstream. No prueba una ejecución observada.

### 3. Seguimiento por byte y ramas

`tools/audit_pre_payload.py` mantiene el conjunto de bytes originales todavía
presentes en `r2`. En cada instrucción:

1. Comprueba las lecturas **antes** de aplicar escrituras.
2. Elimina solamente bytes sobrescritos de manera incondicional bajo la máscara asumida.
3. No elimina bytes por un `mov`/`send` predicado.
4. Para `sel`, el predicado selecciona el valor; no suprime la escritura del destino.
5. Une con **unión** los bytes vivos de todas las ramas; admite backedges hasta punto fijo.
6. Termina una ruta en EOT o cuando ya no queda ningún byte original.

Resultado: **160 instrucciones visitadas con algún byte original vivo; cero
lecturas posibles de esos bytes** bajo los supuestos declarados. Las rutas que
abandonan temprano el kernel pueden terminar con bytes aún presentes, pero no leídos.

Algunos puntos de sobrescritura registrados en el ASM fijado:

- Líneas 20 y 23: reemplazo de los bytes 0..3 mediante selecciones.
- Línea 143: una escritura de cuatro DWORDs reemplaza bytes restantes de 4..15 en esa ruta.
- Línea 179: escritura vectorial reemplaza los bytes restantes en una ruta posterior.
- Línea 379: respuesta de sampler reemplaza los bytes restantes en otra ruta.

El análisis no solo busca nombres de registros ni mensajes stateless. Si detectara
un uso original como dato aritmético, también lo marcaría como lectura posible.
Una lectura posible sería un pendiente, no una prueba de que afecte al resultado.

### 4. No confundir padding del send con datos leídos

Un mensaje transpuesto `d32x4t.a32` usa una dirección escalar de 32 bits y cuatro
componentes de datos. Que el payload reserve un GRF de 64 bytes no significa que
lea todas sus posiciones. El auditor modela esos tamaños reales; para fuentes de
sampler/typed sends usa el rango físico como aproximación conservadora.

Fundamento de semántica, fuentes Intel fijadas a la misma versión:

- [SEL](https://github.com/intel/intel-graphics-compiler/blob/v2.10.10/documentation/visa/instructions/SEL.md):
  `dst[i] = Pred[i] ? src0[i] : src1[i]` para canales con EM habilitado.
- [LSC_UNTYPED](https://github.com/intel/intel-graphics-compiler/blob/v2.10.10/documentation/visa/instructions/LSC_UNTYPED.md):
  transpose consume una dirección y componentes sucesivos; requiere SIMD1.

## Condiciones que siguen abiertas

- **Máscara de ejecución:** el resultado supone todos los canales relevantes activos,
  sin cambios de EM durante el kernel. Un canal deshabilitado podría preservar bytes
  que una lectura posterior con otra máscara alcanzara. El driver upstream fuerza
  dispatch SIMD32 y escala local_size.x por 32; falta compilar/validar la ruta real.
- **Decodificación:** tamaños y operación de los mensajes proceden del IGA incluido
  en la toolchain fijada. El auditor no verifica cada bit del descriptor de manera independiente.
- **Tamaño de GRF:** solo se modelan los 64 bytes de este target Xe2.
- **IR:** se verifica el uso directo de los parámetros, no un análisis semántico
  completo de cada función; la prueba de los bytes extra se apoya en código nativo.
- **Alcance:** un solo kernel/input/output revisado. Otros outputs se rechazan.
- Sampler dinámico, dimensiones locales, layout runtime VKD3D y copia de contexto
  siguen pendientes. No se instaló ni compiló Mesa ni se cambiaron archivos del juego.

El perfil mantiene estado experimental y `runtime_approved=false`. No se añadió
un parche para rellenar direcciones no usadas ni se relajaron canaries.

## Reproducción

Desde la raíz, con el zebin y toolchain locales ya verificados:

```bash
mkdir -p analysis/pre-payload
LD_LIBRARY_PATH="$PWD/artifacts/extracted/intel-toolchain/igc/usr/local/lib:$PWD/artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu" \
artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1 disasm \
  -file "$PWD/analysis/offline-pre/full/pre_bmg.bin" \
  -dump "$PWD/analysis/pre-payload/disasm" -device bmg-g21

python - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, 'tools')
from inspect_zebin import sections
p = Path('analysis/offline-pre/full/pre_bmg.bin')
Path('analysis/pre-payload/embedded.spv').write_bytes(sections(p.read_bytes())['.spv'])
PY
spirv-dis analysis/pre-payload/embedded.spv -o analysis/pre-payload/embedded.spvasm
python tools/audit_pre_payload.py analysis/cm-payloads-0001/module-0000.cmspv \
  analysis/offline-pre/full/pre_bmg.bin \
  analysis/pre-payload/disasm/.text.fsr4_pre_xmx.asm \
  analysis/pre-payload/embedded.spvasm > analysis/pre-payload/report.json
cmp profiles/fsr4-pre-native1080-payload-audit.json analysis/pre-payload/report.json
python -m unittest discover -s tests -v
```

El desensamblador informó `Warnings: unexpected padding at end of kernel` y exit 0.
Se conservó el log. Hay instrucciones `illegal` de padding después del EOT, sin
ruta alcanzable desde el prólogo. El auditor rechaza alcanzarlas con bytes vivos.

Los tests incluyen lecturas reales, escrituras parciales y predicadas, uniones de
ramas, loops, lectura previa a escritura, respuestas de carga cortas y padding de
mensajes. Esas pruebas verifican el analizador limitado, no la salida de imagen GPU.
