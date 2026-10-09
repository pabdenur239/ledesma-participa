from typing import List, Optional, Tuple

from pathlib import Path

from ..atribucion import etiqueta_fuente
from ..db import Database
from ..models import RevisionEstado
from .contenido import ContenidoFacebook, _titulo_y_texto_finales, generar_contenido_facebook
from .imagen import generar_placa, generar_placa_urgente, generar_story, normalizar_url_imagen, preparar_foto_publicable


class ErrorPreparacionFacebook(RuntimeError):
    """Error controlado al preparar una publicación de Facebook."""


def _es_url_remota(valor: str) -> bool:
    return valor.startswith("http://") or valor.startswith("https://")


def _placa(noticia: dict) -> str:
    titulo, texto = _titulo_y_texto_finales(noticia)
    return str(generar_placa(titulo, texto, fuente=etiqueta_fuente(noticia), localidad=noticia.get("localidad")))


def _resolver_imagen(noticia: dict, db: Optional[Database]) -> Tuple[Optional[str], bool]:
    """Devuelve (ruta_local_de_imagen, generada_automaticamente).

    Pipeline robusto (2/10/2026): una foto externa se descarga, se valida y
    se lleva a un formato que aceptan Facebook e Instagram
    (`preparar_foto_publicable`); si la URL no responde o no es una imagen
    válida, se usa la placa propia — nunca se publica una imagen rota ni una
    que Instagram rechace por relación de aspecto (causa real de posts que
    llegaron a Facebook y no a Instagram). La URL original queda guardada
    tal cual en la noticia (no se pisa), y la foto preparada se reutiliza en
    reintentos (nombre determinístico). Una placa nueva solo se persiste
    cuando la noticia no tenía ninguna imagen."""
    ruta_actual = noticia.get("imagen_publicacion_ruta")
    if ruta_actual and _es_url_remota(ruta_actual):
        foto = preparar_foto_publicable(ruta_actual)
        if foto is not None:
            return str(foto), False
        return _placa(noticia), True
    if ruta_actual and Path(ruta_actual).is_file():
        return ruta_actual, bool(noticia.get("imagen_generada_automaticamente"))

    ruta_texto = _placa(noticia)
    id_noticia = noticia.get("id")
    if db is not None and id_noticia is not None and not ruta_actual:
        db.actualizar_imagen_publicacion(id_noticia, ruta_texto, True)
    return ruta_texto, True


def _resolver_imagen_urgente(noticia: dict) -> str:
    """Imagen con la identidad visual URGENTE (rojo): conserva la foto
    original válida con la banda roja, o genera la placa roja si no hay
    foto (una placa normal generada automáticamente no cuenta como foto).
    No se persiste en `imagen_publicacion_ruta`: el archivo es
    determinístico por contenido y se reutiliza en reintentos, y la imagen
    original de la noticia queda intacta."""
    ruta_actual = noticia.get("imagen_publicacion_ruta")
    foto = None if noticia.get("imagen_generada_automaticamente") else ruta_actual
    titulo, _ = _titulo_y_texto_finales(noticia)
    if foto and _es_url_remota(foto):
        foto = normalizar_url_imagen(foto)
    return str(generar_placa_urgente(titulo, fuente=etiqueta_fuente(noticia), imagen_original=foto))


def preparar_publicacion(
    noticia: dict,
    dry_run: bool = True,
    incluir_menciones: Optional[bool] = None,
    menciones: Optional[List[str]] = None,
    db: Optional[Database] = None,
    urgente: bool = False,
) -> ContenidoFacebook:
    """Punto de entrada único para preparar una publicación de Facebook.

    Reglas obligatorias, sin excepción:
    - Solo se puede preparar (ni siquiera en DRY RUN) una noticia con
      revision_estado == 'aprobada'.
    - Si la noticia requiere revisión política/institucional
      (requiere_revision_especial == true), solo se permite DRY RUN;
      cualquier intento de publicación real (dry_run=False) se rechaza.
      La placa igualmente puede generarse para la vista previa: la
      generación de placa nunca reemplaza la revisión humana ni habilita
      publicación real.

    Si se pasa `db`, la elección de imagen (original o placa recién
    generada) queda persistida en la noticia para no regenerarse en
    llamadas futuras.

    `urgente=True` (solo circuito urgente) usa la identidad visual roja
    URGENTE en lugar de la imagen/placa habitual.
    """
    if noticia.get("revision_estado") != RevisionEstado.APROBADA.value:
        raise ErrorPreparacionFacebook(
            "Solo se puede preparar una publicación de Facebook para noticias "
            "con revision_estado = 'aprobada'."
        )

    if noticia.get("requiere_revision_especial") and not dry_run:
        raise ErrorPreparacionFacebook(
            "Esta noticia requiere revisión política/institucional obligatoria: "
            "solo se permite previsualización en modo DRY RUN, nunca publicación "
            "automática."
        )

    contenido = generar_contenido_facebook(
        noticia, incluir_menciones=incluir_menciones, menciones=menciones
    )

    if urgente:
        # Solo el circuito urgente pide esto (clave "urgente-<id>"): el rojo
        # queda reservado exclusivamente a URGENTES.
        imagen_ruta, generada_automaticamente = _resolver_imagen_urgente(noticia), True
    else:
        imagen_ruta, generada_automaticamente = _resolver_imagen(noticia, db)
    contenido.imagen_url = imagen_ruta
    contenido.imagen_generada_automaticamente = generada_automaticamente

    return contenido


def _resolver_imagen_story(noticia: dict, db: Optional[Database]) -> str:
    """Igual criterio que `_resolver_imagen`, pero para la placa vertical
    (9:16) de Story: reutiliza `imagen_story_ruta` si ya está persistida: no
    la regenera en cada reintento. A diferencia del feed, la Story siempre
    usa una placa generada por el proyecto (nunca la foto original de la
    fuente): reutilizar una foto ajena en formato vertical recortaría de
    forma impredecible, y la Story de todos modos necesita el título/fuente
    imprimido porque no lleva caption aparte."""
    ruta_actual = noticia.get("imagen_story_ruta")
    if ruta_actual:
        return ruta_actual

    titulo, texto = _titulo_y_texto_finales(noticia)
    ruta_story = generar_story(
        titulo,
        texto,
        fuente=noticia.get("nombre_fuente"),
        localidad=noticia.get("localidad"),
    )
    ruta_texto = str(ruta_story)

    id_noticia = noticia.get("id")
    if db is not None and id_noticia is not None:
        db.actualizar_imagen_story(id_noticia, ruta_texto)

    return ruta_texto


def preparar_publicacion_story(noticia: dict, db: Optional[Database] = None) -> str:
    """Punto de entrada único para preparar la placa de una Instagram Story.

    Mismas reglas obligatorias que `preparar_publicacion`: solo una noticia
    con revision_estado == 'aprobada' puede prepararse, y una que requiera
    revisión política/institucional nunca genera una Story real (a
    diferencia del feed, acá no existe un modo "solo vista previa": la Story
    o se publica de verdad o no se prepara).

    Devuelve la ruta local de la placa vertical lista para publicar."""
    if noticia.get("revision_estado") != RevisionEstado.APROBADA.value:
        raise ErrorPreparacionFacebook(
            "Solo se puede preparar una Story para noticias con revision_estado = 'aprobada'."
        )
    if noticia.get("requiere_revision_especial"):
        raise ErrorPreparacionFacebook(
            "Esta noticia requiere revisión política/institucional obligatoria: nunca se genera "
            "una Story automática para ella."
        )

    return _resolver_imagen_story(noticia, db)
