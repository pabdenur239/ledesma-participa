"""CRECIMIENTO LEDESMA PARTICIPA (Etapa 3): informe INTERNO diario de
medición, ranking de contenido y alertas.

Se genera dentro de la tarea existente del Informe Diario (07:30,
`generar_informe_diario.py`): no hay tarea programada nueva. Se guarda en
`data/informes/crecimiento_<fecha>.json` + `.txt` y lo muestra el panel
(/crecimiento). NUNCA se publica en redes.

Reglas:
- Solo métricas verificadas (API de Meta con los permisos actuales, la
  medición propia agregada y los datos de publicación confirmados). Lo que
  Meta no entrega figura como NO DISPONIBLE; nunca se estima.
- El ranking es informativo: no interviene en la selección editorial (la
  cascada territorial y el scoring editorial siguen decidiendo qué se
  publica). Una noticia local válida nunca desaparece por tener pocos
  clics: el contenido local tiene además su propio listado.
- Sin explicaciones algorítmicas inventadas: una alerta describe el dato,
  no su causa.
"""
import json
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import contenido_registro, metricas_meta
from .metricas_meta import NO_DISPONIBLE

DIRECTORIO_INFORMES = Path(__file__).resolve().parent.parent / "data" / "informes"
DIAS_VENTANA = 7

FRASE_ALCANCE_CERO = (
    "Existen publicaciones con alcance 0. La causa técnica/editorial todavía no está determinada "
    "y debe medirse antes de atribuirla."
)

# Prioridad territorial (1 Libertador … 5 Internacional): suma puntos fijos
# al ranking para que lo local no quede tapado solo por volumen de clics.
PUNTOS_TERRITORIO = {"local": 10, "departamental": 8, "provincial": 6, "nacional": 3, "internacional": 1}
PESOS_RANKING = {"interaccion": 40, "aperturas_web": 30, "clics_portada": 10, "recencia": 10}


def _valor(metrica: Optional[dict]):
    if not metrica or metrica.get("estado") != "DISPONIBLE":
        return None
    return metrica.get("valor")


def _texto_metrica(metrica: Optional[dict]) -> str:
    valor = _valor(metrica)
    return NO_DISPONIBLE if valor is None else str(valor)


def _variacion(actual, anterior) -> Optional[int]:
    if actual is None or anterior is None:
        return None
    return actual - anterior


def _snapshot_previo(fecha: date, directorio: Optional[Path]) -> tuple:
    """Snapshot de hace 7 días; si no existe, el más viejo dentro de la
    ventana (con su fecha, para no presentar como "7 días" lo que no es)."""
    for dias in range(DIAS_VENTANA, 0, -1):
        previa = (fecha - timedelta(days=dias)).isoformat()
        snapshot = metricas_meta.leer_snapshot(previa, directorio)
        if snapshot:
            return snapshot, previa
    return None, None


def _interacciones_ig(db, desde: str) -> dict:
    """meta_id de Instagram -> likes + comentarios de la última medición."""
    metricas_meta.asegurar_tabla(db)
    filas = db.conn.execute(
        "SELECT m.meta_id, m.likes, m.comentarios FROM metrica_publicacion m "
        "JOIN (SELECT meta_id, MAX(fecha_medicion) AS f FROM metrica_publicacion WHERE red_social = 'instagram' "
        "GROUP BY meta_id) u ON u.meta_id = m.meta_id AND u.f = m.fecha_medicion WHERE m.fecha_medicion >= ?",
        (desde,),
    ).fetchall()
    return {f["meta_id"]: (f["likes"] or 0) + (f["comentarios"] or 0) for f in filas if f["likes"] is not None}


def _alcance_por_publicacion(db, desde: str) -> dict:
    metricas_meta.asegurar_tabla(db)
    filas = db.conn.execute(
        "SELECT meta_id, alcance FROM metrica_publicacion WHERE fecha_medicion >= ? AND alcance IS NOT NULL", (desde,)
    ).fetchall()
    return {f["meta_id"]: f["alcance"] for f in filas}


def _titulo(db, noticia_id: int) -> str:
    n = db.obtener(noticia_id) or {}
    return (n.get("titulo_revisado") or n.get("titulo_preparado") or n.get("titulo_original") or "")[:120]


def ranking_contenido(contenidos: list, interacciones_ig: dict, web: dict, hoy: date) -> list:
    """Puntaje 0–100 transparente, solo con métricas verificadas:
    interacción IG (likes+comentarios), aperturas de la nota en web/app,
    clics desde la portada, recencia y prioridad territorial. Alcance de
    Meta: NO DISPONIBLE con los permisos actuales, por eso no pondera."""
    aperturas = web.get("article_open", {}).get("por_clave", {})
    clics = web.get("home_article_click", {}).get("por_clave", {})
    filas = []
    for c in contenidos:
        filas.append({
            "content_id": c["content_id"],
            "noticia_id": c["noticia_id"],
            "fecha": c["fecha"],
            "hora": c["hora"],
            "territorio": c["territorio"],
            "categoria": c["categoria"],
            "visual_format": c["visual_format"],
            "interaccion_ig": interacciones_ig.get(c.get("instagram_media_id")) if c.get("instagram_media_id") else None,
            "aperturas_web": aperturas.get(str(c["noticia_id"]), 0),
            "clics_portada": clics.get(str(c["noticia_id"]), 0),
        })
    maximos = {
        clave: max([f[clave] or 0 for f in filas] + [0]) for clave in ("interaccion_ig", "aperturas_web", "clics_portada")
    }
    for f in filas:
        puntaje = 0.0
        for clave, peso in (("interaccion_ig", "interaccion"), ("aperturas_web", "aperturas_web"), ("clics_portada", "clics_portada")):
            if maximos[clave]:
                puntaje += PESOS_RANKING[peso] * (f[clave] or 0) / maximos[clave]
        dias = max(0, (hoy - date.fromisoformat(f["fecha"])).days)
        puntaje += PESOS_RANKING["recencia"] * max(0.0, 1 - dias / DIAS_VENTANA)
        puntaje += PUNTOS_TERRITORIO.get(f["territorio"] or "", 0)
        f["puntaje"] = round(puntaje, 1)
    filas.sort(key=lambda f: (f["puntaje"], f["fecha"], f["hora"]), reverse=True)
    return filas


def detectar_alertas(ranking: list, alcances: dict, contenidos: list, publicaciones_por_dia: dict, web_ayer: int,
                     web_semana_promedio: Optional[float]) -> list:
    alertas = []
    # Alcance: solo si Meta entrega alcance por publicación.
    if alcances:
        valores = list(alcances.values())
        con_cero = [m for m, v in alcances.items() if v == 0]
        if len(con_cero) >= 2:
            alertas.append({"tipo": "alcance_cero", "detalle": FRASE_ALCANCE_CERO, "publicaciones": con_cero})
        if len(valores) >= 5:
            media, desvio = statistics.mean(valores), statistics.pstdev(valores)
            altos = [m for m, v in alcances.items() if desvio and v > media + 2 * desvio]
            if altos:
                alertas.append({"tipo": "alcance_alto", "detalle": "Publicaciones con alcance anormalmente alto.", "publicaciones": altos})
    else:
        alertas.append({
            "tipo": "alcance_no_evaluable",
            "detalle": "Alcance por publicación NO DISPONIBLE con los permisos actuales de Meta: no se evalúan alcance alto ni alcance 0.",
        })
    interacciones = [f["interaccion_ig"] for f in ranking if f["interaccion_ig"] is not None]
    if len(interacciones) >= 5:
        media, desvio = statistics.mean(interacciones), statistics.pstdev(interacciones)
        umbral = max(3, media + 2 * desvio)
        altos = [f for f in ranking if (f["interaccion_ig"] or 0) > umbral]
        if altos:
            alertas.append({
                "tipo": "interaccion_alta",
                "detalle": f"Interacción en Instagram (likes+comentarios) por encima de {umbral:.1f}.",
                "contenidos": [f["content_id"] for f in altos],
            })
    locales = [f for f in ranking if f["territorio"] in ("local", "departamental")
               and ((f["interaccion_ig"] or 0) > 0 or f["aperturas_web"] > 0)]
    if locales:
        alertas.append({"tipo": "local_destacado", "detalle": "Contenido local con mejor respuesta medida.",
                        "contenidos": [f["content_id"] for f in locales[:3]]})
    dias = sorted(publicaciones_por_dia)
    if len(dias) >= 4:
        ultimo = publicaciones_por_dia[dias[-1]]
        previos = [publicaciones_por_dia[d] for d in dias[:-1]]
        promedio = statistics.mean(previos)
        if promedio and ultimo < promedio * 0.5:
            alertas.append({"tipo": "caida_actividad",
                            "detalle": f"Publicaciones confirmadas ayer: {ultimo} (promedio previo {promedio:.1f})."})
    if web_semana_promedio and web_ayer < web_semana_promedio * 0.5:
        alertas.append({"tipo": "caida_web",
                        "detalle": f"Notas abiertas ayer: {web_ayer} (promedio de la semana {web_semana_promedio:.1f})."})
    return alertas


def _publicaciones_por_dia(db, desde: str, hasta: str) -> dict:
    filas = db.conn.execute(
        "SELECT fecha, COUNT(*) AS n FROM programacion_meta WHERE estado = 'publicado' AND red_social IN ('facebook', 'instagram') "
        "AND fecha >= ? AND fecha <= ? GROUP BY fecha", (desde, hasta),
    ).fetchall()
    return {f["fecha"]: f["n"] for f in filas}


def _totales_medicion(db_medicion, desde: str, hasta: str, origen: str) -> dict:
    if db_medicion is None:
        return {}
    return db_medicion.totales(desde, hasta, origen)


def _total(eventos: dict, nombre: str) -> int:
    return eventos.get(nombre, {}).get("total", 0)


def _top(eventos: dict, nombre: str, n: int = 5) -> list:
    por_clave = eventos.get(nombre, {}).get("por_clave", {})
    return sorted(por_clave.items(), key=lambda kv: kv[1], reverse=True)[:n]


def generar_informe(db, hoy: date, snapshot: dict, db_medicion=None, directorio_metricas: Optional[Path] = None,
                    medicion_activa: bool = False) -> dict:
    ayer = (hoy - timedelta(days=1)).isoformat()
    desde = (hoy - timedelta(days=DIAS_VENTANA)).isoformat()
    contenido_registro.sincronizar_historico(db, desde_fecha=desde)
    contenidos = contenido_registro.listar_con_plataformas(db, desde, ayer)
    for c in contenidos:
        c["titulo"] = _titulo(db, c["noticia_id"])

    previo, fecha_previa = _snapshot_previo(hoy, directorio_metricas)
    baseline = metricas_meta.leer_baseline(directorio_metricas)

    def bloque_red(red: str) -> dict:
        actual = snapshot.get(red, {})
        seguidores = _valor(actual.get("seguidores"))
        anterior = _valor((previo or {}).get(red, {}).get("seguidores")) if previo else None
        return {
            "seguidores": seguidores if seguidores is not None else NO_DISPONIBLE,
            "variacion": _variacion(seguidores, anterior) if anterior is not None else NO_DISPONIBLE,
            "variacion_desde": fecha_previa,
            "referencia_baseline_23_29_sep": (baseline or {}).get(red, {}).get("seguidores"),
            "metricas": {k: _texto_metrica(v) for k, v in actual.items() if isinstance(v, dict) and "estado" in v},
        }

    web = _totales_medicion(db_medicion, desde, ayer, "web")
    web_ayer = _totales_medicion(db_medicion, ayer, ayer, "web")
    app = _totales_medicion(db_medicion, desde, ayer, "app")
    interacciones = _interacciones_ig(db, desde)
    aperturas_totales = {"article_open": {"por_clave": {}}, "home_article_click": web.get("home_article_click", {})}
    for origen in (web, app):
        for clave, n in origen.get("article_open", {}).get("por_clave", {}).items():
            aperturas_totales["article_open"]["por_clave"][clave] = aperturas_totales["article_open"]["por_clave"].get(clave, 0) + n
    ranking = ranking_contenido(contenidos, interacciones, aperturas_totales, hoy)
    titulos = {c["content_id"]: c["titulo"] for c in contenidos}
    for f in ranking:
        f["titulo"] = titulos.get(f["content_id"], "")

    instagram = bloque_red("instagram")
    mejor_ig = next((f for f in ranking if f["interaccion_ig"]), None)
    instagram["mejor_contenido"] = (
        {"content_id": mejor_ig["content_id"], "titulo": mejor_ig["titulo"], "likes_mas_comentarios": mejor_ig["interaccion_ig"]}
        if mejor_ig else NO_DISPONIBLE
    )
    facebook = bloque_red("facebook")
    facebook["mejor_contenido"] = NO_DISPONIBLE  # sin métricas por publicación con los permisos actuales

    por_dia = _publicaciones_por_dia(db, desde, ayer)
    aperturas_por_dia = []
    if db_medicion is not None:
        for i in range(1, DIAS_VENTANA + 1):
            d = (hoy - timedelta(days=i)).isoformat()
            aperturas_por_dia.append(_total(db_medicion.totales(d, d, "web"), "article_open"))
    promedio_web = statistics.mean(aperturas_por_dia[1:]) if len(aperturas_por_dia) > 1 and any(aperturas_por_dia[1:]) else None

    formatos: dict = {}
    for c in contenidos:
        formatos[c["visual_format"]] = formatos.get(c["visual_format"], 0) + 1

    estado_medicion = "ACTIVA" if medicion_activa else "SIN ENDPOINT PÚBLICO (sin datos)"
    informe = {
        "fecha": hoy.isoformat(),
        "periodo": {"desde": desde, "hasta": ayer},
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "interno": True,
        "facebook": facebook,
        "instagram": instagram,
        "publicaciones": {
            "confirmadas_por_dia": por_dia,
            "contenidos_registrados": len(contenidos),
            "por_formato": formatos,
            "reel_candidatos": sum(1 for c in contenidos if c["reel_candidate"]),
            "titulares_con_alertas": sum(1 for c in contenidos if c.get("titular_alertas")),
        },
        "web": {
            "estado_medicion": estado_medicion,
            "notas_abiertas_ayer": _total(web_ayer, "article_open"),
            "notas_abiertas_7d": _total(web, "article_open"),
            "visitas_portada_7d": _total(web, "home_view"),
            "top5_notas": [{"noticia_id": k, "aperturas": v, "titulo": _titulo(db, int(k))} for k, v in _top(web, "article_open")
                           if k.isdigit()],
            "clics_sociales": {k: v for k, v in web.get("social_click", {}).get("por_clave", {}).items()},
            "cta_seguir": {k: v for k, v in web.get("follow_cta_click", {}).get("por_clave", {}).items()},
            "guia_comercial": {
                "vistas_guia": _total(web, "guia_open"),
                "vistas_ficha": _total(web, "commercial_view"),
                "clics_whatsapp": _total(web, "commercial_whatsapp_click"),
                "clics_instagram": _total(web, "commercial_instagram_click"),
                "promociones_abiertas": _total(web, "commercial_promo_open"),
            },
            "radios": {
                "seleccionada": dict(web.get("radio_select", {}).get("por_clave", {})),
                "play": _total(web, "radio_play"),
                "pausa": _total(web, "radio_pause"),
                "minutos_aprox": _total(web, "radio_listen_minutes"),
            },
            "videos": {"aperturas": _total(web, "video_open"), "reproducciones": NO_DISPONIBLE},
        },
        "app": {
            # La telemetría de la app llega recién con la próxima versión publicada.
            "estado_medicion": estado_medicion if app else f"{estado_medicion}; sin eventos (requiere nueva versión de la app)",
            "eventos_7d": {k: v["total"] for k, v in app.items()},
        },
        "ranking": ranking[:10],
        "contenido_local": [f for f in ranking if f["territorio"] in ("local", "departamental")][:10],
        "alertas": [],
    }
    alcances = _alcance_por_publicacion(db, desde)
    informe["alertas"] = detectar_alertas(
        ranking, alcances, contenidos, por_dia, informe["web"]["notas_abiertas_ayer"], promedio_web
    )
    return informe


def _linea_red(nombre: str, bloque: dict) -> list:
    variacion = bloque["variacion"]
    if isinstance(variacion, int):
        variacion = f"{variacion:+d} (desde {bloque['variacion_desde']})"
    lineas = [nombre, f"- seguidores: {bloque['seguidores']}", f"- variación: {variacion}"]
    for clave, valor in bloque["metricas"].items():
        if clave != "seguidores":
            lineas.append(f"- {clave.replace('_', ' ')}: {valor}")
    mejor = bloque.get("mejor_contenido")
    if isinstance(mejor, dict):
        mejor = f"{mejor['content_id']} — {mejor['titulo']} ({mejor['likes_mas_comentarios']} likes+comentarios)"
    lineas.append(f"- mejor contenido: {mejor}")
    if bloque.get("referencia_baseline_23_29_sep") is not None:
        lineas.append(f"- referencia histórica 23–29/09 (auditoría Meta): {bloque['referencia_baseline_23_29_sep']} seguidores")
    return lineas


def informe_texto(informe: dict) -> str:
    web = informe["web"]
    lineas = [
        f"CRECIMIENTO LEDESMA PARTICIPA — {informe['fecha']} (interno, no se publica)",
        f"Período: {informe['periodo']['desde']} a {informe['periodo']['hasta']}",
        "",
        *_linea_red("FACEBOOK", informe["facebook"]),
        "",
        *_linea_red("INSTAGRAM", informe["instagram"]),
        "",
        "PUBLICACIONES",
        f"- confirmadas por día (FB+IG): {informe['publicaciones']['confirmadas_por_dia']}",
        f"- contenidos con content_id: {informe['publicaciones']['contenidos_registrados']}",
        f"- por formato: {informe['publicaciones']['por_formato']}",
        f"- candidatos a Reel (no publicados): {informe['publicaciones']['reel_candidatos']}",
        f"- titulares con alertas de control: {informe['publicaciones']['titulares_con_alertas']}",
        "",
        f"WEB (medición: {web['estado_medicion']})",
        f"- notas abiertas ayer: {web['notas_abiertas_ayer']} · 7 días: {web['notas_abiertas_7d']}",
        f"- visitas a portada 7 días: {web['visitas_portada_7d']}",
        "- top 5: " + ("; ".join(f"#{t['noticia_id']} ({t['aperturas']}) {t['titulo'][:60]}" for t in web["top5_notas"]) or "sin datos"),
        f"- clics sociales: {web['clics_sociales'] or 'sin datos'} · CTA seguir: {web['cta_seguir'] or 'sin datos'}",
        f"- Guía Comercial: {web['guia_comercial']}",
        f"- Radios: {web['radios']}",
        f"- Videos: {web['videos']}",
        "",
        f"APP (medición: {informe['app']['estado_medicion']})",
        f"- eventos 7 días: {informe['app']['eventos_7d'] or 'sin datos'}",
        "",
        "RANKING INTERNO (informativo; no altera la selección editorial)",
    ]
    for f in informe["ranking"]:
        lineas.append(
            f"- {f['puntaje']:>5} {f['content_id']} [{f['territorio']}/{f['visual_format']}] "
            f"IG:{f['interaccion_ig'] if f['interaccion_ig'] is not None else 'N/D'} web:{f['aperturas_web']} — {f['titulo'][:70]}"
        )
    lineas += ["", "ALERTAS"]
    lineas += [f"- [{a['tipo']}] {a['detalle']}" for a in informe["alertas"]] or ["- ninguna"]
    return "\n".join(lineas) + "\n"


def guardar_informe(informe: dict, directorio: Optional[Path] = None) -> Path:
    directorio = Path(directorio or DIRECTORIO_INFORMES)
    directorio.mkdir(parents=True, exist_ok=True)
    base = directorio / f"crecimiento_{informe['fecha']}"
    base.with_suffix(".json").write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    base.with_suffix(".txt").write_text(informe_texto(informe), encoding="utf-8")
    return base.with_suffix(".json")


def ultimo_informe(directorio: Optional[Path] = None) -> Optional[dict]:
    archivos = sorted(Path(directorio or DIRECTORIO_INFORMES).glob("crecimiento_*.json"))
    if not archivos:
        return None
    try:
        return json.loads(archivos[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ejecutar(db, hoy: Optional[date] = None, medicion_db_path=None) -> Path:
    """Punto de entrada usado por la tarea del Informe Diario."""
    from .medicion import DB_PATH_DEFAULT as MEDICION_DB, AlmacenMedicion
    from .motor_editorial import ZONA_JUJUY
    from .sitio.generador import cargar_config_sitio

    hoy = hoy or datetime.now(ZONA_JUJUY).date()
    snapshot = metricas_meta.obtener_snapshot(db, hoy.isoformat())
    metricas_meta.guardar_snapshot(snapshot)
    ruta_medicion = Path(medicion_db_path or MEDICION_DB)
    almacen = AlmacenMedicion(ruta_medicion) if ruta_medicion.exists() else None
    try:
        informe = generar_informe(
            db, hoy, snapshot, almacen, medicion_activa=bool(cargar_config_sitio().get("medicion_endpoint"))
        )
    finally:
        if almacen is not None:
            almacen.close()
    return guardar_informe(informe)
