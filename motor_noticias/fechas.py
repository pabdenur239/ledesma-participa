"""Fechas de una noticia, separadas y honestas (agregado 2/10/2026).

Cada noticia tiene cuatro momentos distintos que no deben confundirse:

- source_published_at: cuándo la publicó la fuente (`fecha_fuente`). Puede
  venir sin hora (solo fecha) o con una hora "00:00" que en realidad es un
  relleno del feed (El Tribuno arma la fecha desde la URL y a veces no trae
  hora). En ese caso la hora es DESCONOCIDA y nunca se muestra como real.
- ingested_at: cuándo la recolectó el sistema (`fecha_recoleccion`).
- scheduled_at: la franja de la agenda (`agenda_item.fecha` + `hora`).
- published_at: cuándo salió realmente en redes
  (`programacion_meta.publicada_en`, la primera red confirmada).

La web muestra published_at cuando existe (es la hora editorial real de
Ledesma Participa) y, si no, la fecha de la fuente — solo con hora cuando
la hora es conocida.
"""
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import NamedTuple, Optional

# Argentina usa UTC-3 fijo (ver motor_editorial.ZONA_JUJUY): se repite acá
# para no importar motor_editorial desde módulos de bajo nivel.
ZONA_JUJUY = timezone(timedelta(hours=-3), name="America/Argentina/Jujuy")

MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

_RE_SOLO_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class FechaFuente(NamedTuple):
    momento: Optional[datetime]
    hora_conocida: bool


def parsear_fecha(valor: Optional[str]) -> FechaFuente:
    """RFC 2822 (RSS) o ISO 8601. Devuelve siempre un datetime aware (sin
    huso se asume hora de Jujuy) y si la hora es conocida: una fecha sin
    hora, o con hora exactamente 00:00:00, se trata como hora desconocida."""
    if not valor or not str(valor).strip():
        return FechaFuente(None, False)
    valor = str(valor).strip()
    if _RE_SOLO_FECHA.match(valor):
        try:
            return FechaFuente(datetime.fromisoformat(valor).replace(tzinfo=ZONA_JUJUY), False)
        except ValueError:
            return FechaFuente(None, False)
    dt = None
    try:
        dt = parsedate_to_datetime(valor)
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return FechaFuente(None, False)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZONA_JUJUY)
    hora_conocida = not (dt.hour == 0 and dt.minute == 0 and dt.second == 0 and dt.microsecond == 0)
    return FechaFuente(dt, hora_conocida)


def momento_fuente(noticia: dict) -> Optional[datetime]:
    """source_published_at (aware) o None."""
    return parsear_fecha(noticia.get("fecha_fuente")).momento


def momento_ingreso(noticia: dict) -> Optional[datetime]:
    return parsear_fecha(noticia.get("fecha_recoleccion")).momento


def momento_vigencia(noticia: dict) -> Optional[datetime]:
    """Momento desde el que se mide la frescura editorial: el más antiguo
    entre la publicación en la fuente y el ingreso. Una nota de hace dos
    días que recién se recolecta (o se reelabora como contenido propio) no
    es "nueva" por eso. Si la fuente declara una fecha futura (huso mal
    informado), se usa el ingreso."""
    ingreso = momento_ingreso(noticia)
    fuente = momento_fuente(noticia)
    candidatos = [m for m in (ingreso, fuente) if m is not None]
    if not candidatos:
        return None
    if ingreso is not None:
        candidatos = [m for m in candidatos if m <= ingreso + timedelta(hours=1)] or [ingreso]
    return min(candidatos)


def fecha_legible(momento: Optional[datetime], hora_conocida: bool = True) -> str:
    """En hora de Jujuy. Sin hora conocida, solo el día: nunca un "00:00"
    inventado."""
    if momento is None:
        return ""
    local = momento.astimezone(ZONA_JUJUY)
    dia = f"{local.day} de {MESES[local.month - 1]} de {local.year}"
    if not hora_conocida:
        return dia
    return f"{dia}, {local.hour:02d}:{local.minute:02d} hs"
