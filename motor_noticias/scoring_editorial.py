"""Scoring editorial único (agregado 2/10/2026): una sola clasificación,
determinística y sin IA, que alimenta a la vez la selección de las franjas
programadas (`motor_editorial`), el circuito inmediato (`pipeline` marca
`urgente` y `motor_editorial.resolver_urgentes` lo confirma) y la
presentación visual roja de URGENTES (`meta/preparacion.py`).

Puntaje base 0–100 = impacto (0–25) + urgencia (0–20) + magnitud (0–20) +
relevancia para nuestra audiencia (0–15) + actualidad (0–10) + interés
potencial (0–10). El bonus territorial (Libertador +12, resto de Ledesma
+9, resto de Jujuy +5, nacional +0) se suma aparte: decide desempates y da
ventaja razonable en las franjas, nunca prioridad absoluta, y NO cuenta
para los umbrales de publicación inmediata.

Este módulo nunca relaja los filtros existentes: riesgo editorial
obligatorio, rechazo humano, deduplicación y antigüedad máxima se siguen
aplicando antes (en las consultas de `Database`) y siguen excluyendo una
noticia de cualquier circuito automático aunque su puntaje sea alto."""
import json
import re
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from .models import OrigenIngreso

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "config" / "scoring_editorial.json"

MAXIMOS = {"impacto": 25, "urgencia": 20, "magnitud": 20, "relevancia": 15, "actualidad": 10, "interes": 10}

# Base mínima de cualquier noticia periodística apta (ya pasó el gate de
# calidad de `elegibilidad_editorial`): sin señales, una nota igual tiene
# algún impacto, magnitud e interés mínimos.
BASE_SIN_SENALES = {"impacto": 4, "urgencia": 2, "magnitud": 3, "interes": 3}

CLASIFICACION_URGENTE = "urgente"
CLASIFICACION_IMPORTANTE = "importante"
CLASIFICACION_NORMAL = "normal"

# Solo noticias reales (automáticas o cargadas a mano desde el panel) pueden
# ser URGENTES: una reelaboración propia, la institucional o los resúmenes
# nunca son "último momento".
ORIGENES_QUE_PUEDEN_SER_URGENTES = (OrigenIngreso.AUTOMATICO.value, OrigenIngreso.MANUAL.value)

TERRITORIOS_LOCALES = ("local", "departamental")
TERRITORIOS_EXTRAORDINARIOS = ("provincial", "nacional")


def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in normalizado if not unicodedata.combining(c))


@lru_cache(maxsize=4)
def _cargar_config_cacheada(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cargar_config(path: Optional[Path] = None) -> dict:
    return _cargar_config_cacheada(str(path or CONFIG_PATH_DEFAULT))


@lru_cache(maxsize=2048)
def _patron(termino: str) -> "re.Pattern":
    """Palabra/frase completa; un "*" final la vuelve raíz ("evacu*" detecta
    "evacuados") y un " * " intermedio admite una palabra cualquiera ("hace *
    anos"). Bug evitado: sin límite final, "buscan a" disparaba dentro de
    "buscan acompañar"."""
    termino = _sin_acentos(termino).strip()
    raiz = termino.endswith("*")
    termino = termino.rstrip("*")
    cuerpo = r"\s+\w+\s+".join(re.escape(parte.strip()) for parte in termino.split(" * "))
    return re.compile(r"\b" + cuerpo + ("" if raiz else r"\b"))


def _menciona(texto_norm: str, termino: str) -> bool:
    return _patron(termino).search(texto_norm) is not None


def _menciona_alguno(texto_norm: str, terminos) -> bool:
    return any(_menciona(texto_norm, t) for t in terminos)


def _territorio_scoring(noticia: dict) -> str:
    territorio = noticia.get("territorio") or ""
    if territorio in ("local", "departamental", "provincial", "nacional"):
        return territorio
    if territorio == "internacional" or noticia.get("categoria_tematica") == "internacional":
        return "internacional"
    return "otro"


def _segmentos_url(url: Optional[str]) -> List[str]:
    if not url:
        return []
    return [_sin_acentos(seg) for seg in urlparse(url).path.split("/") if seg]


def detectar_tematica_no_urgente(noticia: dict, titulo_norm: str, cuerpo_norm: str, config: dict) -> Optional[str]:
    """Clase temática que nunca justifica salir de inmediato (deportes,
    cultura/espectáculos, turismo/promoción), usando toda la información
    disponible de la noticia y no una sola palabra: sección de la URL,
    `categoria_tematica`, título (1 término alcanza) y bajada (hacen falta
    2 términos distintos, para que una mención de pasada no la reclasifique).
    Bug real: fútbol, promoción turística y teatro locales salían como
    URGENTE con la regla anterior (toda local = urgente)."""
    tematicas = config["tematicas_no_urgentes"]
    segmentos = _segmentos_url(noticia.get("url_fuente"))
    for clase, secciones in tematicas["secciones_url"].items():
        if any(seg in secciones for seg in segmentos):
            return clase
    categoria = noticia.get("categoria_tematica")
    for clase, categorias in tematicas["categorias_tematicas"].items():
        if categoria in categorias:
            return clase
    for clase, terminos in tematicas["clases"].items():
        if _menciona_alguno(titulo_norm, terminos):
            return clase
        if sum(1 for t in set(terminos) if _menciona(cuerpo_norm, t)) >= 2:
            return clase
    return None


def _actualidad(fecha_recoleccion: Optional[str], ahora_utc: datetime) -> int:
    try:
        fecha = datetime.fromisoformat(fecha_recoleccion)
    except (TypeError, ValueError):
        return 0
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    horas = (ahora_utc - fecha).total_seconds() / 3600
    for limite, puntos in ((3, 10), (6, 8), (12, 6), (24, 4), (48, 2)):
        if horas <= limite:
            return puntos
    return 0


def evaluar_noticia(noticia: dict, ahora: Optional[datetime] = None, config: Optional[dict] = None) -> dict:
    """Evalúa una noticia (dict con las columnas de `noticias`) y devuelve
    los componentes, el puntaje base (0–100), el bonus territorial, el
    total (base + bonus), la clasificación (`urgente` | `importante` |
    `normal`) y el motivo legible."""
    config = config or cargar_config()
    ahora_utc = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    territorio = _territorio_scoring(noticia)

    titulo_norm = _sin_acentos(" ".join(
        noticia.get(campo) or "" for campo in ("titulo_original", "titulo_preparado")
    ))
    cuerpo_norm = _sin_acentos(" ".join(
        noticia.get(campo) or "" for campo in ("texto_original", "texto_preparado")
    ))

    # Señales en el TÍTULO: cuentan completas y son las únicas que pueden
    # volver URGENTE una noticia. Solo en el cuerpo: suman la mitad (un
    # cuerpo largo menciona de todo de pasada: "explosión de goles",
    # "simulacro de evacuación", un terremoto en otro país citado de fondo).
    en_titulo = [n for n, sen in config["senales"].items() if _menciona_alguno(titulo_norm, sen["terminos"])]
    en_cuerpo = [
        n for n, sen in config["senales"].items()
        if n not in en_titulo and _menciona_alguno(cuerpo_norm, sen["terminos"])
    ]
    if _menciona_alguno(titulo_norm, config["no_evento"]["terminos"]):
        en_titulo = []
    exclusiones = config.get("exclusiones_por_senal", {})
    en_titulo = [
        n for n in en_titulo
        if n.startswith("_") or not _menciona_alguno(titulo_norm, exclusiones.get(n, ()))
    ]
    contexto = {k: v for k, v in config.get("senales_que_requieren_contexto", {}).items() if not k.startswith("_")}
    todas = en_titulo + en_cuerpo
    en_titulo = [n for n in en_titulo if n not in contexto or any(r in todas for r in contexto[n])]
    en_cuerpo = [n for n in en_cuerpo if n not in contexto or any(r in todas for r in contexto[n])]

    # Título rutinario/protocolar ("se reunió", "acto", "visita"...): sus
    # señales cuentan como si estuvieran solo en el cuerpo (a la mitad) y
    # nunca vuelven URGENTE la noticia.
    es_rutina = _menciona_alguno(titulo_norm, config["rutina"]["terminos"])
    if es_rutina:
        en_cuerpo, en_titulo = en_titulo + en_cuerpo, []

    componentes = dict(BASE_SIN_SENALES)
    for nombre in en_titulo + en_cuerpo:
        senal = config["senales"][nombre]
        for comp in ("impacto", "urgencia", "magnitud", "interes"):
            valor = senal[comp]
            if nombre in en_cuerpo:
                valor = BASE_SIN_SENALES[comp] + (valor - BASE_SIN_SENALES[comp]) // 2
            componentes[comp] = max(componentes[comp], valor)

    negado = _menciona_alguno(titulo_norm, config["negadores_urgencia"]["terminos"]) or _menciona_alguno(
        titulo_norm, config["no_evento"]["terminos"]
    )
    fuertes = [] if negado else [s for s in en_titulo if s in config["senales_fuertes"]]
    if negado:
        componentes["urgencia"] = min(componentes["urgencia"], config["negadores_urgencia"]["tope_urgencia"])

    # Deportes / cultura / turismo: no son URGENTE salvo emergencia real en
    # el título (catástrofe, alerta severa, búsqueda de persona…).
    tematicas = config["tematicas_no_urgentes"]
    tematica = detectar_tematica_no_urgente(noticia, titulo_norm, cuerpo_norm, config)
    if tematica and not any(s in tematicas["excepciones_senales"] for s in fuertes):
        fuertes = []
        componentes["urgencia"] = min(componentes["urgencia"], tematicas["tope_urgencia"])
        componentes["impacto"] = min(componentes["impacto"], tematicas["tope_impacto"])
    rutina = config["rutina"]
    if es_rutina and not any(n in config["senales_fuertes"] for n in en_cuerpo):
        for comp in ("impacto", "urgencia", "magnitud", "interes"):
            componentes[comp] = min(componentes[comp], rutina[f"tope_{comp}"])

    relevancia = config["relevancia_audiencia"].get(territorio, config["relevancia_audiencia"]["otro"])
    alcance = config["alcance_masivo"]
    alcance_masivo = _menciona_alguno(titulo_norm, alcance["terminos"])
    if territorio in TERRITORIOS_EXTRAORDINARIOS:
        audiencia = config["senales_alcance_audiencia"]
        if any(s in audiencia[territorio] for s in en_titulo):
            relevancia += audiencia["relevancia_extra"]
        if alcance_masivo:
            relevancia += alcance["relevancia_extra"]
    if alcance_masivo:
        componentes["impacto"] += alcance["impacto_extra"]
    elif territorio not in ("local", "departamental", "provincial") and not any(
        s in config["senales_alcance_audiencia"]["nacional"] for s in en_titulo
    ):
        sin_alcance = config["sin_alcance_audiencia"]
        componentes["impacto"] = min(componentes["impacto"], sin_alcance["tope_impacto"])
        componentes["urgencia"] = min(componentes["urgencia"], sin_alcance["tope_urgencia"])
    senales_detectadas = en_titulo + [f"{n} (cuerpo)" for n in en_cuerpo]

    componentes["relevancia"] = relevancia
    componentes["actualidad"] = _actualidad(noticia.get("fecha_recoleccion"), ahora_utc)
    componentes = {k: min(v, MAXIMOS[k]) for k, v in componentes.items()}

    # Clima rutinario (pronóstico, estado del tiempo): nunca es candidata. Solo es
    # noticia el clima con alerta/impacto concreto en el título.
    clima = config.get("clima_rutinario") or {}
    clima_rutinario = bool(clima) and _menciona_alguno(titulo_norm, clima.get("terminos", ())) and not any(
        s in en_titulo for s in clima.get("senales_que_lo_vuelven_noticia", ())
    )
    temas = _temas_de(en_titulo, titulo_norm, config)

    base = sum(componentes.values())
    bonus = config["bonus_territorial"].get(territorio, 0)
    clasificacion, motivo = _clasificar(noticia, territorio, base, componentes, fuertes, es_rutina, config)

    return {
        **componentes,
        "territorio": territorio,
        "senales": senales_detectadas,
        "rutina": es_rutina and not fuertes,
        "clima_rutinario": clima_rutinario,
        "temas": temas,
        "tematica": tematica,
        "base": base,
        "bonus_territorial": bonus,
        "total": base + bonus,
        "clasificacion": clasificacion,
        "motivo": motivo,
    }


@lru_cache(maxsize=1)
def _terminos_jujuy() -> tuple:
    from .relevancia import cargar_config as cargar_localidades

    return tuple(cargar_localidades()["jujuy"])


def _titulo_en_jujuy(noticia: dict) -> bool:
    titulo = _sin_acentos(" ".join(noticia.get(c) or "" for c in ("titulo_original", "titulo_preparado")))
    return _menciona_alguno(titulo, _terminos_jujuy())


def _clasificar(noticia, territorio, base, componentes, fuertes, es_rutina, config):
    """URGENTE exige puntaje alto ANTES del bonus territorial Y urgencia
    temporal real (que esperar a la próxima franja le quite valor): ser
    local, policial, político o popular no alcanza por sí solo. Para
    provincial/nacional el umbral es todavía más alto (acontecimiento
    extraordinario: catástrofe, emergencia, decisión económica inmediata,
    resultado electoral, conmoción)."""
    u = config["umbrales"]
    puede_ser_urgente = (
        (noticia.get("origen_ingreso") or OrigenIngreso.AUTOMATICO.value) in ORIGENES_QUE_PUEDEN_SER_URGENTES
        # El informe diario de clima/dólar tiene su franja fija (07:30).
        and not (noticia.get("url_normalizada") or "").startswith("https://ledesma-participa.local/informe-diario/")
    )
    if puede_ser_urgente and territorio in TERRITORIOS_LOCALES:
        if base >= u["urgente_local"] and componentes["urgencia"] >= u["urgencia_minima_local"] and fuertes:
            return CLASIFICACION_URGENTE, (
                f"Local con relevancia suficiente para salir de inmediato ({', '.join(fuertes)})."
            )
    if puede_ser_urgente and territorio in TERRITORIOS_EXTRAORDINARIOS:
        # Una provincial solo puede ser extraordinaria si el TÍTULO la ubica
        # en Jujuy: una mención de pasada en el cuerpo no alcanza (bug real:
        # un terremoto en Colombia quedaba "provincial" y URGENTE).
        if territorio == "provincial" and not _titulo_en_jujuy(noticia):
            return (CLASIFICACION_IMPORTANTE, "Importante: provincial sin Jujuy en el título, no puede ser urgente.")                 if base >= u["importante"] else (CLASIFICACION_NORMAL, "Relevancia normal: compite en franja.")
        if (
            base >= u["urgente_extraordinaria"]
            and componentes["urgencia"] >= u["urgencia_minima_extraordinaria"]
            and componentes["relevancia"] >= u["relevancia_minima_extraordinaria"]
            and fuertes
        ):
            return CLASIFICACION_URGENTE, (
                f"Acontecimiento {territorio} extraordinario: esperar la franja perjudica el servicio ({', '.join(fuertes)})."
            )
    if base >= u["importante"]:
        return CLASIFICACION_IMPORTANTE, "Importante: compite con ventaja en las franjas, sin urgencia que justifique salir ya."
    if es_rutina and not fuertes:
        return CLASIFICACION_NORMAL, "Contenido institucional/rutinario: solo compite en franja."
    return CLASIFICACION_NORMAL, "Relevancia normal: compite en franja."


def urgente_confirmado(noticia: dict) -> bool:
    """¿Corresponde mostrar/tratar esta noticia como URGENTE? Requiere el
    flag `urgente` y, además, que la clasifique URGENTE el scoring evaluado
    al momento de su ingreso (o que un humano la haya tildado al cargarla a
    mano). Así el flag histórico de la regla anterior (toda local =
    urgente: fútbol, turismo, teatro…) deja de mostrarse como URGENTE en la
    app/sitio, sin modificar ningún dato guardado."""
    if not noticia.get("urgente"):
        return False
    if noticia.get("origen_ingreso") == OrigenIngreso.MANUAL.value:
        return True
    try:
        momento = datetime.fromisoformat(noticia.get("fecha_recoleccion") or "")
    except ValueError:
        momento = None
    return evaluar_noticia(noticia, momento)["clasificacion"] == CLASIFICACION_URGENTE


def es_urgente(noticia: dict, ahora: Optional[datetime] = None) -> bool:
    return evaluar_noticia(noticia, ahora)["clasificacion"] == CLASIFICACION_URGENTE


# ---------------------------------------------------------------------------
# Publicación inmediata NO urgente (16/10/2026) y repetición temática.
#
# URGENTE (rojo) sigue siendo la clasificación de `_clasificar`. La
# publicación inmediata es un escalón menor: una noticia local/departamental
# relevante, o una provincial/nacional/internacional muy importante, sale de
# inmediato (sin esperar la franja) con la identidad visual normal, no roja.
# ---------------------------------------------------------------------------


def _temas_de(en_titulo: list, titulo_norm: str, config: dict) -> List[str]:
    """Temas editoriales (corte, búsqueda de persona, bancario…) de una
    noticia, por señales o términos del TÍTULO: sirven para penalizar la
    repetición temática reciente."""
    temas = []
    for nombre, regla in (config.get("repeticion") or {}).get("temas", {}).items():
        if any(s in en_titulo for s in regla.get("senales", ())) or _menciona_alguno(
            titulo_norm, regla.get("terminos", ())
        ):
            temas.append(nombre)
    return temas


def es_inmediata(noticia: dict, evaluacion: dict, config: Optional[dict] = None) -> bool:
    """¿Corresponde publicarla de inmediato (sin esperar franja)? Local/
    departamental: base >= `inmediata_local`. Provincial/nacional/
    internacional: base >= `inmediata_extraordinaria` con urgencia mínima
    (y, si es provincial, con Jujuy en el título: mismo resguardo que el
    URGENTE). El bonus territorial no cuenta. Rutina y clima rutinario no."""
    config = config or cargar_config()
    u = config["umbrales"]
    if evaluacion.get("clima_rutinario") or evaluacion.get("rutina"):
        return False
    territorio = evaluacion["territorio"]
    if territorio in TERRITORIOS_LOCALES:
        return evaluacion["base"] >= u["inmediata_local"]
    if territorio == "provincial" and not _titulo_en_jujuy(noticia):
        return False
    return (
        evaluacion["base"] >= u["inmediata_extraordinaria"]
        and evaluacion["urgencia"] >= u["urgencia_minima_inmediata_extraordinaria"]
    )


def _tokens_titulo(noticia: dict) -> set:
    titulo = _sin_acentos(noticia.get("titulo_original") or noticia.get("titulo_preparado") or "")
    return {t for t in re.findall(r"[a-z0-9]{4,}", titulo)}


def penalizacion_repeticion(
    noticia: dict, evaluacion: dict, recientes: List[dict], ahora: Optional[datetime] = None,
    config: Optional[dict] = None, cache: Optional[dict] = None,
) -> int:
    """Puntos a restar al total por repetir tema (o ser casi igual a una nota
    de la misma fuente) respecto de lo ya publicado/agendado dentro de
    `ventana_horas`. Temporal y acotada (`tope_penalizacion`); una noticia
    con base >= `exenta_desde_base` no se penaliza: relevancia alta nunca se
    bloquea por repetición."""
    config = config or cargar_config()
    regla = config.get("repeticion") or {}
    if not regla or evaluacion["base"] >= regla.get("exenta_desde_base", 80):
        return 0
    ahora_utc = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    limite_horas = regla.get("ventana_horas", 8)
    cache = cache if cache is not None else {}
    mis_temas = set(evaluacion.get("temas") or ())
    mis_tokens = _tokens_titulo(noticia)
    coincidencias = 0
    for reciente in recientes:
        if reciente.get("id") == noticia.get("id"):
            continue
        try:
            fecha = datetime.fromisoformat(reciente.get("fecha_recoleccion") or "")
            if fecha.tzinfo is None:
                fecha = fecha.replace(tzinfo=timezone.utc)
            if (ahora_utc - fecha).total_seconds() / 3600 > limite_horas:
                continue
        except ValueError:
            continue
        rid = reciente.get("id")
        if rid not in cache:
            cache[rid] = set(evaluar_noticia(reciente, ahora_utc, config).get("temas") or ())
        if mis_temas & cache[rid]:
            coincidencias += 1
            continue
        misma_fuente = (reciente.get("nombre_fuente") or "") == (noticia.get("nombre_fuente") or "") != ""
        if misma_fuente and mis_tokens:
            otros = _tokens_titulo(reciente)
            union = mis_tokens | otros
            if union and len(mis_tokens & otros) / len(union) >= regla.get("similitud_titulo_misma_fuente", 0.5):
                coincidencias += 1
    return min(regla.get("tope_penalizacion", 20), coincidencias * regla.get("penalizacion_por_coincidencia", 10))
