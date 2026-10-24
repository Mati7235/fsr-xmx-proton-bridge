# PRE: qué puede servir de referencia independiente

No se ejecutaron nuevas pruebas GPU para esta evaluación. El PRE y FSR completo
siguen sin validar; no hay un oracle de salida disponible todavía.

## Referencia funcional

La opción más directa es capturar los recursos de entrada y salida del mismo
PRE en una implementación de referencia que ya funcione, junto con formatos,
vistas, versión del kernel, constantes y geometría. Una implementación CPU sería
otra opción, pero requiere reconstruir la semántica y validarla contra esa
referencia; no basta con traducir unas operaciones aisladas del shader.

Una captura del bridge experimental bajo Proton puede aportar el contrato del
llamador y evidencia de sus bindings. **No constituye automáticamente una salida
de referencia correcta:** el camino que se investiga podría ya estar fallando.
Hay que identificar la procedencia y el grado de validación de la salida.

## Contraste de bindings con otro frontend Intel

El zebin fijado para B580 (`3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2`)
contiene metadata de buffers stateful, imágenes y sampler. Level Zero ofrece
`ZE_MODULE_FORMAT_NATIVE` y `zeModuleCreate`; su header y bibliotecas de runtime
están presentes localmente. Eso permite investigar una segunda ruta de carga,
**no demuestra que ese zebin particular sea aceptado**.

Ejecutar el mismo kernel mediante Level Zero u OpenCL podría contrastar el ABI
del bridge contra un frontend distinto de shim/ANV, con entradas idénticas y
comparación de bytes. No sería una implementación algorítmica independiente:
conservaría el kernel y posiblemente el mismo compilador. Además, OpenCL y
Level Zero de Intel comparten el core NEO; comparar ambos no proporciona dos
referencias totalmente independientes.

Fuente de arquitectura: [Intel Compute Runtime](https://github.com/intel/compute-runtime/blob/master/ARCHITECTURE.md).
La presencia de bibliotecas no prueba que un ICD sea usable ni autoriza a
enumerar dispositivos o cargar módulos durante la inspección offline.

## Próximo gate offline de esa alternativa

Antes de preparar un experimento con otro frontend:

1. Identificar revisión/versión del Compute Runtime instalado y compatibilidad
   con el IGC/ocloc fijado; revisar su parser de zebin y versión de `.ze_info`.
2. Seguir la conversión de los doce argumentos a objetos de API, BTIs y sampler.
   No asumir que una API expuesta acepta todas las particularidades del kernel CM.
3. Resolver formatos/vistas, contenido, tamaños y geometría que todavía falten.
4. Diseñar readback, canarios y comparación independiente antes del opt-in GPU.

Si se prepara esa ruta, se registrará como **contraste de bindings/backend**, no
como validación matemática de FSR. Crear el módulo o un kernel sin comparar sus
resultados no cierra ningún gate funcional. El [contrato PRE](pre-controlled-test-contract.md)
sigue siendo el criterio de aprobación, y esta evaluación no autoriza runtime.
