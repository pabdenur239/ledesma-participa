import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .db import Database

UMBRAL_FALLOS_CONSECUTIVOS = 3
UMBRAL_INACTIVIDAD_HORAS = 24
UMBRAL_SIN_INFORMACION_LOCAL_HORAS = 6
# Cobertura web/app (9/10/2026). Una sola alerta por fuente y por condición,
# recalculada desde el estado persistido (no se acumulan ni se reenvían):
# - consultas OK seguidas sin ningún ítem;
# - proporción de ítems sin texto en la última consulta;
# - errores estructurales (certificado, parser roto) alertan desde la
#   primera vez; un HTTP/conexión aislado no, recién al repetirse.
UMBRAL_VACIOS_CONSECUTIVOS = 3
UMBRAL_PROPORCION_SIN_TEXTO = 0.5
UMBRAL_FALLOS_ERROR_HTTP = 2

NIVEL_ERROR = "ERROR"
NIVEL_ADVERTENCIA = "ADVERTENCIA"


def _parsear_fecha(fecha: Optional[str]) -> Optional[datetime]:
    if not fecha:
        return None
    return datetime.fromisoformat(fecha)


def clasificar_error(mensaje: Optional[str]) -> str:
    """Tipo de falla a partir del mensaje guardado en `fuente_salud`:
    certificado | parser | http | conexion | otro."""
    texto = (mensaje or "").lower()
    if "certificate" in texto or "ssl" in texto or "certificado" in texto:
        return "certificado"
    if re.search(r"http \d{3}", texto):
        return "http"
    if re.search(r"parse|not well-formed|syntax error|no element found|mismatched tag", texto):
        return "parser"
    if "conectar" in texto or "timed out" in texto or "timeout" in texto or "urlopen" in texto:
        return "conexion"
    return "otro"


DESCRIPCION_ERROR = {
    "certificado": "error de certificado",
    "parser": "parser roto",
    "http": "error HTTP",
    "conexion": "sin conexión",
    "otro": "error",
}


def calcular_alertas(db: Database, ahora: Optional[datetime] = None) -> List[dict]:
    """Calcula las alertas internas activas a partir del estado persistido
    (salud por fuente + noticias ya guardadas). No envía nada externo: solo
    devuelve la lista para mostrarla en el panel."""
    ahora = ahora or datetime.now(timezone.utc)
    alertas: List[dict] = []

    for fuente in db.listar_salud_fuentes():
        fallos = fuente["fallos_consecutivos"]
        if fuente["ultimo_resultado"] != "ok" and fallos > 0:
            causa = clasificar_error(fuente.get("ultimo_error"))
            descripcion = DESCRIPCION_ERROR[causa]
            if fallos >= UMBRAL_FALLOS_CONSECUTIVOS:
                alertas.append(
                    {
                        "tipo": "fuente_con_fallas",
                        "nivel": NIVEL_ERROR,
                        "fuente": fuente["nombre_fuente"],
                        "causa": causa,
                        "mensaje": (
                            f"{fuente['nombre_fuente']}: {fallos} fallos consecutivos ({descripcion})."
                        ),
                    }
                )
            elif causa in ("certificado", "parser") or (causa == "http" and fallos >= UMBRAL_FALLOS_ERROR_HTTP):
                alertas.append(
                    {
                        "tipo": f"fuente_error_{causa}",
                        "nivel": NIVEL_ERROR if causa in ("certificado", "parser") else NIVEL_ADVERTENCIA,
                        "fuente": fuente["nombre_fuente"],
                        "causa": causa,
                        "mensaje": f"{fuente['nombre_fuente']}: {descripcion} ({fallos} consulta(s) seguidas).",
                    }
                )

        # No asumimos que una fuente está caída solo porque no publicó
        # noticias: esta alerta es una ADVERTENCIA aparte de los errores de
        # recolección, y solo se activa si la última consulta respondió OK.
        if fuente["ultimo_resultado"] == "ok":
            vacios = fuente.get("vacios_consecutivos") or 0
            elementos = fuente.get("elementos_obtenidos") or 0
            sin_texto = fuente.get("items_sin_texto") or 0
            if vacios >= UMBRAL_VACIOS_CONSECUTIVOS:
                # Reemplaza a "inactiva" para la misma fuente (una sola alerta).
                alertas.append(
                    {
                        "tipo": "fuente_vacia",
                        "nivel": NIVEL_ADVERTENCIA,
                        "fuente": fuente["nombre_fuente"],
                        "mensaje": f"{fuente['nombre_fuente']}: {vacios} consultas seguidas sin ningún ítem.",
                    }
                )
                continue
            if elementos > 0 and sin_texto / elementos >= UMBRAL_PROPORCION_SIN_TEXTO:
                alertas.append(
                    {
                        "tipo": "fuente_sin_texto",
                        "nivel": NIVEL_ADVERTENCIA,
                        "fuente": fuente["nombre_fuente"],
                        "mensaje": (
                            f"{fuente['nombre_fuente']}: {sin_texto} de {elementos} ítems de la última "
                            "consulta llegaron sin texto."
                        ),
                    }
                )
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
