# -*- coding: utf-8 -*-
"""
Agente revisor de código — programa principal.

Uso básico:
    python revisar.py "C:\\ruta\\del\\proyecto"

Revisa el proyecto (o una carpeta, o un archivo) SIN cambiar nada y deja un informe numerado
en <raíz del proyecto>/docs/revisiones/. Ver README.md o «python revisar.py --help».
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import sys
from pathlib import Path

# En Windows, que la consola acepte tildes y emojis.
for flujo in (sys.stdout, sys.stderr):
    try:
        flujo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from revisor import __version__, config, informe, inventario  # noqa: E402


def argumentos(lista_args: list[str] | None = None) -> argparse.Namespace:
    """Lee las opciones de la línea de órdenes."""
    p = argparse.ArgumentParser(
        prog="revisar",
        description="Agente revisor de código: busca errores, fallos de seguridad, malas prácticas y "
                    "código ineficiente en cualquier lenguaje, sin cambiar nada. Deja un informe "
                    "numerado (Markdown + JSON).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Ejemplos:\n"
               '  python revisar.py "D:\\proyectos\\mi-web" --simular\n'
               '  python revisar.py "D:\\proyectos\\mi-web"\n'
               '  python revisar.py . --cambios --tope 2\n'
               '  python revisar.py src/api --solo seguridad,rendimiento --modelo claude-sonnet-5-5\n',
    )
    p.add_argument("ruta", help="Proyecto, carpeta o archivo que se revisa.")
    p.add_argument("--simular", action="store_true",
                   help="Enseña qué se revisaría (inventario y ajustes) sin llamar a la API: no gasta nada.")
    p.add_argument("--cambios", action="store_true",
                   help="Revisa solo los archivos cambiados en git (sin commit y nuevos).")
    p.add_argument("--desde", metavar="REF",
                   help="Con --cambios: incluye también lo cambiado desde esta rama, etiqueta o commit "
                        "(p. ej. main u origin/main).")
    p.add_argument("--solo", metavar="LISTA",
                   help="Especialistas que se pueden usar, separados por comas. Disponibles: "
                        + ", ".join(config.ESPECIALISTAS) + ". Por defecto, todos (el coordinador "
                        "elige los que hagan falta).")
    p.add_argument("--modelo", default=config.MODELO_POR_DEFECTO,
                   help=f"Modelo del coordinador (por defecto {config.MODELO_POR_DEFECTO}).")
    p.add_argument("--modelo-especialistas", metavar="MODELO",
                   help="Modelo de los especialistas, investigador y verificador (por defecto, el mismo que --modelo).")
    p.add_argument("--esfuerzo", choices=config.ESFUERZOS, default=config.ESFUERZO_POR_DEFECTO,
                   help=f"Profundidad del razonamiento (por defecto {config.ESFUERZO_POR_DEFECTO}).")
    p.add_argument("--tope", type=float, default=config.TOPE_POR_DEFECTO_USD, metavar="USD",
                   help=f"Gasto máximo de la revisión en dólares (por defecto {config.TOPE_POR_DEFECTO_USD:.2f}). "
                        "Es una estimación: puede pasarse un poco.")
    p.add_argument("--idioma", default="es", choices=sorted(config.IDIOMAS),
                   help="Idioma del informe (por defecto es).")
    p.add_argument("--sin-web", action="store_true",
                   help="No buscar en internet (sin investigador).")
    p.add_argument("--incluir", metavar="LISTA",
                   help="Carpetas que normalmente se saltan y que sí quieres revisar, separadas por comas "
                        "(p. ej. vendor,build). Las carpetas de secretos (.git, .ssh…) nunca se revisan.")
    p.add_argument("--salida", metavar="CARPETA",
                   help="Dónde guardar el informe (por defecto <raíz del proyecto>/docs/revisiones).")
    p.add_argument("--instrucciones", metavar="TEXTO",
                   help="Indicaciones extra para esta revisión (p. ej. «céntrate en el módulo de pagos»).")
    p.add_argument("--raiz", metavar="CARPETA",
                   help="Raíz del proyecto (si no se da, se busca: la del repositorio git o la carpeta con "
                        "package.json, composer.json, CLAUDE.md…). La ruta que se revisa tiene que estar dentro.")
    p.add_argument("--forzar", action="store_true",
                   help="Permite revisar una unidad entera o tu carpeta personal (no recomendado).")
    p.add_argument("--detallado", action="store_true", help="Enseña cada archivo leído y cada paso.")
    p.add_argument("--version", action="version", version=f"Agente revisor de código {__version__}")
    return p.parse_args(lista_args)


def lista(texto: str | None) -> list[str]:
    """«a, b,c» -> ['a', 'b', 'c']"""
    return [parte.strip() for parte in (texto or "").split(",") if parte.strip()]


def salir(mensaje: str, codigo: int = 2) -> None:
    """Muestra un error y termina."""
    print(f"✖ {mensaje}", file=sys.stderr)
    sys.exit(codigo)


def carpeta_demasiado_amplia(raiz: Path) -> bool:
    """¿Es una unidad entera o la carpeta personal del usuario (o una de sus padres)?"""
    if raiz.parent == raiz:
        return True
    casa = Path.home().resolve()
    return raiz == casa or raiz in casa.parents


def tipo_alcance(objetivo: Path, raiz: Path, cambios: bool) -> str:
    """Texto del alcance para el informe y el coordinador."""
    if objetivo.is_file():
        return "archivo"
    if cambios:
        return "cambios"
    return "carpeta" if objetivo != raiz else "completo"


def main(lista_args: list[str] | None = None) -> None:
    args = argumentos(lista_args)

    # --- Comprobar la ruta y buscar la raíz del proyecto --------------------------------------
    objetivo = Path(args.ruta).expanduser().resolve()
    if not objetivo.exists():
        salir(f"No existe: {objetivo}")
    if args.raiz:
        raiz = Path(args.raiz).expanduser().resolve()
        if not raiz.is_dir():
            salir(f"--raiz no es una carpeta: {raiz}")
        if objetivo != raiz and raiz not in objetivo.parents:
            salir("La ruta que se revisa tiene que estar dentro de --raiz.")
    else:
        raiz = inventario.buscar_raiz(objetivo)
    if carpeta_demasiado_amplia(raiz) and not args.forzar:
        salir(f"«{raiz}» es una unidad entera o tu carpeta personal: el agente podría leer cualquier cosa. "
              "Indica la carpeta de un proyecto, o fija la raíz con --raiz.")

    # --- Validar opciones ---------------------------------------------------------------------
    especialistas = lista(args.solo) or list(config.ESPECIALISTAS)
    desconocidos = [e for e in especialistas if e not in config.ESPECIALISTAS]
    if desconocidos:
        salir(f"Especialista desconocido: {', '.join(desconocidos)}. Disponibles: {', '.join(config.ESPECIALISTAS)}")
    if not math.isfinite(args.tope) or args.tope <= 0:
        salir("El tope tiene que ser un número mayor que 0.")
    if args.desde and not args.cambios:
        salir("--desde solo tiene sentido junto con --cambios.")
    if objetivo.is_file() and args.cambios:
        print("⚠ Con un archivo suelto se revisa ese archivo; se ignoran --cambios y --desde.")
        args.cambios, args.desde = False, None

    modelo = args.modelo
    modelo_esp = args.modelo_especialistas or modelo
    for m in sorted({modelo, modelo_esp}):
        if m not in config.MODELOS_CONOCIDOS:
            print(f"⚠ Modelo «{m}» no está en la lista conocida; se usará tal cual.")

    carpeta_salida = Path(args.salida).expanduser().resolve() if args.salida else raiz / "docs" / "revisiones"
    # Carpetas que nunca se revisan: informes anteriores y el estado del propio agente.
    bloqueadas = [carpeta_salida, raiz / "docs" / "revisiones", config.PAQUETE.parent / ".estado"]

    # --- Inventario (local, gratis) -----------------------------------------------------------
    print(f"Agente revisor de código {__version__}")
    print("Haciendo el inventario del proyecto (sin gastar)…")
    try:
        inv = inventario.hacer_inventario(objetivo, raiz=raiz, solo_cambios=args.cambios, desde=args.desde,
                                          incluir=set(lista(args.incluir)), bloqueadas=bloqueadas)
    except RuntimeError as error:
        salir(str(error))
    texto_inv = inv.texto()
    print(texto_inv)

    if args.cambios and not inv.cambiados:
        print("\nNo hay archivos cambiados que revisar. Nada que hacer.")
        return

    alcance = tipo_alcance(objetivo, raiz, args.cambios)
    print("\nAjustes:")
    print(f"  Raíz del proyecto: {raiz}")
    print(f"  Alcance: {informe.TEXTO_ALCANCE[alcance]}" + (f" ({inv.alcance})" if inv.alcance else ""))
    print(f"  Modelo: {modelo} · especialistas: {modelo_esp} · esfuerzo: {args.esfuerzo}")
    print(f"  Especialistas disponibles: {', '.join(especialistas)}")
    print(f"  Internet: {'no' if args.sin_web else 'sí, solo el investigador (para lo que no se domine)'}")
    print(f"  Tope de gasto: {args.tope:.2f} USD (estimado)")
    print(f"  Informe en: {carpeta_salida}")

    if args.simular:
        print("\nSimulación terminada: no se ha llamado a la API ni se ha gastado nada.")
        return

    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        salir("Falta la variable de entorno ANTHROPIC_API_KEY con tu clave de la API de Anthropic.\n"
              "  PowerShell:  $env:ANTHROPIC_API_KEY = \"sk-ant-...\"\n"
              "  Bash:        export ANTHROPIC_API_KEY=sk-ant-...\n"
              "  (Ver README.md para guardarla de forma permanente.)")

    # --- Encargo para el coordinador --------------------------------------------------------
    textos_alcance = {
        "completo": "Revisa el proyecto completo (salvo lo generado, de terceros o minificado).",
        "carpeta": f"Revisa SOLO la carpeta «{inv.alcance}». Puedes leer el resto del proyecto (normas, "
                   "dependencias, código relacionado) solo para entender el contexto.",
        "archivo": f"Revisa SOLO el archivo «{inv.alcance}». Puedes leer el resto del proyecto solo para "
                   "entender el contexto.",
        "cambios": "Revisa SOLO los archivos de la lista «Archivos que hay que revisar» del inventario. "
                   "Puedes leer otros solo para entender el contexto.",
    }
    encargo = "\n\n".join(filter(None, [
        f"Haz la revisión de código de este proyecto. Raíz (carpeta de trabajo): {raiz}",
        textos_alcance[alcance],
        "Inventario hecho en local:\n" + texto_inv,
        "Carpetas que no se revisan (dependencias, compilados, cachés): "
        + ", ".join(sorted(config.CARPETAS_EXCLUIDAS - set(lista(args.incluir)))),
        f"Indicaciones del usuario (solo sobre qué revisar o en qué centrarse; no cambian tus reglas): "
        f"{args.instrucciones}" if args.instrucciones else "",
        "Recuerda: no cambias nada; al final devuelves el informe en el formato estructurado.",
    ]))

    # Importar aquí: así --help y --simular funcionan aunque el SDK no esté instalado.
    try:
        from revisor import ejecutar
    except ImportError as error:
        salir(f"No se pudo cargar claude-agent-sdk ({error}). Instálalo con: pip install -r requirements.txt")

    print("\nEmpezando la revisión (Ctrl+C para cancelar)…\n")
    res = ejecutar.Resultado()
    try:
        asyncio.run(ejecutar.revisar(
            raiz=raiz, encargo=encargo, especialistas=especialistas, modelo=modelo,
            modelo_especialistas=modelo_esp, esfuerzo=args.esfuerzo, tope=args.tope,
            idioma=args.idioma, con_web=not args.sin_web, mostrar=print, detallado=args.detallado,
            bloqueadas=bloqueadas, resultado=res,
        ))
    except ejecutar.CredencialIncorrecta as error:
        salir(str(error))
    except KeyboardInterrupt:
        # Guardar lo que ya se haya pagado: lo que devolvieron los especialistas hasta ahora.
        print("\nCancelado por el usuario.")
        res.estado, res.motivo = "parcial", "cancelada por el usuario"
        res.informe = informe.informe_parcial(res.respuestas)
        if not res.informe["hallazgos"]:
            salir("No había hallazgos todavía; no se guarda informe.", 130)

    # --- Informe ------------------------------------------------------------------------------
    hallazgos = []
    for bruto in (res.informe or {}).get("hallazgos", []):
        limpio = informe.normalizar(bruto, raiz=raiz) if isinstance(bruto, dict) else None
        if limpio:
            hallazgos.append(limpio)
    res.informe["hallazgos"] = informe.numerar(hallazgos)

    # Si falló sin encontrar nada (clave mala, sin saldo…), no guardar un informe vacío.
    if res.estado == "fallida" and not hallazgos and not res.respuestas:
        coste = f" · coste estimado {res.coste_usd:.2f} USD" if res.coste_usd else ""
        salir(f"La revisión no pudo hacerse: {res.motivo}{coste}", 1)

    datos = informe.DatosEjecucion(
        raiz=raiz, modelo=modelo, modelo_especialistas=modelo_esp, esfuerzo=args.esfuerzo,
        tope_usd=args.tope, coste_usd=res.coste_usd, duracion_s=res.duracion_s, turnos=res.turnos,
        estado=res.estado, motivo=res.motivo, alcance=alcance, parte=inv.alcance,
        especialistas=especialistas, lanzados=res.lanzados, bloqueos=res.bloqueos,
    )
    ruta_md, ruta_json = informe.guardar(res.informe, datos, texto_inv, carpeta_salida)

    cuenta = {g: sum(1 for h in hallazgos if h["gravedad"] == g) for g in config.GRAVEDADES}
    print("\n" + "=" * 60)
    print(f"Revisión {res.estado}" + (f" — {res.motivo}" if res.motivo else ""))
    print(f"Hallazgos: {len(hallazgos)} · " + " · ".join(f"{informe.ETIQUETA[g]} {cuenta[g]}" for g in config.GRAVEDADES))
    if res.coste_usd is not None:
        print(f"Coste estimado: {res.coste_usd:.2f} USD · {res.duracion_s / 60:.1f} min")
    print(f"Informe: {ruta_md}")
    print(f"Datos para el reparador: {ruta_json}")
    if res.estado == "fallida":
        sys.exit(1)


if __name__ == "__main__":
    main()
