# -*- coding: utf-8 -*-
"""
Protección del agente: decide qué llamadas a herramientas se permiten.

Se engancha como «hook» PreToolUse del Agent SDK, así que se ejecuta ANTES de cada herramienta,
también las de los subagentes (el SDK le pasa «agent_type»). Si el hook falla o tarda, la llamada se
bloquea (on_failure="block" en ejecutar.py y try/except aquí): nunca se permite algo por error.

Reglas:
  1. Solo herramientas de lectura (Read, Glob, Grep), la de lanzar NUESTROS subagentes (Agent) y, solo
     para el investigador, las de internet (WebSearch, WebFetch). Todo lo demás se bloquea.
  2. Nada fuera de la carpeta del proyecto (ni rutas de red \\\\servidor, ni otras unidades, ni «..»,
     ni patrones absolutos o con «~»).
  3. Secretos (.env, claves, certificados, carpetas .git, .ssh, .aws, bases de datos, volcados…): no se
     leen con Read ni se busca dentro de ellos con Grep. Para Grep en una carpeta se usa una LISTA BLANCA:
     solo patrones de archivos de código (*.php, src/**/*.ts…) o tipos de lenguaje de una lista cerrada,
     en todos los modos (también «files_with_matches» y «count», que si no servirían de oráculo).
  4. Internet, solo el investigador: WebFetch a https de servidores públicos (el nombre se resuelve y
     todas sus IP deben ser públicas) y con longitudes limitadas.

Las funciones de comprobación son puras (sin el SDK) para poder probarlas con pytest.
"""

from __future__ import annotations

import fnmatch
import ipaddress
import itertools
import re
import socket
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlsplit

from . import config, inventario

# Herramientas de lectura y el campo de su entrada que lleva la ruta.
CAMPOS_RUTA = {"Read": "file_path", "Glob": "path", "Grep": "path"}

# Extensiones de código en las que Grep puede buscar dentro de una carpeta (lista blanca). Se quita .sql
# (los volcados de bases de datos suelen ser .sql); los .sql se pueden leer uno a uno con Read.
EXTENSIONES_GREP = tuple(sorted(set(inventario.LENGUAJES) - {".sql"}, key=len, reverse=True))

# Tipos de ripgrep permitidos en Grep (solo lenguajes de código; no «sh», que incluye .bashrc, .profile…,
# ni json/yaml/sql/markdown, que pueden llevar secretos o informes).
TIPOS_GREP = {
    "php", "js", "ts", "py", "java", "kotlin", "rust", "go", "c", "cpp", "cs", "ruby", "swift", "html",
    "css", "sass", "less", "vue", "svelte", "dart", "lua", "perl", "scala", "elixir", "erlang", "haskell",
    "clojure", "ocaml", "r", "julia", "zig", "objc", "twig", "ps", "fsharp", "groovy", "elm", "nim",
}

# Opciones de la herramienta Agent que no se permiten (pueden cambiar dónde o cómo corre el subagente).
OPCIONES_AGENT_PROHIBIDAS = ("isolation", "run_in_background", "model", "cwd")

# Límites de longitud para lo que sale a internet (para que no quepa código del proyecto).
MAX_URL = 400
MAX_CONSULTA = 200
MAX_ENCARGO_INVESTIGADOR = 1500

# Dominios que resuelven a la dirección que se quiera (sirven para llegar a equipos locales).
DOMINIOS_COMODIN = ("nip.io", "sslip.io", "xip.io", "localtest.me", "lvh.me", "traefik.me", "vcap.me",
                    "lacolhost.com", "localhost.run", "fbi.com")


# ---------------------------------------------------------------------------
# Comprobaciones básicas
# ---------------------------------------------------------------------------

def es_secreto(nombre: str) -> bool:
    """¿Es un archivo con secretos que no se debe leer nunca? (por su nombre, sin distinguir mayúsculas)"""
    nombre = nombre.lower().rstrip(". ")
    if nombre in config.ARCHIVOS_PERMITIDOS:
        return False
    return any(fnmatch.fnmatchcase(nombre, patron.lower()) for patron in config.ARCHIVOS_PROHIBIDOS)


def en_carpeta_secreta(relativa: Path | PurePosixPath) -> bool:
    """¿Pasa la ruta por una carpeta de secretos (.git, .ssh, .aws…)?"""
    return any(parte.lower() in config.CARPETAS_SECRETAS for parte in relativa.parts)


def texto_peligroso(valor: str) -> str | None:
    """
    Rechaza, ANTES de tocar el disco, rutas que no se deben ni intentar resolver: rutas de red o de
    dispositivo (\\\\servidor, //servidor, /\\servidor, \\\\?\\, \\\\.\\) y «:» fuera de la letra de unidad
    (flujos alternativos de NTFS como «archivo:secreto»).
    """
    limpio = valor.strip()
    if limpio.replace("/", "\\").startswith("\\\\"):
        return "No se permiten rutas de red ni de dispositivo."
    resto = limpio[2:] if re.match(r"^[A-Za-z]:", limpio) else limpio
    if ":" in resto:
        return "No se permiten «:» en las rutas (flujos alternativos o rutas raras)."
    if "\x00" in limpio:
        return "Ruta no válida."
    return None


def misma_unidad(valor: str, carpetas: list[Path]) -> bool:
    """En Windows: una ruta absoluta con una letra de unidad distinta de las permitidas queda fuera."""
    unidad = PureWindowsPath(valor).drive
    return not unidad or unidad.lower() in {c.drive.lower() for c in carpetas}


def dentro_de(ruta: Path, carpetas: list[Path]) -> Path | None:
    """Si «ruta» está dentro de alguna carpeta (o es ella), devuelve esa carpeta; si no, None."""
    for carpeta in carpetas:
        try:
            ruta.relative_to(carpeta)
            return carpeta
        except ValueError:
            continue
    return None


def resolver(valor: str, base: Path) -> Path:
    """Ruta absoluta y normalizada (las relativas cuentan desde «base»)."""
    ruta = Path(valor)
    if not ruta.is_absolute():
        ruta = base / ruta
    return ruta.resolve()


# ---------------------------------------------------------------------------
# Patrones de Glob y Grep
# ---------------------------------------------------------------------------

def patron_peligroso(patron: str) -> str | None:
    """Patrones de Glob o Grep: nada absoluto, ni «~», ni «..», ni «:»."""
    normal = patron.strip().replace("\\", "/")
    if normal.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", normal) or ":" in normal:
        return "Los patrones absolutos o con «~» o «:» no están permitidos: solo se busca dentro del proyecto."
    if ".." in PurePosixPath(normal).parts:
        return "Los patrones con «..» no están permitidos: solo se busca dentro del proyecto."
    return None


def partir_glob(texto: str) -> list[str]:
    """
    Parte el «glob» de Grep como lo hace Claude Code: por espacios y por comas que estén FUERA de llaves
    («*.php *.key» son dos patrones; «*.{php,js}» es uno).
    """
    trozos, actual, nivel = [], "", 0
    for caracter in texto:
        if caracter == "{":
            nivel += 1
        elif caracter == "}":
            nivel = max(0, nivel - 1)
        if nivel == 0 and (caracter.isspace() or caracter == ","):
            if actual:
                trozos.append(actual)
            actual = ""
            continue
        actual += caracter
    if actual:
        trozos.append(actual)
    return trozos


def expandir_llaves(patron: str, limite: int = 200) -> list[str]:
    """«src/*.{php,js}» -> ['src/*.php', 'src/*.js'] (todas las llaves, sin anidar)."""
    partes = re.split(r"(\{[^{}]*\})", patron)
    opciones = [p[1:-1].split(",") if p.startswith("{") and p.endswith("}") else [p] for p in partes]
    resultado = []
    for combinacion in itertools.product(*opciones):
        resultado.append("".join(combinacion))
        if len(resultado) >= limite:
            break
    return resultado


def prefijo_fijo(patron: str) -> PurePosixPath:
    """Parte del patrón sin comodines («src/api/**/*.php» -> src/api)."""
    fijas = []
    for parte in PurePosixPath(patron.replace("\\", "/")).parts[:-1]:
        if any(c in parte for c in "*?[]{}"):
            break
        fijas.append(parte)
    return PurePosixPath(*fijas) if fijas else PurePosixPath(".")


def glob_de_codigo(patron: str) -> str | None:
    """
    Lista blanca de Grep: cada patrón tiene que apuntar a archivos de CÓDIGO (terminar en una extensión de
    EXTENSIONES_GREP sin comodines en la extensión), no puede negar («!») y no puede alcanzar un nombre de
    secreto ni una carpeta de secretos. Devuelve el motivo si no vale.
    """
    if patron.startswith("!"):
        return "No se permiten patrones con «!» en Grep (buscarían en todo lo demás)."
    motivo = patron_peligroso(patron)
    if motivo:
        return motivo
    for concreto in expandir_llaves(patron):
        if "{" in concreto or "}" in concreto:
            return "Llaves anidadas o mal cerradas en el patrón de Grep."
        nombre = concreto.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if not nombre.endswith(EXTENSIONES_GREP):
            return ("En Grep, el patrón tiene que ser de archivos de código (p. ej. «*.php», «src/**/*.ts») "
                    "o usar «type» (p. ej. «php»).")
        if es_secreto(nombre.replace("*", "x").replace("?", "x")):
            return "Ese patrón apunta a un archivo de secretos."
        if en_carpeta_secreta(PurePosixPath(concreto.replace("\\", "/"))):
            return "No se busca dentro de carpetas de secretos (.git, .ssh, .aws…)."
    return None


# ---------------------------------------------------------------------------
# Internet
# ---------------------------------------------------------------------------

def host_local(host: str) -> bool:
    """¿El nombre o la dirección apunta (o puede apuntar) a un equipo local o de una red interna?"""
    host = host.lower().rstrip(".")
    if not host or "." not in host:
        return True
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home", ".corp")):
        return True
    if host.endswith(DOMINIOS_COMODIN) or any(host == d for d in DOMINIOS_COMODIN):
        return True
    # Direcciones numéricas en cualquier forma (127.1, 0x7f.0.0.1, 0177.0.0.1, 10.1…): solo se aceptan
    # nombres de dominio cuya última parte (el dominio de primer nivel) tenga letras y no sea hexadecimal.
    etiquetas = host.split(".")
    if not re.search(r"[a-z]", etiquetas[-1]) or any(e.startswith("0x") for e in etiquetas):
        return True
    return False


def resolver_publico(host: str) -> bool:
    """Resuelve el nombre y comprueba que TODAS sus direcciones son públicas."""
    try:
        direcciones = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return False
    ips = {info[4][0] for info in direcciones}
    try:
        return bool(ips) and all(ipaddress.ip_address(ip.split("%")[0]).is_global for ip in ips)
    except ValueError:
        return False


def url_publica(url: str, resolver_dns: bool = True) -> str | None:
    """WebFetch: solo https, corta, y a servidores públicos (nada de localhost ni redes internas)."""
    if len(url) > MAX_URL:
        return f"La dirección es demasiado larga (máximo {MAX_URL} caracteres)."
    try:
        partes = urlsplit(str(url))
        host = (partes.hostname or "").lower().rstrip(".")
    except ValueError:
        return "Dirección no válida."
    if partes.scheme.lower() != "https":
        return "Solo se permiten direcciones https."
    if partes.username or partes.password:
        return "No se permiten direcciones con usuario o contraseña."
    if partes.port not in (None, 443):
        return "Solo se permite el puerto 443."
    if host.startswith("[") or ":" in host:
        return "No se permiten direcciones IPv6 literales."
    try:
        ipaddress.ip_address(host)
        return "No se permiten direcciones IP: usa el nombre del sitio."
    except ValueError:
        pass
    if host_local(host):
        return "No se permiten direcciones locales o internas."
    if resolver_dns and not resolver_publico(host):
        return "El sitio no se pudo resolver o apunta a una dirección privada."
    return None


# ---------------------------------------------------------------------------
# Decisión
# ---------------------------------------------------------------------------

def comprobar(herramienta: str, entrada: Any, raiz: Path, permitidas: list[Path],
              agente: str | None = None, subagentes: set[str] | None = None,
              bloqueadas: list[Path] | None = None, resolver_dns: bool = True) -> str | None:
    """
    Devuelve None si la llamada se permite, o el motivo (texto, sin rutas del equipo) si se bloquea.

    raiz         carpeta del proyecto (las rutas relativas cuentan desde aquí)
    permitidas   carpetas donde se puede leer (el proyecto y las instrucciones del agente)
    agente       tipo de subagente que hace la llamada (None = el coordinador)
    subagentes   nombres de subagentes que el coordinador puede lanzar
    bloqueadas   carpetas que no se leen aunque estén dentro (informes anteriores, estado del agente)
    resolver_dns si False, WebFetch no resuelve el nombre (para las pruebas sin red)
    """
    if not isinstance(entrada, dict):
        return "Entrada de herramienta no válida."
    bloqueadas = bloqueadas or []

    # 1) Herramientas.
    if herramienta in config.HERRAMIENTAS_PROHIBIDAS:
        return f"La herramienta {herramienta} no está permitida: el revisor es de solo lectura."

    if herramienta in ("Agent", "Task"):
        if agente is not None:
            return "Los subagentes no pueden lanzar otros subagentes."
        tipo = str(entrada.get("subagent_type") or "")
        if tipo not in (subagentes or set()):
            return f"Solo se pueden lanzar los subagentes del revisor ({', '.join(sorted(subagentes or []))})."
        if any(entrada.get(opcion) for opcion in OPCIONES_AGENT_PROHIBIDAS):
            return "No se permiten las opciones isolation, run_in_background, model ni cwd al lanzar subagentes."
        if tipo == "investigador" and len(str(entrada.get("prompt") or "")) > MAX_ENCARGO_INVESTIGADOR:
            return (f"El encargo del investigador es demasiado largo (máximo {MAX_ENCARGO_INVESTIGADOR} "
                    "caracteres): dale solo la tecnología y la versión, sin código del proyecto.")
        return None

    if herramienta in config.HERRAMIENTAS_WEB:
        if agente != "investigador":
            return "Solo el investigador puede usar internet."
        if herramienta == "WebFetch":
            return url_publica(str(entrada.get("url") or ""), resolver_dns=resolver_dns)
        if len(str(entrada.get("query") or "")) > MAX_CONSULTA:
            return f"La búsqueda es demasiado larga (máximo {MAX_CONSULTA} caracteres)."
        return None

    if herramienta not in CAMPOS_RUTA:
        return f"La herramienta {herramienta} no está en la lista de herramientas del revisor."

    # 2) Ruta (Read: file_path obligatorio; Glob y Grep: path opcional = la raíz).
    valor = entrada.get(CAMPOS_RUTA[herramienta])
    if herramienta == "Read" and not valor:
        return "Falta la ruta del archivo."
    ruta = raiz
    if valor:
        valor = str(valor)
        motivo = texto_peligroso(valor)
        if motivo:
            return motivo
        if not misma_unidad(valor, permitidas):
            return f"Solo se puede leer dentro del proyecto ({raiz.name})."
        ruta = resolver(valor, raiz)
    carpeta = dentro_de(ruta, permitidas)
    if carpeta is None:
        return f"Solo se puede leer dentro del proyecto ({raiz.name})."
    if dentro_de(ruta, bloqueadas) is not None:
        return "Esa carpeta es del propio revisor (informes o estado) y no se revisa."
    relativa = ruta.relative_to(carpeta)
    if en_carpeta_secreta(relativa) or (relativa.parts and es_secreto(ruta.name)):
        return (f"«{ruta.name}» puede contener secretos y no se lee ni se busca dentro. "
                "Si te hace falta, revisa cómo lo usa el código, no su contenido.")

    # 3) Glob: el patrón no sale del proyecto ni entra en carpetas de secretos o bloqueadas.
    if herramienta == "Glob":
        patron = str(entrada.get("pattern") or "")
        motivo = patron_peligroso(patron)
        if motivo:
            return motivo
        for concreto in expandir_llaves(patron):
            normal = PurePosixPath(concreto.replace("\\", "/"))
            if en_carpeta_secreta(normal):
                return "No se listan carpetas de secretos (.git, .ssh, .aws…)."
            if dentro_de((ruta / str(prefijo_fijo(concreto))).resolve(), bloqueadas) is not None:
                return "Esa carpeta es del propio revisor (informes o estado) y no se revisa."
        return None

    # 4) Grep. Sobre un archivo concreto (ya comprobado arriba): permitido en cualquier modo.
    if ruta.is_file():
        return None
    # Sobre una carpeta (o algo que no existe): lista blanca en TODOS los modos.
    tipo = entrada.get("type")
    patron = entrada.get("glob")
    if not tipo and not patron:
        return ("Para buscar con Grep en una carpeta, indica «glob» con archivos de código (p. ej. «*.php») "
                "o «type» (p. ej. «php»).")
    if tipo and str(tipo).lower() not in TIPOS_GREP:
        return f"El tipo «{tipo}» no está permitido en Grep; usa uno de lenguaje de código (php, js, py…)."
    if patron:
        trozos = partir_glob(str(patron))
        if not trozos:
            return "Patrón de Grep vacío."
        for trozo in trozos:
            motivo = glob_de_codigo(trozo)
            if motivo:
                return motivo
            for concreto in expandir_llaves(trozo):
                if dentro_de((ruta / str(prefijo_fijo(concreto))).resolve(), bloqueadas) is not None:
                    return "Esa carpeta es del propio revisor (informes o estado) y no se revisa."
    return None


def crear_hook(raiz: Path, subagentes: set[str], bloqueadas: list[Path] | None = None, avisar=None):
    """
    Crea la función «hook» PreToolUse para el Agent SDK.

    «avisar» es una función opcional que recibe el texto de cada bloqueo (para mostrarlo en pantalla).
    """
    raiz = raiz.resolve()
    permitidas = [raiz, config.INSTRUCCIONES.resolve()]
    bloqueadas = [b.resolve() for b in (bloqueadas or [])]

    def denegar(motivo: str) -> dict[str, Any]:
        if avisar:
            avisar(motivo)
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": motivo}}

    async def hook(datos: Any, tool_use_id: str | None, contexto: Any) -> dict[str, Any]:
        try:
            if not isinstance(datos, dict):
                return denegar("Llamada no válida.")
            agente = datos.get("agent_type") if datos.get("agent_id") else None
            motivo = comprobar(str(datos.get("tool_name", "")), datos.get("tool_input"), raiz, permitidas,
                               agente=agente, subagentes=subagentes, bloqueadas=bloqueadas)
        except Exception as error:  # cualquier fallo inesperado: bloquear, nunca permitir
            return denegar(f"Bloqueado por un error al comprobar la llamada ({type(error).__name__}).")
        return {} if motivo is None else denegar(motivo)

    return hook


def reglas_permisos() -> dict[str, Any]:
    """
    Reglas de permisos de Claude Code que niegan leer secretos (Claude Code las aplica también a Glob
    y Grep). Es una segunda barrera además del hook; se pasan con la opción «settings» del SDK.
    """
    reglas = [f"Read(**/{patron})" for patron in config.ARCHIVOS_PROHIBIDOS]
    reglas += [f"Read(**/{carpeta}/**)" for carpeta in sorted(config.CARPETAS_SECRETAS)]
    reglas += list(config.HERRAMIENTAS_PROHIBIDAS)
    return {"permissions": {"deny": reglas}}
