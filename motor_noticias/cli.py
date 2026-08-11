import argparse
import sys
from pathlib import Path

from .collectors.fixtures import FixtureCollector
from .collectors.html_municipio_libertador import (
    ErrorRecoleccionHTML,
    MunicipioLibertadorHTMLCollector,
)
from .collectors.rss_prensa_jujuy import ErrorRecoleccionRSS, PrensaJujuyRSSCollector
from .db import Database
from .pipeline import ejecutar_pipeline
from .redaccion.mock import RedactorMock
from .redaccion.ollama import ErrorRedaccionOllama, RedactorOllama

DB_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "ledesma_participa.db"


def main():
    parser = argparse.ArgumentParser(description="Motor de noticias — Ledesma Participa (Fase 1)")
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Ruta a la base de datos SQLite")
    parser.add_argument(
        "--fuente",
        choices=["fixture", "rss-prensa-jujuy", "municipio-libertador"],
        default="fixture",
        help=(
            "Fuente a recolectar: datos de prueba locales (default), "
            "el RSS real de Prensa Jujuy, o la página real de actividades "
            "del Municipio Libertador"
        ),
    )
    parser.add_argument(
        "--fixtures", default=None, help="Ruta al archivo de noticias de prueba (solo con --fuente fixture)"
    )
    parser.add_argument(
        "--redactor",
        choices=["mock", "ollama"],
        default="mock",
        help="Redactor a usar: mock de prueba (default) u Ollama local",
    )
    args = parser.parse_args()

    db = Database(args.db)
    if args.fuente == "rss-prensa-jujuy":
        collector = PrensaJujuyRSSCollector()
    elif args.fuente == "municipio-libertador":
        collector = MunicipioLibertadorHTMLCollector()
    else:
        collector = FixtureCollector(args.fixtures) if args.fixtures else FixtureCollector()
    redactor = RedactorOllama() if args.redactor == "ollama" else RedactorMock()

    try:
        resultados = ejecutar_pipeline(db, collector, redactor)
    except (ErrorRecoleccionRSS, ErrorRecoleccionHTML) as error:
        db.close()
        print(f"Error al recolectar noticias: {error}", file=sys.stderr)
        sys.exit(1)
    except ErrorRedaccionOllama as error:
        db.close()
        print(f"Error al redactar noticias: {error}", file=sys.stderr)
        sys.exit(1)

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
