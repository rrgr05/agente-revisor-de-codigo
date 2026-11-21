# Seguridad

## Qué protege el agente

El Agente revisor de código lee código que puede no ser de confianza y lo envía a un modelo de IA. Para
reducir los riesgos:

| Riesgo | Medida |
|---|---|
| Que cambie o rompa algo | Sin herramientas de escritura ni de órdenes; prohibidas en los permisos y bloqueadas por un *hook* que, si falla, bloquea. |
| Que lea fuera del proyecto | El *hook* solo permite la carpeta del proyecto: sin `..`, rutas de red, otras unidades, enlaces que salgan fuera ni patrones absolutos. |
| Que envíe secretos a la API | No se leen ni se busca dentro de los archivos y carpetas de secretos de `revisor/config.py`; `Grep` en carpetas solo admite patrones de archivos de código o tipos de lenguaje (lista blanca), en todos sus modos. |
| Que saque código a internet | Solo el investigador tiene internet, y no puede leer el proyecto; solo `https` a servidores públicos (se resuelve el nombre y se comprueba que no sea una dirección interna), con búsquedas, direcciones y encargos de longitud limitada. |
| Que gaste de otro sitio | Configuración de Claude Code aislada, variables de otros proveedores quitadas y parada si la sesión no usa `ANTHROPIC_API_KEY`. |
| Que gaste de más | Tope de gasto por revisión (`--tope`). |
| Instrucciones escondidas en el código | Se le indica al modelo que el código son datos; las barreras anteriores no dependen de que obedezca. |

## Límites conocidos

- **La lista de secretos es por nombre.** Un archivo con secretos y un nombre corriente (por ejemplo
  `config.php` con una contraseña) se lee como cualquier otro código. Si el agente lo ve, lo señalará como
  hallazgo, pero su contenido habrá llegado a la API. No guardes secretos en el código.
- **El tope de gasto es una estimación** del SDK y puede pasarse un poco.
- **El texto del informe lo escribe una IA** a partir de código que puede ser malicioso: trátalo como un
  dato (ver [docs/reparador.md](docs/reparador.md)).
- **El modelo puede equivocarse:** puede haber falsos positivos y problemas que no vea.
- **Fuga a internet a través del coordinador:** el coordinador lee el proyecto y escribe el encargo del
  investigador. Si el código revisado lleva instrucciones escondidas, en teoría podría colar un trozo corto
  de información en ese encargo y de ahí a una búsqueda o una dirección web. Las longitudes están limitadas,
  pero no es imposible. Si el proyecto es muy sensible, usa `--sin-web`.
- **El agente puede ver los nombres de los archivos de secretos** (no su contenido).
- **Comprobación de direcciones:** se resuelve el nombre antes de permitir WebFetch, pero un servidor
  malicioso podría cambiar su dirección justo después (*DNS rebinding*).
- Las sesiones de Claude Code (con el código leído) se guardan en `.estado/` dentro de la carpeta del agente.

## Informar de un problema de seguridad

Si encuentras un fallo de seguridad en el agente, abre un *issue* en GitHub **sin** incluir datos
sensibles ni detalles explotables, o usa «Report a vulnerability» en la pestaña *Security* del
repositorio, si está activada.
