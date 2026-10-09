"""Volumen del portal web/app (Etapa 1, 9/10/2026).

Antes la web y la app mostraban solo lo publicado en Facebook/Instagram
(~6 notas por día durante la prueba editorial). Ahora muestran entre 15 y
25 noticias válidas por día, más los urgentes, sin cambiar en nada la
frecuencia de las redes: no todo lo que entra al portal se publica en
Meta.

Qué entra (por día local de recolección):
1. Todo lo publicado en redes ese día (ya pasó el circuito editorial).
2. Hasta completar `MAXIMO_POR_DIA`, las candidatas `preparada` de mayor
   puntaje del scoring editorial único (el mismo que elige las franjas:
   ser local suma, no garantiza), con topes por territorio para que lo
   nacional no tape lo local.
3. Los URGENTES confirmados por el scoring, aunque el día esté completo.

Nunca entra: riesgo editorial obligatorio, rechazadas, descartadas
(duplicados, vigencia, calidad), el mismo hecho repetido desde otro medio,
la nota de un medio que ya tiene su reelaboración propia, informes de
clima/dólar (tienen su propio módulo en la portada) ni contenido sin
territorio que no sea entretenimiento verificable. No se rellena: si un
día hay 9 notas válidas, se muestran 9.

La selección se guarda en `portal_seleccion` para que el histórico quede
estable: cada corrida solo completa hoy y ayer.
"""
import logging
import math
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional

from .categorias import clasificar_categoria, territorio_vigente
from .db import Database
from .dedupe import es_mismo_contenido, palabras_clave, refieren_a_hecho_distinto
from .entretenimiento import es_entretenimiento_o_curiosidad
from .models import OrigenIngreso
from .motor_editorial import ZONA_JUJUY
from .scoring_editorial import CLASIFICACION_URGENTE, evaluar_noticia

logger = logging.getLogger("motor_noticias.portal")

MAXIMO_POR_DIA = 25
OBJETIVO_MINIMO_POR_DIA = 15  # referencia editorial: nunca se rellena para llegar
DIAS_A_COMPLETAR = 2
HORAS_GRACIA_CUPO = 2  # a las 00:00 ya hay cupo para ~2 h de noticias  # hoy y ayer: lo anterior ya quedó fijo
DIAS_HISTORICO_PORTAL = 90

# Topes diarios por territorio para lo que entra SOLO al portal (lo
# publicado en redes y los urgentes no cuentan contra el tope). Local y
# departamental no tienen tope: siempre entran si son válidas.
TOPES_POR_TERRITORIO = {
    "provincial": 10,
    "nacional": 8,
    "internacional": 2,
    "sin_clasificar": 2,
}

# Ninguna categoría temática puede ocupar más que esto de lo que entra solo
# al portal en un día (variedad: tres notas del dólar no copan la jornada).
TOPE_POR_CATEGORIA = 6

# Piezas periódicas que el módulo Clima + Dólar de la portada ya cubre: no
# entran como noticia al portal (evita que una cotización o un pronóstico
# diario monopolicen una sección acumulando días). Sin acentos.
PERIODICAS_EXCLUIDAS = (
    "dolar hoy", "dolar blue hoy", "precio del dolar", "cotizacion del dolar", "cotizaciones minuto a minuto",
    "clima en jujuy hoy", "pronostico del tiempo para", "calidad del aire en", "el tiempo en",
)

PREFIJO_INFORME_DIARIO = "https://ledesma-participa.local/informe-diario/"
ORIGENES_EXCLUIDOS = (OrigenIngreso.INSTITUCIONAL.value, OrigenIngreso.RESUMEN_DIARIO.value)


def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def fecha_local(fecha_recoleccion: Optional[str]) -> Optional[str]:
    try:
        momento = datetime.fromisoformat(fecha_recoleccion or "")
    except ValueError:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(ZONA_JUJUY).date().isoformat()


def es_informe_diario(noticia: dict) -> bool:
    return (noticia.get("url_normalizada") or noticia.get("url_fuente") or "").startswith(PREFIJO_INFORME_DIARIO)


def _apta(noticia: dict, territorio: str) -> bool:
    if es_informe_diario(noticia) or noticia.get("origen_ingreso") in ORIGENES_EXCLUIDOS:
        return False
    titulo = noticia.get("titulo_preparado") or noticia.get("titulo_original") or ""
    texto = noticia.get("texto_preparado") or noticia.get("texto_original") or ""
    if len(titulo.strip()) < 8 or len(texto.strip()) < 40:
        return False
    titulo_norm = _sin_acentos(titulo)
    if any(p in titulo_norm for p in PERIODICAS_EXCLUIDAS):
        return False
    if territorio in (None, "sin_clasificar", "institucional"):
        return es_entretenimiento_o_curiosidad(titulo, texto)
    return True


def _repetida(noticia: dict, elegidas: list) -> bool:
    titulo = noticia.get("titulo_original") or ""
    huella = palabras_clave(titulo)
    for otra in elegidas:
        otro_titulo = otra.get("titulo_original") or ""
        if es_mismo_contenido(huella, palabras_clave(otro_titulo)) and not refieren_a_hecho_distinto(titulo, otro_titulo):
            return True
    return False


def completar_seleccion(db: Database, ahora: Optional[datetime] = None) -> dict:
    """Completa la selección del portal para hoy y ayer (hora de Jujuy).
    Devuelve {fecha: cantidad_agregada}. Idempotente: una noticia nunca se
    selecciona dos veces y un día completo no recibe más notas (salvo
    urgentes)."""
    ahora_local = (ahora or datetime.now(timezone.utc)).astimezone(ZONA_JUJUY)
    fechas = [(ahora_local.date() - timedelta(days=d)).isoformat() for d in range(DIAS_A_COMPLETAR)]
    inicio_local = datetime.combine(
        ahora_local.date() - timedelta(days=DIAS_A_COMPLETAR - 1), datetime.min.time(), tzinfo=ZONA_JUJUY
    )
    fecha_limite = inicio_local.astimezone(timezone.utc).isoformat()

    reelaboradas = db.ids_fuente_reelaborados()
    publicadas = db.noticias_publicadas_recientes(fecha_limite)
    ya_seleccionadas = db.portal_seleccion_por_fecha(fechas)
    candidatas = db.candidatas_portal(fecha_limite)

    por_id = {n["id"]: n for n in candidatas}
    agregadas: dict = {}
    momento_guardado = datetime.now(timezone.utc).isoformat()
    # Lo ya asignado a una franja o urgente de hoy entra primero (no cuenta
    # contra los topes): así su página propia existe ANTES de publicarse en
    # redes y el copy puede enlazar a ledesmaparticipa.com.ar.
    for item in db.listar_agenda(fechas[0]):
        n = por_id.get(item.get("noticia_id"))
        if n is not None and not es_informe_diario(n):
            db.guardar_portal_seleccion(n["id"], fecha_local(n.get("fecha_recoleccion")) or fechas[0], 0, momento_guardado)
            ya_seleccionadas.setdefault(fecha_local(n.get("fecha_recoleccion")) or fechas[0], []).append(n["id"])
            del por_id[n["id"]]
    for fecha in fechas:
        # El cupo del día se libera en proporción a las horas transcurridas:
        # sin esto, lo que llega de madrugada (mayormente nacional) llenaría
        # el día y no dejaría lugar a notas mejores de la tarde.
        if fecha == fechas[0]:
            horas = ahora_local.hour + ahora_local.minute / 60
            fraccion = min(1.0, (horas + HORAS_GRACIA_CUPO) / 24)
        else:
            fraccion = 1.0

        def cupo(tope: int) -> int:
            return max(1, math.ceil(tope * fraccion))

        elegidas = [n for n in publicadas if fecha_local(n.get("fecha_recoleccion")) == fecha]
        seleccionadas_ids = ya_seleccionadas.get(fecha, [])
        elegidas += [n for n in (db.obtener(i) for i in seleccionadas_ids) if n]
        conteo_territorio: dict = {}
        conteo_categoria: dict = {}
        for n in elegidas:
            if n["id"] in seleccionadas_ids:
                t = territorio_vigente(n) or "sin_clasificar"
                conteo_territorio[t] = conteo_territorio.get(t, 0) + 1
                c = clasificar_categoria(n)["valor"]
                conteo_categoria[c] = conteo_categoria.get(c, 0) + 1
        ocupados = len(elegidas)

        del_dia = []
        for n in por_id.values():
            if fecha_local(n.get("fecha_recoleccion")) != fecha or n["id"] in reelaboradas:
                continue
            territorio = territorio_vigente(n) or "sin_clasificar"
            if not _apta(n, territorio):
                continue
            evaluacion = evaluar_noticia(n, ahora)
            del_dia.append((evaluacion["total"], evaluacion["clasificacion"] == CLASIFICACION_URGENTE, territorio, n))
        del_dia.sort(key=lambda t: (t[1], t[0], t[3]["id"]), reverse=True)

        agregadas[fecha] = 0
        for puntaje, urgente, territorio, n in del_dia:
            categoria = clasificar_categoria(n)["valor"]
            if not urgente:
                if ocupados >= cupo(MAXIMO_POR_DIA):
                    continue
                tope = TOPES_POR_TERRITORIO.get(territorio)
                if tope is not None and conteo_territorio.get(territorio, 0) >= cupo(tope):
                    continue
                if categoria and conteo_categoria.get(categoria, 0) >= cupo(TOPE_POR_CATEGORIA):
                    continue
            if _repetida(n, elegidas):
                continue
            db.guardar_portal_seleccion(n["id"], fecha, int(puntaje), momento_guardado)
            elegidas.append(n)
            if not urgente:
                ocupados += 1
                conteo_territorio[territorio] = conteo_territorio.get(territorio, 0) + 1
                conteo_categoria[categoria] = conteo_categoria.get(categoria, 0) + 1
            agregadas[fecha] += 1
    logger.info("Portal: selección completada %s", agregadas)
    return agregadas


def noticias_del_portal(db: Database, ahora: Optional[datetime] = None) -> list:
    """Publicadas + seleccionadas para el portal (más nuevas primero)."""
    ahora_utc = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    limite = (ahora_utc - timedelta(days=DIAS_HISTORICO_PORTAL)).isoformat()
    return db.listar_portal(limite)
