# -*- coding: utf-8 -*-
"""
Pruebas sin conexión de la ejecución con el SDK: comprobación de credenciales, variables de entorno,
opciones del SDK y una revisión completa con un «query» falso. Están aparte para que, si el SDK no está
instalado, solo se salten estas y no las de seguridad.

Ejecutar:  python -m pytest -q
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from revisor import config, seguridad

SUBAGENTES = set(config.ESPECIALISTAS) | {"verificador", "investigador"}


@pytest.fixture
def proyecto(tmp_path: Path) -> Path:
    raiz = tmp_path / "proyecto"
    (raiz / "src").mkdir(parents=True)
    (raiz / "src" / "app.php").write_text("<?php echo 1;\n", encoding="utf-8")
    return raiz


# ---------------------------------------------------------------------------
# Credenciales y ejecución con un «query» falso
# ---------------------------------------------------------------------------

ejecutar = pytest.importorskip("revisor.ejecutar")


def init_bueno(**cambios):
    datos = {"apiKeySource": "ANTHROPIC_API_KEY", "apiProvider": "firstParty",
             "tools": ["Read", "Glob", "Grep", "Agent"], "model": "claude-opus-5-5"}
    datos.update(cambios)
    return datos


def test_comprobar_inicio() -> None:
    ejecutar.comprobar_inicio(init_bueno())
    for malo in (init_bueno(apiKeySource="none"), init_bueno(apiKeySource="/login managed key"),
                 init_bueno(apiProvider="bedrock"), init_bueno(auth_conflict=True),
                 init_bueno(tools=["Read", "Bash"])):
        with pytest.raises(ejecutar.CredencialIncorrecta):
            ejecutar.comprobar_inicio(malo)


def test_quita_variables_ajenas(monkeypatch) -> None:
    for nombre in ("ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_GATEWAY",
                   "CLAUDE_CODE_SUBAGENT_MODEL", "ANTHROPIC_UNIX_SOCKET", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.setenv(nombre, "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", "C:/git/bash.exe")
    quitadas = ejecutar.quitar_variables_ajenas()
    assert "CLAUDE_CODE_SUBAGENT_MODEL" in quitadas and "ANTHROPIC_UNIX_SOCKET" not in os.environ
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-prueba" and "CLAUDE_CODE_GIT_BASH_PATH" in os.environ


def test_opciones_del_sdk(proyecto: Path) -> None:
    hook = seguridad.crear_hook(proyecto, SUBAGENTES)
    opts = ejecutar.opciones(proyecto, ["seguridad"], "m", "m", "high", 2.0, "es", True, hook, "sk-prueba")
    assert "Write" not in opts.tools and "Bash" not in opts.tools
    assert opts.permission_mode == "dontAsk" and opts.setting_sources == []
    assert opts.max_budget_usd == 2.0
    assert opts.env["ANTHROPIC_API_KEY"] == "sk-prueba" and "CLAUDE_CONFIG_DIR" in opts.env
    assert opts.hooks["PreToolUse"][0].on_failure == "block"
    assert json.loads(opts.settings)["permissions"]["deny"]


def mensajes_falsos(*mensajes):
    """Sustituye a claude_agent_sdk.query devolviendo estos mensajes."""
    async def falso(prompt, options):
        for m in mensajes:
            yield m
    return falso


def correr(monkeypatch, proyecto: Path, *mensajes):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    monkeypatch.setattr(ejecutar, "query", mensajes_falsos(*mensajes))
    return asyncio.run(ejecutar.revisar(proyecto, "encargo", ["seguridad"], "m", "m", "high", 1.0, "es",
                                        False, mostrar=lambda _: None))


def resultado_sdk(**campos):
    base = dict(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=3,
                session_id="s", total_cost_usd=0.5)
    base.update(campos)
    return ejecutar.ResultMessage(**base)


def test_revisar_completa(monkeypatch, proyecto: Path) -> None:
    final = {"resumen": "ok", "puntos_fuertes": [], "investigado": [], "sin_revisar": [],
             "hallazgos": [{"gravedad": "alta", "archivo": "src/app.php", "linea": 1, "titulo": "X"}]}
    res = correr(monkeypatch, proyecto, ejecutar.SystemMessage(subtype="init", data=init_bueno()),
                 resultado_sdk(structured_output=final))
    assert res.estado == "completa" and res.informe["resumen"] == "ok" and res.coste_usd == 0.5


def test_revisar_para_si_la_credencial_no_es_la_api_key(monkeypatch, proyecto: Path) -> None:
    with pytest.raises(ejecutar.CredencialIncorrecta):
        correr(monkeypatch, proyecto, ejecutar.SystemMessage(subtype="init", data=init_bueno(apiKeySource="none")))


def test_revisar_para_si_no_llega_init(monkeypatch, proyecto: Path) -> None:
    with pytest.raises(ejecutar.CredencialIncorrecta):
        correr(monkeypatch, proyecto, resultado_sdk())


def test_revisar_tope_y_clave_mala(monkeypatch, proyecto: Path) -> None:
    res = correr(monkeypatch, proyecto, ejecutar.SystemMessage(subtype="init", data=init_bueno()),
                 resultado_sdk(subtype="error_max_budget_usd", is_error=True))
    assert res.estado == "parcial" and "tope" in res.motivo
    res = correr(monkeypatch, proyecto, ejecutar.SystemMessage(subtype="init", data=init_bueno()),
                 resultado_sdk(is_error=True, api_error_status=401, result="Invalid API key"))
    assert res.estado == "fallida" and "401" in res.motivo


def test_lanzados_solo_si_el_subagente_responde(monkeypatch, proyecto: Path) -> None:
    from claude_agent_sdk import AssistantMessage, ToolResultBlock, ToolUseBlock, UserMessage
    usar_ok = AssistantMessage(content=[ToolUseBlock(id="1", name="Agent", input={"subagent_type": "seguridad"})],
                               model="m")
    usar_mal = AssistantMessage(content=[ToolUseBlock(id="2", name="Agent", input={"subagent_type": "otro"})],
                                model="m")
    respuesta_ok = UserMessage(content=[ToolResultBlock(tool_use_id="1", content='{"hallazgos": []}')])
    respuesta_mal = UserMessage(content=[ToolResultBlock(tool_use_id="2", content="bloqueado", is_error=True)])
    res = correr(monkeypatch, proyecto, ejecutar.SystemMessage(subtype="init", data=init_bueno()),
                 usar_ok, usar_mal, respuesta_ok, respuesta_mal, resultado_sdk(is_error=True, subtype="error_max_turns"))
    assert res.lanzados == ["seguridad"]
    assert [n for n, _ in res.respuestas] == ["seguridad"]
