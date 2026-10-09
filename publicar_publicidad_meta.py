#!/usr/bin/env python3
"""Publica en Facebook e Instagram (feed + Story) la publicidad comercial
gratuita del día: 1 publicación ADICIONAL a las 18:00, rotando los
comercios de `config/publicidad.json`. Circuito independiente de las
franjas editoriales y de urgentes (ver motor_noticias/publicidad.py).

Solo actúa dentro de la ventana de la hora configurada (18:00-18:59): la
tarea programada se dispara varias veces en esa hora para reintentar una
red que haya fallado, nunca para duplicar una ya publicada. Fuera de la
ventana no hace nada (no se publica anticipadamente ni se recupera un día
ya pasado)."""
import argparse
import sys
from datetime import datetime

from motor_noticias.meta.cliente import ClienteMetaGraphAPI
from motor_noticias.motor_editorial import ZONA_JUJUY
from motor_noticias.publicidad import (
    DB_PATH_DEFAULT,
    DatabasePublicidad,
    cargar_config,
    publicar_publicidad_del_dia,
)


def _dentro_de_ventana(ahora, hora: str, ventana_minutos: int) -> bool:
    hh, mm = (int(x) for x in hora.split(":"))
    inicio = ahora.replace(hour=hh, minute=mm, second=0, microsecond=0)
    delta = (ahora - inicio).total_seconds() / 60
    return 0 <= delta <= ventana_minutos


def main() -> int:
    parser = argparse.ArgumentParser(description="Publicidad comercial diaria — Ledesma Participa")
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Base SQLite de publicidad comercial")
    parser.add_argument("--metricas", action="store_true", help="Solo mostrar métricas comerciales")
    args = parser.parse_args()

    db = DatabasePublicidad(args.db)
    try:
        if args.metricas:
            filas = db.metricas()
            if not filas:
                print("Sin publicaciones comerciales registradas todavía.")
            for f in filas:
                print(
                    f"{f['comercio_id']}: turnos={f['turnos']} facebook={f['facebook']} "
                    f"instagram={f['instagram']} story={f['instagram_story']} errores={f['errores']} "
                    f"ultima={f['ultima_fecha']}"
                )
            return 0

        config = cargar_config()
        ahora = datetime.now(ZONA_JUJUY)
        if not _dentro_de_ventana(ahora, config.get("hora", "18:00"), int(config.get("ventana_minutos", 59))):
            print("Fuera de la ventana de publicidad comercial. No se hace nada.")
            return 0

        fecha = ahora.strftime("%Y-%m-%d")
        resultado = publicar_publicidad_del_dia(
            db, fecha, cliente_fb=ClienteMetaGraphAPI(), cliente_ig=ClienteMetaGraphAPI(), config=config
        )
    finally:
        db.close()

    print(f"Publicidad comercial {resultado.fecha} ({resultado.comercio_id}): {resultado.resultado}")
    for red in resultado.redes:
        detalle = f" ({red.detalle})" if red.detalle else ""
        print(f"  - {red.red_social}: {red.estado}{detalle}")
    return 1 if any(r.estado == "error" for r in resultado.redes) else 0


if __name__ == "__main__":
    sys.exit(main())
