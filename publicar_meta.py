#!/usr/bin/env python3
"""Publica en Facebook e Instagram el contenido programado para la franja
horaria actual (o una franja explícita con --hora). Pensado para invocarse
desde una tarea programada disparada varias veces al día, una por franja
fija: detecta sola cuál es la franja más cercana a la hora actual dentro de
una tolerancia (por si la tarea programada se dispara con algunos minutos
de diferencia)."""
import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from motor_noticias.db import Database
from motor_noticias.meta.cliente import ClienteMetaGraphAPI
from motor_noticias.meta.publicador import publicar_franja
from motor_noticias.motor_editorial import (
    HORA_INFORME_DIARIO,
    HORA_INSTITUCIONAL_RESERVADA,
    HORA_NOTICIA_DEL_DIA,
    HORA_RESUMEN_DEL_DIA,
    HORARIOS_DEFAULT,
    ZONA_JUJUY,
)

DB_PATH_DEFAULT = Path(__file__).resolve().parent / "data" / "ledesma_participa.db"
TOLERANCIA_MINUTOS_DEFAULT = 15

# Las cuatro franjas fijas reservadas (excluidas de HORARIOS_DEFAULT porque
# no compiten con la cascada territorial) también se publican por este
# mismo mecanismo genérico de franja-más-cercana: sin agregarlas acá,
# Noticia del Día/Institucional/Resumen del Día nunca encontrarían
# coincidencia y no se publicarían nunca.
HORAS_FIJAS_RESERVADAS = (
    HORA_INFORME_DIARIO,
    HORA_NOTICIA_DEL_DIA,
    HORA_INSTITUCIONAL_RESERVADA,
    HORA_RESUMEN_DEL_DIA,
)


def _franja_actual(ahora_jujuy: datetime, tolerancia_minutos: int) -> Optional[str]:
    horas = list(HORAS_FIJAS_RESERVADAS) + list(HORARIOS_DEFAULT)
    candidatas = []
    for hora in horas:
        hh, mm = (int(x) for x in hora.split(":"))
        momento = ahora_jujuy.replace(hour=hh, minute=mm, second=0, microsecond=0)
        delta_minutos = (ahora_jujuy - momento).total_seconds() / 60
        if 0 <= delta_minutos <= tolerancia_minutos:
            candidatas.append((delta_minutos, hora))
    if not candidatas:
        return None
    candidatas.sort()
    return candidatas[0][1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publica el contenido programado de la franja actual en Facebook e Instagram — "
        "Ledesma Participa"
    )
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Ruta a la base de datos SQLite")
    parser.add_argument(
        "--fecha", default=None, help="YYYY-MM-DD (default: hoy en America/Argentina/Jujuy)"
    )
    parser.add_argument("--hora", default=None, help="HH:MM (default: detectar por hora actual)")
    parser.add_argument(
        "--tolerancia-minutos", type=int, default=TOLERANCIA_MINUTOS_DEFAULT,
        help="Ventana, en minutos, para asociar la hora actual a una franja fija",
    )
    args = parser.parse_args()

    ahora_jujuy = datetime.now(ZONA_JUJUY)
    fecha = args.fecha or ahora_jujuy.strftime("%Y-%m-%d")
    hora = args.hora or _franja_actual(ahora_jujuy, args.tolerancia_minutos)

    if not hora:
        print("No hay ninguna franja de publicación cerca de la hora actual. No se hace nada.")
        return 0

    db = Database(args.db)
    try:
        cliente_fb = ClienteMetaGraphAPI()
        cliente_ig = ClienteMetaGraphAPI()
        resultado = publicar_franja(db, fecha, hora, cliente_fb=cliente_fb, cliente_ig=cliente_ig)
    finally:
        db.close()

    print(f"Franja {fecha} {hora}: {resultado.resultado}")
    for red in resultado.redes:
        detalle = f" ({red.detalle})" if red.detalle else ""
        print(f"  - {red.red_social}: {red.estado}{detalle}")

    return 1 if any(r.estado == "error" for r in resultado.redes) else 0


if __name__ == "__main__":
    sys.exit(main())
