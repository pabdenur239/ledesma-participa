"""Programación diaria de publicación en Meta: reutiliza por completo el
sistema de Agenda Editorial (motor_editorial) que ya elige contenido por
cascada territorial (local -> departamental -> provincial -> nacional) y
franja horaria fija, sin duplicar selección de contenido. Solo agrega, por
franja, la aprobación automática (si el contenido es apto según
elegibilidad_automatica) y la generación anticipada de la placa."""
import logging
from datetime import datetime, timezone
from typing import List, NamedTuple, Optional

from ..db import Database
from ..meta.elegibilidad_automatica import evaluar_elegibilidad_publicacion_automatica
from ..meta.preparacion import ErrorPreparacionFacebook, preparar_publicacion
from ..models import Estado, RevisionEstado
from ..motor_editorial import EntradaAgenda, generar_agenda, reservar_franja_informe_diario

logger = logging.getLogger("motor_noticias.meta.programacion")


def generar_programacion_diaria(
    db: Database, fecha: Optional[str] = None, ahora: Optional[datetime] = None
) -> List[EntradaAgenda]:
    """Reserva la franja fija del informe diario (07:30) y completa las
    demás franjas por cascada territorial. Idempotente y seguro de llamar
    repetidas veces (misma garantía que `generar_agenda`)."""
    entrada_informe = reservar_franja_informe_diario(db, fecha=fecha, ahora=ahora)
    entradas_cascada = generar_agenda(db, fecha=fecha, ahora=ahora)
    return [entrada_informe] + entradas_cascada


def aprobar_si_elegible(db: Database, noticia: dict, ahora: Optional[datetime] = None) -> dict:
    """Si la noticia es apta para publicación 100% automática (ver
    elegibilidad_automatica) y todavía no está aprobada, la aprueba
    automáticamente (revision_automatica=1, auditable) y devuelve la fila
    actualizada. Si no es apta, la deja intacta (sigue pendiente para
    revisión humana en el panel, como cualquier otra noticia)."""
    if noticia.get("revision_estado") == RevisionEstado.APROBADA.value:
        return noticia

    ahora_utc = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    resultado = evaluar_elegibilidad_publicacion_automatica(noticia, ahora=ahora_utc)
    if not resultado.elegible:
        return noticia

    db.actualizar_revision(
        noticia["id"],
        RevisionEstado.APROBADA.value,
        noticia.get("titulo_preparado"),
        noticia.get("texto_preparado"),
        datetime.now(timezone.utc).isoformat(),
        automatica=True,
    )
    return db.obtener(noticia["id"])


class ResultadoPlaca(NamedTuple):
    fecha: str
    hora: Optional[str]
    noticia_id: Optional[int]
    resultado: str  # "placa_lista" | "sin_contenido" | "pendiente_revision_humana" | "bloqueada_sin_imagen"
    detalle: Optional[str] = None


def generar_placas_del_dia(
    db: Database, fecha: Optional[str] = None, ahora: Optional[datetime] = None
) -> List[ResultadoPlaca]:
    """Recorre la agenda del día y, para cada franja con contenido, intenta
    dejar la placa lista de antemano (aprobando automáticamente si
    corresponde). Si una noticia no puede ilustrarse de forma segura, no se
    publica: se deja constancia del bloqueo, nunca se publica sin imagen."""
    fecha = fecha or datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    resultados: List[ResultadoPlaca] = []

    for item in db.listar_agenda(fecha):
        if item["tipo"] != "normal" or not item["noticia_id"]:
            continue
        noticia = db.obtener(item["noticia_id"])
        if noticia is None:
            resultados.append(ResultadoPlaca(fecha, item["hora"], item["noticia_id"], "sin_contenido"))
            continue

        noticia = aprobar_si_elegible(db, noticia, ahora=ahora)
        if noticia["revision_estado"] != RevisionEstado.APROBADA.value:
            resultados.append(
                ResultadoPlaca(fecha, item["hora"], noticia["id"], "pendiente_revision_humana")
            )
            continue

        try:
            contenido = preparar_publicacion(noticia, dry_run=True, db=db)
        except ErrorPreparacionFacebook as error:
            logger.error("Placa bloqueada para noticia %s: %s", noticia["id"], error)
            resultados.append(
                ResultadoPlaca(fecha, item["hora"], noticia["id"], "bloqueada_sin_imagen", str(error))
            )
            continue

        if not contenido.imagen_url:
            mensaje = "No se pudo generar ni resolver una imagen segura para esta noticia."
            logger.error("Placa bloqueada para noticia %s: %s", noticia["id"], mensaje)
            resultados.append(
                ResultadoPlaca(fecha, item["hora"], noticia["id"], "bloqueada_sin_imagen", mensaje)
            )
            continue

        resultados.append(ResultadoPlaca(fecha, item["hora"], noticia["id"], "placa_lista"))

    return resultados
