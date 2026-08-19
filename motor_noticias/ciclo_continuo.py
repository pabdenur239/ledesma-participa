import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, NamedTuple, Optional

from .collectors.html_infoyungas import ErrorRecoleccionInfoYungas, InfoYungasHTMLCollector
from .collectors.html_jujuyalmomento import (
    ErrorRecoleccionJujuyAlMomento,
    JujuyAlMomentoHTMLCollector,
)
from .collectors.html_municipio_libertador import (
    ErrorRecoleccionHTML,
    MunicipioLibertadorHTMLCollector,
)
from .collectors.html_tribuno_jujuy import ErrorRecoleccionTribunoJujuy, TribunoJujuyHTMLCollector
from .collectors.rss_canal6libertador import (
    Canal6LibertadorRSSCollector,
    ErrorRecoleccionCanal6Libertador,
)
from .collectors.rss_infobae import ErrorRecoleccionInfobae, InfobaeRSSCollector
from .collectors.rss_jujuyaldia import ErrorRecoleccionJujuyAlDia, JujuyAlDiaRSSCollector
from .collectors.rss_lanacion import ErrorRecoleccionLaNacion, LaNacionRSSCollector
from .collectors.rss_prensa_jujuy import ErrorRecoleccionRSS, PrensaJujuyRSSCollector
from .collectors.rss_somosjujuy import ErrorRecoleccionSomosJujuy, SomosJujuyRSSCollector
from .collectors.rss_todojujuy import ErrorRecoleccionTodoJujuy, TodoJujuyRSSCollector
from .db import Database
from .motor_editorial import generar_agenda, reservar_franja_informe_diario
from .pipeline import ejecutar_pipeline
from .redaccion.base import Redactor
from .redaccion.mock import RedactorMock

logger = logging.getLogger("motor_noticias.continuo")

INTERVALO_SEGUNDOS_DEFAULT = 1800

# Clave sintética usada en la tabla `fuente_salud` (reutilizada, no se crea
# una tabla nueva) para registrar la salud de la actualización automática de
# la Agenda Editorial, aparte de la salud de cada fuente de noticias.
NOMBRE_SALUD_AGENDA = "agenda_editorial"

CONFIG_AGENDA_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "agenda.json"

# Las fuentes reales ya incorporadas y operativas al proyecto. No se agrega
# ninguna fuente nueva en este módulo: se reutilizan los collectors
# existentes tal como están, sin modificarlos.
FUENTES_CONTINUAS = (
    ("rss-prensa-jujuy", PrensaJujuyRSSCollector, ErrorRecoleccionRSS),
    ("municipio-libertador", MunicipioLibertadorHTMLCollector, ErrorRecoleccionHTML),
    ("infoyungas", InfoYungasHTMLCollector, ErrorRecoleccionInfoYungas),
    ("jujuy-al-momento", JujuyAlMomentoHTMLCollector, ErrorRecoleccionJujuyAlMomento),
    ("tribuno-jujuy", TribunoJujuyHTMLCollector, ErrorRecoleccionTribunoJujuy),
    ("todojujuy", TodoJujuyRSSCollector, ErrorRecoleccionTodoJujuy),
    ("somos-jujuy", SomosJujuyRSSCollector, ErrorRecoleccionSomosJujuy),
    ("jujuyaldia", JujuyAlDiaRSSCollector, ErrorRecoleccionJujuyAlDia),
    ("canal6-libertador", Canal6LibertadorRSSCollector, ErrorRecoleccionCanal6Libertador),
    ("la-nacion", LaNacionRSSCollector, ErrorRecoleccionLaNacion),
    ("infobae", InfobaeRSSCollector, ErrorRecoleccionInfobae),
)


class ResultadoFuente(NamedTuple):
    identificador: str
    resultado: str  # "ok" | "error"
    elementos_obtenidos: int
    noticias_nuevas: int
    mensaje_error: Optional[str]


class ResumenCiclo(NamedTuple):
    fecha_inicio: str
    fecha_fin: str
    resultados: List[ResultadoFuente]
    total_noticias_nuevas: int
    total_errores: int
    agenda_actualizada: Optional[bool] = None  # None = actualización automática deshabilitada
    agenda_mensaje_error: Optional[str] = None


def agenda_automatica_habilitada(path: Optional[Path] = None) -> bool:
    """Lee `config/agenda.json` → "agenda_automatica" (default `true` si el
    archivo falta o es inválido). Se relee en cada ciclo, así se puede
    desactivar la actualización automática sin reiniciar el Motor Continuo."""
    try:
        with open(path or CONFIG_AGENDA_PATH_DEFAULT, encoding="utf-8") as f:
            config = json.load(f)
        return bool(config.get("agenda_automatica", True))
    except (OSError, json.JSONDecodeError):
        return True


def _procesar_fuente(db: Database, identificador: str, collector_cls, error_cls, redactor: Redactor) -> ResultadoFuente:
    """Ejecuta el pipeline existente (sin modificarlo) para una fuente. Un
    fallo acá nunca se propaga: se traduce a un resultado "error" para que el
    ciclo continúe con las demás fuentes."""
    try:
        collector = collector_cls()
        resultados = ejecutar_pipeline(db, collector, redactor)
    except error_cls as error:
        mensaje = str(error)
        logger.error("Fuente %s: %s", identificador, mensaje)
        return ResultadoFuente(identificador, "error", 0, 0, mensaje)
    except Exception as error:  # salvaguarda: un bug inesperado no debe frenar el ciclo
        mensaje = f"Error inesperado: {error}"
        logger.exception("Fuente %s: error inesperado", identificador)
        return ResultadoFuente(identificador, "error", 0, 0, mensaje)

    elementos_obtenidos = len(resultados)
    noticias_nuevas = sum(1 for _, resultado in resultados if resultado != "duplicado")
    logger.info(
        "Fuente %s: OK — %d elementos, %d nuevas", identificador, elementos_obtenidos, noticias_nuevas
    )
    return ResultadoFuente(identificador, "ok", elementos_obtenidos, noticias_nuevas, None)


def _actualizar_agenda(db: Database) -> "tuple[bool, Optional[str]]":
    """Ejecuta una sola actualización de la Agenda Editorial (misma lógica
    que `generar_agenda.py`, sin duplicarla) tras haber consultado todas las
    fuentes del ciclo. Un fallo acá nunca tumba el Motor Continuo: se
    registra como salud "error" y las próximas rondas siguen funcionando
    igual."""
    try:
        entrada_informe = reservar_franja_informe_diario(db)
        entradas = [entrada_informe] + generar_agenda(db)
    except Exception as error:  # nunca debe interrumpir el ciclo continuo
        mensaje = f"Error actualizando agenda: {error}"
        logger.error(mensaje)
        db.registrar_salud_fuente(NOMBRE_SALUD_AGENDA, "error", mensaje_error=mensaje)
        return False, mensaje

    actualizadas = sum(1 for entrada in entradas if entrada.estado in ("creado", "actualizado"))
    db.registrar_salud_fuente(
        NOMBRE_SALUD_AGENDA, "ok", elementos_obtenidos=len(entradas), noticias_nuevas=actualizadas
    )
    logger.info("Agenda editorial actualizada")
    return True, None


def ejecutar_ciclo(
    db: Database,
    redactor: Optional[Redactor] = None,
    intervalo_segundos: int = INTERVALO_SEGUNDOS_DEFAULT,
    agenda_automatica: Optional[bool] = None,
) -> ResumenCiclo:
    """Consulta todas las fuentes habilitadas una vez, registra la salud de
    cada una y, recién después de terminar con todas (nunca entre medio),
    ejecuta una única actualización de la Agenda Editorial — misma cascada,
    mismos horarios y mismas protecciones que ya existían, reutilizados sin
    duplicar lógica. Una fuente que falla no interrumpe a las demás, y un
    fallo al actualizar la agenda no interrumpe el ciclo ni detiene el Motor
    Continuo.

    `agenda_automatica`: si se pasa explícitamente, tiene prioridad; si es
    `None` (default), se lee `config/agenda.json` en cada ciclo."""
    redactor = redactor or RedactorMock()
    fecha_inicio = datetime.now(timezone.utc).isoformat()

    resultados = []
    for identificador, collector_cls, error_cls in FUENTES_CONTINUAS:
        resultado = _procesar_fuente(db, identificador, collector_cls, error_cls, redactor)
        db.registrar_salud_fuente(
            identificador,
            resultado.resultado,
            elementos_obtenidos=resultado.elementos_obtenidos,
            noticias_nuevas=resultado.noticias_nuevas,
            mensaje_error=resultado.mensaje_error,
        )
        resultados.append(resultado)

    habilitada = agenda_automatica if agenda_automatica is not None else agenda_automatica_habilitada()
    if habilitada:
        agenda_actualizada, agenda_mensaje_error = _actualizar_agenda(db)
    else:
        logger.info("Actualización automática de agenda deshabilitada (agenda_automatica=false).")
        agenda_actualizada, agenda_mensaje_error = None, None

    fecha_fin = datetime.now(timezone.utc).isoformat()
    total_noticias_nuevas = sum(r.noticias_nuevas for r in resultados)
    total_errores = sum(1 for r in resultados if r.resultado == "error")
    db.registrar_ciclo(
        fecha_inicio,
        fecha_fin,
        total_fuentes=len(resultados),
        total_noticias_nuevas=total_noticias_nuevas,
        total_errores=total_errores,
        intervalo_segundos=intervalo_segundos,
    )
    return ResumenCiclo(
        fecha_inicio,
        fecha_fin,
        resultados,
        total_noticias_nuevas,
        total_errores,
        agenda_actualizada,
        agenda_mensaje_error,
    )
