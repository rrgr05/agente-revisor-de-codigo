# Agente revisor de código

Un agente de IA que **revisa tu código en cualquier lenguaje** y te entrega un informe numerado con:

- 🐞 **errores** de programación y de sintaxis,
- 🔒 **fallos de seguridad**,
- ⚡ **código ineficiente** (lo que hace la aplicación lenta o carga de más el servidor),
- 🧱 **malas prácticas** y lo que incumple las normas de tu proyecto,
- 🗄️ problemas de **integridad de datos** y de **fiabilidad** (errores mal tratados, recursos sin cerrar…).

**No cambia nada.** Es de solo lectura: encuentra los problemas y los explica. Después tú, u otro agente
(el «reparador»), decidís cuáles arreglar.

Funciona con el [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview) y **tu propia API
key de Anthropic**: el gasto sale de tu saldo de la API (también del saldo promocional), no de una
suscripción de Claude.

---

## Cómo funciona

```
                      ┌──────────────────────────────┐
  inventario local ──▶│        Coordinador           │  lee normas y dependencias,
  (gratis)            │  (no cambia nada)            │  reparte el trabajo
                      └──────┬───────────────┬───────┘
                             │               │
            ¿lenguaje o versión que no domina?│
                             ▼               ▼
                     ┌─────────────┐  ┌─────────────────────────────────────────────┐
                     │ Investigador│  │ Especialistas (a la vez, solo los que hacen │
                     │ (internet)  │  │ falta): seguridad · errores · rendimiento · │
                     └─────────────┘  │ datos · fiabilidad · buenas prácticas       │
                                      └──────────────────┬──────────────────────────┘
                                                         ▼
                                              ┌──────────────────┐
                                              │   Verificador    │  quita falsos positivos
                                              └────────┬─────────┘
                                                       ▼
                             docs/revisiones/revision-AAAA-MM-DD-HHMM.md  (para ti)
                             docs/revisiones/revision-AAAA-MM-DD-HHMM.json (para el reparador)
```

1. **Inventario local (gratis):** cuenta archivos y lenguajes, encuentra los archivos de dependencias y
   de normas (`CLAUDE.md`, `CONTRIBUTING.md`…) y salta lo que no es tuyo (`vendor`, `node_modules`,
   librerías copiadas en `public/assets`, compilados, minificados).
2. **Coordinador:** entiende el proyecto y reparte el trabajo por zonas entre los especialistas que hacen
   falta (si no hay base de datos, no lanza al de datos).
3. **Investigador:** si hay un lenguaje, framework o versión que el modelo no domina, busca en internet
   (documentación oficial, notas de versión, OWASP…) y prepara una guía para los especialistas.
4. **Especialistas:** cada uno revisa su tema con reglas estrictas de evidencia (solo lo que tienen al
   menos un 70 % de seguridad de que es real, siempre con archivo y línea).
5. **Verificador:** comprueba cada hallazgo contra el código y descarta los falsos positivos.
6. **Informe:** hallazgos numerados `H-001`, `H-002`… ordenados de más grave a menos, en Markdown (para
   leer) y en JSON (para que otro agente los arregle).

### Medidas de seguridad del propio agente

Estas medidas reducen mucho los riesgos, pero ninguna herramienta es perfecta: lee también los límites
de [SECURITY.md](SECURITY.md).

- **Solo lectura:** el agente no tiene herramientas para escribir, editar ni ejecutar órdenes (`Write`,
  `Edit`, `Bash`, `PowerShell`… están quitadas, prohibidas en los permisos y bloqueadas por un *hook*). El
  informe lo escribe el programa en Python, no la IA.
- **Dentro del proyecto:** el *hook* bloquea lecturas y búsquedas fuera de la carpeta revisada, rutas de red
  (`\\servidor\…`), otras unidades, `..` y patrones absolutos. Si el *hook* falla, la llamada se bloquea.
- **Secretos:** no se leen ni se busca dentro de `.env`, claves (`*.key`, `*.pem`, `id_rsa`…),
  certificados, carpetas como `.git`, `.ssh` o `.aws`, bases de datos locales ni volcados (el agente sí puede
  ver que existen, por su nombre). `Grep` en una carpeta solo busca en archivos de código (`*.php`,
  `type: php`…), en todos sus modos. La lista está en
  `revisor/config.py`; si guardas secretos con otros nombres, añádelos ahí. (`.env.example` sí se lee.)
- **Internet, solo el investigador**, que no puede leer tu proyecto, solo a páginas `https` de servidores
  públicos y con búsquedas y direcciones cortas. El encargo que le da el coordinador también está limitado;
  aun así, ver los límites en [SECURITY.md](SECURITY.md).
- **Solo tu API key:** usa una configuración de Claude Code aislada (sin tus ajustes, hooks, plugins ni tu
  sesión de Claude), quita las variables de otros proveedores y se para si la sesión no usa
  `ANTHROPIC_API_KEY` o tiene herramientas que no debería.
- **Tope de gasto** en cada revisión (por defecto 5 USD).
- **Instrucciones escondidas:** el código, los `CLAUDE.md` y las páginas web se tratan como datos; si un
  archivo intenta darle órdenes al agente, no debe seguirlas (y lo señala como sospechoso). Es una
  instrucción al modelo, no una garantía: por eso las barreras anteriores no dependen de él.

---

## Requisitos

- **Python 3.10 o superior** (las pruebas automáticas se pasan con 3.10 y 3.13).
- Una **API key de Anthropic** ([console.anthropic.com](https://console.anthropic.com) → *API keys*) con saldo.
- Git (solo para la opción `--cambios`).

No hace falta instalar Claude Code aparte: el SDK lo trae incluido (salvo en Windows ARM64, donde hay que
instalarlo y tenerlo en el `PATH`).

## Instalación

```powershell
git clone https://github.com/rrgr05/agente-revisor-de-codigo.git
cd agente-revisor-de-codigo
py -m venv .venv
.venv\Scripts\Activate.ps1          # si PowerShell lo bloquea: Set-ExecutionPolicy -Scope Process RemoteSigned
pip install -r requirements.txt
```

En Linux o macOS:

```bash
git clone https://github.com/rrgr05/agente-revisor-de-codigo.git
cd agente-revisor-de-codigo
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Tu API key

El programa la lee de la variable de entorno `ANTHROPIC_API_KEY` (nunca la guarda ni la escribe en ningún
archivo).

- **Solo para la ventana actual (PowerShell):** `$env:ANTHROPIC_API_KEY = "sk-ant-..."`
- **Para siempre en Windows:** Panel de control → Sistema → Configuración avanzada → Variables de entorno
  → Nueva (de usuario) → nombre `ANTHROPIC_API_KEY`. Cierra y vuelve a abrir la terminal.
- **Linux / macOS:** añade `export ANTHROPIC_API_KEY=sk-ant-...` a tu `~/.bashrc` o `~/.zshrc`.

> Consejo: crea una clave solo para este agente y ponle un límite de gasto en la consola de Anthropic.

---

## Uso

```powershell
# Ver qué se revisaría, sin gastar nada
python revisar.py "D:\proyectos\mi-web" --simular

# Revisar el proyecto entero
python revisar.py "D:\proyectos\mi-web"

# Revisar solo lo que has cambiado (sin commit), con un tope de 2 dólares
python revisar.py . --cambios --tope 2

# Lo cambiado desde la rama main
python revisar.py . --cambios --desde main

# Una carpeta o un archivo concreto
python revisar.py src/api
python revisar.py src/api/pagos.php

# Solo seguridad y rendimiento, con un modelo más barato
python revisar.py . --solo seguridad,rendimiento --modelo claude-sonnet-5-5

# Indicaciones extra
python revisar.py . --instrucciones "céntrate en el módulo de pagos y en las consultas a la base de datos"
```

En Windows también puedes usar `revisar.bat` (usa el entorno `.venv` sin activarlo):

```powershell
.\revisar.bat "D:\proyectos\mi-web" --simular
```

### Opciones

| Opción | Qué hace | Por defecto |
|---|---|---|
| `ruta` | Proyecto, carpeta o archivo que se revisa | — |
| `--simular` | Enseña el inventario y los ajustes **sin llamar a la API** | — |
| `--cambios` | Solo los archivos cambiados en git (sin commit y nuevos) | todo el proyecto |
| `--desde REF` | Con `--cambios`: también lo cambiado desde esa rama, etiqueta o commit | — |
| `--solo LISTA` | Especialistas permitidos: `seguridad`, `errores`, `rendimiento`, `datos`, `fiabilidad`, `buenas-practicas` | todos (el coordinador elige) |
| `--modelo` | Modelo del coordinador | `claude-opus-5-5` |
| `--modelo-especialistas` | Modelo de especialistas, investigador y verificador | el mismo que `--modelo` |
| `--esfuerzo` | Profundidad: `low`, `medium`, `high`, `xhigh`, `max` | `high` |
| `--tope USD` | Gasto máximo (estimado; puede pasarse un poco) | `5` |
| `--idioma` | Idioma del informe: `es`, `en`, `fr`, `it`, `pt`, `de` | `es` |
| `--sin-web` | No buscar en internet (sin investigador) | busca si hace falta |
| `--incluir LISTA` | Carpetas que normalmente se saltan y quieres revisar (p. ej. `vendor`) | — |
| `--salida CARPETA` | Dónde guardar el informe | `<proyecto>/docs/revisiones` |
| `--instrucciones TEXTO` | Indicaciones extra para esta revisión | — |
| `--forzar` | Permite revisar una unidad entera o tu carpeta personal (no recomendado) | — |
| `--detallado` | Enseña cada archivo leído y cada paso | — |

---

## Cuánto cuesta

Depende sobre todo del tamaño de lo que se revisa y del modelo. Precios por millón de tokens
(entrada / salida) en noviembre de 2026; consulta siempre los
[precios oficiales](https://www.anthropic.com/pricing#api), que pueden cambiar:

| Modelo | Entrada | Salida | Para qué |
|---|---|---|---|
| `claude-opus-5-5` (por defecto) | 4 $ | 20 $ | El mejor equilibrio calidad/precio |
| `claude-sonnet-5-5` | 2 $ | 10 $ | Más o menos la mitad de precio |
| `claude-haiku-5-5` | 0,10 $ | 0,50 $ | Muy barato; menos fino |
| `claude-fable-5-2` | 8 $ | 40 $ | El más capaz; el más caro |

**Orientación (no es una medida):** revisar unos pocos archivos cambiados suele costar céntimos; un
módulo, menos de 1–2 USD; un proyecto mediano completo, varios dólares. Para gastar menos:

- empieza con `--simular` para ver el tamaño;
- revisa por partes (`python revisar.py src/modulo`) o solo los cambios (`--cambios`);
- usa `--modelo-especialistas claude-sonnet-5-5` (el coordinador sigue en Opus);
- baja `--esfuerzo` a `medium`;
- limita con `--tope`. Si se alcanza, el informe sale **parcial** con lo que ya se encontró.

El coste estimado aparece al final de cada revisión y en el informe.

---

## El informe

Se guardan dos archivos en `docs/revisiones/` de la **raíz del proyecto** (aunque revises solo una
carpeta o un archivo, el agente busca la raíz: la del repositorio git o la carpeta con `package.json`,
`composer.json`, `CLAUDE.md`…, para poder leer sus normas y dependencias). Los informes llevan rutas
relativas al proyecto, sin rutas de tu equipo.

- **`revision-AAAA-MM-DD-HHMM.md`**: para leer. Resumen, tabla por gravedad, lo que está bien hecho,
  índice y detalle de cada hallazgo (qué pasa, impacto, cómo arreglarlo, confianza), lo investigado en
  internet con sus fuentes y lo que quedó sin revisar.
- **`revision-AAAA-MM-DD-HHMM.json`**: los mismos datos, para que un programa u otro agente los lea.

Hay un ejemplo en [docs/ejemplo-informe.md](docs/ejemplo-informe.md).

Gravedades: 🔴 **crítica** (explotable o rompe datos o el servicio), 🟠 **alta**, 🟡 **media**, 🔵 **baja**.

> Si no quieres subir los informes a tu repositorio, añade `docs/revisiones/` a tu `.gitignore` o usa
> `--salida` con otra carpeta.

## Arreglar los hallazgos (agente reparador)

Este agente solo informa. Para arreglar, usa otro agente (por ejemplo Claude Code) con el JSON del informe
y elige qué puntos arreglar. En [docs/reparador.md](docs/reparador.md) tienes unas instrucciones listas
para copiar.

---

## Personalizar

- **Instrucciones de cada agente:** `revisor/instrucciones/` (Markdown). Puedes ajustar lo que busca cada
  especialista o las reglas comunes de evidencia.
- **Nuevo especialista:** añade su archivo en `revisor/instrucciones/especialistas/<clave>.md` y su línea
  en `ESPECIALISTAS` de `revisor/config.py`.
- **Carpetas que se saltan, archivos prohibidos, modelos y valores por defecto:** `revisor/config.py`.

## Pruebas

```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```

Las pruebas no llaman a la API ni gastan nada: protección de lecturas, inventario y git, informe,
montaje de los agentes, comprobación de credenciales y una revisión completa con respuestas simuladas.

## Preguntas frecuentes

**¿Envía mi código a algún sitio?** Los fragmentos que el agente lee se envían a la API de Anthropic para
analizarlos, como con cualquier uso de Claude. El investigador hace búsquedas en internet sobre los
lenguajes y frameworks (no puede leer tu código). Los archivos de secretos de la lista no se leen.

**¿Guarda algo en mi equipo?** El informe, en `docs/revisiones/` del proyecto. Además, Claude Code guarda
las sesiones del agente (con el código que leyó) en la carpeta `.estado/` del propio agente: puedes
borrarla cuando quieras (no se sube a git).

**¿Puede romper algo?** No tiene herramientas para escribir ni ejecutar nada, y un *hook* lo bloquea
igualmente. Lo único que se escribe es el informe, y lo escribe el programa.

**¿Usa mi suscripción de Claude (Pro/Max)?** No. Usa solo `ANTHROPIC_API_KEY` y se para si detecta otra
credencial u otro proveedor.

**¿Revisa cualquier lenguaje?** Sí. Para lenguajes, frameworks o versiones que no domine, el investigador
busca la documentación en internet antes de revisar (se puede desactivar con `--sin-web`).

**Me sale «la API rechazó la clave (401)».** La clave está mal copiada o revocada. Crea otra en la consola.

---

## Créditos y licencia

Licencia **MIT** (ver [LICENSE](LICENSE)).

Ideas tomadas, con agradecimiento, de dos proyectos también MIT (ver [AVISOS.md](AVISOS.md)):

- [anthropics/claude-code-security-review](https://github.com/anthropics/claude-code-security-review):
  criterios de seguridad y filtro de falsos positivos.
- [vaibhav-k/claude-code-review-agents](https://github.com/vaibhav-k/claude-code-review-agents):
  reparto en especialistas con alcance estricto y lanzar solo los que hacen falta.
