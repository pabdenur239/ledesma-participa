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

Cobertura web/app (9/10/2026): ~45 notas válidas por día + urgentes (antes
25, que se llenaban temprano con provincial/nacional y dejaban afuera
noticias locales de la tarde). Cambios, solo para web/app:
- Local y departamental no tienen tope ni quedan bloqueadas por el cupo
  general ni por el tope por categoría: toda local válida entra. Sí ocupan
  lugar, así que reducen lo que queda para provincial/nacional (reserva
  dinámica). El cupo proporcional a la hora sigue frenando a lo demás.
- Recuperación 48 h: una local/departamental válida que quedó afuera entra
  aunque su día ya no sea hoy ni ayer, mientras siga vigente (recolectada y
  publicada por la fuente hace menos de `HORAS_RECUPERACION_LOCAL`). No se
  recuperan las marcadas urgentes (urgencia ya superada si no salió a
  tiempo). La repetición se controla contra todo lo elegido en la ventana,
  no solo contra el mismo día.
- Internacional relevante (`Estado.SOLO_PORTAL`, ver pipeline) con tope
  propio de 4 por día.
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
from .fechas import momento_vigencia
from .models import OrigenIngreso
from .motor_editorial import ZONA_JUJUY
from .scoring_editorial import CLASIFICACION_URGENTE, evaluar_noticia

logger = logging.getLogger("motor_noticias.portal")

MAXIMO_POR_DIA = 45  # orientativo: nunca se rellena para llegar
OBJETIVO_MINIMO_POR_DIA = 15  # referencia editorial: nunca se rellena para llegar
DIAS_A_COMPLETAR = 2  # hoy y ayer: lo anterior ya quedó fijo (salvo recuperación local)
HORAS_GRACIA_CUPO = 2  # a las 00:00 ya hay cupo para ~2 h de noticias
HORAS_RECUPERACION_LOCAL = 48
DIAS_HISTORICO_PORTAL = 90

# Local y departamental: sin tope, nunca bloqueadas por el cupo general.
TERRITORIOS_PRIORITARIOS = ("local", "departamental")

# Topes diarios por territorio para lo que entra SOLO al portal (lo
# publicado en redes y los urgentes no cuentan contra el tope). Suman 32 de
# 45: siempre queda lugar para lo local aunque el resto venga lleno.
TOPES_POR_TERRITORIO = {
    "provincial": 15,
    "nacional": 10,
    "internacional": 4,
    "sin_clasificar": 3,
}

# Ninguna categoría temática puede ocupar más que esto de lo que entra solo
# al portal en un día (variedad: tres notas del dólar no copan la jornada).
# No aplica a local/departamental ni a "general" (el comodín de baja
# confianza de `clasificar_categoria`, no un tema).
TOPE_POR_CATEGORIA = 10
CATEGORIAS_SIN_TOPE = ("general",)

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


def territorio_portal(noticia: dict) -> str:
    territorio = territorio_vigente(noticia) or "sin_clasificar"
    if territorio == "sin_clasificar" and noticia.get("categoria_tematica") == "internacional":
        return "internacional"
    return territorio


def _vigente_para_recuperar(noticia: dict, ahora_utc: datetime) -> bool:
    """Recuperación local: recolectada y publicada por la fuente dentro de
    las últimas `HORAS_RECUPERACION_LOCAL`, y no marcada urgente."""
    if noticia.get("urgente"):
        return False
    limite = ahora_utc - timedelta(hours=HORAS_RECUPERACION_LOCAL)
    try:
        recoleccion = datetime.fromisoformat(noticia.get("fecha_recoleccion") or "")
    except ValueError:
        return False
    if recoleccion.tzinfo is None:
        recoleccion = recoleccion.replace(tzinfo=timezone.utc)
    if recoleccion < limite:
        return False
    vigencia = momento_vigencia(noticia)
    return vigencia is None or vigencia >= limite


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
    if noticia.get("estado") == "solo_portal" and territorio != "internacional":
        return False  # el estado solo_portal es exclusivo de internacionales
    return True


# Resto del nombre "Libertador General San Martín" (dedupe.PALABRAS_CONTEXTO_LOCAL
# ya ignora "libertador"): sin esto, dos notas locales distintas con el
# nombre completo de la ciudad en el título compartían 3 palabras y el
# portal las tomaba como el mismo hecho (bloqueo real detectado en las
# pruebas de cobertura, 9/10/2026). Solo afecta al portal: la deduplicación
# de Meta no cambia.
PALABRAS_NOMBRE_CIUDAD = frozenset({"general", "san", "martin"})


def _huella(titulo: str) -> frozenset:
    return palabras_clave(titulo) - PALABRAS_NOMBRE_CIUDAD


def _repetida(noticia: dict, elegidas: list) -> bool:
    titulo = noticia.get("titulo_original") or ""
    huella = _huella(titulo)
    for otra in elegidas:
        otro_titulo = otra.get("titulo_original") or ""
        if es_mismo_contenido(huella, _huella(otro_titulo)) and not refieren_a_hecho_distinto(titulo, otro_titulo):
            return True
    return False


def completar_seleccion(db: Database, ahora: Optional[datetime] = None) -> dict:
    """Completa la selección del portal para hoy y ayer (hora de Jujuy),
    más la recuperación local de las últimas 48 h. Devuelve
    {fecha: cantidad_agregada}. Idempotente: una noticia nunca se
    selecciona dos veces y un día completo no recibe más notas (salvo
    urgentes y locales/departamentales válidas)."""
    ahora_utc = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    ahora_local = ahora_utc.astimezone(ZONA_JUJUY)
    fechas = [(ahora_local.date() - timedelta(days=d)).isoformat() for d in range(DIAS_A_COMPLETAR)]
    inicio_local = datetime.combine(
        ahora_local.date() - timedelta(days=DIAS_A_COMPLETAR - 1), datetime.min.time(), tzinfo=ZONA_JUJUY
    )
    inicio_recuperacion = ahora_utc - timedelta(hours=HORAS_RECUPERACION_LOCAL)
    fecha_limite = min(inicio_local.astimezone(timezone.utc), inicio_recuperacion).isoformat()

    reelaboradas = db.ids_fuente_reelaborados()
    candidatas = db.candidatas_portal(fecha_limite)
    # Días anteriores a ayer: solo para recuperar locales (lo demás de ese
    # día ya quedó fijo y su cupo no se toca).
    fechas_recuperacion = sorted(
        {f for f in (fecha_local(n.get("fecha_recoleccion")) for n in candidatas) if f and f not in fechas},
        reverse=True,
    )
    todas_las_fechas = fechas + fechas_recuperacion
    publicadas = db.noticias_publicadas_recientes(fecha_limite)
    ya_seleccionadas = db.portal_seleccion_por_fecha(todas_las_fechas)

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

    # La repetición se controla contra toda la ventana (hoy, ayer y
    # recuperación): recuperar nunca trae el mismo hecho ya mostrado.
    elegidas_ventana = list(publicadas)
    ids_ventana = {n["id"] for n in publicadas}
    for ids in ya_seleccionadas.values():
        for n in (db.obtener(i) for i in ids if i not in ids_ventana):
            if n:
                elegidas_ventana.append(n)
                ids_ventana.add(n["id"])

    for fecha in todas_las_fechas:
        solo_recuperacion = fecha not in fechas
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

        seleccionadas_ids = set(ya_seleccionadas.get(fecha, []))
        elegidas_del_dia = [n for n in elegidas_ventana if fecha_local(n.get("fecha_recoleccion")) == fecha]
        conteo_territorio: dict = {}
        conteo_categoria: dict = {}
        for n in elegidas_del_dia:
            if n["id"] in seleccionadas_ids:
                t = territorio_portal(n)
                conteo_territorio[t] = conteo_territorio.get(t, 0) + 1
                c = clasificar_categoria(n)["valor"]
                conteo_categoria[c] = conteo_categoria.get(c, 0) + 1
        ocupados = len(elegidas_del_dia)

        del_dia = []
        for n in por_id.values():
            if fecha_local(n.get("fecha_recoleccion")) != fecha or n["id"] in reelaboradas:
                continue
            territorio = territorio_portal(n)
            if not _apta(n, territorio):
                continue
            prioritaria = territorio in TERRITORIOS_PRIORITARIOS
            if solo_recuperacion and not (prioritaria and _vigente_para_recuperar(n, ahora_utc)):
                continue
            evaluacion = evaluar_noticia(n, ahora)
            urgente = evaluacion["clasificacion"] == CLASIFICACION_URGENTE and not solo_recuperacion
            del_dia.append((evaluacion["total"], urgente, prioritaria, territorio, n))
        del_dia.sort(key=lambda t: (t[1], t[0], t[4]["id"]), reverse=True)

        agregadas[fecha] = 0
        for puntaje, urgente, prioritaria, territorio, n in del_dia:
            categoria = clasificar_categoria(n)["valor"]
            if not urgente and not prioritaria:
                if ocupados >= cupo(MAXIMO_POR_DIA):
                    continue
                tope = TOPES_POR_TERRITORIO.get(territorio)
                if tope is not None and conteo_territorio.get(territorio, 0) >= cupo(tope):
                    continue
                if categoria and categoria not in CATEGORIAS_SIN_TOPE and conteo_categoria.get(categoria, 0) >= cupo(TOPE_POR_CATEGORIA):
                    continue
            if _repetida(n, elegidas_ventana):
                continue
            db.guardar_portal_seleccion(n["id"], fecha, int(puntaje), momento_guardado)
            elegidas_ventana.append(n)
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
