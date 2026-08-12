#!/usr/bin/env python3
import argparse

from motor_noticias.panel.server import iniciar_servidor
from motor_noticias.redaccion import crear_redactor


def main():
    parser = argparse.ArgumentParser(description="Panel de revisión — Ledesma Participa")
    parser.add_argument(
        "--redactor",
        choices=["mock", "ollama"],
        default=None,
        help=(
            "Override puntual del redactor a usar para la carga manual (mock u Ollama local). "
            "Si no se pasa, se usa config/redaccion.json → \"proveedor\"."
        ),
    )
    args = parser.parse_args()

    iniciar_servidor(redactor=crear_redactor(args.redactor))


if __name__ == "__main__":
    main()
