import logging
from datetime import datetime, timezone
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
from .collectors.rss_prensa_jujuy import ErrorRecoleccionRSS, PrensaJujuyRSSCollector
from .collectors.rss_somosjujuy import ErrorRecoleccionSomosJujuy, SomosJujuyRSSCollector
from .collectors.rss_todojujuy import ErrorRecoleccionTodoJujuy, TodoJujuyRSSCollector
from .db import Database
from .pipeline import ejecutar_pipeline
from .redaccion.base import Redactor
from .redaccion.mock import RedactorMock

logger = logging.getLogger("motor_noticias.continuo")

INTERVALO_SEGUNDOS_DEFAULT = 1800

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


def ejecutar_ciclo(
    db: Database,
    redactor: Optional[Redactor] = None,
    intervalo_segundos: int = INTERVALO_SEGUNDOS_DEFAULT,
) -> ResumenCiclo:
    """Consulta todas las fuentes habilitadas una vez, registra la salud de
    cada una y el resumen del ciclo. Una fuente que falla no interrumpe a
    las demás."""
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
    return ResumenCiclo(fecha_inicio, fecha_fin, resultados, total_noticias_nuevas, total_errores)
