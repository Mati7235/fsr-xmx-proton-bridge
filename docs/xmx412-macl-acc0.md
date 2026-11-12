# macl + acc0 en fsr4_pre_xmx 4.1.2: semántica, flujos y veredicto

CPU-only, estático. Sin ejecutar DLLs, sin GPU/Wine, sin tocar
`artifacts/original`, juegos ni prefijos. IGA y zebin solo lectura.
REA/Ghidra no desensambla ISA EU; la evidencia primaria es el IGA fijado
(`analysis/offline-pre-412/disasm/.text.fsr4_pre_xmx.asm`, 2390 líneas,
sha `7773a88b…`) más fuentes públicas IGC/Mesa citadas abajo.

## 1. Semántica exacta de `macl` (línea 444)

IGA (líneas 441-444, numeración de fichero):

```
L6024:                                                            // 441
(W)     mul (1|M0)               acc0.0<1>:d   r82.14<0;1,0>:d   r80.2<0;1,0>:uw  // 442
        shl (1|M0)               r1.1<1>:d     r80.0<0;1,0>:d    3:w               {Compacted}  // 443
        macl (1|M0)              r1.0<1>:d     r82.14<0;1,0>:d   r80.1<0;1,0>:d   {Compacted}  // 444
```

Desglose:

- Opcode `macl`, ancho `(1|M0)`, sin predicado, sin `condmod`, sin saturación.
  Ejecución incondicional bajo la máscara completa asumida.
- Destino explícito: `r1.0<1>:d` — 1 DWORD (bytes GRF 64..67).
- Fuentes explícitas: `r82.14<0;1,0>:d` (bytes 5304..5307),
  `r80.1<0;1,0>:d` (bytes 5124..5127). Ancho 1, región `0;1,0`
  (vertical 0, span 1, horizontal 0): un solo elemento.
  Ninguna solapa `r2` (bytes 128..159, semilla línea 11).
- Fuente implícita: `acc0.0` (siempre `acc0.0`, 1 elemento `:d`).
  IGC: “`macl creates an implicit src using the supplied accType.
  AccWrCtrl is not set. acc0.0 is always used” (`visa/BuildIRImpl.cpp`,
  commit `66d1f97`, `createMach/createMacl wrapper`).
  Dependencias IGA: “`mac/mach has implicitly read to acc0`” y la lista
  incluye `MACL` (`visa/iga/IGALibrary/IR/RegDeps.cpp`, `setInputsSrcDep`).
- Escritura: solo el destino GRF `r1.0`. `macl` **no** escribe `acc`
  en este modelo (conservador *no-kill*): IGC dice que `AccWrCtrl`
  **no** se activa para `macl` (a diferencia de `mach`, que crea
  “both implicit acc src and dst” y activa `AccWrCtrl`).
  `RegDeps.cpp` marca `MACL/MACH` como escritores implícitos de `acc`
  por sobre-aproximación de dependencias/SWSB; asumir la escritura
  limpiaría `taint` y sería *unsound* (falso negativo). No asumirla
  preserva `taint` (seguro; a lo sumo falso positivo, que no ocurre aquí).
  Mesa confirma el coste de acumulador: “New on Xe2, this instruction
  enables faster 32x32 integer multiply at the cost of extra accumulator
  usage”, opcode 83, 2 src / 1 dst, `GFX_GE(XE2)`
  (commit `73701c3`, `brw: wire up MACL`).
- Sin efectos laterales modelables: no `send`, no `null` con `condmod`,
  no direccionamiento indirecto (`r[`/`a0.` ausentes en todo el kernel),
  descriptores inmediatos. `{Compacted}` es anotación del finalizador,
  no cambia el footprint.
- No toca los bytes bajo análisis por operandos explícitos
  (disjuntos de `r2.0..r2.7`, offsets 0..31). El único canal restante
  sería el `acc0` implícito, que es limpio en todos los caminos vivos
  (§3). Predicado ausente: no hay supresión por lanes.

Fuentes:

- IGC `createMach/createMacl`:
  `https://github.com/intel/intel-graphics-compiler/commit/66d1f97ea95492de78c400af9dba65a0b637460f`
- IGC `RegDeps.cpp` (`setInputsSrcDep`, `setDstRegion`, par `acc0/acc1`):
  `https://github.com/intel/intel-graphics-compiler/blob/master/visa/iga/IGALibrary/IR/RegDeps.cpp`
- Mesa `MACL` Xe2:
  `https://github.com/maurossi/mesa/commit/73701c305e9ddc4087a3f68a372193a841cebed9`
- `AccWrCtrl`: “When set, the result is written to both destination and
  accumulator” (PRM Vol 2b, `AccWrCtrl`).

## 2. Todos los flujos por `acc0` (grupo `acc0/acc1`)

Modelo del auditor (`tools/audit_pre_payload.py`): `accN` explícitos por
par solapado (`(n//2)*2`; `acc0/acc1` grupo 0, `acc2/acc3` grupo 1, …,
conservador según `RegDeps`: “we always mark them together”),
más lectura implícita grupo 0 para `mac`/`macl`/`mach`.
`mac`/`macl` nunca escriben `acc` (no-kill); `mach` sigue rechazado
(`fail-closed`, no observado). Escrituras predicadas no-`sel` no matan
(unionan); `sel` sí mata (selecciona valor). `send` con `acc` se rechaza.
`acc` arranca limpio (el payload cross-thread solo está en `r2`).

Conteo estático en el IGA 4.1.2 (fichero, 2390 líneas):

- Líneas con `acc0`: 253 (viejo: 252; +1 por el `mul acc0` de la línea 442
  que alimenta a `macl`; `macl` misma no contiene la cadena `acc0`).
- Escrituras grupo 0 explícitas: 179 (`add`/`mad`/`mul`/`sel` a `acc0`,
  más `acc1` del mismo grupo). Lecturas explícitas grupo 0: 218
  (`mad`/`mul`/`cmp`/`sel`/`rnde`/`rndd`/`add` desde `acc0/acc1`,
  incl. `(abs)acc0`, `-acc2` no cuenta aquí).
- Lecturas implícitas grupo 0: 9 (8× `mac` líneas 2328-2354 + 1× `macl`
  línea 444). `mach`: 0 obserwado.
- Resto de `acc`: grupo 2 (`acc2/acc3`) y pares altos para expansiones
  `mad`/`mul`/`sel` intermedias; aislados del grupo 0.

Escrituras `acc` (muestra; `overlap_r2` = footprint GRF bruto, sin liveness):

- 174 `add acc0 = r99,-1.0`, 175 `mad acc0 = r80.7,acc0,r81.4`, …,
  212/214/216-220 (bloque `add`/`mad` en `f`), 236/251/273/… `sel acc0`,
  442 `mul acc0 = r82.14,r80.2` (alimenta `macl`), 555… `mul acc0`,
  699/702/719/721…, 1022 `add acc0`, 1031… etc. Ninguna lee `r2`
  en bruto salvo las listadas abajo.
- Escrituras `acc` que **sintácticamente** leen `r2` (vectores anchos o
  broadcast; p. ej. `r1.0<1;1,0>` ancho 32 solapa `r1-r4` incl. `r2`,
  `r2.0<0;0>` broadcast 1 DWORD):
  278/300/330/358 `sel acc2 = r1,acc0` (ancho 32, solapa `r2`),
  541 `mad acc0 = r2.0<0;0>,…` (1 DWORD 128..131),
  1027 `add acc2 = r2,…` (ancho 16, todo `r2`),
  1105 `mad acc0 = r2.0<0;0>,…`, 1590 `add acc1 = r2,…`,
  1701 `mad acc0 = …,r2`, 1740/1742/1744/1746 (`acc1/acc2/acc3 = …,r2`),
  1849 `add acc2 = r2,0.5`, 2329 `mul acc0 = r2,…`, etc.

Lecturas `acc0` (muestra):

- 176/179/182/185/189/… `rnde rX = acc0`, 238/253/281/303/333/361…
  `cmp null = …,acc0`, 244/259 `sel r61 = …,acc0`, 278/300…
  `sel acc2 = …,acc0`, 557 `mul acc0 = acc0,…` (auto-acumulación),
  702/721 `sel acc0 = acc0,0.0`, 1024 `mul r6 = …, (abs)acc0`, …,
  2328-2354 `mac …` (implícito), 444 `macl` (implícito).

¿Algún camino conecta `acc0` con los bytes bajo análisis?

No. Auditoría flujo-sensible (`audit_native` extendido, semilla línea 11,
`r2` 32 B, unión en joins, punto fijo en backedges):

- Estado: `(grf_live, acc_live)`; `acc_live` grupo→conjunto de offsets
  originales. Lectura `grf_live & usado` o `acc_taint & leído` ⇒
  `possible-read`. Escritura incondicional reemplaza; predicada no-`sel`
  une. `macl`/`mac` leen grupo 0 sin escribirlo.
- Resultado 4.1.2: `unread-before-overwrite-or-end`, 160 visitadas,
  0 lecturas, overwrites líneas 20/23/143/179/379 — idéntico al viejo.
  `macl` (idx 415) **no es alcanzable con bytes vivos** (`states` vacío);
  sus fuentes explícitas son disjuntas de `r2` y su `acc0` implícito está
  limpio en todos los predecesores vivos.
- Todas las escrituras `acc` que leen `r2` en bruto ocurren solo donde
  `grf_live` ya es vacío (tras los kills 20/23/143/179/379 en esos
  caminos): el análisis podado por `live` nunca las visita con `live`
  no vacío, luego nunca introducen `taint` (`new_from_grf = live & usado`
  vacío) y nunca reportan. Ninguna instrucción que escribe `acc`
  con `live` no vacío lee `r2`; por tanto `acc_live` permanece vacío
  en todos los estados alcanzables y todas las lecturas `acc0`
  (explícitas + 8×`mac` + 1×`macl`) son limpias.
- Aislamiento de grupos verificado por tests: `acc2` manchado no
  contamina `macl` (grupo 0); `acc0→acc1` sí contamina (mismo par).

## 3. Veredicto

Con el modelo mínimo y conservador `macl`+`acc0` (sin relajar nada:
`mach` y opcodes desconocidos siguen rechazados, `send` con `acc`
rechazado, regiones no modeladas conservadoras o rechazadas):

- IGA 4.1.2 `fsr4_pre_xmx`: **no lectura antes de sobrescritura o fin**,
  bajo máscara completa y constante, GRFs 64 B, descripciones `send`
  del IGA. 160 visitadas, 0 lecturas posibles, overwrites
  20 (0..1), 23 (2..3), 143 (4..15), 179 (4..31), 379 (4..31).
- `macl` línea 444 benigno: operandos disjuntos de `r2`, `acc0`
  implícito limpio, incondicional, sin side-effects a `r2`.
- Perfil `profiles/fsr4-pre-412-native1080-payload-audit.json`
  actualizado a `static-analysis-only` / `unread-before-overwrite-or-end`
  (era `static-analysis-blocked`); `runtime_approved=false` se mantiene.
  `build_report` sigue rechazando por pins viejos (correcto
  *fail-closed* de identidades, no bug). `mach` sigue rechazado.
- Esto **no** autoriza runtime, ni generaliza a otras variantes/stages/
  máscaras. Alcance: un kernel/input/output revisado.

Reproducción (solo CPU):

```bash
python3 -m unittest tests.test_xmx412_payload_macl -v
python3 -m unittest tests.test_pre_payload_audit -v
python3 <<'PY'
import sys; sys.path.insert(0,'tools')
from audit_pre_payload import audit_native
print(audit_native(open('analysis/offline-pre-412/disasm/.text.fsr4_pre_xmx.asm').read(),11))
PY
```
