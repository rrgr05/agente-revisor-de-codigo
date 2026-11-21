# -*- coding: utf-8 -*-
"""
Montaje de los agentes: lee las instrucciones (archivos .md) y crea las definiciones del
coordinador y de los subagentes (especialistas, investigador y verificador) para el Agent SDK.

También define el esquema JSON del informe final, que el coordinador está obligado a cumplir
(salida estructurada del SDK).
"""

from __future__ import annotations

from claude_agent_sdk import AgentDefinition

from . import config

# Nombres de idioma para las instrucciones (definidos en config).
IDIOMAS = config.IDIOMAS


def leer_instruccion(nombre: str) -> str:
    """Lee un archivo de instrucciones de la carpeta «instrucciones» (p. ej. 'coordinador.md')."""
    return (config.INSTRUCCIONES / nombre).read_text(encoding="utf-8")


def rellenar(texto: str, valores: dict[str, str]) -> str:
    """
    Sustituye los huecos {nombre} del texto. Se usa replace y no str.format porque las
    instrucciones llevan ejemplos JSON con llaves que format rompería.
    """
    for clave, valor in valores.items():
        texto = texto.replace("{" + clave + "}", valor)
    return texto


def crear_subagentes(especialistas: list[str], modelo: str, idioma: str, esfuerzo: str,
                     con_web: bool) -> dict[str, AgentDefinition]:
    """
    Definiciones de los subagentes que el coordinador puede lanzar con la herramienta Agent.

    Ninguno tiene herramientas para escribir ni ejecutar órdenes: solo leer (y buscar en
    internet el investigador, si la web está activada).
    """
    valores = {"idioma": IDIOMAS.get(idioma, idioma)}
    comun = rellenar(leer_instruccion("comun.md"), valores)
    lectura = list(config.HERRAMIENTAS_LECTURA)

    agentes: dict[str, AgentDefinition] = {}

    for clave in especialistas:
        propias = rellenar(leer_instruccion(f"especialistas/{clave}.md"), valores)
        agentes[clave] = AgentDefinition(
            description=f"Especialista en revisión de código ({clave}): {config.ESPECIALISTAS[clave]}",
            prompt=propias + "\n\n" + comun,
            tools=lectura,
            disallowedTools=list(config.HERRAMIENTAS_PROHIBIDAS),
            model=modelo,
            effort=esfuerzo,
            maxTurns=config.TURNOS_ESPECIALISTA,
            background=False,
        )

    if con_web:
        agentes["investigador"] = AgentDefinition(
            description="Busca en internet las buenas prácticas, errores típicos y problemas de seguridad "
                        "de un lenguaje, framework o versión que no se domine, y devuelve una guía corta.",
            prompt=rellenar(leer_instruccion("investigador.md"), valores),
            # Solo internet: NO lee el proyecto, así no puede sacar código privado a una web.
            tools=list(config.HERRAMIENTAS_WEB),
            disallowedTools=list(config.HERRAMIENTAS_PROHIBIDAS),
            model=modelo,
            effort=esfuerzo,
            maxTurns=40,
            background=False,
        )

    agentes["verificador"] = AgentDefinition(
        description="Comprueba una lista de hallazgos contra el código, corrige los que estén mal y "
                    "descarta los falsos positivos.",
        prompt=rellenar(leer_instruccion("verificador.md"), valores) + "\n\n" + comun,
        tools=lectura,
        disallowedTools=list(config.HERRAMIENTAS_PROHIBIDAS),
        model=modelo,
        effort=esfuerzo,
        maxTurns=config.TURNOS_ESPECIALISTA,
        background=False,
    )
    return agentes


def instrucciones_coordinador(especialistas: list[str], idioma: str, tope: float,
                              con_web: bool = True) -> str:
    """Texto de sistema del coordinador, con la lista de especialistas disponibles."""
    lista = "\n".join(f"  - `{clave}`: {config.ESPECIALISTAS[clave]}" for clave in especialistas)
    if con_web:
        investigador = ("  - `investigador`: busca en internet cómo se programa bien en un lenguaje, "
                        "framework o versión que no conozcas a fondo y devuelve una guía corta con los "
                        "errores típicos y las buenas prácticas. NO puede leer el proyecto: dale en el "
                        "encargo solo el nombre de la tecnología y su versión, nunca código ni datos del "
                        "proyecto.")
        paso_web = ("Si hay un lenguaje, un framework o una versión reciente que no conozcas con "
                    "seguridad (o cuyas buenas prácticas hayan cambiado), lanza al `investigador` (uno "
                    "por tema, a la vez si son varios) antes que a los especialistas. Si lo conoces "
                    "bien, no gastes en esto.")
    else:
        investigador = ""
        paso_web = ("Internet está desactivado en esta revisión: usa lo que ya sabes y, si algo no lo "
                    "dominas, dilo en «sin_revisar».")
    return rellenar(leer_instruccion("coordinador.md"), {
        "lista_especialistas": lista,
        "linea_investigador": investigador,
        "paso_investigar": paso_web,
        "idioma": IDIOMAS.get(idioma, idioma),
        "tope": f"{tope:.2f}",
    })


# Esquema del informe final que devuelve el coordinador (salida estructurada).
ESQUEMA_INFORME = {
    "type": "object",
    "additionalProperties": False,
    "required": ["resumen", "puntos_fuertes", "hallazgos", "investigado", "sin_revisar"],
    "properties": {
        "resumen": {"type": "string", "description": "Estado general del código en 2 a 5 frases."},
        "puntos_fuertes": {"type": "array", "items": {"type": "string"}},
        "hallazgos": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["gravedad", "categoria", "especialista", "archivo", "linea", "linea_fin",
                             "titulo", "descripcion", "impacto", "recomendacion", "confianza"],
                "properties": {
                    "gravedad": {"type": "string", "enum": list(config.GRAVEDADES)},
                    "categoria": {"type": "string"},
                    "especialista": {"type": "string"},
                    "archivo": {"type": "string", "description": "Ruta relativa a la raíz del proyecto."},
                    "linea": {"type": "integer", "description": "Primera línea (0 si es todo el archivo)."},
                    "linea_fin": {"type": "integer", "description": "Última línea (igual que linea si es una)."},
                    "titulo": {"type": "string"},
                    "descripcion": {"type": "string"},
                    "impacto": {"type": "string"},
                    "recomendacion": {"type": "string"},
                    "confianza": {"type": "number"},
                },
            },
        },
        "investigado": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["tema", "fuentes"],
                "properties": {
                    "tema": {"type": "string"},
                    "fuentes": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "sin_revisar": {"type": "array", "items": {"type": "string"},
                        "description": "Zonas o archivos que no se revisaron y por qué."},
    },
}
