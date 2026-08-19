#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.meta.cliente import ClienteMetaGraphAPI
from motor_noticias.meta.publicador import MAX_INTENTOS_DEFAULT, reintentar_publicaciones

DB_PATH_DEFAULT = Path(__file__).resolve().parent / "data" / "ledesma_participa.db"
CONFIG_META_PATH_DEFAULT = Path(__file__).resolve().parent / "config" / "meta.json"


def _max_intentos(config_path: str) -> int:
    try:
        with open(config_path, encoding="utf-8") as f:
            return int(json.load(f).get("max_intentos_reintento", MAX_INTENTOS_DEFAULT))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return MAX_INTENTOS_DEFAULT


def main():
    parser = argparse.ArgumentParser(
        description="Reintenta (de forma acotada) publicaciones de Meta que quedaron en error — "
        "Ledesma Participa"
    )
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Ruta a la base de datos SQLite")
    parser.add_argument("--config-meta", default=str(CONFIG_META_PATH_DEFAULT))
    parser.add_argument(
        "--max-pendientes", type=int, default=1,
        help="Máximo de franjas a reintentar en esta corrida (default: 1, evita vaciar toda la cola de una vez)",
    )
    args = parser.parse_args()

    db = Database(args.db)
    try:
        cliente_fb = ClienteMetaGraphAPI()
        cliente_ig = ClienteMetaGraphAPI()
        resultados = reintentar_publicaciones(
            db, cliente_fb=cliente_fb, cliente_ig=cliente_ig,
            max_intentos=_max_intentos(args.config_meta), max_pendientes=args.max_pendientes,
        )
    finally:
        db.close()

    if not resultados:
        print("No hay publicaciones pendientes de reintento.")
        return

    for resultado in resultados:
        print(f"Franja {resultado.fecha} {resultado.hora}: {resultado.resultado}")
        for red in resultado.redes:
            detalle = f" ({red.detalle})" if red.detalle else ""
            print(f"  - {red.red_social}: {red.estado}{detalle}")


if __name__ == "__main__":
    main()
