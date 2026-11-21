# -*- coding: utf-8 -*-
"""
Inventario local del proyecto que se va a revisar.

Recorre la carpeta SIN llamar a la API (no gasta nada) y cuenta:
  - cuántos archivos de código hay y de qué lenguajes,
  - qué archivos de dependencias y de normas del proyecto existen (package.json, composer.json,
    CLAUDE.md, CONTRIBUTING.md…),
  - qué librerías de terceros hay copiadas (para no revisarlas),
  - y, si se pide, qué archivos cambiaron en git (para revisar solo los cambios).

También localiza la RAÍZ del proyecto cuando se pide revisar una subcarpeta o un archivo suelto, para
que el agente pueda leer las normas y dependencias de la raíz aunque solo revise una parte.

Este resumen se le pasa al coordinador para que no gaste turnos descubriéndolo, y es también lo que
enseña la opción --simular.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import config

# Extensión -> lenguaje. Lo que no está aquí no cuenta como «código» en el inventario,
# pero el agente puede leerlo igualmente si lo necesita.
LENGUAJES = {
    ".py": "Python", ".pyw": "Python",
    ".php": "PHP", ".phtml": "PHP",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript (React)",
    ".ts": "TypeScript", ".tsx": "TypeScript (React)", ".mts": "TypeScript", ".cts": "TypeScript",
    ".vue": "Vue", ".svelte": "Svelte", ".astro": "Astro",
    ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "SCSS", ".sass": "Sass", ".less": "Less",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala", ".groovy": "Groovy",
    ".cs": "C#", ".vb": "Visual Basic", ".fs": "F#",
    ".c": "C", ".h": "C/C++", ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++",
    ".rs": "Rust", ".go": "Go", ".swift": "Swift", ".m": "Objective-C", ".mm": "Objective-C++",
    ".rb": "Ruby", ".erb": "Ruby (ERB)", ".pl": "Perl", ".pm": "Perl", ".lua": "Lua",
    ".dart": "Dart", ".ex": "Elixir", ".exs": "Elixir", ".erl": "Erlang", ".hs": "Haskell",
    ".clj": "Clojure", ".ml": "OCaml", ".r": "R", ".jl": "Julia", ".zig": "Zig", ".nim": "Nim",
    ".sql": "SQL", ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".ps1": "PowerShell",
    ".psm1": "PowerShell", ".bat": "Batch", ".cmd": "Batch",
    ".scad": "OpenSCAD", ".sol": "Solidity", ".tf": "Terraform", ".gd": "GDScript",
    ".asm": "Ensamblador", ".s": "Ensamblador", ".v": "Verilog", ".vhd": "VHDL",
    ".twig": "Twig", ".blade.php": "Blade", ".liquid": "Liquid", ".hbs": "Handlebars",
}

# Archivos que dicen mucho del proyecto: dependencias, configuración y normas.
ARCHIVOS_CLAVE = (
    "CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md", "README.md", ".editorconfig",
    "package.json", "composer.json", "requirements.txt", "pyproject.toml", "Pipfile",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle.kts",
    "Gemfile", "*.csproj", "*.sln", "pubspec.yaml", "mix.exs", "Dockerfile", "docker-compose.yml",
    ".htaccess", "web.config", "phpstan.neon", "phpcs.xml", "tsconfig.json", ".eslintrc*",
)

# Archivos que marcan la raíz de un proyecto (para encontrarla desde una subcarpeta).
MARCAS_RAIZ = (".git", "CLAUDE.md", "AGENTS.md", "package.json", "composer.json", "pyproject.toml",
               "requirements.txt", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
               "settings.gradle.kts", "Gemfile", "pubspec.yaml", "mix.exs")

# Tamaño a partir del cual un archivo se considera «enorme» (seguramente generado o minificado).
TAMANO_ENORME = 1_000_000


@dataclass
class Inventario:
    """Resumen del proyecto que se va a revisar."""

    raiz: Path                    # raíz del proyecto (normas, dependencias)
    alcance: str = ""             # parte que se revisa, relativa a la raíz ("" = todo)
    archivos_codigo: int = 0
    lineas_aprox: int = 0
    por_lenguaje: Counter = field(default_factory=Counter)
    archivos_clave: list[str] = field(default_factory=list)
    enormes: list[str] = field(default_factory=list)
    terceros: list[str] = field(default_factory=list)  # librerías de terceros copiadas (se saltan)
    cambiados: list[str] | None = None                 # solo con --cambios

    def lenguajes_ordenados(self) -> list[tuple[str, int]]:
        """Lenguajes de más a menos archivos."""
        return self.por_lenguaje.most_common()

    def texto(self) -> str:
        """Resumen legible para el coordinador y para --simular."""
        partes = [
            f"Proyecto: {self.raiz.name}",
            f"Parte que se revisa: {self.alcance or 'todo el proyecto'}",
            f"Archivos de código: {self.archivos_codigo} (unas {self.lineas_aprox:,} líneas)".replace(",", "."),
            "Lenguajes: " + (", ".join(f"{leng} ({n})" for leng, n in self.lenguajes_ordenados()) or "ninguno reconocido"),
            "Archivos clave: " + (", ".join(self.archivos_clave[:60]) or "ninguno"),
        ]
        if self.terceros:
            partes.append(f"Librerías de terceros copiadas en el proyecto ({len(self.terceros)}; NO se revisan): "
                          + ", ".join(self.terceros[:40]) + (" …" if len(self.terceros) > 40 else ""))
        if self.enormes:
            partes.append("Archivos enormes (seguramente generados o minificados; no revisarlos salvo que haga falta): "
                          + ", ".join(self.enormes[:30]) + (" …" if len(self.enormes) > 30 else ""))
        if self.cambiados is not None:
            partes.append(f"Archivos que hay que revisar ({len(self.cambiados)}):")
            partes.extend(f"  - {c}" for c in self.cambiados[:400])
            if len(self.cambiados) > 400:
                partes.append(f"  … y {len(self.cambiados) - 400} más")
        return "\n".join(partes)


def lenguaje_de(nombre: str) -> str | None:
    """Lenguaje de un archivo según su extensión (None si no es código conocido)."""
    nombre = nombre.lower()
    if nombre.endswith(".blade.php"):
        return LENGUAJES[".blade.php"]
    return LENGUAJES.get(os.path.splitext(nombre)[1])


def es_clave(nombre: str) -> bool:
    """¿Es un archivo de dependencias, configuración o normas?"""
    return any(fnmatch.fnmatch(nombre, patron) for patron in ARCHIVOS_CLAVE)


def es_terceros(relativa: Path, archivos: list[str], subcarpetas: list[str]) -> bool:
    """
    ¿Es esta carpeta una librería de terceros copiada en el proyecto? Lo es si está dentro de una zona
    de recursos web (public, assets, static…), tiene su propio manifiesto (package.json, bower.json…) y
    además otra señal de paquete publicado (licencia, carpeta dist o archivos minificados).
    """
    if not {parte.lower() for parte in relativa.parts[:-1]} & config.ZONAS_RECURSOS:
        return False
    if not any(nombre in config.MANIFIESTOS_TERCEROS for nombre in archivos):
        return False
    licencia = any(nombre.lower().startswith(("license", "licence", "copying")) for nombre in archivos)
    compilado = "dist" in subcarpetas or any(n.endswith((".min.js", ".min.css")) for n in archivos)
    return licencia or compilado


def contar_lineas(ruta: Path) -> int:
    """Cuenta líneas sin cargar el archivo entero en memoria (0 si no se puede leer)."""
    try:
        with ruta.open("rb") as archivo:
            return sum(1 for _ in archivo)
    except OSError:
        return 0


def git(carpeta: Path, *argumentos: str, permitir_fallo: bool = False, nulos: bool = False) -> list[str] | None:
    """
    Ejecuta git en «carpeta» y devuelve las líneas de salida. Usa core.quotepath=false para que los
    nombres con tildes no lleguen escapados; con nulos=True parte la salida por el carácter nulo (para
    órdenes con -z: nombres con espacios, comillas o saltos de línea llegan tal cual). Lanza RuntimeError
    con un mensaje claro si falla (o devuelve None con permitir_fallo=True).
    """
    try:
        resultado = subprocess.run(
            ["git", "-c", "core.quotepath=false", "-C", str(carpeta), *argumentos],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=60,
        )
    except FileNotFoundError:
        raise RuntimeError("git no está instalado o no está en el PATH (hace falta para --cambios).") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("git tardó demasiado en responder.") from None
    if resultado.returncode != 0:
        if permitir_fallo:
            return None
        raise RuntimeError(f"git {' '.join(argumentos)} falló: {resultado.stderr.strip()[:300]}")
    if nulos:
        return [nombre for nombre in resultado.stdout.split("\0") if nombre]
    return [linea.strip() for linea in resultado.stdout.splitlines() if linea.strip()]


def raiz_git(carpeta: Path) -> Path | None:
    """Raíz del repositorio git que contiene «carpeta» (None si no hay git o no es un repositorio)."""
    try:
        salida = git(carpeta, "rev-parse", "--show-toplevel", permitir_fallo=True)
    except RuntimeError:
        return None
    return Path(salida[0]).resolve() if salida else None


def buscar_raiz(objetivo: Path) -> Path:
    """
    Raíz del proyecto de «objetivo» (archivo o carpeta): la del repositorio git, o la carpeta más cercana
    hacia arriba (como mucho 2 niveles) con un archivo de proyecto (package.json, composer.json,
    CLAUDE.md…). Nunca sube hasta la carpeta personal ni por encima de ella (ahí podría leer otros
    proyectos). Si no encuentra nada, la propia carpeta. Se puede fijar a mano con --raiz.
    """
    carpeta = objetivo if objetivo.is_dir() else objetivo.parent
    casa = Path.home().resolve()

    def demasiado_alta(ruta: Path) -> bool:
        return ruta.parent == ruta or ruta == casa or ruta in casa.parents

    repo = raiz_git(carpeta)
    if repo is not None and not demasiado_alta(repo):
        return repo
    actual = carpeta
    for _ in range(3):  # la propia carpeta y 2 niveles más arriba
        if demasiado_alta(actual):
            break
        if any((actual / marca).exists() for marca in MARCAS_RAIZ):
            return actual
        actual = actual.parent
    return carpeta


def archivos_cambiados(raiz: Path, desde: str | None) -> list[str]:
    """
    Archivos cambiados según git, relativos a «raiz».

    - Sin «desde»: los cambios sin commit (preparados o no) y los archivos nuevos sin seguimiento.
    - Con «desde» (una rama, etiqueta o commit): además, todo lo que cambió desde ahí hasta ahora.
    """
    repo = raiz_git(raiz)
    if repo is None:
        raise RuntimeError(f"{raiz} no está dentro de un repositorio git (hace falta para --cambios).")

    hay_head = git(raiz, "rev-parse", "--verify", "--quiet", "HEAD", permitir_fallo=True) is not None
    nombres: set[str] = set()
    if desde:
        if desde.startswith("-"):
            raise RuntimeError(f"Referencia de git no válida: {desde}")
        if git(raiz, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{desde}^{{commit}}",
               permitir_fallo=True) is None:
            raise RuntimeError(f"No existe la rama, etiqueta o commit «{desde}».")
        if hay_head:
            nombres.update(git(raiz, "diff", "-z", "--name-only", "--diff-filter=ACMR", f"{desde}...HEAD", "--",
                               nulos=True) or [])
    if hay_head:
        nombres.update(git(raiz, "diff", "-z", "--name-only", "--diff-filter=ACMR", "HEAD", "--", nulos=True) or [])
    else:
        # Repositorio sin ningún commit: lo preparado cuenta como cambiado.
        nombres.update(git(raiz, "diff", "-z", "--name-only", "--diff-filter=ACMR", "--cached", "--",
                           nulos=True) or [])
    # --full-name: rutas desde la raíz del repositorio también al ejecutarlo en una subcarpeta.
    nombres.update(git(raiz, "ls-files", "-z", "--others", "--exclude-standard", "--full-name", "--",
                       nulos=True) or [])

    relativos = []
    for nombre in sorted(nombres):
        absoluto = (repo / nombre).resolve()
        try:
            relativos.append(absoluto.relative_to(raiz).as_posix())
        except ValueError:
            continue  # cambio fuera de la carpeta que se revisa
    return relativos


def hacer_inventario(objetivo: Path, raiz: Path | None = None, solo_cambios: bool = False,
                     desde: str | None = None, incluir: set[str] | None = None,
                     bloqueadas: list[Path] | None = None) -> Inventario:
    """
    Inventario de «objetivo» (archivo o carpeta) dentro del proyecto «raiz» (si no se da, se busca).

    incluir    nombres de carpeta de CARPETAS_EXCLUIDAS que el usuario quiere revisar igualmente
    bloqueadas carpetas que nunca se cuentan ni se revisan (informes anteriores, estado del agente)
    """
    objetivo = objetivo.resolve()
    raiz = (raiz or buscar_raiz(objetivo)).resolve()
    excluidas = config.CARPETAS_EXCLUIDAS - (incluir or set())
    bloqueadas = [b.resolve() for b in (bloqueadas or [])]
    relativo = objetivo.relative_to(raiz).as_posix() if objetivo != raiz else ""
    inv = Inventario(raiz=raiz, alcance=relativo)

    def bloqueada(ruta: Path) -> bool:
        return any(ruta == b or b in ruta.parents for b in bloqueadas)

    # Archivos clave de la raíz (aunque se revise solo una parte).
    if objetivo != raiz:
        inv.archivos_clave = sorted(n.name for n in raiz.iterdir() if n.is_file() and es_clave(n.name))

    # Un archivo suelto: el inventario es solo ese archivo.
    if objetivo.is_file():
        inv.archivos_codigo = 1
        inv.lineas_aprox = contar_lineas(objetivo)
        inv.por_lenguaje[lenguaje_de(objetivo.name) or "otro"] += 1
        inv.cambiados = [relativo]
        return inv

    for carpeta, subcarpetas, archivos in os.walk(objetivo):
        actual = Path(carpeta)
        # Quitar las carpetas excluidas, las de secretos y las bloqueadas (se modifica la lista en su sitio).
        subcarpetas[:] = sorted(s for s in subcarpetas
                                if s not in excluidas and s.lower() not in config.CARPETAS_SECRETAS
                                and not bloqueada(actual / s))

        # ¿Es una librería de terceros copiada dentro de una zona web (public/assets/…)?
        if actual != raiz and es_terceros(actual.relative_to(raiz), archivos, subcarpetas):
            inv.terceros.append(actual.relative_to(raiz).as_posix())
            subcarpetas[:] = []
            continue

        for nombre in sorted(archivos):
            ruta = actual / nombre
            relativa = ruta.relative_to(raiz).as_posix()
            if es_clave(nombre) and len(inv.archivos_clave) < 200 and relativa not in inv.archivos_clave:
                inv.archivos_clave.append(relativa)
            lenguaje = lenguaje_de(nombre)
            if not lenguaje:
                continue
            try:
                tamano = ruta.stat().st_size
            except OSError:
                continue
            if tamano > TAMANO_ENORME or nombre.endswith((".min.js", ".min.css")):
                inv.enormes.append(relativa)
                continue
            inv.archivos_codigo += 1
            inv.por_lenguaje[lenguaje] += 1
            inv.lineas_aprox += contar_lineas(ruta)

    if solo_cambios:
        cambiados = []
        for c in archivos_cambiados(raiz, desde):
            ruta = raiz / c
            if relativo and not (ruta == objetivo or objetivo in ruta.parents):
                continue  # fuera de la parte que se revisa
            partes = c.split("/")[:-1]
            if any(p in excluidas or p.lower() in config.CARPETAS_SECRETAS for p in partes) or bloqueada(ruta):
                continue
            cambiados.append(c)
        inv.cambiados = cambiados
    return inv
