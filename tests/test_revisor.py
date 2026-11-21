# -*- coding: utf-8 -*-
"""
Pruebas sin conexión (no llaman a la API ni gastan nada).

Cubren la protección de lecturas, el inventario y git, el informe, el montaje de los agentes, la
comprobación de credenciales y la ejecución completa con un «query» falso.

Ejecutar:  python -m pytest -q
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from revisor import agentes, config, informe, inventario, seguridad

SUBAGENTES = set(config.ESPECIALISTAS) | {"verificador", "investigador"}
HAY_GIT = shutil.which("git") is not None


# ---------------------------------------------------------------------------
# Proyecto de ejemplo
# ---------------------------------------------------------------------------

@pytest.fixture
def proyecto(tmp_path: Path) -> Path:
    """Proyecto de ejemplo con código, secretos, dependencias y una librería copiada."""
    raiz = tmp_path / "proyecto"
    (raiz / "src").mkdir(parents=True)
    (raiz / "src" / "app.php").write_text("<?php echo 1;\n", encoding="utf-8")
    (raiz / "src" / "util.js").write_text("export const a = 1;\n", encoding="utf-8")
    (raiz / ".env").write_text("SECRETO=1\n", encoding="utf-8")
    (raiz / ".env.example").write_text("SECRETO=\n", encoding="utf-8")
    (raiz / "vendor" / "lib").mkdir(parents=True)
    (raiz / "vendor" / "lib" / "x.php").write_text("<?php\n", encoding="utf-8")
    jquery = raiz / "public" / "assets" / "jquery"
    jquery.mkdir(parents=True)
    (jquery / "package.json").write_text("{}", encoding="utf-8")
    (jquery / "LICENSE.txt").write_text("MIT", encoding="utf-8")
    (jquery / "jquery.js").write_text("var a;\n", encoding="utf-8")
    propio = raiz / "public" / "assets" / "mi-modulo"
    propio.mkdir(parents=True)
    (propio / "package.json").write_text("{}", encoding="utf-8")  # sin licencia ni dist: es código propio
    (propio / "modulo.js").write_text("var c;\n", encoding="utf-8")
    (raiz / "public" / "assets" / "app.js").write_text("var b;\n", encoding="utf-8")
    (raiz / "composer.json").write_text("{}", encoding="utf-8")
    (raiz / ".git_falso").mkdir()
    return raiz


def comprobar(proyecto: Path, herramienta: str, entrada, agente=None, bloqueadas=None):
    permitidas = [proyecto.resolve(), config.INSTRUCCIONES.resolve()]
    return seguridad.comprobar(herramienta, entrada, proyecto.resolve(), permitidas, agente=agente,
                               subagentes=SUBAGENTES, bloqueadas=bloqueadas, resolver_dns=False)


# ---------------------------------------------------------------------------
# Protección: rutas y secretos
# ---------------------------------------------------------------------------

def test_lectura_dentro_del_proyecto(proyecto: Path) -> None:
    assert comprobar(proyecto, "Read", {"file_path": str(proyecto / "src" / "app.php")}) is None
    assert comprobar(proyecto, "Read", {"file_path": "src/app.php"}) is None
    assert comprobar(proyecto, "Glob", {"pattern": "src/**/*.php"}) is None
    assert comprobar(proyecto, "Grep", {"pattern": "echo", "glob": "*.php"}) is None


def test_lectura_fuera_del_proyecto(proyecto: Path, tmp_path: Path) -> None:
    fuera = tmp_path / "fuera.txt"
    fuera.write_text("x", encoding="utf-8")
    assert comprobar(proyecto, "Read", {"file_path": str(fuera)})
    assert comprobar(proyecto, "Read", {"file_path": "../fuera.txt"})
    assert comprobar(proyecto, "Grep", {"path": str(tmp_path)})
    assert comprobar(proyecto, "Glob", {"path": "..", "pattern": "*"})


@pytest.mark.parametrize("ruta", [
    "\\\\servidor\\compartida\\x.txt", "//servidor/compartida/x.txt", "\\\\?\\C:\\x.txt", "\\\\.\\PhysicalDrive0",
    "src/app.php:secreto", "src/app.php::$DATA",
])
def test_rutas_de_red_y_raras_bloqueadas(proyecto: Path, ruta: str) -> None:
    assert comprobar(proyecto, "Read", {"file_path": ruta})


def test_otra_unidad_bloqueada(proyecto: Path) -> None:
    otra = "Z:\\x.txt" if proyecto.drive.upper() != "Z:" else "Y:\\x.txt"
    assert comprobar(proyecto, "Read", {"file_path": otra})


@pytest.mark.parametrize("ruta", [
    ".env", ".ENV", ".env.local", ".env.", "config/app.env", "certs/server.KEY", "id_rsa", "id_ed25519.pub",
    "backup.dump", "datos.sqlite", ".htpasswd", "infra/prod.tfvars", "terraform.tfstate", ".git/config",
    ".ssh/id_rsa", ".aws/credentials", ".docker/config.json", "secrets/clave.txt", "kubeconfig",
])
def test_secretos_bloqueados_al_leer(proyecto: Path, ruta: str) -> None:
    assert comprobar(proyecto, "Read", {"file_path": ruta}), ruta


def test_plantilla_de_ejemplo_se_puede_leer(proyecto: Path) -> None:
    assert comprobar(proyecto, "Read", {"file_path": ".env.example"}) is None


def test_grep_y_glob_no_alcanzan_secretos(proyecto: Path) -> None:
    # Buscar directamente dentro de un secreto.
    assert comprobar(proyecto, "Grep", {"pattern": "x", "path": ".env", "output_mode": "content"})
    assert comprobar(proyecto, "Glob", {"pattern": "**/*", "path": ".git"})
    assert comprobar(proyecto, "Glob", {"pattern": ".git/**"})
    # Patrones permitidos: archivos de código o tipos de lenguaje.
    for buena in ({"glob": "*.php"}, {"glob": "src/**/*.{php,js}"}, {"type": "php"}, {"type": "PY"},
                  {"glob": "*.php", "type": "php"}, {"glob": "*.ts *.tsx"}):
        assert comprobar(proyecto, "Grep", {"pattern": "x", "output_mode": "content", **buena}) is None, buena


@pytest.mark.parametrize("modo", ["content", "files_with_matches", "count"])
@pytest.mark.parametrize("entrada", [
    {},                                         # sin patrón ni tipo: buscaría en todo
    {"glob": ".env"}, {"glob": ".env*"}, {"glob": "*"}, {"glob": "**/*"}, {"glob": "*.{php,env}"},
    {"glob": "!*.php"}, {"glob": "*.php *.key"}, {"glob": "*.php,*.pem"}, {"glob": "*.ph*"},
    {"glob": ".env", "type": "php"},            # el glob manda sobre el tipo en ripgrep
    {"glob": "service-account*.json"}, {"glob": "google-services.json"}, {"glob": ".netrc"},
    {"glob": ".pgpass"}, {"glob": "*.sqlite3"}, {"glob": "*.crt"}, {"glob": "*.sql"}, {"glob": "*.md"},
    {"type": "json"}, {"type": "yaml"}, {"type": "sql"}, {"type": "sh"}, {"type": "markdown"},
    {"glob": "secrets.php"}, {"glob": ".git/**/*.php"}, {"glob": "*.{php,{js,env}}"},
])
def test_grep_lista_blanca_en_todos_los_modos(proyecto: Path, modo: str, entrada: dict) -> None:
    # También en files_with_matches y count: si no, serviría de oráculo («^APP_KEY=a» en .env).
    assert comprobar(proyecto, "Grep", {"pattern": "^APP_KEY=a", "output_mode": modo, **entrada}), entrada


def test_grep_archivo_concreto(proyecto: Path) -> None:
    assert comprobar(proyecto, "Grep", {"pattern": "x", "path": "src/app.php", "output_mode": "content"}) is None
    assert comprobar(proyecto, "Grep", {"pattern": "x", "path": ".env.example"}) is None


def test_partir_glob_como_claude_code() -> None:
    assert seguridad.partir_glob("*.php *.key") == ["*.php", "*.key"]
    assert seguridad.partir_glob("*.php,*.js") == ["*.php", "*.js"]
    assert seguridad.partir_glob("*.{php,js}") == ["*.{php,js}"]
    assert seguridad.expandir_llaves("src/*.{php,js}") == ["src/*.php", "src/*.js"]


@pytest.mark.parametrize("patron", ["../**/*.php", "..\\*.php", "C:/Users/**/*.txt", "C:\\Users\\*", "~/**",
                                    "/etc/**", "src/a:b"])
def test_patrones_peligrosos_bloqueados(proyecto: Path, patron: str) -> None:
    assert comprobar(proyecto, "Glob", {"pattern": patron})
    assert comprobar(proyecto, "Grep", {"pattern": "x", "glob": patron})


def test_enlace_simbolico_hacia_fuera(proyecto: Path, tmp_path: Path) -> None:
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (fuera / "privado.txt").write_text("x", encoding="utf-8")
    try:
        os.symlink(fuera / "privado.txt", proyecto / "enlace.txt")
    except (OSError, NotImplementedError):
        pytest.skip("No se pueden crear enlaces simbólicos en este sistema.")
    assert comprobar(proyecto, "Read", {"file_path": "enlace.txt"})


def test_carpetas_bloqueadas(proyecto: Path) -> None:
    informes = proyecto / "docs" / "revisiones"
    informes.mkdir(parents=True)
    (informes / "revision.md").write_text("x", encoding="utf-8")
    bloq = [informes.resolve()]
    assert comprobar(proyecto, "Read", {"file_path": "docs/revisiones/revision.md"}, bloqueadas=bloq)
    assert comprobar(proyecto, "Glob", {"pattern": "docs/revisiones/*.md"}, bloqueadas=bloq)
    assert comprobar(proyecto, "Grep", {"pattern": "x", "glob": "docs/revisiones/*.php"}, bloqueadas=bloq)
    assert comprobar(proyecto, "Grep", {"pattern": "x", "path": "docs/revisiones", "type": "php"}, bloqueadas=bloq)


def test_se_pueden_leer_las_instrucciones_propias(proyecto: Path) -> None:
    assert comprobar(proyecto, "Read", {"file_path": str(config.INSTRUCCIONES / "comun.md")}) is None


def test_entrada_no_valida(proyecto: Path) -> None:
    assert comprobar(proyecto, "Read", "no es un diccionario")
    assert comprobar(proyecto, "Read", {})


# ---------------------------------------------------------------------------
# Protección: herramientas, subagentes e internet
# ---------------------------------------------------------------------------

def test_herramientas_que_cambian_bloqueadas(proyecto: Path) -> None:
    for herramienta in ("Write", "Edit", "Bash", "PowerShell", "NotebookEdit", "HerramientaRara"):
        assert comprobar(proyecto, herramienta, {"file_path": "src/app.php"}), herramienta


def test_solo_nuestros_subagentes(proyecto: Path) -> None:
    assert comprobar(proyecto, "Agent", {"subagent_type": "seguridad", "prompt": "x"}) is None
    assert comprobar(proyecto, "Agent", {"subagent_type": "general-purpose"})
    assert comprobar(proyecto, "Agent", {"prompt": "x"})
    assert comprobar(proyecto, "Agent", {"subagent_type": "seguridad", "isolation": "worktree"})
    assert comprobar(proyecto, "Agent", {"subagent_type": "seguridad", "run_in_background": True})
    assert comprobar(proyecto, "Agent", {"subagent_type": "seguridad", "model": "otro"})
    # Un subagente no puede lanzar otros.
    assert comprobar(proyecto, "Agent", {"subagent_type": "errores"}, agente="seguridad")


def test_longitudes_limitadas(proyecto: Path) -> None:
    assert comprobar(proyecto, "WebSearch", {"query": "x" * 300}, agente="investigador")
    assert comprobar(proyecto, "Agent", {"subagent_type": "investigador", "prompt": "x" * 2000})
    assert comprobar(proyecto, "Agent", {"subagent_type": "investigador", "prompt": "PHP 8.4"}) is None


def test_resolver_publico(monkeypatch) -> None:
    def falso(host, puerto, proto=0):
        ips = {"publico.example": "93.184.215.14", "privado.example": "10.0.0.5"}
        return [(2, 1, 6, "", (ips[host], 443))]
    monkeypatch.setattr(seguridad.socket, "getaddrinfo", falso)
    assert seguridad.url_publica("https://publico.example/") is None
    assert seguridad.url_publica("https://privado.example/")


def test_internet_solo_para_el_investigador(proyecto: Path) -> None:
    assert comprobar(proyecto, "WebSearch", {"query": "php 8.4 cambios"})
    assert comprobar(proyecto, "WebSearch", {"query": "x"}, agente="seguridad")
    assert comprobar(proyecto, "WebSearch", {"query": "php 8.4 cambios"}, agente="investigador") is None
    assert comprobar(proyecto, "WebFetch", {"url": "https://www.php.net/releases/8.4/"}, agente="investigador") is None


@pytest.mark.parametrize("url", ["http://www.php.net/", "https://localhost/x", "https://127.0.0.1/",
                                 "https://192.168.1.10/", "https://169.254.169.254/latest/", "https://[::1]/",
                                 "https://intranet/", "https://servidor.local/", "file:///etc/passwd",
                                 "https://127.1/", "https://0x7f.0.0.1/", "https://0177.0.0.1/", "https://10.1/",
                                 "https://8.8.8.8/", "https://127.0.0.1.nip.io/", "https://localtest.me/",
                                 "https://usuario:clave@www.php.net/", "https://www.php.net:8443/",
                                 "https://www.php.net/" + "a" * 500])
def test_webfetch_solo_https_publico(proyecto: Path, url: str) -> None:
    assert comprobar(proyecto, "WebFetch", {"url": url}, agente="investigador"), url


def test_hook_bloquea_y_no_falla_en_abierto(proyecto: Path) -> None:
    avisos: list[str] = []
    hook = seguridad.crear_hook(proyecto, SUBAGENTES, avisar=avisos.append)

    def llamar(datos):
        return asyncio.run(hook(datos, None, None))

    salida = llamar({"tool_name": "Read", "tool_input": {"file_path": ".env"}})
    assert salida["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert avisos
    assert llamar({"tool_name": "Read", "tool_input": {"file_path": "src/app.php"}}) == {}
    # Entradas raras: se bloquea, nunca se permite por error.
    assert llamar({"tool_name": "Read", "tool_input": None})["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert llamar("basura")["hookSpecificOutput"]["permissionDecision"] == "deny"
    # El tipo de subagente llega en agent_type (con agent_id).
    web = {"tool_name": "WebSearch", "tool_input": {"query": "x"}, "agent_id": "a1", "agent_type": "investigador"}
    assert llamar(web) == {}


def test_reglas_de_permisos() -> None:
    reglas = seguridad.reglas_permisos()["permissions"]["deny"]
    assert "Read(**/.env)" in reglas and "Bash" in reglas


# ---------------------------------------------------------------------------
# Inventario y git
# ---------------------------------------------------------------------------

def test_inventario_salta_dependencias_y_terceros(proyecto: Path) -> None:
    inv = inventario.hacer_inventario(proyecto, raiz=proyecto)
    # app.php, util.js, public/assets/app.js y mi-modulo/modulo.js; no vendor ni la librería jquery copiada.
    assert inv.archivos_codigo == 4
    assert "public/assets/jquery" in inv.terceros
    assert "public/assets/mi-modulo" not in inv.terceros
    assert "composer.json" in inv.archivos_clave
    assert "Proyecto: proyecto" in inv.texto()
    assert str(proyecto) not in inv.texto()  # sin rutas del equipo


def test_inventario_incluir_carpeta(proyecto: Path) -> None:
    inv = inventario.hacer_inventario(proyecto, raiz=proyecto, incluir={"vendor"})
    assert inv.por_lenguaje["PHP"] == 2


def test_inventario_archivo_suelto(proyecto: Path) -> None:
    inv = inventario.hacer_inventario(proyecto / "src" / "app.php", raiz=proyecto)
    assert inv.archivos_codigo == 1
    assert inv.cambiados == ["src/app.php"]
    assert inv.alcance == "src/app.php"
    assert "composer.json" in inv.archivos_clave  # se ven los archivos clave de la raíz


def test_buscar_raiz_sin_git(proyecto: Path, monkeypatch) -> None:
    monkeypatch.setattr(inventario, "raiz_git", lambda carpeta: None)
    assert inventario.buscar_raiz(proyecto / "src" / "app.php") == proyecto


def test_buscar_raiz_no_sube_a_la_carpeta_personal(tmp_path: Path, monkeypatch) -> None:
    casa = tmp_path / "casa"
    (casa / "proyecto" / "src").mkdir(parents=True)
    (casa / "CLAUDE.md").write_text("x", encoding="utf-8")  # una marca en la carpeta personal
    monkeypatch.setattr(inventario.Path, "home", classmethod(lambda cls: casa))
    monkeypatch.setattr(inventario, "raiz_git", lambda carpeta: None)
    assert inventario.buscar_raiz(casa / "proyecto" / "src") == casa / "proyecto" / "src"


def test_lenguaje_de() -> None:
    assert inventario.lenguaje_de("vista.blade.php") == "Blade"
    assert inventario.lenguaje_de("main.RS") == "Rust"
    assert inventario.lenguaje_de("foto.png") is None


def git(carpeta: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(carpeta), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    if not HAY_GIT:
        pytest.skip("git no está instalado")
    raiz = tmp_path / "repo"
    (raiz / "sub dir").mkdir(parents=True)
    git(raiz, "init", "-q")
    git(raiz, "config", "user.email", "prueba@example.com")
    git(raiz, "config", "user.name", "Prueba")
    return raiz


def test_cambios_sin_commits_y_con_tildes(repo: Path) -> None:
    (repo / "sub dir" / "código.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "a.py").write_text("a = 1\n", encoding="utf-8")
    git(repo, "add", "a.py")
    cambiados = inventario.archivos_cambiados(repo, None)
    assert "a.py" in cambiados
    assert "sub dir/código.py" in cambiados


def test_cambios_en_subcarpeta_y_desde(repo: Path) -> None:
    (repo / "a.py").write_text("a = 1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "uno")
    git(repo, "tag", "v1")
    (repo / "sub dir" / "nuevo.py").write_text("n = 1\n", encoding="utf-8")
    (repo / "a.py").write_text("a = 2\n", encoding="utf-8")
    # Revisando solo la subcarpeta: el archivo nuevo sale (relativo a la raíz) y a.py no.
    inv = inventario.hacer_inventario(repo / "sub dir", raiz=repo, solo_cambios=True)
    assert inv.cambiados == ["sub dir/nuevo.py"]
    assert inventario.archivos_cambiados(repo, "v1")
    with pytest.raises(RuntimeError):
        inventario.archivos_cambiados(repo, "--output=x")
    with pytest.raises(RuntimeError):
        inventario.archivos_cambiados(repo, "no-existe")


def test_cambios_sin_repositorio(proyecto: Path, monkeypatch) -> None:
    monkeypatch.setattr(inventario, "raiz_git", lambda carpeta: None)
    with pytest.raises(RuntimeError):
        inventario.archivos_cambiados(proyecto, None)


def test_git_no_instalado(proyecto: Path, monkeypatch) -> None:
    def falla(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(inventario.subprocess, "run", falla)
    with pytest.raises(RuntimeError, match="git no está instalado"):
        inventario.git(proyecto, "status")


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------

def test_normalizar_y_numerar() -> None:
    brutos = [
        {"gravedad": "baja", "archivo": "b.php", "linea": "3", "titulo": "B"},
        {"gravedad": "Crítica", "archivo": "a.php", "linea": 10, "linea_fin": 2, "titulo": "A", "confianza": 7},
        {"gravedad": "rara", "archivo": "c.php", "titulo": "C", "confianza": "nan"},
        {"gravedad": "alta", "archivo": "", "titulo": "sin archivo"},
    ]
    limpios = [h for h in (informe.normalizar(b) for b in brutos) if h]
    assert len(limpios) == 3
    numerados = informe.numerar(limpios)
    assert [h["id"] for h in numerados] == ["H-001", "H-002", "H-003"]
    assert numerados[0]["gravedad"] == "critica"
    assert numerados[0]["linea_fin"] == 10
    assert numerados[0]["confianza"] == 1.0
    assert numerados[1]["gravedad"] == "media" and numerados[1]["confianza"] == 0.0


def test_normalizar_ruta_absoluta(tmp_path: Path) -> None:
    absoluta = (tmp_path / "src" / "a.php").as_posix()
    h = informe.normalizar({"titulo": "X", "archivo": absoluta}, raiz=tmp_path)
    assert h["archivo"] == "src/a.php"


def test_extraer_json_de_respuesta() -> None:
    texto = 'Hecho.\n```json\n{"hallazgos": [{"titulo": "X", "archivo": "a.py"}], "notas": ""}\n```\n'
    assert informe.extraer_json(texto)["hallazgos"][0]["titulo"] == "X"
    assert informe.extraer_json("sin json") is None


def test_informe_parcial() -> None:
    respuestas = [
        ("seguridad", '{"hallazgos": [{"gravedad": "alta", "titulo": "Inyección", "archivo": "a.php"}]}'),
        ("investigador", "guía de texto"),
        ("rendimiento", "respuesta rota"),
    ]
    parcial = informe.informe_parcial(respuestas)
    assert len(parcial["hallazgos"]) == 1
    assert parcial["hallazgos"][0]["especialista"] == "seguridad"
    assert "PARCIAL" in parcial["resumen"]


def datos_prueba(raiz: Path) -> informe.DatosEjecucion:
    return informe.DatosEjecucion(raiz=raiz, modelo="m", modelo_especialistas="m", esfuerzo="high",
                                  tope_usd=5, coste_usd=1.234, lanzados=["seguridad"])


def test_markdown_escapado(tmp_path: Path) -> None:
    hallazgo = informe.normalizar({"gravedad": "alta", "archivo": "a`b.php", "linea": 5,
                                   "titulo": "Fallo | con tubería\ny salto <script>alert(1)</script>",
                                   "descripcion": "<img src=x onerror=alert(1)>"})
    contenido = {"resumen": "ok", "puntos_fuertes": [], "investigado": [], "sin_revisar": [],
                 "hallazgos": informe.numerar([hallazgo])}
    texto = informe.a_markdown(contenido, datos_prueba(tmp_path), "inventario\n```\nfin")
    fila = next(linea for linea in texto.splitlines() if linea.startswith("| [H-001]"))
    assert fila.count(" | ") == 3          # la tabla no se rompe
    assert "<script>" not in texto and "<img" not in texto
    assert "````text" in texto             # la valla del inventario es más larga que su ```
    otro = informe.texto_md("mira ![x](https://atacante/?d=1) y [y](javascript:alert(1))")
    assert "![x](" not in otro and "[y](" not in otro
    assert str(tmp_path) not in texto      # sin rutas del equipo


def test_guardar_informe(tmp_path: Path) -> None:
    contenido = {"resumen": "Bien.", "puntos_fuertes": ["Ordenado"], "investigado": [],
                 "sin_revisar": [], "hallazgos": informe.numerar([informe.normalizar(
                     {"gravedad": "alta", "archivo": "a.php", "linea": 5, "titulo": "Fallo"})])}
    md, js = informe.guardar(contenido, datos_prueba(tmp_path), "inventario", tmp_path / "docs" / "revisiones")
    texto = md.read_text(encoding="utf-8")
    assert "H-001" in texto and "Fallo" in texto and "1.23 USD" in texto
    datos_json = json.loads(js.read_text(encoding="utf-8"))
    assert datos_json["hallazgos"][0]["id"] == "H-001"
    assert str(tmp_path) not in js.read_text(encoding="utf-8")
    md2, _ = informe.guardar(contenido, datos_prueba(tmp_path), "inventario", tmp_path / "docs" / "revisiones")
    assert md2 != md


# ---------------------------------------------------------------------------
# Agentes (montaje, sin llamar a la API)
# ---------------------------------------------------------------------------

def test_subagentes_son_de_solo_lectura() -> None:
    subagentes = agentes.crear_subagentes(list(config.ESPECIALISTAS), "claude-opus-5-5", "es", "high", True)
    assert set(config.ESPECIALISTAS) <= set(subagentes)
    assert {"investigador", "verificador"} <= set(subagentes)
    for nombre, definicion in subagentes.items():
        assert not set(definicion.tools) & {"Write", "Edit", "Bash", "PowerShell"}, nombre
        assert "{idioma}" not in definicion.prompt, nombre
    # El investigador no puede leer el proyecto; los demás no tienen internet.
    assert set(subagentes["investigador"].tools) == set(config.HERRAMIENTAS_WEB)
    assert not set(subagentes["seguridad"].tools) & set(config.HERRAMIENTAS_WEB)
    assert "investigador" not in agentes.crear_subagentes(["seguridad"], "m", "es", "high", False)


def test_instrucciones_del_coordinador() -> None:
    texto = agentes.instrucciones_coordinador(["seguridad", "rendimiento"], "es", 3.5, True)
    assert "3.50" in texto and "  - `seguridad`:" in texto and "  - `datos`:" not in texto
    assert "`investigador`" in texto
    assert "{" not in texto.replace("{{", "")  # ningún hueco sin rellenar
    sin_web = agentes.instrucciones_coordinador(["seguridad"], "es", 1, False)
    assert "  - `investigador`" not in sin_web and "Internet está desactivado" in sin_web


# ---------------------------------------------------------------------------
# Línea de órdenes
# ---------------------------------------------------------------------------

def test_cli_simular_y_validaciones(proyecto: Path, capsys) -> None:
    import revisar
    revisar.main([str(proyecto), "--simular"])
    salida = capsys.readouterr().out
    assert "Simulación terminada" in salida
    for malos in ([str(proyecto), "--tope", "inf"], [str(proyecto), "--tope", "nan"], [str(proyecto), "--tope", "0"],
                  [str(proyecto), "--solo", "inventado"], [str(proyecto), "--desde", "main"],
                  [str(proyecto / "no-existe")]):
        with pytest.raises(SystemExit):
            revisar.main(malos)
    with pytest.raises(SystemExit):
        revisar.main([str(proyecto), "--idioma", "xx"])


def test_cli_raiz(proyecto: Path, tmp_path: Path, capsys) -> None:
    import revisar
    revisar.main([str(proyecto / "src"), "--raiz", str(proyecto), "--simular"])
    assert "Parte que se revisa: src" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        revisar.main([str(proyecto), "--raiz", str(proyecto / "src"), "--simular"])


def test_cli_no_acepta_la_carpeta_personal(capsys) -> None:
    import revisar
    with pytest.raises(SystemExit):
        revisar.main([str(Path.home()), "--simular"])
