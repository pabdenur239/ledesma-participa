"""Despliegue del sitio estático generado (`docs/`) al repositorio de
GitHub que sirve GitHub Pages.

`generar_sitio` (motor_noticias.sitio.generador) solo escribe archivos
locales: sin este paso, GitHub Pages nunca se entera de nada, porque sigue
sirviendo el último commit efectivamente empujado a `origin` — no lee el
disco de esta notebook. Este módulo hace exactamente ese último paso (git
add + commit + push, todo acotado a `docs/`) para que la regeneración
periódica del sitio realmente llegue al público, sin cambiar en nada el
hosting/arquitectura ya elegida (GitHub Pages sobre `docs/` en `main`)."""
import logging
import os
import subprocess
from pathlib import Path
from typing import NamedTuple, Optional

logger = logging.getLogger("motor_noticias.sitio.deploy")

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
RUTA_RELATIVA_SALIDA_DEFAULT = "docs"
RAMA_DEPLOY = "main"
TIMEOUT_GIT_SEGUNDOS = 60

# Identidad de commit dedicada para estas actualizaciones automáticas: no
# reutiliza la identidad de git configurada en la máquina (que puede ser la
# de una sesión de Claude Code o la del usuario) para que quede claro, en
# el propio historial, qué commits salieron solos y cuáles fueron manuales.
COMMIT_AUTOR_NOMBRE = "Ledesma Participa (automático)"
COMMIT_AUTOR_EMAIL = "ledesmaparticipa@gmail.com"


class ResultadoDeploy(NamedTuple):
    resultado: str  # "sin_cambios" | "desplegado" | "rama_incorrecta" | "error"
    detalle: Optional[str] = None


def _git(args, repo_root: Path, ejecutar):
    """Envoltorio único de todos los llamados a `git`: fuerza
    `GIT_TERMINAL_PROMPT=0` (nunca debe quedar colgado esperando una
    contraseña/2FA interactiva desde un proceso de fondo sin consola) y
    nunca deja escapar una excepción — timeout o `git` no encontrado se
    traducen al mismo `CompletedProcess` con código de error que ya
    manejan los llamadores."""
    entorno = dict(os.environ)
    entorno["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return ejecutar(
            ["git", "-C", str(repo_root), *args],
            capture_output=True, text=True, timeout=TIMEOUT_GIT_SEGUNDOS, env=entorno,
        )
    except (subprocess.TimeoutExpired, OSError) as error:
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr=str(error))


def _rama_actual(repo_root: Path, ejecutar) -> Optional[str]:
    resultado = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root, ejecutar)
    if resultado.returncode != 0:
        return None
    return resultado.stdout.strip()


def desplegar_sitio(
    repo_root: Optional[Path] = None,
    ruta_relativa_salida: str = RUTA_RELATIVA_SALIDA_DEFAULT,
    ejecutar=subprocess.run,
) -> ResultadoDeploy:
    """Publica en GitHub (git add + commit + push, acotado a
    `ruta_relativa_salida`) lo que `generar_sitio` ya escribió en el disco
    local. Idempotente: si no hay cambios reales en `docs/` desde el último
    despliegue, no crea un commit vacío. Solo despliega si el repo está
    parado en `RAMA_DEPLOY` (nunca crea una rama, nunca cambia de rama,
    nunca hace force-push): si alguien está trabajando en otra rama en esta
    misma notebook, este paso se queda quieto en vez de mezclar su propio
    commit automático con trabajo en curso.

    Un fallo (red caída, credenciales no configuradas, conflicto de push)
    se reporta como "error" sin lanzar ninguna excepción: los archivos
    locales de `docs/` de todos modos ya quedaron actualizados por
    `generar_sitio`, y un commit local que no llegó a empujarse queda
    esperando el próximo intento (no se pierde ni se descarta)."""
    repo_root = Path(repo_root or RAIZ_PROYECTO)

    rama = _rama_actual(repo_root, ejecutar)
    if rama != RAMA_DEPLOY:
        detalle = f"repo en rama '{rama}', no '{RAMA_DEPLOY}': no se despliega automáticamente."
        logger.warning(detalle)
        return ResultadoDeploy("rama_incorrecta", detalle)

    resultado_add = _git(["add", "--", ruta_relativa_salida], repo_root, ejecutar)
    if resultado_add.returncode != 0:
        detalle = f"git add falló: {resultado_add.stderr.strip()}"
        logger.error(detalle)
        return ResultadoDeploy("error", detalle)

    resultado_diff = _git(["diff", "--cached", "--quiet", "--", ruta_relativa_salida], repo_root, ejecutar)
    if resultado_diff.returncode == 0:
        return ResultadoDeploy("sin_cambios")

    resultado_commit = _git(
        [
            "-c", f"user.name={COMMIT_AUTOR_NOMBRE}",
            "-c", f"user.email={COMMIT_AUTOR_EMAIL}",
            "commit", "-m", "Actualizar sitio web automáticamente",
        ],
        repo_root, ejecutar,
    )
    if resultado_commit.returncode != 0:
        detalle = f"git commit falló: {resultado_commit.stderr.strip()}"
        logger.error(detalle)
        return ResultadoDeploy("error", detalle)

    resultado_push = _git(["push", "origin", RAMA_DEPLOY], repo_root, ejecutar)
    if resultado_push.returncode != 0:
        detalle = f"git push falló (el commit quedó local, se reintenta en el próximo ciclo): {resultado_push.stderr.strip()}"
        logger.error(detalle)
        return ResultadoDeploy("error", detalle)

    logger.info("Sitio desplegado a GitHub Pages (rama %s).", RAMA_DEPLOY)
    return ResultadoDeploy("desplegado")
