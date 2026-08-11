from typing import List, Optional, Tuple

from ..db import Database
from ..models import RevisionEstado
from .contenido import ContenidoFacebook, _titulo_y_texto_finales, generar_contenido_facebook
from .imagen import generar_placa


class ErrorPreparacionFacebook(RuntimeError):
    """Error controlado al preparar una publicación de Facebook."""


def _resolver_imagen(noticia: dict, db: Optional[Database]) -> Tuple[Optional[str], bool]:
    """Devuelve (ruta_o_url_de_imagen, generada_automaticamente).

    Reutiliza la imagen ya persistida (original o placa) si existe: no
    regenera nada innecesariamente. Solo genera una placa nueva cuando la
    noticia no tiene imagen original ni una placa previamente asociada."""
    ruta_actual = noticia.get("imagen_publicacion_ruta")
    if ruta_actual:
        return ruta_actual, bool(noticia.get("imagen_generada_automaticamente"))

    if noticia.get("tiene_imagen_original"):
        return None, False

    titulo, texto = _titulo_y_texto_finales(noticia)
    ruta_placa = generar_placa(
        titulo,
        texto,
        fuente=noticia.get("nombre_fuente"),
        localidad=noticia.get("localidad"),
    )
    ruta_texto = str(ruta_placa)

    id_noticia = noticia.get("id")
    if db is not None and id_noticia is not None:
        db.actualizar_imagen_publicacion(id_noticia, ruta_texto, True)

    return ruta_texto, True


def preparar_publicacion(
    noticia: dict,
    dry_run: bool = True,
    incluir_menciones: Optional[bool] = None,
    menciones: Optional[List[str]] = None,
    db: Optional[Database] = None,
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

    imagen_ruta, generada_automaticamente = _resolver_imagen(noticia, db)
    contenido.imagen_url = imagen_ruta
    contenido.imagen_generada_automaticamente = generada_automaticamente

    return contenido
