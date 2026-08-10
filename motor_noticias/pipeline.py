from datetime import datetime, timezone
from typing import List, Tuple

from .collectors.base import Collector
from .db import Database
from .dedupe import hash_contenido, normalizar_url
from .models import Estado, Noticia
from .redaccion.base import Redactor
from .relevancia import clasificar_relevancia


def normalizar_noticia(cruda: dict) -> Noticia:
    return Noticia(
        id=None,
        titulo_original=cruda["titulo"].strip(),
        texto_original=cruda["texto"].strip(),
        url_fuente=cruda["url"].strip(),
        nombre_fuente=cruda.get("fuente", "").strip(),
        fecha_fuente=cruda.get("fecha", ""),
        fecha_recoleccion=datetime.now(timezone.utc).isoformat(),
        estado=Estado.ENCONTRADA.value,
        hash_contenido="",
        localidad=cruda.get("localidad") or None,
    )


def procesar_noticia(db: Database, noticia: Noticia, redactor: Redactor) -> Tuple[Noticia, str]:
    noticia.url_normalizada = normalizar_url(noticia.url_fuente)
    noticia.hash_contenido = hash_contenido(noticia.titulo_original, noticia.texto_original)

    resultado = clasificar_relevancia(
        noticia.titulo_original, noticia.texto_original, localidad=noticia.localidad
    )
    noticia.relevancia_local = resultado["relevante"]
    noticia.motivo_relevancia = resultado["motivo"]
    noticia.localidad = resultado["localidad"]

    if db.existe_duplicado(noticia.url_normalizada, noticia.hash_contenido):
        return noticia, "duplicado"

    if not noticia.relevancia_local:
        noticia.estado = Estado.DESCARTADA.value
        db.guardar(noticia)
        return noticia, "descartada"

    titulo_preparado, texto_preparado = redactor.redactar(noticia)
    noticia.titulo_preparado = titulo_preparado
    noticia.texto_preparado = texto_preparado
    noticia.estado = Estado.PREPARADA.value
    db.guardar(noticia)
    return noticia, "preparada"


def ejecutar_pipeline(
    db: Database, collector: Collector, redactor: Redactor
) -> List[Tuple[Noticia, str]]:
    resultados = []
    for cruda in collector.recolectar():
        noticia = normalizar_noticia(cruda)
        resultados.append(procesar_noticia(db, noticia, redactor))
    return resultados
