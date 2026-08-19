#!/usr/bin/env python3
"""Publica en Facebook e Instagram, sin esperar la siguiente franja fija,
las propuestas urgentes (último momento local/departamental confirmado) del
día que ya tengan noticia asignada por la Agenda Editorial. Pensado para
invocarse desde una tarea programada frecuente (cada 15 minutos), separada
de `publicar_meta.py` (que solo cubre las franjas fijas)."""
import sys
from datetime import datetime
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.meta.cliente import ClienteMetaGraphAPI
from motor_noticias.meta.publicador import publicar_urgentes
from motor_noticias.motor_editorial import ZONA_JUJUY

DB_PATH_DEFAULT = Path(__file__).resolve().parent / "data" / "ledesma_participa.db"


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Publica de inmediato las propuestas urgentes del día — Ledesma Participa"
    )
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Ruta a la base de datos SQLite")
    parser.add_argument(
        "--fecha", default=None, help="YYYY-MM-DD (default: hoy en America/Argentina/Jujuy)"
    )
    parser.add_argument(
        "--max-pendientes", type=int, default=1,
        help="Máximo de propuestas nuevas a publicar en esta corrida (default: 1, evita vaciar toda la cola de una vez)",
    )
    args = parser.parse_args()

    fecha = args.fecha or datetime.now(ZONA_JUJUY).strftime("%Y-%m-%d")

    db = Database(args.db)
    try:
        cliente_fb = ClienteMetaGraphAPI()
        cliente_ig = ClienteMetaGraphAPI()
        resultados = publicar_urgentes(
            db, fecha, cliente_fb=cliente_fb, cliente_ig=cliente_ig, max_pendientes=args.max_pendientes
        )
    finally:
        db.close()

    if not resultados:
        print(f"{fecha}: no hay propuestas urgentes con noticia asignada.")
        return 0

    for resultado in resultados:
        print(f"Urgente {resultado.fecha} ({resultado.hora}): {resultado.resultado}")
        for red in resultado.redes:
            detalle = f" ({red.detalle})" if red.detalle else ""
            print(f"  - {red.red_social}: {red.estado}{detalle}")

    return 1 if any(r.estado == "error" for resultado in resultados for r in resultado.redes) else 0


if __name__ == "__main__":
    sys.exit(main())
