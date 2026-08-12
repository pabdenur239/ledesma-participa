import argparse
import sys
from pathlib import Path

from .collectors.fixtures import FixtureCollector
from .collectors.html_infoyungas import ErrorRecoleccionInfoYungas, InfoYungasHTMLCollector
from .collectors.html_jujuyalmomento import (
    ErrorRecoleccionJujuyAlMomento,
    JujuyAlMomentoHTMLCollector,
)
from .collectors.html_municipio_libertador import (
    ErrorRecoleccionHTML,
    MunicipioLibertadorHTMLCollector,
)
from .collectors.html_tribuno_jujuy import ErrorRecoleccionTribunoJujuy, TribunoJujuyHTMLCollector
from .collectors.rss_infobae import ErrorRecoleccionInfobae, InfobaeRSSCollector
from .collectors.rss_lanacion import ErrorRecoleccionLaNacion, LaNacionRSSCollector
from .collectors.rss_prensa_jujuy import ErrorRecoleccionRSS, PrensaJujuyRSSCollector
from .collectors.rss_somosjujuy import ErrorRecoleccionSomosJujuy, SomosJujuyRSSCollector
from .collectors.rss_todojujuy import ErrorRecoleccionTodoJujuy, TodoJujuyRSSCollector
from .db import Database
from .pipeline import ejecutar_pipeline
from .redaccion import crear_redactor
from .redaccion.ollama import ErrorRedaccionOllama

DB_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "ledesma_participa.db"


def main():
    parser = argparse.ArgumentParser(description="Motor de noticias — Ledesma Participa (Fase 1)")
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Ruta a la base de datos SQLite")
    parser.add_argument(
        "--fuente",
        choices=[
            "fixture",
            "rss-prensa-jujuy",
            "municipio-libertador",
            "infoyungas",
            "jujuy-al-momento",
            "tribuno-jujuy",
            "todojujuy",
            "somos-jujuy",
            "la-nacion",
            "infobae",
        ],
        default="fixture",
        help=(
            "Fuente a recolectar: datos de prueba locales (default), "
            "el RSS real de Prensa Jujuy, la página real de actividades "
            "del Municipio Libertador, el listado real de InfoYungas, "
            "el listado real de Jujuy al Momento, el listado real de "
            "El Tribuno de Jujuy, el RSS real de TodoJujuy, el RSS "
            "real de Somos Jujuy, el RSS real de La Nación, o el RSS "
            "real de Infobae"
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
    elif args.fuente == "infoyungas":
        collector = InfoYungasHTMLCollector()
    elif args.fuente == "jujuy-al-momento":
        collector = JujuyAlMomentoHTMLCollector()
    elif args.fuente == "tribuno-jujuy":
        collector = TribunoJujuyHTMLCollector()
    elif args.fuente == "todojujuy":
        collector = TodoJujuyRSSCollector()
    elif args.fuente == "somos-jujuy":
        collector = SomosJujuyRSSCollector()
    elif args.fuente == "la-nacion":
        collector = LaNacionRSSCollector()
    elif args.fuente == "infobae":
        collector = InfobaeRSSCollector()
    else:
        collector = FixtureCollector(args.fixtures) if args.fixtures else FixtureCollector()
    redactor = crear_redactor(args.redactor)

    try:
        resultados = ejecutar_pipeline(db, collector, redactor)
    except (
        ErrorRecoleccionRSS,
        ErrorRecoleccionHTML,
        ErrorRecoleccionInfoYungas,
        ErrorRecoleccionJujuyAlMomento,
        ErrorRecoleccionTribunoJujuy,
        ErrorRecoleccionTodoJujuy,
        ErrorRecoleccionSomosJujuy,
        ErrorRecoleccionLaNacion,
        ErrorRecoleccionInfobae,
    ) as error:
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
