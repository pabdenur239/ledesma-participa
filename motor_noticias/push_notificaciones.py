"""Envío de notificaciones push reales (Firebase Cloud Messaging) para la
app móvil de Ledesma Participa.

Diseño sin backend nuevo de registro de tokens: la app se suscribe a UN
solo tópico FCM (`TOPICO_FCM`, ver `app/lib/services/notification_service.dart`
— el id debe coincidir exactamente en los dos lados). Este módulo publica
al tópico; Firebase se encarga de entregarlo a todos los dispositivos
suscriptos, sin que el VPS tenga que guardar ni mantener tokens por
dispositivo.

Regla dura, no una preferencia: NUNCA una notificación por cada
publicación. Solo dos casos (ver `evaluar_push`):
  A) noticias urgentes reales (accidentes graves, cortes importantes,
     emergencias, desapariciones, alertas, hechos policiales relevantes,
     información crítica de servicios);
  B) noticias locales/departamentales de alta importancia — mismo criterio,
     no hay una categoría B distinta en la práctica: ambas se evalúan con
     el mismo filtro de palabras clave sobre contenido ya local/
     departamental y ya publicado.

Nunca infiere ni interpreta: solo reconoce palabras clave explícitas en el
título/texto YA redactado y publicado — mismo principio que
`motor_noticias.contenido_propio`. Institucional y Resumen del Día quedan
excluidos siempre, aunque coincidan por accidente con alguna palabra clave
(no son noticias reales). Deportes/espectáculos/gastronomía/salud/
internacional de "último recurso" quedan excluidos estructuralmente: ese
contenido nunca tiene `territorio` local/departamental, que es un filtro
obligatorio acá.

Dedup: como mucho un push por noticia (`noticias.push_enviado_en`,
ver `motor_noticias.db`) — no existe en este proyecto un mecanismo de
"actualización sustancial" de una noticia ya publicada (no se reeditan
notas después de publicadas), así que la excepción de la regla de
deduplicación no aplica hoy: la regla efectiva es simple, nunca dos veces
la misma noticia."""
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from .db import Database
from .models import OrigenIngreso

logger = logging.getLogger("motor_noticias.push_notificaciones")

# Debe coincidir exactamente con NotificationService._topicoNotificaciones
# en app/lib/services/notification_service.dart.
TOPICO_FCM = "ledesma_participa_importantes"

CREDENCIAL_PATH_DEFAULT = Path("/etc/ledesma-participa/firebase-adminsdk.json")
VENTANA_HORAS_DEFAULT = 48
LONGITUD_CUERPO_PUSH = 120

# Nunca push, sin importar el contenido: no son noticias reales (ver
# motor_noticias.institucional / motor_noticias.resumen_dia).
ORIGENES_EXCLUIDOS_PUSH = (OrigenIngreso.INSTITUCIONAL.value, OrigenIngreso.RESUMEN_DIARIO.value)

# Palabras clave explícitas de urgencia/importancia real — ejemplos del
# propio alcance pedido: accidentes graves, cortes importantes,
# emergencias, desapariciones, alertas, hechos policiales relevantes,
# información crítica de servicios. Deliberadamente NO incluye "policía"
# ni "urgente" solas (demasiado amplias: aparecerían en coberturas
# rutinarias) — exige la palabra concreta del hecho.
PALABRAS_CLAVE_PUSH_DEFAULT = (
    "accidente", "choque", "colisión", "colision", "vuelco", "atropell",
    "incendio", "explosión", "explosion", "derrumbe", "inundación", "inundacion",
    "evacua",
    "corte de luz", "corte de agua", "corte programado", "sin luz", "sin agua",
    "emergencia", "alerta meteorológica", "alerta meteorologica", "alerta sanitaria",
    "desaparici", "desaparecid", "busca a", "encontrar a",
    "operativo policial", "tiroteo", "balacera", "asalto", "robo a mano armada",
    "persona herida", "personas heridas", "hallaron el cuerpo",
    "corte de tránsito", "corte de transito", "corte total de",
)


def _cargar_config(path: Optional[Path] = None) -> dict:
    import json
    ruta = path or (Path(__file__).resolve().parent.parent / "config" / "push_notificaciones.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def evaluar_push(noticia: dict, palabras_clave: tuple = PALABRAS_CLAVE_PUSH_DEFAULT) -> Optional[str]:
    """Devuelve la palabra clave que justifica el push, o None si esta
    noticia no califica. Puramente determinístico: título/texto ya
    publicados, sin inferir nada. `territorio` local/departamental y
    `origen_ingreso` no institucional/resumen ya se filtran en la consulta
    (`Database.noticias_candidatas_a_push`), pero se revalidan acá por si
    esta función se llama directo (p.ej. desde un test o `--forzar-noticia-id`)."""
    if noticia.get("origen_ingreso") in ORIGENES_EXCLUIDOS_PUSH:
        return None
    if noticia.get("territorio") not in ("local", "departamental"):
        return None

    titulo = (noticia.get("titulo_revisado") or noticia.get("titulo_preparado") or noticia.get("titulo_original") or "").lower()
    texto = (noticia.get("texto_revisado") or noticia.get("texto_preparado") or noticia.get("texto_original") or "").lower()
    contenido = f"{titulo} {texto}"

    for palabra in palabras_clave:
        if palabra in contenido:
            return palabra
    return None


def _resumen_breve(texto: str, longitud_maxima: int = LONGITUD_CUERPO_PUSH) -> str:
    texto = (texto or "").strip()
    if len(texto) <= longitud_maxima:
        return texto
    recorte = texto[:longitud_maxima]
    ultimo_espacio = recorte.rfind(" ")
    if ultimo_espacio > 0:
        recorte = recorte[:ultimo_espacio]
    return recorte.rstrip(",.;: ") + "…"


@dataclass
class ResultadoPush:
    noticia_id: int
    resultado: str  # "enviado" | "no_califica" | "error"
    palabra_clave: Optional[str] = None
    mensaje_error: Optional[str] = None


def _construir_app_firebase(credencial_path: Path):
    import firebase_admin
    from firebase_admin import credentials

    if firebase_admin._apps:
        return firebase_admin.get_app()
    return firebase_admin.initialize_app(credentials.Certificate(str(credencial_path)))


def _enviar_mensaje_fcm(noticia: dict) -> str:
    """Arma y envía el mensaje real a FCM. Separado en su propia función
    para poder simularlo en tests sin credenciales reales (nunca se llama
    en dry-run, ver `enviar_push_pendientes`)."""
    from firebase_admin import messaging

    titulo = noticia.get("titulo_revisado") or noticia.get("titulo_preparado") or noticia.get("titulo_original") or ""
    texto = noticia.get("texto_revisado") or noticia.get("texto_preparado") or noticia.get("texto_original") or ""

    mensaje = messaging.Message(
        notification=messaging.Notification(title=titulo.strip(), body=_resumen_breve(texto)),
        data={"noticia_id": str(noticia["id"])},
        topic=TOPICO_FCM,
        android=messaging.AndroidConfig(priority="high"),
    )
    return messaging.send(mensaje)


def enviar_push_pendientes(
    db: Database,
    ahora: Optional[datetime] = None,
    credencial_path: Optional[Path] = None,
    config: Optional[dict] = None,
    dry_run: bool = False,
    forzar_noticia_id: Optional[int] = None,
) -> List[ResultadoPush]:
    """Evalúa candidatas (o una única noticia real forzada, para pruebas
    controladas) y envía push real por FCM a las que califiquen. Idempotente:
    una noticia con `push_enviado_en` ya seteado nunca se reevalúa ni se
    reenvía (ver `Database.noticias_candidatas_a_push`); `forzar_noticia_id`
    sortea ese filtro a propósito (para poder probar con una noticia real
    ya publicada aunque no haya calificado sola), pero igual respeta el
    resto de las reglas (`evaluar_push`) y sigue marcando `push_enviado_en`
    al enviar, así una prueba controlada tampoco duplica un envío real
    posterior."""
    config = config or _cargar_config()
    palabras_clave = tuple(config.get("palabras_clave") or PALABRAS_CLAVE_PUSH_DEFAULT)
    ventana_horas = config.get("ventana_horas", VENTANA_HORAS_DEFAULT)
    credencial_path = credencial_path or CREDENCIAL_PATH_DEFAULT

    ahora_utc = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)

    if forzar_noticia_id is not None:
        noticia = db.obtener(forzar_noticia_id)
        candidatas = [noticia] if noticia else []
    else:
        fecha_limite = (ahora_utc - timedelta(hours=ventana_horas)).isoformat()
        candidatas = db.noticias_candidatas_a_push(fecha_limite)

    resultados = []
    app_inicializada = False
    for noticia in candidatas:
        palabra = evaluar_push(noticia, palabras_clave)
        if not palabra:
            resultados.append(ResultadoPush(noticia["id"], "no_califica"))
            continue

        try:
            if dry_run:
                logger.info("[dry-run] Push que se enviaría (noticia #%s, palabra clave '%s')", noticia["id"], palabra)
                resultados.append(ResultadoPush(noticia["id"], "enviado", palabra_clave=palabra))
                continue

            if not app_inicializada:
                _construir_app_firebase(credencial_path)
                app_inicializada = True
            id_mensaje = _enviar_mensaje_fcm(noticia)
            # Se marca recién después de que FCM confirmó el envío (no antes,
            # no en dry-run): así un error real deja la noticia disponible
            # para reintentar en la próxima corrida en vez de darla por
            # enviada sin haberlo estado.
            db.marcar_push_enviado(noticia["id"], ahora_utc.isoformat())
            logger.info("Push enviado (noticia #%s, palabra clave '%s'): %s", noticia["id"], palabra, id_mensaje)
            resultados.append(ResultadoPush(noticia["id"], "enviado", palabra_clave=palabra))
        except Exception as error:  # noqa: BLE001 — cualquier falla de FCM se reporta, nunca se oculta
            logger.error("Error enviando push (noticia #%s): %s", noticia["id"], error)
            resultados.append(ResultadoPush(noticia["id"], "error", palabra_clave=palabra, mensaje_error=str(error)))

    return resultados
