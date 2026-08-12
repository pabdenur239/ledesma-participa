import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from .ciclo_continuo import INTERVALO_SEGUNDOS_DEFAULT, ejecutar_ciclo
from .db import Database
from .redaccion import crear_redactor

DB_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "ledesma_participa.db"
LOCK_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "run_continuo.lock"
LOG_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "logs" / "run_continuo.log"

logger = logging.getLogger("motor_noticias.continuo")


class InstanciaEnEjecucion(RuntimeError):
    """Ya existe un lock activo: hay (o hubo) otra instancia corriendo."""


def tomar_lock(lock_path: Path) -> None:
    """Mecanismo simple y portable (sin fcntl/msvcrt) para evitar dos
    instancias simultáneas: crea el archivo de forma exclusiva y falla si ya
    existe. No detecta automáticamente locks de procesos que ya terminaron
    (best effort, ver mensaje de error)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise InstanciaEnEjecucion(
            f"Ya existe un lock en {lock_path}. Si estás seguro de que no hay otra "
            "instancia de run_continuo.py activa, borrá ese archivo y volvé a intentar."
        ) from error
    with os.fdopen(fd, "w") as f:
        f.write(str(os.getpid()))


def liberar_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def configurar_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Motor continuo de noticias — Ledesma Participa")
    parser.add_argument("--db", default=str(DB_PATH_DEFAULT), help="Ruta a la base de datos SQLite")
    parser.add_argument(
        "--intervalo",
        type=int,
        default=INTERVALO_SEGUNDOS_DEFAULT,
        help=f"Segundos entre ciclos (default: {INTERVALO_SEGUNDOS_DEFAULT})",
    )
    parser.add_argument(
        "--redactor",
        choices=["mock", "ollama"],
        default=None,
        help=(
            "Override puntual del redactor a usar (mock u Ollama local). "
            "Si no se pasa, se usa config/redaccion.json → \"proveedor\"."
        ),
    )
    parser.add_argument("--lock", default=str(LOCK_PATH_DEFAULT), help="Ruta al archivo de lock")
    parser.add_argument("--log", default=str(LOG_PATH_DEFAULT), help="Ruta al archivo de log")
    parser.add_argument(
        "--max-ciclos",
        type=int,
        default=None,
        help=argparse.SUPPRESS,  # uso interno para pruebas: detiene el bucle tras N ciclos
    )
    return parser


def bucle_continuo(
    db: Database,
    redactor,
    intervalo_segundos: int,
    max_ciclos: Optional[int] = None,
    dormir=time.sleep,
) -> None:
    """Ejecuta un ciclo inmediatamente y luego repite cada `intervalo_segundos`.
    `dormir` es inyectable para pruebas (evita esperas reales). Se detiene
    limpiamente ante KeyboardInterrupt (Ctrl+C) o, si `max_ciclos` está
    definido, luego de esa cantidad de ciclos."""
    ciclos_ejecutados = 0
    logger.info("Motor continuo iniciado. Intervalo: %d segundos.", intervalo_segundos)
    try:
        while True:
            logger.info("Iniciando ciclo de recolección...")
            resumen = ejecutar_ciclo(db, redactor, intervalo_segundos=intervalo_segundos)
            logger.info(
                "Ciclo completado: %d fuentes, %d noticias nuevas, %d errores.",
                len(resumen.resultados),
                resumen.total_noticias_nuevas,
                resumen.total_errores,
            )
            for resultado in resumen.resultados:
                if resultado.resultado == "error":
                    logger.warning(
                        "Fuente %s con error: %s", resultado.identificador, resultado.mensaje_error
                    )
            ciclos_ejecutados += 1
            if max_ciclos is not None and ciclos_ejecutados >= max_ciclos:
                logger.info("Alcanzada la cantidad máxima de ciclos configurada (%d). Deteniendo.", max_ciclos)
                return
            logger.info("Próximo ciclo en %d segundos.", intervalo_segundos)
            dormir(intervalo_segundos)
    except KeyboardInterrupt:
        logger.info("Interrupción recibida (Ctrl+C). Cerrando motor continuo...")


def main(argv=None) -> int:
    args = construir_parser().parse_args(argv)
    configurar_logging(Path(args.log))
    lock_path = Path(args.lock)

    try:
        tomar_lock(lock_path)
    except InstanciaEnEjecucion as error:
        logger.error(str(error))
        return 1

    redactor = crear_redactor(args.redactor)
    db = Database(args.db)
    try:
        bucle_continuo(db, redactor, args.intervalo, max_ciclos=args.max_ciclos)
    finally:
        db.close()
        liberar_lock(lock_path)
        logger.info("Motor continuo detenido limpiamente.")
    return 0
