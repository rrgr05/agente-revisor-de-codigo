# -*- coding: utf-8 -*-
"""
Configuración fija del Agente revisor de código.

Aquí están los valores por defecto (modelo, tope de gasto, carpetas que no se revisan,
archivos que nunca se leen) y la lista de especialistas. Todo lo demás del programa lee
de aquí, así que para cambiar un valor por defecto basta con tocar este archivo.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Rutas del propio programa
# ---------------------------------------------------------------------------

# Carpeta del paquete «revisor» (donde está este archivo).
PAQUETE = Path(__file__).resolve().parent

# Carpeta con las instrucciones (prompts) de cada agente, en Markdown.
INSTRUCCIONES = PAQUETE / "instrucciones"

# ---------------------------------------------------------------------------
# Modelo y gasto
# ---------------------------------------------------------------------------

# Modelo por defecto del coordinador y de los especialistas.
# Se puede cambiar en cada ejecución con --modelo y --modelo-especialistas.
MODELO_POR_DEFECTO = "claude-opus-5-5"

# Modelos que se aceptan sin preguntar (cualquier otro nombre también se pasa tal cual,
# pero se avisa por si es un error de escritura).
MODELOS_CONOCIDOS = {
    "claude-opus-5-5": "Opus 5.5 (el mejor equilibrio; por defecto)",
    "claude-sonnet-5-5": "Sonnet 5.5 (más o menos la mitad de precio)",
    "claude-haiku-5-5": "Haiku 5.5 (muy barato; menos fino)",
    "claude-fable-5-2": "Fable 5.2 (el más capaz; el más caro)",
}

# Esfuerzo de razonamiento: low, medium, high, xhigh, max.
ESFUERZO_POR_DEFECTO = "high"
ESFUERZOS = ("low", "medium", "high", "xhigh", "max")

# Tope de gasto por revisión, en dólares (estimación del propio SDK; puede pasarse un poco).
TOPE_POR_DEFECTO_USD = 5.0

# Turnos máximos del coordinador y de cada especialista (evita bucles sin fin).
TURNOS_COORDINADOR = 250
TURNOS_ESPECIALISTA = 80

# ---------------------------------------------------------------------------
# Qué no se revisa
# ---------------------------------------------------------------------------

# Carpetas que se saltan siempre al hacer el inventario y que el agente no revisa
# (dependencias de terceros, compilados, cachés, entornos virtuales…).
CARPETAS_EXCLUIDAS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", ".vs",
    "node_modules", "vendor", "bower_components", "jspm_packages",
    ".venv", "venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "dist", "build", "out", "target", "obj", ".gradle", ".kotlin", ".dart_tool",
    ".next", ".nuxt", ".svelte-kit", ".angular", ".expo", ".turbo", ".parcel-cache",
    "coverage", ".nyc_output", "storage", "logs", "tmp", "temp",
    "libs", "third_party", "third-party", "vendors", "Pods", "Carthage",
}

# Una carpeta dentro de una de estas zonas web con su propio manifiesto (package.json…) y una licencia, una
# carpeta dist o archivos minificados se considera una librería de terceros copiada (p. ej.
# public/assets/jquery) y no se revisa.
ZONAS_RECURSOS = {"public", "static", "assets", "www", "wwwroot", "web", "resources", "media"}
MANIFIESTOS_TERCEROS = {"package.json", "bower.json", "composer.json"}

# Archivos que el agente NUNCA puede leer: se bloquean en un «hook» antes de que la
# lectura llegue a ejecutarse, para que su contenido no se envíe nunca a la API.
# Se comparan con el nombre del archivo en minúsculas (patrones de fnmatch).
ARCHIVOS_PROHIBIDOS = (
    ".env", ".env.*", "*.env", ".envrc",
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.crt", "*.cer", "*.der", "*.csr",
    "id_rsa*", "id_ed25519*", "id_ecdsa*", "id_dsa*", "*.ppk", "known_hosts", "authorized_keys",
    "*.kdbx", "*.gpg", "*.asc", "*.ovpn", "*.mobileconfig",
    "credentials", "credentials*.json", "service-account*.json", "secrets.*", "*secret*.json", "*secrets*.y*ml",
    ".npmrc", ".pypirc", ".netrc", "_netrc", ".git-credentials", ".htpasswd", ".pgpass", ".my.cnf",
    "kubeconfig", "*.kubeconfig", "*.tfstate", "*.tfstate.*", "*.tfvars", "terraform.tfvars.json",
    "*.sqlite", "*.sqlite3", "*.db", "*.mdb", "*.accdb",
    "*.dump", "*.bak", "*.backup", "*.sql.gz", "*dump*.sql", "*backup*.sql", "*volcado*.sql",
    "local.properties", "google-services.json", "GoogleService-Info.plist", "*.mobileprovision",
)

# Carpetas que nunca se leen, listan ni buscan (llevan tokens, claves o credenciales).
CARPETAS_SECRETAS = {
    ".git", ".ssh", ".aws", ".azure", ".gnupg", ".docker", ".kube", ".gcloud", ".terraform",
    ".vercel", ".netlify", ".firebase", ".config", "secrets", ".secrets",
}

# Excepciones: plantillas de ejemplo que sí se pueden leer (no llevan secretos reales).
ARCHIVOS_PERMITIDOS = (".env.example", ".env.sample", ".env.dist", ".env.template")

# ---------------------------------------------------------------------------
# Herramientas
# ---------------------------------------------------------------------------

# Herramientas de solo lectura para revisar el código.
HERRAMIENTAS_LECTURA = ["Read", "Glob", "Grep"]

# Herramientas para buscar información en internet (lenguajes o versiones que el modelo
# no conozca bien). Se quitan con --sin-web.
HERRAMIENTAS_WEB = ["WebSearch", "WebFetch"]

# Herramienta con la que el coordinador lanza a los especialistas.
HERRAMIENTA_SUBAGENTES = "Agent"

# Herramientas que NO se dan nunca (ni al coordinador ni a los especialistas):
# así el agente no puede cambiar nada ni ejecutar órdenes en el equipo.
HERRAMIENTAS_PROHIBIDAS = [
    "Write", "Edit", "NotebookEdit", "Bash", "PowerShell", "Monitor",
    "TodoWrite", "Skill", "LSP", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode",
]

# ---------------------------------------------------------------------------
# Especialistas
# ---------------------------------------------------------------------------

# Cada especialista tiene su archivo de instrucciones en instrucciones/especialistas/<clave>.md.
# «descripcion» le dice al coordinador cuándo lanzarlo.
ESPECIALISTAS = {
    "seguridad": "Vulnerabilidades explotables: inyecciones (SQL, órdenes, plantillas, rutas), XSS, CSRF, "
                 "autenticación y permisos, sesiones, secretos escritos en el código, criptografía débil, "
                 "deserialización insegura, subida de archivos, exposición de datos.",
    "errores": "Fallos de programación y de sintaxis: lógica equivocada, condiciones al revés, casos sin "
               "tratar, nulos, tipos, errores de uno, variables sin definir, código inalcanzable, llamadas "
               "a funciones o APIs que no existen o con argumentos equivocados.",
    "rendimiento": "Eficiencia y carga del servidor: consultas N+1, consultas sin índice o que traen de más, "
                   "trabajo repetido, bucles costosos, falta de caché o de paginación, E/S bloqueante, "
                   "archivos o recursos del navegador pesados, peticiones de sobra.",
    "datos": "Integridad de los datos: SQL y migraciones, transacciones, cálculos de dinero, cantidades y "
             "fechas, redondeos, zonas horarias, validación de lo que se guarda, duplicados, borrados.",
    "fiabilidad": "Manejo de errores y recursos: excepciones tragadas o demasiado amplias, falta de tiempos "
                  "de espera, reintentos peligrosos, recursos sin cerrar, concurrencia y condiciones de "
                  "carrera, fugas de memoria.",
    "buenas-practicas": "Mantenibilidad y normas: convenciones del lenguaje y del framework, código duplicado, "
                        "funciones gigantes, nombres engañosos, código muerto, dependencias obsoletas o "
                        "vulnerables, y las normas propias del proyecto (CLAUDE.md, CONTRIBUTING, guías).",
}

# Idiomas del informe (código -> nombre para las instrucciones: «Escribe los textos en …»).
IDIOMAS = {"es": "español", "en": "inglés (English)", "fr": "francés (français)",
           "it": "italiano", "pt": "portugués (português)", "de": "alemán (Deutsch)"}

# Gravedades del informe, de mayor a menor.
GRAVEDADES = ("critica", "alta", "media", "baja")
