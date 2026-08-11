from datetime import datetime, timezone
from typing import List, Tuple

from .collectors.base import Collector
from .db import Database
from .dedupe import hash_contenido, normalizar_url
from .models import Estado, Noticia, RevisionEstado
from .redaccion.base import Redactor
from .relevancia import clasificar_relevancia
from .riesgo_editorial import evaluar_riesgo_editorial


def _aplicar_riesgo_editorial(noticia: Noticia) -> None:
    resultado = evaluar_riesgo_editorial(
        noticia.titulo_original,
        noticia.texto_original,
        noticia.titulo_preparado,
        noticia.texto_preparado,
        noticia.nombre_fuente,
    )
    noticia.requiere_revision_especial = resultado["requiere_revision_especial"]
    noticia.categoria_riesgo = resultado["categoria_riesgo"]
    noticia.motivo_revision_especial = resultado["motivo"]


def normalizar_noticia(cruda: dict) -> Noticia:
    imagen_url = cruda.get("imagen_url") or None
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
        tiene_imagen_original=bool(imagen_url),
        imagen_publicacion_ruta=imagen_url,
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
        _aplicar_riesgo_editorial(noticia)
        db.guardar(noticia)
        return noticia, "descartada"

    titulo_preparado, texto_preparado = redactor.redactar(noticia)
    noticia.titulo_preparado = titulo_preparado
    noticia.texto_preparado = texto_preparado
    noticia.estado = Estado.PREPARADA.value
    noticia.revision_estado = RevisionEstado.PENDIENTE.value
    _aplicar_riesgo_editorial(noticia)
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
