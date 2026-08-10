import argparse
from pathlib import Path

from .collectors.fixtures import FixtureCollector
from .db import Database
from .pipeline import ejecutar_pipeline
from .redaccion.mock import RedactorMock

DB_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "ledesma_participa.db"


def main():
    parser = argparse.ArgumentParser(description="Motor de noticias — Ledesma Participa (Fase 1)")
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Ruta a la base de datos SQLite")
    parser.add_argument("--fixtures", default=None, help="Ruta al archivo de noticias de prueba")
    args = parser.parse_args()

    db = Database(args.db)
    collector = FixtureCollector(args.fixtures) if args.fixtures else FixtureCollector()
    redactor = RedactorMock()

    resultados = ejecutar_pipeline(db, collector, redactor)

    print(f"Base de datos: {args.db}")
    print(f"Noticias procesadas: {len(resultados)}")
    for noticia, resultado in resultados:
        print(f"- [{resultado}] {noticia.titulo_original}")
        if resultado != "duplicado":
            print(
                f"    estado={noticia.estado} "
                f"relevancia={noticia.relevancia_local} motivo={noticia.motivo_relevancia}"
            )

    db.close()


if __name__ == "__main__":
    main()
