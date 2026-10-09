from typing import List, Optional, Tuple

from pathlib import Path

from ..db import Database
from ..models import RevisionEstado
from .contenido import ContenidoFacebook, _titulo_y_texto_finales, generar_contenido_facebook
from .identidad_visual import DatosPieza, generar_pieza_clima_dolar, generar_pieza_feed, generar_story_pieza
from . import imagen as _imagen
from .imagen import _hash_contenido_placa, normalizar_url_imagen, preparar_foto_publicable
from ..clasificacion import clasificar_noticia
from ..informe_diario_datos import datos_informe_de_noticia
from ..regla_imagenes import evaluar_imagen


class ErrorPreparacionFacebook(RuntimeError):
    """Error controlado al preparar una publicación de Facebook."""


def _es_url_remota(valor: str) -> bool:
    return valor.startswith("http://") or valor.startswith("https://")


def datos_pieza(noticia: dict, tipo: Optional[str] = None) -> DatosPieza:
    """Datos de la pieza Versión C: titular, territorio, categoría y tipo
    (urgente rojo / servicio verde / institucional / noticia)."""
    titulo, _ = _titulo_y_texto_finales(noticia)
    clasificacion = clasificar_noticia(noticia, urgente=False)
    categoria = clasificacion["categoria"]
    etiqueta = categoria["etiqueta"] if categoria["valor"] not in (None, "general") else None
    if tipo is None:
        if noticia.get("territorio") == "institucional" or noticia.get("origen_ingreso") == "institucional":
            tipo = "institucional"
        elif categoria["valor"] == "servicios":
            tipo = "servicio"
        else:
            tipo = "noticia"
    return DatosPieza(titulo=titulo, territorio=clasificacion["territorio"]["valor"], categoria=etiqueta, tipo=tipo)


def _guardar_pieza(prefijo: str, datos: DatosPieza, foto_ruta: Optional[str], generar) -> str:
    """Archivo determinístico por contenido (se reutiliza en reintentos)."""
    _imagen.DIRECTORIO_PLACAS_DEFAULT.mkdir(parents=True, exist_ok=True)
    clave = _hash_contenido_placa(datos.titulo, f"{datos.territorio}|{datos.categoria}|{datos.tipo}", "", foto_ruta or "")
    ruta = _imagen.DIRECTORIO_PLACAS_DEFAULT / f"{prefijo}_{clave}.png"
    if not ruta.exists():
        foto = Path(foto_ruta).read_bytes() if foto_ruta else None
        try:
            ruta.write_bytes(generar(datos, foto=foto))
        except (OSError, ValueError):
            if foto is None:
                raise
            ruta.write_bytes(generar(datos, foto=None))
    return str(ruta)


def _placa(noticia: dict) -> str:
    """PLACA EDITORIAL GRÁFICA (sin foto) o, para el informe de la
    mañana, la pieza Clima + Dólar."""
    datos_informe = datos_informe_de_noticia(noticia)
    if datos_informe is not None:
        _imagen.DIRECTORIO_PLACAS_DEFAULT.mkdir(parents=True, exist_ok=True)
        ruta = _imagen.DIRECTORIO_PLACAS_DEFAULT / f"clima_dolar_{datos_informe.get('fecha', 'sin-fecha')}.png"
        if not ruta.exists():
            ruta.write_bytes(generar_pieza_clima_dolar(datos_informe))
        return str(ruta)
    return _guardar_pieza("pieza", datos_pieza(noticia), None, generar_pieza_feed)


def _foto_apta(noticia: dict, url: str, db: Optional[Database]) -> bool:
    usos = db.contar_usos_imagen(url, noticia.get("id")) if db is not None else 0
    return evaluar_imagen(url, usos)[0]


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
    if datos_informe_de_noticia(noticia) is not None:
        return _placa(noticia), True
    if ruta_actual and _es_url_remota(ruta_actual):
        # Regla de imágenes (Etapa 1): stock, genérica o de archivo
        # reutilizada -> placa editorial gráfica, nunca la foto.
        foto = preparar_foto_publicable(ruta_actual) if _foto_apta(noticia, ruta_actual, db) else None
        if foto is not None:
            return _guardar_pieza("pieza", datos_pieza(noticia), str(foto), generar_pieza_feed), False
        return _placa(noticia), True
    if ruta_actual and Path(ruta_actual).is_file():
        if noticia.get("imagen_generada_automaticamente") or noticia.get("origen_ingreso") == "institucional":
            # Imagen propia ya configurada/persistida (institucional, placa
            # ya generada): se usa tal cual, como siempre.
            return ruta_actual, bool(noticia.get("imagen_generada_automaticamente"))
        return _guardar_pieza("pieza", datos_pieza(noticia), ruta_actual, generar_pieza_feed), False

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
    foto_local = None
    if foto and _es_url_remota(foto):
        if evaluar_imagen(foto)[0]:
            preparada = preparar_foto_publicable(normalizar_url_imagen(foto))
            foto_local = str(preparada) if preparada else None
    elif foto and Path(foto).is_file():
        foto_local = foto
    return _guardar_pieza("urgente", datos_pieza(noticia, tipo="urgente"), foto_local, generar_pieza_feed)


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
        noticia, incluir_menciones=incluir_menciones, menciones=menciones, urgente=urgente
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

    ruta_texto = _guardar_pieza("story", datos_pieza(noticia), None, generar_story_pieza)

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
