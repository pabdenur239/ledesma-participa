#!/usr/bin/env python3
import argparse
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.motor_editorial import generar_agenda

DB_PATH_DEFAULT = Path(__file__).resolve().parent / "data" / "ledesma_participa.db"


def main():
    parser = argparse.ArgumentParser(
        description="Genera la agenda editorial en cascada — Ledesma Participa"
    )
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Ruta a la base de datos SQLite")
    parser.add_argument(
        "--fecha", default=None, help="YYYY-MM-DD (default: hoy en America/Argentina/Jujuy)"
    )
    args = parser.parse_args()

    db = Database(args.db)
    try:
        entradas = generar_agenda(db, fecha=args.fecha)
    finally:
        db.close()

    fecha_mostrada = entradas[0].fecha if entradas else args.fecha
    print(f"Agenda editorial — {fecha_mostrada}")
    for entrada in entradas:
        etiqueta = entrada.hora or "URGENTE"
        if entrada.noticia_id:
            print(
                f"- [{etiqueta}] ({entrada.territorio}) noticia #{entrada.noticia_id} — {entrada.estado}"
            )
        else:
            print(f"- [{etiqueta}] sin_candidato")


if __name__ == "__main__":
    main()
