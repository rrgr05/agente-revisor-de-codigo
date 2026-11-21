# Cambios

## 1.0.1 — 21-11-2026

Arreglos encontrados en la primera revisión real:

- El coordinador no podía entregar el informe final: la protección bloqueaba la herramienta interna
  `StructuredOutput` del SDK. Ahora se permite, solo al coordinador.
- Los especialistas se lanzaban en segundo plano y el coordinador no esperaba su respuesta. Ahora van en
  primer plano (`background=False` y `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`).
- «Conectado con la API key» se mostraba en cada turno; ahora solo una vez (la comprobación se sigue
  haciendo siempre).

## 1.0.0 — 21-11-2026

Primera versión.

- Revisión de solo lectura de proyectos, carpetas o archivos en cualquier lenguaje.
- Coordinador + 6 especialistas (seguridad, errores, rendimiento, datos, fiabilidad, buenas prácticas),
  investigador en internet para lo que no se domine y verificador de falsos positivos.
- Informe numerado (H-001…) en Markdown y JSON en `docs/revisiones/` de la raíz del proyecto (rutas
  relativas, sin rutas del equipo); informe parcial si se corta, se alcanza el tope o se pulsa Ctrl+C.
- Busca la raíz del proyecto aunque se revise una subcarpeta o un archivo, para leer sus normas y dependencias.
- Protección:
  - sin herramientas de escritura ni de órdenes (quitadas, prohibidas en los permisos y bloqueadas por un
    *hook* que bloquea también si falla);
  - lecturas y búsquedas solo dentro del proyecto (sin `..`, rutas de red, otras unidades ni patrones absolutos);
  - no se leen, listan ni buscan archivos ni carpetas de secretos (`.env`, claves, `.git`, `.ssh`, `.aws`…);
  - solo nuestros subagentes; internet solo para el investigador, que no lee el proyecto, y solo `https` público;
  - configuración de Claude Code aislada, variables de otros proveedores quitadas y parada si la sesión no
    usa `ANTHROPIC_API_KEY`;
  - tope de gasto.
- Opciones: `--simular`, `--cambios`/`--desde`, `--solo`, modelos, esfuerzo, tope de gasto, idioma,
  `--sin-web`, `--incluir`, `--salida`, `--instrucciones`, `--forzar`, `--detallado`.
- Pruebas sin conexión (pytest) y pruebas automáticas en GitHub con Python 3.10 y 3.13 en Windows y Linux.
