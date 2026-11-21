# -*- coding: utf-8 -*-
"""
Ejecución de la revisión con el Claude Agent SDK.

Lanza al coordinador con:
  - solo herramientas de lectura y la de lanzar subagentes (internet, solo el investigador);
  - el «hook» de seguridad (bloquea lecturas fuera del proyecto, secretos, subagentes ajenos…), que si
    falla BLOQUEA (on_failure="block");
  - reglas de permisos que niegan leer secretos, como segunda barrera;
  - la configuración de Claude Code aislada (sin ajustes, hooks, plugins ni sesión del usuario) y sin
    variables de otros proveedores o credenciales, para que solo pague la API key;
  - el tope de gasto del SDK.

Mientras trabaja, enseña en pantalla qué está haciendo y va guardando las respuestas de los
especialistas en «resultado», para poder sacar un informe parcial si se corta o se cancela.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import aclosing
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)
from claude_agent_sdk.types import HookMatcher

from . import agentes, config, informe, seguridad

# Carpeta privada para la configuración aislada de Claude Code (no se sube a git). Guarda las sesiones
# del agente (incluido el código que leyó); se puede borrar sin problema cuando se quiera.
CONFIG_AISLADA = config.PAQUETE.parent / ".estado" / "claude-config"

# Variables de entorno de Anthropic o de Claude Code que se CONSERVAN. Todas las demás que empiecen por
# ANTHROPIC_, CLAUDE_ o CLAUDECODE se quitan antes de lanzar Claude Code (el SDK le pasa todo el entorno):
# podrían mandar la clave a otro servidor, usar otro proveedor u otra cuenta, o cambiar los modelos.
VARIABLES_PERMITIDAS = {"ANTHROPIC_API_KEY", "CLAUDE_CODE_GIT_BASH_PATH"}
PREFIJOS_AJENOS = ("ANTHROPIC_", "CLAUDE_", "CLAUDECODE")

# Herramientas que, si aparecen en la sesión, significan que algo no está como debe.
HERRAMIENTAS_PELIGROSAS = set(config.HERRAMIENTAS_PROHIBIDAS)


class CredencialIncorrecta(RuntimeError):
    """Se lanza si la sesión no está usando solo la API key, o no está como debe (para no gastar)."""


@dataclass
class Resultado:
    """Lo que devuelve una revisión. Se va llenando mientras trabaja (sirve también si se cancela)."""

    informe: dict[str, Any] | None = None
    coste_usd: float | None = None
    duracion_s: float = 0.0
    turnos: int = 0
    estado: str = "completa"
    motivo: str = ""
    lanzados: list[str] = field(default_factory=list)
    respuestas: list[tuple[str, str]] = field(default_factory=list)  # (especialista, texto)
    bloqueos: list[str] = field(default_factory=list)


def texto_resultado(contenido: Any) -> str:
    """Texto de un ToolResultBlock (puede venir como texto o como lista de bloques)."""
    if isinstance(contenido, str):
        return contenido
    if isinstance(contenido, list):
        return "\n".join(str(b.get("text", "")) for b in contenido if isinstance(b, dict) and b.get("type") == "text")
    return ""


def quitar_variables_ajenas() -> list[str]:
    """Quita del entorno las variables ANTHROPIC_* / CLAUDE_* que no estén permitidas. Devuelve sus nombres."""
    quitadas = sorted(nombre for nombre in os.environ
                      if nombre.upper().startswith(PREFIJOS_AJENOS) and nombre.upper() not in VARIABLES_PERMITIDAS)
    for nombre in quitadas:
        os.environ.pop(nombre, None)
    return quitadas


def comprobar_inicio(datos: dict[str, Any]) -> None:
    """
    Comprueba el mensaje «init» de la sesión. Lanza CredencialIncorrecta si:
      - la credencial no es ANTHROPIC_API_KEY,
      - el proveedor no es la API de Anthropic,
      - hay un conflicto de credenciales,
      - o la sesión tiene alguna herramienta que pueda cambiar algo o ejecutar órdenes.
    """
    origen = str(datos.get("apiKeySource", ""))
    if origen != "ANTHROPIC_API_KEY":
        raise CredencialIncorrecta(f"La sesión no usa ANTHROPIC_API_KEY (origen: {origen or 'desconocido'}). "
                                   "Se para para no gastar de otro sitio.")
    proveedor = datos.get("apiProvider")
    if proveedor not in (None, "", "firstParty"):
        raise CredencialIncorrecta(f"La sesión usa el proveedor «{proveedor}» en vez de la API de Anthropic.")
    if datos.get("auth_conflict"):
        raise CredencialIncorrecta("Hay un conflicto de credenciales en la sesión; se para por seguridad.")
    peligrosas = sorted(set(datos.get("tools") or []) & HERRAMIENTAS_PELIGROSAS)
    if peligrosas:
        raise CredencialIncorrecta(f"La sesión tiene herramientas que no debería: {', '.join(peligrosas)}.")


def opciones(raiz: Path, especialistas: list[str], modelo: str, modelo_especialistas: str,
             esfuerzo: str, tope: float, idioma: str, con_web: bool,
             hook, clave_api: str) -> ClaudeAgentOptions:
    """Opciones del SDK para el coordinador."""
    # El coordinador NO tiene internet: así no puede sacar código del proyecto a una web. Solo el
    # investigador (que no lee el proyecto) busca en internet.
    herramientas = list(config.HERRAMIENTAS_LECTURA) + [config.HERRAMIENTA_SUBAGENTES]
    if con_web:
        herramientas += list(config.HERRAMIENTAS_WEB)  # existen en la sesión; el hook solo deja al investigador

    CONFIG_AISLADA.mkdir(parents=True, exist_ok=True)

    return ClaudeAgentOptions(
        # Solo estas herramientas existen para el agente, y se aprueban sin preguntar.
        tools=herramientas,
        allowed_tools=herramientas,
        disallowed_tools=list(config.HERRAMIENTAS_PROHIBIDAS),
        # Cualquier otra cosa que pidiera permiso se deniega sola (nadie está mirando).
        permission_mode="dontAsk",
        system_prompt=agentes.instrucciones_coordinador(especialistas, idioma, tope, con_web),
        agents=agentes.crear_subagentes(especialistas, modelo_especialistas, idioma, esfuerzo, con_web),
        model=modelo,
        effort=esfuerzo,
        thinking={"type": "adaptive"},
        cwd=str(raiz),
        max_turns=config.TURNOS_COORDINADOR,
        max_budget_usd=tope,
        output_format={"type": "json_schema", "schema": agentes.ESQUEMA_INFORME},
        # No cargar ajustes, hooks, plugins ni CLAUDE.md del usuario o del proyecto: el agente lee las
        # normas del proyecto él mismo con Read, como un dato más.
        setting_sources=[],
        settings=json.dumps(seguridad.reglas_permisos()),
        strict_mcp_config=True,
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[hook], timeout=15, on_failure="block")]},
        env={
            "ANTHROPIC_API_KEY": clave_api,
            # Configuración aislada: así no se usa la sesión iniciada de Claude (suscripción) aunque exista
            # en el equipo, y no se cargan ajustes personales.
            "CLAUDE_CONFIG_DIR": str(CONFIG_AISLADA),
        },
    )


async def revisar(raiz: Path, encargo: str, especialistas: list[str], modelo: str,
                  modelo_especialistas: str, esfuerzo: str, tope: float, idioma: str, con_web: bool,
                  mostrar: Callable[[str], None], detallado: bool = False,
                  bloqueadas: list[Path] | None = None, resultado: Resultado | None = None) -> Resultado:
    """
    Hace la revisión y devuelve el resultado. «encargo» es el mensaje inicial para el coordinador.
    «mostrar» escribe una línea de progreso. «resultado» se puede pasar ya creado para conservar lo
    encontrado aunque la revisión se cancele (Ctrl+C).
    """
    clave_api = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not clave_api:
        raise CredencialIncorrecta("Falta la variable de entorno ANTHROPIC_API_KEY.")
    quitadas = quitar_variables_ajenas()
    if quitadas:
        mostrar(f"  (se ignoran {len(quitadas)} variables de entorno de Anthropic/Claude Code para usar solo "
                "la API key" + (": " + ", ".join(quitadas) if detallado else "; --detallado para verlas") + ")")

    resultado = resultado if resultado is not None else Resultado()
    inicio = time.monotonic()

    def bloqueo(motivo: str) -> None:
        resultado.bloqueos.append(motivo)
        mostrar(f"  ⛔ Bloqueado: {motivo}")

    subagentes = set(especialistas) | {"verificador"} | ({"investigador"} if con_web else set())
    hook = seguridad.crear_hook(raiz, subagentes, bloqueadas=bloqueadas, avisar=bloqueo)
    opts = opciones(raiz, especialistas, modelo, modelo_especialistas, esfuerzo, tope, idioma,
                    con_web, hook, clave_api)

    pendientes: dict[str, str] = {}  # id de la llamada a Agent -> nombre del subagente
    lecturas = 0
    verificado = False
    final: ResultMessage | None = None

    try:
        async with aclosing(query(prompt=encargo, options=opts)) as mensajes:
            async for mensaje in mensajes:
                # 1) Al empezar: comprobar credencial, proveedor y herramientas. Nada antes de esto.
                if isinstance(mensaje, SystemMessage) and mensaje.subtype == "init":
                    comprobar_inicio(mensaje.data)
                    verificado = True
                    mostrar(f"✔ Conectado con la API key · modelo {mensaje.data.get('model', modelo)}")
                    continue
                if not verificado and not isinstance(mensaje, SystemMessage):
                    raise CredencialIncorrecta("La sesión empezó sin el mensaje de inicio; no se puede "
                                               "comprobar la credencial. Se para por seguridad.")

                # 2) Lo que hace el coordinador o un subagente.
                if isinstance(mensaje, AssistantMessage):
                    sangria = "  " if mensaje.parent_tool_use_id else ""
                    for bloque in mensaje.content:
                        if isinstance(bloque, ToolUseBlock):
                            entrada = bloque.input if isinstance(bloque.input, dict) else {}
                            if bloque.name in ("Agent", "Task"):
                                nombre = str(entrada.get("subagent_type") or "general-purpose")
                                pendientes[bloque.id] = nombre
                                descripcion = str(entrada.get("description") or "")
                                mostrar(f"{sangria}→ Lanza a «{nombre}»" + (f": {descripcion}" if descripcion else ""))
                            elif bloque.name == "WebSearch":
                                mostrar(f"{sangria}🔎 Busca en internet: {entrada.get('query', '')}")
                            elif bloque.name == "WebFetch":
                                mostrar(f"{sangria}🌐 Lee la página: {entrada.get('url', '')}")
                            elif bloque.name == "Read":
                                lecturas += 1
                                if detallado:
                                    mostrar(f"{sangria}📄 Lee: {entrada.get('file_path', '')}")
                                elif lecturas % 25 == 0:
                                    mostrar(f"  … {lecturas} archivos leídos")
                            elif detallado:
                                mostrar(f"{sangria}· {bloque.name}: {entrada}")
                        elif isinstance(bloque, TextBlock) and detallado and not mensaje.parent_tool_use_id:
                            texto = bloque.text.strip()
                            if texto:
                                mostrar("  💬 " + texto[:300])
                    continue

                # 3) Respuestas de los subagentes (llegan como resultado de la herramienta Agent).
                if isinstance(mensaje, UserMessage) and isinstance(mensaje.content, list):
                    for bloque in mensaje.content:
                        if isinstance(bloque, ToolResultBlock) and bloque.tool_use_id in pendientes:
                            nombre = pendientes.pop(bloque.tool_use_id)
                            if bloque.is_error:
                                mostrar(f"✖ «{nombre}» no se pudo lanzar o falló")
                                continue
                            resultado.lanzados.append(nombre)
                            resultado.respuestas.append((nombre, texto_resultado(bloque.content)))
                            mostrar(f"✔ «{nombre}» ha terminado")
                    continue

                # 4) El final.
                if isinstance(mensaje, ResultMessage):
                    final = mensaje
    except CredencialIncorrecta:
        raise
    except Exception as error:  # el SDK lanza una excepción tras un resultado de error
        if final is None:
            resultado.estado = "fallida"
            resultado.motivo = f"{type(error).__name__}: {error}"
    finally:
        resultado.duracion_s = time.monotonic() - inicio

    if final is not None:
        interpretar_final(final, resultado, tope)

    # Si no hay informe final, montar uno parcial con lo que dijeron los especialistas.
    if resultado.informe is None:
        if resultado.estado == "completa":
            resultado.estado = "parcial"
        resultado.informe = informe.informe_parcial(resultado.respuestas)
    return resultado


def interpretar_final(final: ResultMessage, resultado: Resultado, tope: float) -> None:
    """Pasa el ResultMessage del SDK a «resultado» (coste, turnos, informe o motivo del fallo)."""
    resultado.coste_usd = final.total_cost_usd
    resultado.turnos = final.num_turns
    if final.subtype == "success" and not final.is_error and isinstance(final.structured_output, dict):
        resultado.informe = final.structured_output
        return

    resultado.estado = "parcial"
    motivos = {
        "error_max_budget_usd": f"se alcanzó el tope de gasto ({tope:.2f} USD)",
        "error_max_turns": "se alcanzó el máximo de turnos",
        "error_max_structured_output_retries": "el informe final no tenía el formato pedido",
        "error_during_execution": "error durante la ejecución",
    }
    estado_api = final.api_error_status
    if estado_api == 401:
        resultado.motivo = "la API rechazó la clave (401): revisa ANTHROPIC_API_KEY"
    elif estado_api in (402, 403):
        resultado.motivo = f"la API no permite la petición ({estado_api}): revisa el saldo o los permisos de la clave"
    elif final.stop_reason == "refusal":
        resultado.motivo = "el modelo rechazó la petición"
    else:
        resultado.motivo = motivos.get(final.subtype, "error al terminar")
    detalle = "; ".join(str(e) for e in (final.errors or [])) or str(final.result or "")
    if detalle and (final.subtype != "success" or final.is_error):
        resultado.motivo += f" — {detalle.strip()[:300]}"
    if estado_api in (401, 402, 403):
        resultado.estado = "fallida"
