#!/usr/bin/env python3
import argparse
from pathlib import Path

from motor_noticias.contenido_propio import generar_contenido_propio
from motor_noticias.db import Database

DB_PATH_DEFAULT = Path(__file__).resolve().parent / "data" / "ledesma_participa.db"


def main():
    parser = argparse.ArgumentParser(
        description="Genera notas de contenido propio (piloto) a partir de fuentes primarias oficiales "
        "— Ledesma Participa. Nunca publica: deja las notas 'preparada'/'pendiente' para el circuito "
        "normal de revisión y elegibilidad automática, igual que cualquier otra noticia."
    )
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Ruta a la base de datos SQLite")
    args = parser.parse_args()

    db = Database(args.db)
    try:
        resultados = generar_contenido_propio(db)
    finally:
        db.close()

    if not resultados:
        print("Contenido propio: ninguna nota nueva (sin candidatas o tope diario ya alcanzado).")
        return

    for resultado in resultados:
        print(f"- [{resultado.tipo}] {resultado.resultado} — {resultado.titulo}" + (
            f" (noticia #{resultado.noticia_id})" if resultado.noticia_id else ""
        ))


if __name__ == "__main__":
    main()
