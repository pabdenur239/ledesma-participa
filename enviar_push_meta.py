#!/usr/bin/env python3
"""Envía notificaciones push reales (Firebase Cloud Messaging) para las
noticias locales/departamentales ya publicadas que califiquen como
urgente/importante real — nunca una por cada publicación. Pensado para
invocarse desde una tarea programada, separada de la publicación en Meta."""
import sys
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.push_notificaciones import CREDENCIAL_PATH_DEFAULT, enviar_push_pendientes

DB_PATH_DEFAULT = Path(__file__).resolve().parent / "data" / "ledesma_participa.db"


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Envía push reales (FCM) para urgentes/locales importantes — Ledesma Participa"
    )
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Ruta a la base de datos SQLite")
    parser.add_argument(
        "--credencial", default=str(CREDENCIAL_PATH_DEFAULT),
        help="Ruta al JSON de cuenta de servicio de Firebase Admin (fuera del repo)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Evalúa y muestra qué se enviaría, sin llamar a FCM ni marcar push_enviado_en",
    )
    parser.add_argument(
        "--forzar-noticia-id", type=int, default=None,
        help="Prueba controlada: evalúa/envía para una única noticia real ya publicada, "
        "aunque no esté en la ventana normal de candidatas",
    )
    args = parser.parse_args()

    db = Database(args.db)
    try:
        resultados = enviar_push_pendientes(
            db,
            credencial_path=Path(args.credencial),
            dry_run=args.dry_run,
            forzar_noticia_id=args.forzar_noticia_id,
        )
    finally:
        db.close()

    if not resultados:
        print("Sin candidatas para push en esta corrida.")
        return 0

    for resultado in resultados:
        detalle = f" (palabra clave: {resultado.palabra_clave})" if resultado.palabra_clave else ""
        error = f" — {resultado.mensaje_error}" if resultado.mensaje_error else ""
        print(f"Noticia #{resultado.noticia_id}: {resultado.resultado}{detalle}{error}")

    return 1 if any(r.resultado == "error" for r in resultados) else 0


if __name__ == "__main__":
    sys.exit(main())
