"""Registro UNICO de noticias publicadas en Meta, compartido por el sistema de imagenes/posts (motor_noticias.meta.publicador)
y el sistema audiovisual (produccion_audiovisual/piloto_periodistas: Reels).

Archivo JSON (escritura atomica + bloqueo): data/registro_publicaciones.json, o $LEDESMA_REGISTRO_PUBLICACIONES.
Ambos sistemas deben apuntar al MISMO archivo (misma maquina, o carpeta compartida/VPS).
Cada entrada: id, noticia_id, url (normalizada), titulo_norm, fecha_hora, formato (imagen|reel), plataforma (facebook|instagram),
estado (publicado|omitida_por_duplicado), actualiza_a (id de la entrada original si es una actualizacion), motivo, tokens.

Regla: antes de publicar, `evaluar(...)` busca la noticia por 1) noticia_id, 2) URL, 3) titulo normalizado. Si ya salio publicada
en cualquier formato/plataforma, es duplicado; solo se permite una actualizacion SUSTANCIAL comprobable (ver `es_actualizacion_sustancial`).
"""
import json
import os
import re
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .dedupe import es_mismo_contenido, normalizar_url, palabras_clave, refieren_a_hecho_distinto

RUTA_DEFECTO = Path(__file__).resolve().parent.parent / "data" / "registro_publicaciones.json"
VENTANA_HORAS = 24 * 7
TZ = timezone(timedelta(hours=-3))
MARCAS_ACTUALIZACION = re.compile(
    r"parte oficial|actualiz|confirm[oó]|confirmaron|nuevo balance|asciende|ascendi[oó]|se elev[oó]|trasladad|liberad|identific|"
    r"restablec|normaliz|reabri|levant[oó]|levantaron|suspendi[oó]|amplia|ampli[oó]|se registr[oó] un nuevo|estado de salud", re.I)
MIN_NUEVO = 0.4   # fraccion minima de palabras clave nuevas
MIN_NUEVAS_PALABRAS = 6
MIN_HORAS_ENTRE = 1


def ruta(base=None):
    """$LEDESMA_REGISTRO_PUBLICACIONES, o <carpeta de la base de datos>/registro_publicaciones.json (el sistema de imagenes lo
    deriva de su propia DB: en produccion es data/, igual que el default del sistema audiovisual), o data/ del repo."""
    return Path(os.environ.get("LEDESMA_REGISTRO_PUBLICACIONES") or (Path(base) / "registro_publicaciones.json" if base else RUTA_DEFECTO))


class _Bloqueo:
    def __init__(self, r):
        self.lock = r.with_suffix(".lock")

    def __enter__(self):
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        while True:
            try:
                os.close(os.open(self.lock, os.O_CREAT | os.O_EXCL))
                return self
            except FileExistsError:
                if time.time() - t0 > 10 or time.time() - self.lock.stat().st_mtime > 30:  # bloqueo viejo: se retoma
                    try:
                        self.lock.unlink()
                    except OSError:
                        pass
                time.sleep(0.05)

    def __exit__(self, *a):
        try:
            self.lock.unlink()
        except OSError:
            pass


def _leer(r=None):
    try:
        return json.loads((r or ruta()).read_text(encoding="utf-8"))
    except Exception:
        return []


def _guardar(datos, r=None):
    r = r or ruta()
    r.parent.mkdir(parents=True, exist_ok=True)
    tmp = r.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, r)


def entradas(base=None):
    return _leer(ruta(base))


def titulo_normalizado(t):
    t = unicodedata.normalize("NFD", (t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()


def _url(u):
    try:
        return normalizar_url(u) if u else None
    except Exception:
        return None


def _tokens(titulo, texto):
    return sorted(palabras_clave(f"{titulo or ''} {texto or ''}"))[:80]


def _ahora():
    return datetime.now(TZ)


def _reciente(e, ahora_, horas):
    try:
        return ahora_ - datetime.fromisoformat(e["fecha_hora"]) <= timedelta(hours=horas)
    except Exception:
        return True


def es_actualizacion_sustancial(nueva_tokens, nuevo_texto, previa, ahora_=None):
    """True solo si hay informacion NUEVA comprobable en el texto (no basta un titulo o redaccion distintos):
    al menos MIN_NUEVAS_PALABRAS palabras clave que no estaban y >= MIN_NUEVO del contenido, mas una marca explicita de
    actualizacion (parte oficial, cambio de estado, confirmacion, ampliacion...), y al menos MIN_HORAS_ENTRE horas despues."""
    ahora_ = ahora_ or _ahora()
    try:
        if ahora_ - datetime.fromisoformat(previa["fecha_hora"]) < timedelta(hours=MIN_HORAS_ENTRE):
            return False
    except Exception:
        return False
    previos = set(previa.get("tokens") or [])
    nuevas = set(nueva_tokens) - previos
    if not previos or len(nuevas) < MIN_NUEVAS_PALABRAS or len(nuevas) / max(len(set(nueva_tokens)), 1) < MIN_NUEVO:
        return False
    return bool(MARCAS_ACTUALIZACION.search(nuevo_texto or ""))


def evaluar(noticia_id, url, titulo, texto="", formato_propio=None, ahora_=None, entradas_=None, autorizadas=(), base=None):
    """-> {"duplicado": entrada|None, "motivo": str, "actualiza_a": id_entrada|None}.
    `formato_propio`: formato que se quiere publicar. Las entradas del MISMO noticia_id y MISMO formato se ignoran
    (son los reintentos idempotentes del propio sistema, que ya los resuelve por su cuenta)."""
    ahora_ = ahora_ or _ahora()
    datos = _leer(ruta(base)) if entradas_ is None else entradas_
    u, tn = _url(url), titulo_normalizado(titulo)
    pal = palabras_clave(titulo or "")
    toks = _tokens(titulo, texto)
    hallada, motivo = None, ""
    for e in datos:
        if e.get("estado") != "publicado" or not _reciente(e, ahora_, VENTANA_HORAS):
            continue
        if formato_propio and e["formato"] == formato_propio and e.get("noticia_id") == noticia_id:
            continue
        if noticia_id is not None and e.get("noticia_id") == noticia_id:
            hallada, motivo = e, "mismo ID"
        elif u and e.get("url") == u:
            hallada, motivo = e, "misma URL"
        elif len(tn.split()) >= 4 and (e.get("titulo_norm") == tn or (pal and es_mismo_contenido(pal, palabras_clave(e.get("titulo_norm", "")))
                                                   and not refieren_a_hecho_distinto(titulo or "", e.get("titulo_norm", "")))):
            hallada, motivo = e, "titulo normalizado"
        if hallada:
            break
    if not hallada:
        return {"duplicado": None, "motivo": "", "actualiza_a": None}
    if noticia_id in autorizadas or es_actualizacion_sustancial(toks, f"{titulo} {texto}", hallada, ahora_):
        return {"duplicado": None, "motivo": f"actualizacion de {hallada['id']}", "actualiza_a": hallada["id"]}
    return {"duplicado": hallada,
            "motivo": f"{motivo}: ya publicada como {hallada['formato']} en {hallada['plataforma']} ({hallada['fecha_hora'][:16]})",
            "actualiza_a": None}


def registrar(noticia_id, url, titulo, texto, formato, plataforma, estado="publicado", actualiza_a=None, motivo=None, ahora_=None, base=None):
    """Agrega una entrada (idempotente por noticia_id+formato+plataforma+estado). Devuelve su id."""
    assert formato in ("imagen", "reel") and plataforma in ("facebook", "instagram") and estado in ("publicado", "omitida_por_duplicado")
    r = ruta(base)
    with _Bloqueo(r):
        datos = _leer(r)
        for e in datos:
            if (e.get("noticia_id"), e["formato"], e["plataforma"], e["estado"]) == (noticia_id, formato, plataforma, estado) \
                    and (estado != "publicado" or e.get("actualiza_a") == actualiza_a):
                return e["id"]
        e = {"id": uuid.uuid4().hex[:12], "noticia_id": noticia_id, "url": _url(url), "titulo_norm": titulo_normalizado(titulo),
             "fecha_hora": (ahora_ or _ahora()).isoformat(timespec="seconds"), "formato": formato, "plataforma": plataforma,
             "estado": estado, "actualiza_a": actualiza_a, "motivo": motivo, "tokens": _tokens(titulo, texto)}
        datos.append(e)
        _guardar(datos, r)
        return e["id"]


def importar_desde_db(db_path, dias=7):
    base = Path(db_path).parent
    """Siembra el registro con lo ya publicado por el sistema de imagenes (tabla programacion_meta). Idempotente.
    Uso (en la maquina donde corre el motor): python -m motor_noticias.registro_publicaciones importar --db data/ledesma_participa.db"""
    import sqlite3
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    lim = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%d")
    n = 0
    for f in c.execute("SELECT p.noticia_id, p.red_social, p.publicada_en, p.fecha, p.estado, n.url_normalizada, n.titulo_original, n.texto_original "
                       "FROM programacion_meta p JOIN noticias n ON n.id = p.noticia_id "
                       "WHERE p.estado = 'publicado' AND p.red_social IN ('facebook','instagram') AND p.fecha >= ?", (lim,)):
        when = datetime.fromisoformat(f["publicada_en"]).astimezone(TZ) if f["publicada_en"] else None
        registrar(f["noticia_id"], f["url_normalizada"], f["titulo_original"], f["texto_original"], "imagen", f["red_social"], ahora_=when, base=base)
        n += 1
    return n


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["importar", "listar"])
    ap.add_argument("--db")
    a = ap.parse_args()
    if a.cmd == "importar":
        print("importadas:", importar_desde_db(a.db))
    else:
        for e in entradas():
            print(e["fecha_hora"][:16], e["formato"], e["plataforma"], e["estado"], e["noticia_id"], e["titulo_norm"][:60])
