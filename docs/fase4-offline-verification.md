# Fase 4: puente shim/ANV listo para integrar (solo CPU, sin instalar)

Objetivo cumplido: el puente queda en estado candidato, compilado y
CPU-probado, a la espera de que la traza Fase 1 confirme el layout real.
No se instaló nada, no se tocó Steam/prefijos, no se ejecutó DLL/GPU/Wine.

> Actualización 2026-11-13: los parches se regeneraron contra `662dc6e`.
> El registry sigue con 2 entradas y `registry_gen()=0x3ddd809f`; la suite
> completa pasa 415 tests (3 skips) y el cross-build nuevo está en
> `docs/shim-cross-build.md`. Las cifras de la tabla siguiente son la
> corrida histórica sobre `ef39559`.

## Verificado en esta fase

| Pieza | Evidencia |
|---|---|
| Reuse D3D12 (0003 sobre 0002) | `tools/build_context_reuse_patch.py` determinista y fijado; `patch -p1` apilado `0002 -> 0003`; `tests/test_context_reuse.py` (5 tests: pin, rechazo, stack, ABI Windows, harness CPU con matrices de device/versión y Context2; el original sale `6` sin refresco) |
| Selector perfil-por-hash | `profiles/registry.json` + `tools/pre_profile_registry.py`; `find_profile` devuelve la entrada solo para el code hash revisado, `None` (ruta legacy) para el resto |
| Bump de cache identity | `registry_gen() = 912cda6a` mezclado en `anv_cm_toolchain_gen` en ambas variantes; `patches/0001-...` regenerado, `git apply --check` limpio; `tests/test_profile_selection.py` (8 tests: registro, identidad, legacy intacto, C parametrizado con 10 layouts) |
| Compilación cruzada shim (stack completo) | Copia aislada en `/tmp`, `patch -p2` 0002+0003, cmake+ninja con LLVM-MinGW existente: **14/14 objetivos, 0 errores/warnings**, `igdext64.dll` 1.616.896 B `8afc4973…`, PE32+ AMD64, 75 exports con nombre, imports KERNEL32/ADVAPI32/UCRT (misma forma que el baseline documentado; UCRT pendiente de validación runtime como ya se sabía) |
| Suite completa | **204 tests OK** (183 baseline + 13 de esta fase + 8 de commits paralelos `603dd4b`/`c565142`) |
| Mesa completa | **No recompilada**: no hay árbol de fuentes en `build/` (solo logs previos). Cubierto por `apply --check` del 0001 regenerado + validación C sintética del bloque lector en CPU. La build Mesa documentada en `lab-mesa-build.md` sigue siendo la evidencia de compilación del driver |

## Veredicto configuración-vs-cambios

**Configuración (sin código nuevo):** overrides `IGDEXT_*`, toolchain IGC/ocloc
fijado (`profiles/intel-toolchain.json` + `registry.json`), selección del PRE
por hash (solo `registry.json`), layout `(4, 52)` de este PRE (perfil), y el
bump de identidad (generado automáticamente al regenerar 0001).

**Cambios de código (candidatos, requieren validación runtime antes de
instalar):** 0002 (copia en init), 0003 (validación + refresco en reuse),
0001 regenerado (lector CMK3 + identidad). Los tres preservan el
comportamiento global: mitades D3D11 intactas, ruta CMK2 intacta, hashes
desconocidos → legacy, errores nuevos solo donde antes había `S_OK`
silencioso sin outputs.

## Orden de integración propuesto

1. **Traza Fase 1** (prefijo descartable): layout Vulkan real del PRE.
   Comparar contra el perfil (b0@0, superficies 4..44, sampler 48, total 52).
2. **Si coincide:** congelar perfil/registro; si difiere: nueva variante en
   `registry.json` + regenerar 0001 (el bump invalida cachés solo) + casos
   parametrizados. No se espera cambio de forma del código.
3. **Runtime descartable:** probe sintético → readback PRE contra oracle CPU
   (`docs/pre-resource-descriptors.md:192-231`), con canary del driver y
   logs de inyección. Solo entonces plantear instalación reversible.
4. **Juego (Cyberpunk):** último, reversible por juego.

Nada de lo anterior copia artefactos a cachés runtime ni activa el helper con
estos perfiles; el estado sigue `experimental-offline-only`.
