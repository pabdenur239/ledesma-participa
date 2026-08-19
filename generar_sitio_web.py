#!/usr/bin/env python3
import argparse
from pathlib import Path

from motor_noticias.sitio.deploy import desplegar_sitio
from motor_noticias.sitio.generador import SALIDA_DEFAULT, deploy_automatico_habilitado, generar_sitio

DB_PATH_DEFAULT = Path(__file__).resolve().parent / "data" / "ledesma_participa.db"


def main():
    parser = argparse.ArgumentParser(
        description="Genera el sitio web público de Ledesma Participa (HTML estático) "
        "a partir de las noticias ya publicadas en la base de datos."
    )
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Ruta a la base de datos SQLite")
    parser.add_argument("--salida", default=str(SALIDA_DEFAULT), help="Directorio de salida (default: docs/)")
    parser.add_argument(
        "--base-url",
        default=None,
        help="URL base absoluta para OG/canonical/sitemap (default: config/sitio.json → base_url_produccion)",
    )
    args = parser.parse_args()

    resultado = generar_sitio(args.db, args.salida, base_url=args.base_url)
    print(f"Sitio generado en {resultado['salida_dir']}: {resultado['noticias']} noticias publicadas.")
    for slug, cantidad in sorted(resultado["secciones"].items()):
        print(f"  - {slug}: {cantidad}")

    if deploy_automatico_habilitado():
        resultado_deploy = desplegar_sitio()
        print(f"Deploy: {resultado_deploy.resultado}" + (f" ({resultado_deploy.detalle})" if resultado_deploy.detalle else ""))


if __name__ == "__main__":
    main()
