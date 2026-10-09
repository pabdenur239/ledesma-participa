#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.informe_diario import generar_informe_diario

DB_PATH_DEFAULT = Path(__file__).resolve().parent / "data" / "ledesma_participa.db"


def _informe_crecimiento(db) -> None:
    """Etapa 3: sección interna CRECIMIENTO LEDESMA PARTICIPA, en la misma
    tarea del Informe Diario (sin tarea programada nueva). Nunca se publica
    en redes y nunca afecta al informe de clima/dólar."""
    try:
        from motor_noticias.crecimiento import ejecutar

        print(f"Informe interno de crecimiento guardado en {ejecutar(db)}.")
    except Exception as error:  # noqa: BLE001 — la medición no puede romper el informe
        print(f"No se pudo generar el informe interno de crecimiento: {error}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Genera el informe diario de clima y dólar — Ledesma Participa"
    )
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Ruta a la base de datos SQLite")
    args = parser.parse_args()

    db = Database(args.db)
    try:
        resultado = generar_informe_diario(db)
        _informe_crecimiento(db)
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
