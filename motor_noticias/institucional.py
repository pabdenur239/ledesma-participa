"""Publicación institucional diaria de Ledesma Participa: misma imagen y
mismo texto todos los días, para dar a conocer la página, explicar de qué
se trata y promocionar el sitio web — no es una noticia real.

No pasa por clasificación territorial, elegibilidad automática ni riesgo
editorial: el contenido es fijo, siempre el mismo, ya vetado por diseño
(no depende de ninguna fuente externa ni de redacción). Reutiliza el
mismo mecanismo de identidad por URL que ya usa el informe diario
(`motor_noticias.informe_diario`) para garantizar como máximo una
publicación institucional por día, en su propia franja fija (19:30, fuera
de `HORARIOS_DEFAULT`): nunca compite por espacio con la cascada
territorial normal ni con las urgentes, y `origen_ingreso = "institucional"`
la excluye explícitamente del gate de deduplicación por contenido (ver
`motor_noticias.meta.publicador`) y de la Story — sin esa marca, el propio
texto repetido día a día quedaría bloqueado como "duplicado" del día
anterior."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .db import Database
from .dedupe import normalizar_url
from .meta.imagen import generar_placa
from .models import Estado, Noticia, OrigenIngreso, RevisionEstado
from .motor_editorial import EntradaAgenda, ZONA_JUJUY

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "institucional.json"

# Fuera de HORARIOS_DEFAULT (horas en punto) e distinta de
# HORA_INFORME_DIARIO: nunca colisiona con ninguna franja existente.
HORA_INSTITUCIONAL = "19:30"
NOMBRE_FUENTE = "Ledesma Participa"
TERRITORIO_INSTITUCIONAL = "institucional"


def _cargar_config(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)


def _hash_institucional(fecha_iso: str) -> str:
    """Identificador estable por día: a diferencia de una noticia real, el
    texto institucional es intencionalmente idéntico todos los días, así
    que no puede reutilizarse `dedupe.hash_contenido(titulo, texto)` tal
    cual — chocaría con la restricción UNIQUE de `noticias.hash_contenido`
    a partir del segundo día. Se sala con la fecha: mismo texto siempre,
    hash distinto cada día."""
    return hashlib.sha256(f"institucional|{fecha_iso}".encode("utf-8")).hexdigest()


def _url_institucional(fecha_iso: str) -> str:
    return normalizar_url(f"https://ledesma-participa.local/institucional/{fecha_iso}")


def _crear_noticia_institucional(db: Database, fecha_iso: str, ahora_local: datetime, config: dict) -> int:
    imagen_ruta = str(
        generar_placa(config["titulo"], config["texto"], fuente="", localidad="")
    )
    noticia = Noticia(
        id=None,
        titulo_original=config["titulo"],
        texto_original=config["texto"],
        # Vacío a propósito: `generar_contenido_facebook` agrega "Fuente y
        # nota completa: {url_fuente}" solo si no está vacío. Esta
        # publicación no tiene una nota fuente externa que citar (el sitio
        # ya está en el propio texto institucional) — mostrar la URL
        # interna de identidad (`local`, no pública) sería confuso.
        url_fuente="",
        # La URL de identidad (usada por existe_duplicado/obtener_por_url
        # para el "una vez por día") sí se guarda, en `url_normalizada`
        # nada más: nunca se muestra en la publicación real.
        url_normalizada=_url_institucional(fecha_iso),
        nombre_fuente=NOMBRE_FUENTE,
        fecha_fuente=ahora_local.isoformat(),
        fecha_recoleccion=ahora_local.astimezone(timezone.utc).isoformat(),
        estado=Estado.PREPARADA.value,
        hash_contenido=_hash_institucional(fecha_iso),
        titulo_preparado=config["titulo"],
        texto_preparado=config["texto"],
        # Aprobada de entrada (revision_automatica=True para que quede
        # auditable el origen): contenido fijo, sin nada que un humano deba
        # revisar caso por caso. territorio="institucional" (fuera de
        # ORDEN_CASCADA y de TERRITORIOS_VALIDOS de elegibilidad_automatica)
        # la vuelve estructuralmente invisible para candidato_editorial/
        # candidatos_urgentes: ningún otro circuito puede seleccionarla.
        revision_estado=RevisionEstado.APROBADA.value,
        revision_automatica=True,
        requiere_revision_especial=False,
        territorio=TERRITORIO_INSTITUCIONAL,
        motivo_territorio="Publicación institucional fija: no se clasifica territorialmente.",
        tiene_imagen_original=True,
        imagen_publicacion_ruta=imagen_ruta,
        imagen_generada_automaticamente=False,
        origen_ingreso=OrigenIngreso.INSTITUCIONAL.value,
    )
    db.guardar(noticia)
    return noticia.id


def reservar_franja_institucional(
    db: Database,
    fecha: Optional[str] = None,
    ahora: Optional[datetime] = None,
    config: Optional[dict] = None,
) -> EntradaAgenda:
    """Crea (si no existe) la noticia institucional del día y reserva su
    franja fija (19:30), igual que `informe_diario.reservar_franja_informe_diario`
    reserva la suya. Idempotente y segura de llamar repetidas veces: si la
    de hoy ya existe (misma URL determinística por fecha), no crea nada
    nuevo ni vuelve a tocar la fila de agenda."""
    ahora_local = (ahora or datetime.now(ZONA_JUJUY)).astimezone(ZONA_JUJUY)
    fecha = fecha or ahora_local.strftime("%Y-%m-%d")
    config = config or _cargar_config()

    url = _url_institucional(fecha)
    existente_noticia = db.obtener_por_url(url)
    if existente_noticia is not None:
        noticia_id = existente_noticia["id"]
    else:
        noticia_id = _crear_noticia_institucional(db, fecha, ahora_local, config)

    existente_item = db.obtener_agenda_item(fecha, HORA_INSTITUCIONAL)
    if existente_item is not None and existente_item.get("noticia_id") == noticia_id:
        return EntradaAgenda(
            fecha, HORA_INSTITUCIONAL, "normal", TERRITORIO_INSTITUCIONAL, noticia_id, "existente"
        )

    creada_en = datetime.now(timezone.utc).isoformat()
    db.guardar_agenda_item(
        fecha, HORA_INSTITUCIONAL, "normal", TERRITORIO_INSTITUCIONAL, noticia_id, creada_en,
        id_existente=existente_item["id"] if existente_item else None,
    )
    estado_entrada = "actualizado" if existente_item else "creado"
    return EntradaAgenda(fecha, HORA_INSTITUCIONAL, "normal", TERRITORIO_INSTITUCIONAL, noticia_id, estado_entrada)
