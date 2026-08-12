from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .db import Database

UMBRAL_FALLOS_CONSECUTIVOS = 3
UMBRAL_INACTIVIDAD_HORAS = 24
UMBRAL_SIN_INFORMACION_LOCAL_HORAS = 6

NIVEL_ERROR = "ERROR"
NIVEL_ADVERTENCIA = "ADVERTENCIA"


def _parsear_fecha(fecha: Optional[str]) -> Optional[datetime]:
    if not fecha:
        return None
    return datetime.fromisoformat(fecha)


def calcular_alertas(db: Database, ahora: Optional[datetime] = None) -> List[dict]:
    """Calcula las alertas internas activas a partir del estado persistido
    (salud por fuente + noticias ya guardadas). No envía nada externo: solo
    devuelve la lista para mostrarla en el panel."""
    ahora = ahora or datetime.now(timezone.utc)
    alertas: List[dict] = []

    for fuente in db.listar_salud_fuentes():
        if fuente["fallos_consecutivos"] >= UMBRAL_FALLOS_CONSECUTIVOS:
            alertas.append(
                {
                    "tipo": "fuente_con_fallas",
                    "nivel": NIVEL_ERROR,
                    "fuente": fuente["nombre_fuente"],
                    "mensaje": (
                        f"{fuente['nombre_fuente']}: {fuente['fallos_consecutivos']} fallos "
                        "consecutivos."
                    ),
                }
            )

        # No asumimos que una fuente está caída solo porque no publicó
        # noticias: esta alerta es una ADVERTENCIA aparte de los errores de
        # recolección, y solo se activa si la última consulta respondió OK.
        if fuente["ultimo_resultado"] == "ok":
            ultima_noticia = _parsear_fecha(fuente["ultima_noticia_fecha"])
            if ultima_noticia is None or (ahora - ultima_noticia) >= timedelta(hours=UMBRAL_INACTIVIDAD_HORAS):
                alertas.append(
                    {
                        "tipo": "fuente_inactiva",
                        "nivel": NIVEL_ADVERTENCIA,
                        "fuente": fuente["nombre_fuente"],
                        "mensaje": (
                            f"{fuente['nombre_fuente']}: sin noticias nuevas en las últimas "
                            f"{UMBRAL_INACTIVIDAD_HORAS} horas."
                        ),
                    }
                )

    ultima_relevante = _parsear_fecha(db.ultima_noticia_relevante_fecha())
    if ultima_relevante is None or (ahora - ultima_relevante) >= timedelta(
        hours=UMBRAL_SIN_INFORMACION_LOCAL_HORAS
    ):
        alertas.append(
            {
                "tipo": "sin_informacion_local",
                "nivel": NIVEL_ADVERTENCIA,
                "fuente": None,
                "mensaje": (
                    "Sin noticias relevantes para Libertador General San Martín o el "
                    f"Departamento Ledesma en las últimas {UMBRAL_SIN_INFORMACION_LOCAL_HORAS} horas."
                ),
            }
        )

    return alertas
