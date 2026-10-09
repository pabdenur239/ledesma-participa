#!/usr/bin/env python3
"""Receptor de la medición propia y anónima de web/app (Etapa 3):
`motor_noticias.medicion`. Escucha solo en 127.0.0.1; la exposición pública
(HTTPS) la da un túnel aparte. Sin almacenamiento de IPs ni access log."""
import argparse
import logging

from motor_noticias.medicion import servir

ORIGENES_WEB = ("https://ledesmaparticipa.com.ar", "https://www.ledesmaparticipa.com.ar")


def main():
    parser = argparse.ArgumentParser(description="Medición agregada web/app — Ledesma Participa")
    parser.add_argument("--puerto", type=int, default=8010)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    servir(args.puerto, ORIGENES_WEB)


if __name__ == "__main__":
    main()
