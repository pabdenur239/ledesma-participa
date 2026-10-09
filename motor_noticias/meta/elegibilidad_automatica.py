"""Determina si una noticia ya `preparada` puede aprobarse y publicarse en
Meta de forma 100% automática, sin intervención humana — a diferencia de la
aprobación manual desde el panel, que sigue existiendo igual que antes para
cualquier noticia.

Reutiliza exclusivamente reglas y datos que ya existen en el pipeline (no
inventa una segunda clasificación paralela):
- `requiere_revision_especial` / `categoria_riesgo` (motor_noticias.riesgo_editorial,
  con las categorías de config/riesgo_editorial.json: institucional/política,
  judicial, muertes, menores identificables, salud sensible, contenido
  violento) es la lista taxativa de motivos de revisión humana obligatoria.
- `ANTIGUEDAD_MAXIMA_HORAS` (motor_editorial) es el mismo límite de vigencia
  que ya usa la cascada territorial.

Una noticia sin ningún motivo de bloqueo es "apta": completa, verificable
(tiene fuente citada), clasificada territorialmente y dentro de la
antigüedad máxima. No decide *cuándo* se publica (eso es la franja de la
Agenda Editorial); solo si puede saltarse la revisión humana."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from ..calidad_editorial import evaluar_calidad
from ..fechas import momento_vigencia
from ..motor_editorial import ANTIGUEDAD_MAXIMA_HORAS
from ..models import Estado, RevisionEstado

TERRITORIOS_VALIDOS = ("local", "departamental", "provincial", "nacional", "internacional", "sin_clasificar")


@dataclass
class ResultadoElegibilidadAutomatica:
    elegible: bool
    motivos_bloqueo: List[str] = field(default_factory=list)


def evaluar_elegibilidad_publicacion_automatica(
    noticia: dict, ahora: Optional[datetime] = None
) -> ResultadoElegibilidadAutomatica:
    ahora = ahora or datetime.now(timezone.utc)
    motivos: List[str] = []

    if noticia.get("estado") != Estado.PREPARADA.value:
        motivos.append("La noticia no está en estado 'preparada'.")

    if noticia.get("revision_estado") == RevisionEstado.RECHAZADA.value:
        motivos.append("La noticia fue rechazada por revisión humana.")

    if noticia.get("requiere_revision_especial"):
        categoria = noticia.get("categoria_riesgo") or "sin especificar"
        motivos.append(f"Requiere revisión humana obligatoria (categoría de riesgo: {categoria}).")

    if not (noticia.get("titulo_preparado") or "").strip():
        motivos.append("Sin título preparado: contenido incompleto.")

    if not (noticia.get("texto_preparado") or "").strip():
        motivos.append("Sin texto preparado: contenido incompleto.")

    if not (noticia.get("nombre_fuente") or "").strip():
        motivos.append("Sin fuente citable: contenido no verificable.")

    if noticia.get("territorio") not in TERRITORIOS_VALIDOS:
        motivos.append("Territorio sin clasificar: no se puede determinar prioridad territorial.")

    fecha_recoleccion = noticia.get("fecha_recoleccion")
    if not fecha_recoleccion:
        motivos.append("Sin fecha de recolección: no se puede verificar vigencia.")
    else:
        try:
            momento = datetime.fromisoformat(fecha_recoleccion)
            if momento.tzinfo is None:
                momento = momento.replace(tzinfo=timezone.utc)
            limite = ahora - timedelta(hours=ANTIGUEDAD_MAXIMA_HORAS)
            if momento < limite:
                motivos.append("Contenido vencido (supera la antigüedad máxima permitida).")
        except ValueError:
            motivos.append("Fecha de recolección inválida: no se puede verificar vigencia.")

    # Vigencia también por la fecha de la FUENTE (no solo de recolección):
    # una nota de hace dos días recolectada o reelaborada hoy no es nueva.
    vigencia = momento_vigencia(noticia)
    if vigencia is not None and vigencia < ahora - timedelta(hours=ANTIGUEDAD_MAXIMA_HORAS):
        motivo_vencida = "Contenido vencido (la fuente lo publicó hace más de la antigüedad máxima)."
        if motivo_vencida not in motivos:
            motivos.append(motivo_vencida)

    calidad = evaluar_calidad(noticia)
    if calidad.accion == "retener":
        motivos.append("Control de calidad: " + "; ".join(calidad.problemas))

    return ResultadoElegibilidadAutomatica(elegible=not motivos, motivos_bloqueo=motivos)
