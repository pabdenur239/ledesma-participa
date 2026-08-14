#!/usr/bin/env python3
import argparse
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.meta.programacion import generar_placas_del_dia

DB_PATH_DEFAULT = Path(__file__).resolve().parent / "data" / "ledesma_participa.db"


def main():
    parser = argparse.ArgumentParser(
        description="Genera por adelantado las placas del día para Meta (y aprueba automáticamente "
        "el contenido apto) — Ledesma Participa"
    )
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Ruta a la base de datos SQLite")
    parser.add_argument(
        "--fecha", default=None, help="YYYY-MM-DD (default: hoy en America/Argentina/Jujuy)"
    )
    args = parser.parse_args()

    db = Database(args.db)
    try:
        resultados = generar_placas_del_dia(db, fecha=args.fecha)
    finally:
        db.close()

    if not resultados:
        print("No hay franjas con contenido programado todavía.")
        return

    for r in resultados:
        detalle = f" — {r.detalle}" if r.detalle else ""
        print(f"- [{r.hora}] noticia #{r.noticia_id}: {r.resultado}{detalle}")


if __name__ == "__main__":
    main()
