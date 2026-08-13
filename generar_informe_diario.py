#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.informe_diario import generar_informe_diario

DB_PATH_DEFAULT = Path(__file__).resolve().parent / "data" / "ledesma_participa.db"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Genera el informe diario de clima y dólar — Ledesma Participa"
    )
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Ruta a la base de datos SQLite")
    args = parser.parse_args()

    db = Database(args.db)
    try:
        resultado = generar_informe_diario(db)
    finally:
        db.close()

    if resultado.resultado == "preparada":
        print(f"Informe diario del {resultado.fecha_local} generado — noticia #{resultado.noticia_id} (pendiente).")
        return 0
    if resultado.resultado == "duplicado":
        print(f"El informe diario del {resultado.fecha_local} ya existía. No se duplicó.")
        return 0

    print(f"Error generando el informe diario del {resultado.fecha_local}: {resultado.mensaje_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
