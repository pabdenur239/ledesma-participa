#!/usr/bin/env python3
import argparse
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.meta.programacion import generar_programacion_diaria

DB_PATH_DEFAULT = Path(__file__).resolve().parent / "data" / "ledesma_participa.db"


def main():
    parser = argparse.ArgumentParser(
        description="Genera la programación diaria de publicación en Meta (franjas fijas) — Ledesma Participa"
    )
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Ruta a la base de datos SQLite")
    parser.add_argument(
        "--fecha", default=None, help="YYYY-MM-DD (default: hoy en America/Argentina/Jujuy)"
    )
    args = parser.parse_args()

    db = Database(args.db)
    try:
        entradas = generar_programacion_diaria(db, fecha=args.fecha)
    finally:
        db.close()

    fecha_mostrada = entradas[0].fecha if entradas else args.fecha
    print(f"Programación de publicación en Meta — {fecha_mostrada}")
    for entrada in entradas:
        if entrada.noticia_id:
            print(
                f"- [{entrada.hora}] ({entrada.territorio}) noticia #{entrada.noticia_id} — {entrada.estado}"
            )
        else:
            print(f"- [{entrada.hora}] sin_candidato")


if __name__ == "__main__":
    main()
