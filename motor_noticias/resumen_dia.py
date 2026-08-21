"""Resumen del Día: una publicación nocturna fija (22:30, fuera de
HORARIOS_DEFAULT, agregada 20/8/2026) con las 5-6 noticias reales más
importantes ya publicadas ese día, en formato breve, priorizando locales y
departamentales.

Es una publicación sintética (como institucional/informe diario): compone
un texto propio a partir de noticias YA publicadas hoy, nunca las vuelve a
publicar como posts individuales — es un resumen, no una republicación.
`origen_ingreso = "resumen_diario"` la excluye de la cascada territorial
normal (igual que institucional) y del gate de deduplicación por fingerprint
de contenido (necesario: su texto necesariamente menciona títulos de
noticias reales ya publicadas hoy, así que compararla contra ellas por
fingerprint la bloquearía como "duplicado" de sí misma)."""
import hashlib
from datetime import datetime, timezone
from typing import List, Optional

from .db import Database
from .dedupe import normalizar_url
from .meta.imagen import generar_placa
from .models import Estado, Noticia, OrigenIngreso, RevisionEstado
from .motor_editorial import EntradaAgenda, HORA_RESUMEN_DEL_DIA, ZONA_JUJUY

NOMBRE_FUENTE = "Ledesma Participa"
NOMBRE_FUENTE_INFORME_DIARIO = "Informe Diario (Clima y Dólar) — Ledesma Participa"
TERRITORIO_RESUMEN = "resumen_diario"
CANTIDAD_MINIMA = 5
CANTIDAD_MAXIMA = 6

# Orden de prioridad editorial para elegir qué entra en el resumen cuando
# hay más de 6 candidatas: igual criterio que la cascada normal, locales y
# departamentales primero ("Priorizar locales y departamentales").
PRIORIDAD_TERRITORIO = {"local": 0, "departamental": 1, "provincial": 2, "nacional": 3, "sin_clasificar": 4}


def _prioridad(noticia: dict) -> tuple:
    return (PRIORIDAD_TERRITORIO.get(noticia.get("territorio"), 5), noticia.get("fecha_recoleccion") or "")


def _titulo_publico(noticia: dict) -> str:
    return (noticia.get("titulo_preparado") or noticia.get("titulo_original") or "").strip()


def _seleccionar_noticias_del_dia(db: Database, fecha_limite_utc: str) -> List[dict]:
    candidatas = [
        n
        for n in db.publicadas_para_resumen(fecha_limite_utc)
        if n.get("nombre_fuente") != NOMBRE_FUENTE_INFORME_DIARIO and _titulo_publico(n)
    ]
    # Más prioritarias primero (local/departamental primero, más reciente
    # primero dentro del mismo nivel); orden estable por fecha_recoleccion
    # DESC ya viene de la consulta, `sorted` con la prioridad territorial
    # como clave principal preserva ese desempate.
    candidatas.sort(key=_prioridad)
    return candidatas[:CANTIDAD_MAXIMA]


def _componer_texto(noticias: List[dict], fecha_local: datetime) -> tuple:
    fecha_legible = fecha_local.strftime("%d/%m/%Y")
    titulo = f"Resumen del día {fecha_legible}"
    lineas = [f"Lo más importante de hoy en Libertador General San Martín y el Departamento Ledesma:", ""]
    for noticia in noticias:
        lineas.append(f"• {_titulo_publico(noticia)}")
    lineas.append("")
    lineas.append("Notas completas en https://ledesmaparticipa.com.ar")
    return titulo, "\n".join(lineas)


def _hash_resumen(fecha_iso: str) -> str:
    """Salado por fecha, igual criterio que institucional: el texto
    depende de las noticias del día, pero por las dudas de que un día
    tenga exactamente el mismo lote (no debería, cada noticia es única),
    se sala igual para garantizar unicidad por día sin depender del
    contenido."""
    return hashlib.sha256(f"resumen_diario|{fecha_iso}".encode("utf-8")).hexdigest()


def _url_resumen(fecha_iso: str) -> str:
    return normalizar_url(f"https://ledesma-participa.local/resumen-del-dia/{fecha_iso}")


def _crear_noticia_resumen(db: Database, fecha_iso: str, ahora_local: datetime, noticias: List[dict]) -> int:
    titulo, texto = _componer_texto(noticias, ahora_local)
    imagen_ruta = str(generar_placa(titulo, texto, fuente="", localidad=""))
    noticia = Noticia(
        id=None,
        titulo_original=titulo,
        texto_original=texto,
        url_fuente="",
        url_normalizada=_url_resumen(fecha_iso),
        nombre_fuente=NOMBRE_FUENTE,
        fecha_fuente=ahora_local.isoformat(),
        fecha_recoleccion=ahora_local.astimezone(timezone.utc).isoformat(),
        estado=Estado.PREPARADA.value,
        hash_contenido=_hash_resumen(fecha_iso),
        titulo_preparado=titulo,
        texto_preparado=texto,
        revision_estado=RevisionEstado.APROBADA.value,
        revision_automatica=True,
        requiere_revision_especial=False,
        territorio=TERRITORIO_RESUMEN,
        motivo_territorio="Resumen del día: compilación de noticias ya publicadas, no se clasifica territorialmente.",
        tiene_imagen_original=True,
        imagen_publicacion_ruta=imagen_ruta,
        imagen_generada_automaticamente=False,
        origen_ingreso=OrigenIngreso.RESUMEN_DIARIO.value,
    )
    db.guardar(noticia)
    return noticia.id


def reservar_franja_resumen_del_dia(
    db: Database, fecha: Optional[str] = None, ahora: Optional[datetime] = None
) -> EntradaAgenda:
    """Crea (si no existe) el resumen del día de hoy y reserva su franja
    fija (22:30). Idempotente: si ya existe (misma URL determinística por
    fecha), no vuelve a componerlo. Solo se genera si hay al menos
    `CANTIDAD_MINIMA` noticias reales ya publicadas hoy — con menos, no hay
    material real para un resumen honesto y la franja queda sin_candidato,
    nunca se rellena con menos de lo esperado."""
    ahora_local = (ahora or datetime.now(ZONA_JUJUY)).astimezone(ZONA_JUJUY)
    fecha = fecha or ahora_local.strftime("%Y-%m-%d")
    hora = HORA_RESUMEN_DEL_DIA

    url = _url_resumen(fecha)
    existente_noticia = db.obtener_por_url(url)
    if existente_noticia is not None:
        noticia_id = existente_noticia["id"]
        existente_item = db.obtener_agenda_item(fecha, hora)
        if existente_item is not None and existente_item.get("noticia_id") == noticia_id:
            return EntradaAgenda(fecha, hora, "normal", TERRITORIO_RESUMEN, noticia_id, "existente")
        creada_en = datetime.now(timezone.utc).isoformat()
        db.guardar_agenda_item(
            fecha, hora, "normal", TERRITORIO_RESUMEN, noticia_id, creada_en,
            id_existente=existente_item["id"] if existente_item else None,
        )
        estado_entrada = "actualizado" if existente_item else "creado"
        return EntradaAgenda(fecha, hora, "normal", TERRITORIO_RESUMEN, noticia_id, estado_entrada)

    inicio_dia_local = ahora_local.replace(hour=0, minute=0, second=0, microsecond=0)
    fecha_limite_utc = inicio_dia_local.astimezone(timezone.utc).isoformat()
    noticias = _seleccionar_noticias_del_dia(db, fecha_limite_utc)

    existente_item = db.obtener_agenda_item(fecha, hora)
    if len(noticias) < CANTIDAD_MINIMA:
        if existente_item is None or existente_item.get("noticia_id") is not None:
            creada_en = datetime.now(timezone.utc).isoformat()
            db.guardar_agenda_item(
                fecha, hora, "normal", None, None, creada_en,
                id_existente=existente_item["id"] if existente_item else None,
            )
        return EntradaAgenda(fecha, hora, "normal", None, None, "sin_candidato")

    noticia_id = _crear_noticia_resumen(db, fecha, ahora_local, noticias)
    creada_en = datetime.now(timezone.utc).isoformat()
    db.guardar_agenda_item(
        fecha, hora, "normal", TERRITORIO_RESUMEN, noticia_id, creada_en,
        id_existente=existente_item["id"] if existente_item else None,
    )
    estado_entrada = "actualizado" if existente_item else "creado"
    return EntradaAgenda(fecha, hora, "normal", TERRITORIO_RESUMEN, noticia_id, estado_entrada)
