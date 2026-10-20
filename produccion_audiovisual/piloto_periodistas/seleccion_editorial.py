"""Seleccion automatica de UNA noticia desde la portada publica (solo lectura) + presentador + guion.

Fuente: https://ledesmaparticipa.com.ar/api/portada.json (JSON publico generado por el sitio; ya contiene
solo notas publicadas/vetadas). Se re-aplica scoring y riesgo editorial del proyecto. No escribe nada en el sitio.
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI.parents[1]))

import generar_noticia_presentador as gnp  # noqa: E402
import generar_piloto as gp  # noqa: E402
import generar_resumen_visual as g  # noqa: E402
import mezcla_musical as mm  # noqa: E402
from motor_noticias.riesgo_editorial import evaluar_riesgo_editorial  # noqa: E402
from motor_noticias.scoring_editorial import evaluar_noticia  # noqa: E402

PRIORIDAD_TERRITORIAL = {"local": 1, "departamental": 2, "provincial": 3}  # resto: 4 (solo si no hay nada mejor)
EXCLUIR = (r"se busca|buscan a|desaparec|paradero|extravi|menor(es)?\b|ni(?:ñ|n)[oa]s?\b|nene|adolescente|"
           r"beb[eé]|fallec|muri[oó]|muerte|abus|homicid|femicid|imputad|detenid|v[ií]ctima")
DURO = r"choque|accidente|vuelco|incendio|siniestro|robo|asalto|balacera|herid|operativo policial|rescate|explosi"
YA_PRODUCIDAS = AQUI / "salidas" / "producidas.json"


def leer_portada():
    d = json.loads(g._get(g.API))
    todas = {}
    for n in [d.get("principal")] + list(d.get("urgentes") or []) + [n for s in d["secciones"] for n in s["noticias"]]:
        if n and n.get("id") not in todas:
            todas[n["id"]] = n
    return list(todas.values())


def _producidas():
    try:
        return set(json.loads(YA_PRODUCIDAS.read_text(encoding="utf-8")))
    except Exception:
        return set()


def marcar_producida(nid):
    YA_PRODUCIDAS.parent.mkdir(parents=True, exist_ok=True)
    YA_PRODUCIDAS.write_text(json.dumps(sorted(_producidas() | {nid})), encoding="utf-8")


def seleccionar(horas=48, forzada=None):
    """Devuelve (noticia, motivo). Cascada Libertador -> Ledesma -> Jujuy -> resto; dentro del nivel, mayor puntaje."""
    lim = datetime.now(timezone.utc) - timedelta(hours=horas)
    hechas = _producidas()
    cands = []
    for n in leer_portada():
        if forzada and n["id"] != forzada:
            continue
        if not forzada:
            if n["id"] in hechas or datetime.fromisoformat(n["fecha_iso"]) < lim:
                continue
            if not n.get("imagen") or (n.get("bajada") or "") == "":
                continue
            if re.search(EXCLUIR, (n["titulo"] + " " + (n["bajada"] or "")).lower()):
                continue
            if evaluar_riesgo_editorial(n["titulo"], n["bajada"] or "", None, None, n["fuente_nombre"])["requiere_revision_especial"]:
                continue
            if n["fuente_nombre"].lower().startswith("ledesma participa"):
                continue  # agendas/resumenes propios: no son una noticia con hecho
        reg = {"titulo_original": n["titulo"], "texto_original": n["bajada"] or "", "titulo_preparado": n["titulo"],
               "texto_preparado": n["bajada"] or "", "url_fuente": n["fuente_url"], "nombre_fuente": n["fuente_nombre"],
               "fecha_recoleccion": n["fecha_iso"], "localidad": n.get("localidad"), "territorio": n.get("territorio")}
        n["_score"] = evaluar_noticia(reg)
        n["_total"] = n["_score"]["total"]
        n["_nivel"] = PRIORIDAD_TERRITORIAL.get(n.get("territorio"), 4)
        cands.append(n)
    if not cands:
        raise SystemExit("No hay noticia vigente apta en la portada publica.")
    cands.sort(key=lambda n: (n["_nivel"], -n["_total"]))
    n = cands[0]
    return n, f"nivel territorial {n['_nivel']} ({n.get('territorio')}), puntaje {n['_total']}, {len(cands)} candidatas aptas"


def imagenes_extra(n, maximo=2):
    """Otras imagenes de la propia nota (<img> con alt en nuestra pagina; las miniaturas de notas relacionadas no tienen alt)."""
    base = re.split(r"[?]|/v1/", n.get("imagen") or "")[0]
    try:
        h = g._get(n["url"]).decode("utf-8", "replace")
    except Exception:
        return []
    out = []
    for src, alt in re.findall(r'<img[^>]+src="([^"]+)"[^>]*alt="([^"]+)"', h):
        src = src.replace("&amp;", "&")
        if alt.strip() and re.split(r"[?]|/v1/", src)[0] != base and src not in out:
            out.append(src)
    return out[:maximo]


def presentador_para(n):
    """Mateo: policiales/accidentes/hechos duros (o categoria musical policial/urgente). Valentina: el resto."""
    texto = (n["titulo"] + " " + (n["bajada"] or "")).lower()
    if re.search(DURO, texto) or mm.categoria_musical(n) in ("policial", "urgente"):
        return "mateo"
    return "valentina"


def guion_automatico(n, max_palabras=62):
    """Locucion de 15-30 s armada SOLO con titulo y texto de la propia nota (sin agregar hechos)."""
    cuerpo = gnp.cuerpo_noticia(n)
    titulo = gp._limpiar(n["titulo"]).strip().rstrip(".")
    frases = [f.strip() for f in re.split(r"(?<=[.!?])\s+", gp._limpiar(cuerpo)) if f.strip()]
    cierre = "Ampliá la información en Ledesma Participa."
    out, pal = [], len(titulo.split()) + len(cierre.split())
    for f in frases:
        if not re.search(r"[.!?]$", f) or f.lower().rstrip(".") == titulo.lower():
            continue
        if pal + len(f.split()) > max_palabras:
            break
        out.append(f)
        pal += len(f.split())
    return f"{titulo}. " + " ".join(out) + (" " if out else "") + cierre, cuerpo


if __name__ == "__main__":
    n, motivo = seleccionar()
    pres = presentador_para(n)
    texto, _ = guion_automatico(n)
    print(n["id"], n["titulo"], "|", n["fuente_nombre"], "|", pres, "|", mm.categoria_musical(n), "|", motivo)
    print(texto)
