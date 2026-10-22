"""Programacion de videos: 2 ventanas diarias (~10:00 y ~19:00) + deteccion de urgentes + cola de revision.
NO publica nada: todo MP4 queda en estado pendiente_revision (ver cola_publicacion.py y publicador_meta_video.py).

Uso (desde la raiz del repo):
  python produccion_audiovisual/piloto_periodistas/programador_audiovisual.py tick            # una pasada (para cron/Tareas/systemd timer)
  python produccion_audiovisual/piloto_periodistas/programador_audiovisual.py loop --cada 300  # proceso continuo (local o VPS)
  ...  simular                                  # muestra que haria ahora, sin generar ni registrar nada
  ...  cola | aprobar ID | rechazar ID          # revision manual
Opciones de tick/loop: --sin-voz (prueba sin gastar ElevenLabs).
"""
import argparse
import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import cola_publicacion as cp  # noqa: E402

VENTANAS = {"programado_manana": (10, 0), "programado_tarde": (19, 0)}  # hora local Argentina
GRACIA_H = 3          # una ventana puede generarse hasta 3 h despues de su hora
MIN_SCORE = 40        # relevancia minima (scoring editorial del proyecto) para video programado
HORAS_PROGRAMADO = 36
HORAS_URGENTE = 6     # una urgencia vieja deja de ser urgente
MAX_ERRORES = 2       # reintentos de generacion por noticia/tipo

# ------------------------------------------------------------------ urgencia
# FUERTE: hecho grave/inmediato (vale tambien para toda la provincia). MEDIA: solo local/departamental.
URG_FUERTE = (r"choque fatal|accidente fatal|vuelco|choque (frontal|entre|en la)|choc[oó] |accidente (grave|de transito)|incendio|incendi[oó] |"
              r"siniestro vial|explosi[oó]n|derrumbe|inundaci|desborde|temporal|alerta (naranja|roja)|"
              r"corte (total )?de (la )?ruta|ruta (cortada|cortad[ao]s?|bloqueada)|"
              r"herid[oa]s? (grave|de gravedad)|grave estado|evacuaci|balacera|tiroteo|hecho de alto impacto")
URG_MEDIA = (r"alerta (amarilla|meteorol)|corte de (energ[ií]a|luz|agua|gas) (imprevisto|masivo|total)|sin (luz|agua|energ[ií]a)|"
             r"falla (el[eé]ctrica|en el suministro)|interrupci[oó]n del (servicio|suministro)|corte (de calle|vial)|calle cortada|"
             r"cortes? de tr[aá]nsito|rescate|operativo de emergencia|asalto|robo (violento|a mano armada)|decreto de emergencia|"
             r"emergencia (h[ií]drica|sanitaria|clim)|suspenden (las )?clases")
URG_GRAVE = (r"fatal|grave|muri[oó]|fallec|incendio|explosi[oó]n|derrumbe|inundaci|desborde|temporal|alerta (naranja|roja)|"
             r"corte (total )?de (la )?ruta|ruta (cortada|bloqueada)|evacuaci|balacera|tiroteo|v[ií]ctimas? m[uú]ltiples|m[uú]ltiples v[ií]ctimas")
URG_NO = (r"tareas (programadas|de mantenimiento)|mantenimiento|programad[oa]s?|cronograma|opini[oó]n|columna|declar|dijo|afirm|"
          r"balotaje|campa[nñ]a|candidat|elecciones|torneo|liga|ni(ñ|n)[oa]s?\b|menor(es)?\b|desaparec|abus|femicid|"
          r"promoci|sorteo|descuento|espect[aá]culo|show|recital|festival|homenaje|aniversario|capacitaci|inaugur|celebr[ae]")


def _norm(t):
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def evaluar_urgencia(n, ahora_=None):
    """-> (es_urgente, motivo). Estricto: hecho concreto + reciente + territorio prioritario (o hecho fuerte provincial)."""
    ahora_ = ahora_ or cp.ahora()
    texto = _norm(n["titulo"] + ". " + (n.get("bajada") or ""))
    try:
        edad = ahora_ - datetime.fromisoformat(n["fecha_iso"])
    except Exception:
        return False, "sin fecha valida"
    if edad > timedelta(hours=HORAS_URGENTE):
        return False, f"antigua ({int(edad.total_seconds() // 3600)} h)"
    terr = n.get("territorio")
    if terr not in ("local", "departamental", "provincial"):
        return False, f"territorio {terr}"
    if re.search(_norm(URG_NO), texto):
        return False, "tema rutinario/excluido"
    if terr == "provincial":  # fuera de Libertador/Ledesma solo hechos de gravedad explicita
        if re.search(_norm(URG_GRAVE), texto):
            return True, "hecho grave de alcance provincial"
        return False, "provincial sin gravedad explicita"
    if re.search(_norm(URG_FUERTE), texto):
        return True, f"hecho urgente fuerte ({terr})"
    if terr in ("local", "departamental") and re.search(_norm(URG_MEDIA), texto):
        return True, f"hecho urgente de alcance local ({terr})"
    return False, "sin hecho urgente"


def _riesgo(n):
    from motor_noticias.riesgo_editorial import evaluar_riesgo_editorial
    return evaluar_riesgo_editorial(n["titulo"], n.get("bajada") or "", None, None, n["fuente_nombre"])["requiere_revision_especial"]


def _prioridad(n):
    return {"local": 1, "departamental": 2, "provincial": 3}.get(n.get("territorio"), 4)


def _puntaje(n):
    from motor_noticias.scoring_editorial import evaluar_noticia
    reg = {"titulo_original": n["titulo"], "texto_original": n.get("bajada") or "", "titulo_preparado": n["titulo"],
           "texto_preparado": n.get("bajada") or "", "url_fuente": n.get("fuente_url"), "nombre_fuente": n["fuente_nombre"],
           "fecha_recoleccion": n["fecha_iso"], "localidad": n.get("localidad"), "territorio": n.get("territorio")}
    return evaluar_noticia(reg)["total"]


def _apta_basica(n):
    return bool(n.get("imagen") and (n.get("bajada") or "") and not n["fuente_nombre"].lower().startswith("ledesma participa"))


def detectar_urgente(noticias, reg=None, ahora_=None, puntaje=_puntaje):
    """Mejor noticia urgente aun no usada, o (None, motivo). Prioridad: Libertador > Ledesma > Jujuy; luego mas reciente."""
    ahora_ = ahora_ or cp.ahora()
    reg = cp.registro() if reg is None else reg
    cands = []
    for n in noticias:
        if not _apta_basica(n):
            continue
        ok, motivo = evaluar_urgencia(n, ahora_)
        if not ok or cp.es_duplicado(n, reg, ahora_=ahora_)[0] or _riesgo(n):
            continue
        cands.append((n, motivo))
    if not cands:
        return None, "sin urgencias nuevas"
    cands.sort(key=lambda x: (_prioridad(x[0]), -datetime.fromisoformat(x[0]["fecha_iso"]).timestamp()))
    return cands[0]


def seleccionar_programada(noticias, reg=None, ahora_=None, puntaje=_puntaje, minimo=MIN_SCORE):
    """UNA noticia apta y relevante para la ventana; (None, motivo) si no hay una suficientemente relevante."""
    from seleccion_editorial import EXCLUIR
    ahora_ = ahora_ or cp.ahora()
    reg = cp.registro() if reg is None else reg
    lim = ahora_ - timedelta(hours=HORAS_PROGRAMADO)
    cands = []
    for n in noticias:
        if not _apta_basica(n) or datetime.fromisoformat(n["fecha_iso"]) < lim or cp.es_duplicado(n, reg, ahora_=ahora_)[0]:
            continue
        if re.search(EXCLUIR, (n["titulo"] + " " + n["bajada"]).lower()) or _riesgo(n):
            continue
        n["_total"] = puntaje(n)
        if n["_total"] >= minimo and _prioridad(n) <= 3:  # "resto" solo si corresponde: no se produce por defecto
            cands.append(n)
    if not cands:
        return None, f"ninguna noticia con puntaje >= {minimo} y alcance Jujuy/Ledesma/Libertador"
    cands.sort(key=lambda n: (_prioridad(n), -n["_total"]))
    n = cands[0]
    return n, f"prioridad {_prioridad(n)} ({n.get('territorio')}), puntaje {n['_total']}, {len(cands)} candidatas"


# ------------------------------------------------------------------ texto para redes
def _hashtag(t):
    return "#" + "".join(w.capitalize() for w in re.findall(r"[A-Za-z0-9]+", _norm(t)))


def texto_redes(n, urgente=False):
    """(texto, hashtags). Solo datos de la propia nota; urgentes: mas corto y directo."""
    bajada = re.sub(r"\s+", " ", n.get("bajada") or "").strip()
    frases = [f for f in re.split(r"(?<=[.!?])\s+", bajada) if f and not f.endswith(("…", "..."))]  # sin frases cortadas por la fuente
    ctx, tope = [], (150 if urgente else 260)
    for f in frases[:1 if urgente else 2]:
        if len(" ".join(ctx + [f])) <= tope:
            ctx.append(f)
    if not ctx and bajada:
        ctx = [bajada[:tope].rsplit(" ", 1)[0].rstrip(",;:") + "…"]
    tags = ["#LedesmaParticipa", "#Jujuy"] + (["#Urgente"] if urgente else [])
    loc = (n.get("localidad") or "").strip()
    if n.get("territorio") == "local" or "libertador" in loc.lower():
        tags.append("#LibertadorGeneralSanMartin")
    if n.get("territorio") in ("local", "departamental"):
        tags.append("#DepartamentoLedesma")
    if loc and "libertador" not in loc.lower() and _hashtag(loc) not in tags and loc.lower() not in ("jujuy",):
        tags.append(_hashtag(loc))
    cat = _norm(n.get("categoria_etiqueta") or "")
    texto_busq = _norm(n["titulo"])
    for pat, tag in ((r"polic|robo|asalto", "#Policiales"), (r"choque|accidente|vuelco|ruta", "#Transito"), (r"alerta|clima|viento|lluvia|tormenta", "#Clima"),
                     (r"energ|luz|agua|corte", "#Servicios"), (r"deporte|torneo|futbol", "#Deportes"), (r"incendio", "#Emergencias")):
        if re.search(pat, cat + " " + texto_busq) and tag not in tags:
            tags.append(tag)
    partes = [n["titulo"].strip().rstrip(".")] + ([" ".join(ctx)] if ctx else [])
    if n.get("fuente_nombre"):
        partes.append(f"Fuente: {n['fuente_nombre']}.")
    partes.append("Más información en ledesmaparticipa.com.ar")
    return "\n\n".join(partes), tags[:7]


# ------------------------------------------------------------------ generacion
def producir(n, tipo, sin_voz=False):
    """Genera el MP4 llamando al pipeline aprobado (producir_automatico.py). Devuelve la ruta del MP4."""
    cmd = [sys.executable, "-X", "utf8", str(AQUI / "producir_automatico.py"), "--id", str(n["id"]),
           "--max-palabras", "100" if tipo == "urgente" else "62"] + (["--sin-voz"] if sin_voz else [])
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    m = re.search(r"MP4:\s*(.+\.mp4)", r.stdout)
    if r.returncode == 3:  # guion rechazado por validacion_guion: no se genera ni se publica
        raise RuntimeError("guion_invalido: " + (re.search(r"GUION_INVALIDO:\s*(.+)", r.stdout) or [0, "sin detalle"])[1][:350])
    if r.returncode != 0 or not m:
        raise RuntimeError((r.stderr or r.stdout)[-400:] or "fallo la generacion")
    return Path(m.group(1).strip())


def _presentador_categoria(n):
    import mezcla_musical as mm
    import seleccion_editorial as se
    return se.presentador_para(n), mm.categoria_musical(n)


def _errores(n, tipo):
    return sum(1 for it in cp.cola() if it["noticia_id"] == n["id"] and it["tipo"] == tipo and it["estado"] == "error")


def procesar(n, tipo, sin_voz=False, generar=producir, log=print):
    """Genera, encola en pendiente_revision y registra el uso. No publica."""
    if _errores(n, tipo) >= MAX_ERRORES:
        log(f"  omitida {n['id']}: {MAX_ERRORES} errores previos")
        return None
    dup, motivo_dup = cp.es_duplicado(n)
    if dup:  # ultima barrera contra el registro unico compartido
        log(f"  omitida {n['id']}: omitida_por_duplicado ({motivo_dup})")
        try:
            from motor_noticias import registro_publicaciones as rp
            for red in ("facebook", "instagram"):
                rp.registrar(n["id"], n.get("fuente_url") or n.get("url"), n["titulo"], n.get("bajada"), "reel", red,
                             "omitida_por_duplicado", motivo=motivo_dup)
        except Exception:
            pass
        return None
    pres, cat = _presentador_categoria(n)
    texto, tags = texto_redes(n, urgente=tipo == "urgente")
    try:
        mp4 = generar(n, tipo, sin_voz)
    except Exception as e:  # queda en la cola como error; la noticia NO se marca como usada
        log(f"  ERROR generando {n['id']}: {e}")
        return cp.encolar(n, tipo, pres, None, texto, tags, cat, estado="error", error=str(e)[:400])
    cp.registrar_uso(n, tipo)
    import publicador_meta_video as pm
    if not pm.config()["publicacion_automatica"]:  # modo seguro: sin publicacion automatica queda para revision
        it = cp.encolar(n, tipo, pres, mp4, texto, tags, cat, estado="pendiente_revision")
        log(f"  OK {tipo}: noticia {n['id']} -> {mp4} [pendiente_revision]")
        return it
    it = cp.encolar(n, tipo, pres, mp4, texto, tags, cat, estado="generado")
    cp.cambiar_estado(it["id"], "aprobado", "automatico")
    log(f"  OK {tipo}: noticia {n['id']} -> {mp4} [aprobado, publicando]")
    try:
        return pm.publicar(it["id"], log=log)
    except Exception as e:
        log(f"  ERROR publicando {it['id']}: {pm.redactar(e)}")
        cp.cambiar_estado(it["id"], "error", pm.redactar(e))
        return it


def ventana_vigente(ahora_):
    """Tipo de ventana programada abierta ahora (hora local) o None."""
    for tipo, (h, m) in VENTANAS.items():
        ini = ahora_.replace(hour=h, minute=m, second=0, microsecond=0)
        if ini <= ahora_ < ini + timedelta(hours=GRACIA_H):
            return tipo
    return None


def ya_hecha_hoy(tipo, ahora_):
    return any(r["tipo"] == tipo and r["fecha_hora"][:10] == ahora_.date().isoformat() for r in cp.registro())


def tick(noticias=None, ahora_=None, sin_voz=False, generar=producir, log=print, simular=False):
    """Una pasada: urgentes primero (video adicional) y luego la ventana programada si corresponde."""
    ahora_ = ahora_ or cp.ahora()
    if noticias is None:
        import seleccion_editorial as se
        noticias = se.leer_portada()
    hechos = []
    if not simular:
        import publicador_meta_video as pm
        try:
            pm.reintentar_pendientes(ahora_=ahora_, log=log)
        except Exception as e:
            log(f"  ERROR en reintentos: {pm.redactar(e)}")
    n, motivo = detectar_urgente(noticias, ahora_=ahora_)
    log(f"[{ahora_:%Y-%m-%d %H:%M}] urgente: {('noticia ' + str(n['id']) + ' - ' + motivo) if n else motivo}")
    if n and not simular:
        hechos.append(procesar(n, "urgente", sin_voz, generar, log))
    tipo = ventana_vigente(ahora_)
    if tipo and not ya_hecha_hoy(tipo, ahora_):
        n, motivo = seleccionar_programada(noticias, ahora_=ahora_)
        log(f"  ventana {tipo}: {('noticia ' + str(n['id']) + ' - ' + motivo) if n else 'sin video (' + motivo + ')'}")
        if n and not simular:
            hechos.append(procesar(n, tipo, sin_voz, generar, log))
    elif tipo:
        log(f"  ventana {tipo}: ya generada hoy")
    return [h for h in hechos if h]


def _log_a_archivo():
    """stdout/stderr -> salidas/cola/logs/programador.log (rotado por tamano); mensajes sin secretos."""
    import publicador_meta_video as pm
    d = cp.carpeta() / "logs"
    d.mkdir(exist_ok=True)
    ruta = d / "programador.log"
    if ruta.exists() and ruta.stat().st_size > 2_000_000:
        ruta.replace(d / "programador.log.1")

    class Salida:
        def __init__(self):
            self.f = open(ruta, "a", encoding="utf-8", buffering=1)

        def write(self, t):
            if t.strip():
                self.f.write(f"{cp.ahora():%Y-%m-%d %H:%M:%S} {pm.redactar(t.rstrip())}\n")
            return len(t)

        def flush(self):
            self.f.flush()

    sys.stdout = sys.stderr = Salida()


def _tomar_lock():
    """Una sola instancia: archivo con pid; se ignora si ese proceso ya no existe."""
    lock = cp.carpeta() / "programador.lock"
    try:
        pid = int(lock.read_text())
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, errors="replace")
        if pid != os.getpid() and str(pid) in r.stdout:
            return False
    except Exception:
        pass
    lock.write_text(str(os.getpid()))
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["tick", "loop", "simular", "cola", "aprobar", "rechazar"])
    ap.add_argument("id", nargs="?")
    ap.add_argument("--cada", type=int, default=300, help="segundos entre pasadas (loop)")
    ap.add_argument("--sin-voz", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if a.cmd in ("tick", "loop"):
        _log_a_archivo()
    if a.cmd == "cola":
        for it in cp.cola():
            print(it["id"], it["estado"], it["tipo"], it["noticia_id"], it["presentador"], it["titulo"][:60], "|", it["ruta_mp4"])
    elif a.cmd in ("aprobar", "rechazar"):
        it = cp.cambiar_estado(a.id, "aprobado" if a.cmd == "aprobar" else "error", None if a.cmd == "aprobar" else "rechazado en revision")
        print(it["id"], "->", it["estado"])
    elif a.cmd == "simular":
        tick(simular=True)
    elif a.cmd == "tick":
        tick(sin_voz=a.sin_voz)
    else:
        if not _tomar_lock():
            print("Ya hay un programador corriendo; salgo.")
            return
        print(f"programador iniciado (pid {os.getpid()}), cada {a.cada}s", flush=True)
        while True:
            try:
                tick(sin_voz=a.sin_voz)
            except Exception as e:  # el loop no debe morir por un fallo de red puntual
                print("ERROR en la pasada:", e, flush=True)
            time.sleep(a.cada)


if __name__ == "__main__":
    main()
