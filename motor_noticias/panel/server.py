import base64
import html
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

from ..alertas import NIVEL_ERROR, calcular_alertas
from ..ciclo_continuo import NOMBRE_SALUD_AGENDA, agenda_automatica_habilitada
from ..continuo_runner import LOCK_PATH_DEFAULT
from ..db import Database
from ..ingreso_manual import ErrorIngresoManual, ResultadoIngresoManual, cargar_noticia_manual
from ..meta.preparacion import ErrorPreparacionFacebook, preparar_publicacion
from ..models import Estado, OrigenIngreso, RevisionEstado
from ..motor_editorial import HORARIOS_DEFAULT, ZONA_JUJUY
from ..redaccion import crear_redactor
from ..redaccion import _cargar_config_redaccion

# Timeout corto: /estado nunca debe quedar colgado esperando a Ollama.
TIMEOUT_ESTADO_OLLAMA_SEGUNDOS = 2

# El panel es exclusivamente local: se enlaza siempre a 127.0.0.1, nunca a
# 0.0.0.0 ni a una dirección configurable, para que no sea accesible desde
# fuera de esta máquina.
HOST = "127.0.0.1"
PORT = 8000

DB_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "ledesma_participa.db"

# Tope defensivo del cuerpo del POST de "Cargar noticia" (los límites reales
# por campo los valida `ingreso_manual`; esto solo evita leer un cuerpo
# arbitrariamente grande en memoria antes de llegar a esa validación).
LONGITUD_MAXIMA_CUERPO_POST_CARGA = 200_000

FILTROS_VALIDOS = ("pendientes", "aprobadas", "rechazadas", "todas")
FILTRO_A_REVISION_ESTADO = {
    "pendientes": RevisionEstado.PENDIENTE.value,
    "aprobadas": RevisionEstado.APROBADA.value,
    "rechazadas": RevisionEstado.RECHAZADA.value,
    "todas": None,
}


def _e(texto: Optional[str]) -> str:
    """Escapa contenido de la noticia antes de incrustarlo en HTML."""
    return html.escape(texto or "", quote=True)


def _pagina(titulo: str, cuerpo: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>{_e(titulo)}</title>
<style>
body {{ font-family: sans-serif; margin: 2rem; max-width: 900px; }}
.noticia {{ border: 1px solid #ccc; padding: 1rem; margin-bottom: 1rem; }}
.estado-pendiente {{ color: #b8860b; }}
.estado-aprobada {{ color: #2e7d32; }}
.estado-rechazada {{ color: #c62828; }}
.advertencia-riesgo {{
  color: #b71c1c; font-weight: bold; border: 2px solid #b71c1c;
  padding: 0.5rem; margin: 0.5rem 0; background: #fdecea;
}}
.modo-prueba {{
  color: #0d47a1; font-weight: bold; border: 2px solid #0d47a1;
  padding: 0.5rem; margin: 0.5rem 0; background: #e3f2fd;
}}
textarea {{ width: 100%; min-height: 6rem; }}
input[type=text] {{ width: 100%; box-sizing: border-box; }}
pre {{ white-space: pre-wrap; border: 1px solid #ccc; padding: 0.75rem; background: #fafafa; }}
.placa-preview {{ max-width: 100%; height: auto; border: 1px solid #ccc; }}
.imagen-original {{ max-width: 100%; border: 1px solid #ccc; }}
nav a {{ margin-right: 1rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }}
.indicador {{ display: inline-block; padding: 0.1rem 0.5rem; border-radius: 3px; font-weight: bold; color: #fff; }}
.indicador-ok {{ background: #2e7d32; }}
.indicador-advertencia {{ background: #b8860b; }}
.indicador-error {{ background: #c62828; }}
.alerta {{ padding: 0.5rem; margin-bottom: 0.5rem; border-radius: 3px; }}
.alerta-advertencia {{ background: #fff3cd; border: 1px solid #b8860b; }}
.alerta-error {{ background: #fdecea; border: 1px solid #c62828; }}
.etiqueta-urgente {{ background: #b71c1c; color: #fff; padding: 0.1rem 0.4rem; border-radius: 3px; font-weight: bold; }}
.etiqueta-manual {{ background: #6a1b9a; color: #fff; padding: 0.1rem 0.4rem; border-radius: 3px; font-weight: bold; }}
form.acciones-en-linea {{ display: inline; }}
form.acciones-en-linea button {{ margin-right: 0.3rem; }}
label {{ display: block; margin-top: 0.75rem; font-weight: bold; }}
.ayuda-campo {{ font-weight: normal; color: #555; font-size: 0.85em; }}
.error-formulario {{
  color: #c62828; font-weight: bold; border: 2px solid #c62828;
  padding: 0.5rem; margin: 0.5rem 0; background: #fdecea;
}}
.resultado-carga {{ border: 1px solid #ccc; padding: 1rem; margin: 1rem 0; }}
.acciones-resultado a {{
  display: inline-block; margin: 0.3rem 0.5rem 0.3rem 0; padding: 0.4rem 0.8rem;
  border: 1px solid #ccc; border-radius: 3px; text-decoration: none; color: inherit;
}}
</style>
</head>
<body>
<h1><a href="/" style="text-decoration:none;color:inherit;">Ledesma Participa — Panel de revisión</a></h1>
<nav><a href="/">Noticias</a> | <a href="/estado">Estado del sistema</a> | <a href="/agenda">Agenda Editorial</a> | <a href="/cargar-noticia">Cargar noticia</a></nav>
{cuerpo}
</body>
</html>"""


def _advertencia_riesgo(n: dict) -> str:
    if not n.get("requiere_revision_especial"):
        return ""
    return f"""<p class="advertencia-riesgo">
⚠ REVISIÓN POLÍTICA/INSTITUCIONAL OBLIGATORIA<br>
Categoría de riesgo: {_e(n.get('categoria_riesgo'))}<br>
Motivo: {_e(n.get('motivo_revision_especial'))}
</p>"""


def _enlace_facebook(n: dict) -> str:
    if n.get("revision_estado") != RevisionEstado.APROBADA.value:
        return ""
    return f'<p><a href="/facebook?id={n["id"]}">Preparar publicación Facebook (modo prueba)</a></p>'


def _etiqueta_manual(n: dict) -> str:
    if n.get("origen_ingreso") != OrigenIngreso.MANUAL.value:
        return ""
    return ' <span class="etiqueta-manual">MANUAL</span>'


def _tarjeta_noticia(n: dict) -> str:
    return f"""<div class="noticia">
{_advertencia_riesgo(n)}
<p><strong>Título original:</strong> {_e(n['titulo_original'])}{_etiqueta_manual(n)}</p>
<p><strong>Texto original:</strong> {_e(n['texto_original'])}</p>
<p><strong>Fuente:</strong> {_e(n['nombre_fuente'])} — <strong>Localidad:</strong> {_e(n['localidad'])}</p>
<p><strong>Título preparado:</strong> {_e(n['titulo_preparado'])}</p>
<p><strong>Texto preparado:</strong> {_e(n['texto_preparado'])}</p>
<p><strong>URL fuente:</strong> <a href="{_e(n['url_fuente'])}">{_e(n['url_fuente'])}</a></p>
<p><strong>Estado de revisión:</strong>
<span class="estado-{_e(n['revision_estado'])}">{_e(n['revision_estado'])}</span></p>
<p><a href="/noticia?id={n['id']}">Editar / aprobar / rechazar</a></p>
{_enlace_facebook(n)}
</div>"""


def _lista_html(db: Database, filtro: str) -> str:
    noticias = db.listar_preparadas(FILTRO_A_REVISION_ESTADO[filtro])
    nav = " | ".join(
        f"<strong>{f}</strong>" if f == filtro else f'<a href="/?filtro={f}">{f}</a>'
        for f in FILTROS_VALIDOS
    )
    if noticias:
        tarjetas = "\n".join(_tarjeta_noticia(n) for n in noticias)
    else:
        tarjetas = "<p>No hay noticias en este filtro.</p>"
    return _pagina("Panel de revisión — Ledesma Participa", f"<nav>{nav}</nav>\n{tarjetas}")


def _detalle_html(noticia: dict, mensaje: Optional[str] = None) -> str:
    aviso = f"<p><em>{_e(mensaje)}</em></p>" if mensaje else ""
    valor_titulo = noticia["titulo_revisado"] or noticia["titulo_preparado"] or ""
    valor_texto = noticia["texto_revisado"] or noticia["texto_preparado"] or ""
    cuerpo = f"""
{aviso}
{_advertencia_riesgo(noticia)}
<p><a href="/">&laquo; Volver al panel</a></p>
<h2>{_e(noticia['titulo_original'])}</h2>
<p><strong>Fuente:</strong> {_e(noticia['nombre_fuente'])}
— <strong>Localidad:</strong> {_e(noticia['localidad'])}</p>
<p><strong>URL fuente:</strong>
<a href="{_e(noticia['url_fuente'])}">{_e(noticia['url_fuente'])}</a></p>
<p><strong>Texto original:</strong></p>
<p>{_e(noticia['texto_original'])}</p>
<p><strong>Título preparado (IA):</strong> {_e(noticia['titulo_preparado'])}</p>
<p><strong>Texto preparado (IA):</strong> {_e(noticia['texto_preparado'])}</p>
<p><strong>Estado de revisión:</strong>
<span class="estado-{_e(noticia['revision_estado'])}">{_e(noticia['revision_estado'])}</span></p>

<form method="post" action="/noticia?id={noticia['id']}">
<label>Título revisado:<br>
<input type="text" name="titulo_revisado" value="{_e(valor_titulo)}"></label>
<br><br>
<label>Texto revisado:<br>
<textarea name="texto_revisado">{_e(valor_texto)}</textarea></label>
<br><br>
<button type="submit" name="accion" value="guardar">Guardar cambios</button>
<button type="submit" name="accion" value="aprobar">Aprobar</button>
<button type="submit" name="accion" value="rechazar">Rechazar</button>
</form>
{_enlace_facebook(noticia)}
"""
    return _pagina(f"Revisar noticia #{noticia['id']}", cuerpo)


def _seccion_imagen(contenido) -> str:
    if not contenido.imagen_url:
        return "<h3>Imagen</h3>\n<p><em>Sin imagen disponible.</em></p>"

    if contenido.imagen_generada_automaticamente:
        try:
            datos_png = Path(contenido.imagen_url).read_bytes()
            data_uri = "data:image/png;base64," + base64.b64encode(datos_png).decode("ascii")
        except OSError:
            data_uri = ""
        return f"""<h3>Imagen: placa generada automáticamente</h3>
<img class="placa-preview" src="{data_uri}" alt="Placa generada automáticamente">"""

    return f"""<h3>Imagen: imagen original</h3>
<img class="imagen-original" src="{_e(contenido.imagen_url)}" alt="Imagen original de la noticia">"""


def _facebook_preview_html(noticia: dict, contenido) -> str:
    cuerpo = f"""
<p class="modo-prueba">MODO PRUEBA — NO SE PUBLICARÁ NADA</p>
{_advertencia_riesgo(noticia)}
<p><a href="/noticia?id={noticia['id']}">&laquo; Volver a la noticia</a></p>
<h2>Vista previa de publicación en Facebook</h2>

<h3>Publicación principal</h3>
<pre>{_e(contenido.post_principal)}</pre>

<h3>Primer comentario</h3>
<pre>{_e(contenido.primer_comentario)}</pre>

<p><strong>Hashtags:</strong> {_e(' '.join(contenido.hashtags))}</p>

{_seccion_imagen(contenido)}
"""
    return _pagina(f"Vista previa Facebook — noticia #{noticia['id']}", cuerpo)


def _indicador(nivel: str) -> str:
    clase = {"OK": "ok", "ADVERTENCIA": "advertencia", "ERROR": "error"}[nivel]
    return f'<span class="indicador indicador-{clase}">{nivel}</span>'


def _indicador_fuente(fuente: dict, alertas_por_fuente: dict) -> str:
    if fuente["ultimo_resultado"] == "error":
        return _indicador("ERROR")
    if fuente["nombre_fuente"] in alertas_por_fuente:
        return _indicador("ADVERTENCIA")
    return _indicador("OK")


def _fila_fuente(fuente: dict, alertas_por_fuente: dict) -> str:
    return f"""<tr>
<td>{_e(fuente['nombre_fuente'])}</td>
<td>{_indicador_fuente(fuente, alertas_por_fuente)}</td>
<td>{_e(fuente['ultima_consulta'])}</td>
<td>{fuente['elementos_obtenidos']}</td>
<td>{fuente['noticias_nuevas']}</td>
<td>{_e(fuente['ultima_noticia_fecha'])}</td>
<td>{fuente['fallos_consecutivos']}</td>
<td>{_e(fuente['ultimo_error'])}</td>
</tr>"""


def _alerta_html(alerta: dict) -> str:
    clase = "error" if alerta["nivel"] == NIVEL_ERROR else "advertencia"
    return f'<p class="alerta alerta-{clase}">{_indicador(alerta["nivel"])} {_e(alerta["mensaje"])}</p>'


def _proxima_ejecucion_aproximada(ultimo_ciclo: Optional[dict]) -> Optional[str]:
    if not ultimo_ciclo or not ultimo_ciclo.get("fecha_fin") or not ultimo_ciclo.get("intervalo_segundos"):
        return None
    try:
        fecha_fin = datetime.fromisoformat(ultimo_ciclo["fecha_fin"])
    except ValueError:
        return None
    return (fecha_fin + timedelta(seconds=ultimo_ciclo["intervalo_segundos"])).isoformat()


def _proxima_franja_prevista(ahora: datetime) -> Optional[str]:
    hoy = ahora.strftime("%Y-%m-%d")
    for hora in HORARIOS_DEFAULT:
        momento = datetime.strptime(f"{hoy} {hora}", "%Y-%m-%d %H:%M").replace(tzinfo=ZONA_JUJUY)
        if momento > ahora:
            return hora
    return None  # todas las franjas de hoy ya pasaron


def _resumen_agenda_hoy(db: Database, ahora: datetime) -> dict:
    fecha_hoy = ahora.strftime("%Y-%m-%d")
    items = [item for item in db.listar_agenda(fecha_hoy) if item["tipo"] == "normal"]
    pendientes = aprobados = sin_candidato = 0
    for item in items:
        if not item["noticia_id"]:
            sin_candidato += 1
            continue
        noticia = db.obtener(item["noticia_id"])
        if not noticia:
            continue
        if noticia["revision_estado"] == RevisionEstado.APROBADA.value:
            aprobados += 1
        elif noticia["revision_estado"] == RevisionEstado.PENDIENTE.value:
            pendientes += 1
    return {"pendientes": pendientes, "aprobados": aprobados, "sin_candidato": sin_candidato}


def _seccion_agenda_automatica_html(db: Database) -> str:
    ahora = datetime.now(ZONA_JUJUY)
    salud_agenda = db.obtener_salud_fuente(NOMBRE_SALUD_AGENDA)
    resumen = _resumen_agenda_hoy(db, ahora)
    habilitada = agenda_automatica_habilitada()

    if salud_agenda:
        resultado = salud_agenda["ultimo_resultado"].upper()
        indicador_resultado = _indicador("OK" if resultado == "OK" else "ERROR")
        ultima_actualizacion = _e(salud_agenda["ultima_consulta"])
        error_agenda = (
            f"<p><strong>Último error:</strong> {_e(salud_agenda['ultimo_error'])}</p>"
            if salud_agenda["ultimo_resultado"] == "error"
            else ""
        )
    else:
        indicador_resultado = "<em>sin datos aún</em>"
        ultima_actualizacion = "sin datos aún"
        error_agenda = ""

    return f"""
<h3>Agenda Editorial automática</h3>
<p><strong>Agenda automática:</strong> {"activada" if habilitada else "desactivada (config/agenda.json)"}</p>
<p><strong>Última actualización:</strong> {ultima_actualizacion} — {indicador_resultado}</p>
{error_agenda}
<p><strong>Espacios pendientes:</strong> {resumen['pendientes']} —
<strong>Aprobados:</strong> {resumen['aprobados']} —
<strong>Sin candidato:</strong> {resumen['sin_candidato']}</p>
<p><strong>Próxima franja prevista:</strong> {_e(_proxima_franja_prevista(ahora)) or "sin franjas restantes hoy"}</p>
"""


def _estado_ollama() -> str:
    """Chequeo liviano y puramente informativo para /estado: reutiliza la
    misma config/redaccion.json que ya lee `crear_redactor`/`RedactorOllama`
    (sin duplicar valores) e intenta una consulta corta a la API de Ollama.
    Nunca cambia nada ni sustituye el redactor configurado — un fallo acá
    solo se muestra como "no disponible", no interrumpe la carga de /estado."""
    try:
        config = _cargar_config_redaccion()
        endpoint = config.get("endpoint") or "http://127.0.0.1:11434/api/chat"
        base = endpoint.rsplit("/api/", 1)[0]
        with urllib.request.urlopen(f"{base}/api/tags", timeout=TIMEOUT_ESTADO_OLLAMA_SEGUNDOS) as resp:
            json.loads(resp.read().decode("utf-8"))
        return "disponible"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return "no disponible"


def _estado_sistema_html(db: Database, lock_path: Path) -> str:
    motor_activo = lock_path.exists()
    ultimo_ciclo = db.ultimo_ciclo()
    fuentes = db.listar_salud_fuentes()
    alertas = calcular_alertas(db)
    alertas_por_fuente = {a["fuente"] for a in alertas if a.get("fuente")}

    resumen = f"""
<h2>Estado del sistema</h2>
<p><strong>Motor continuo:</strong> {"activo" if motor_activo else "inactivo"}</p>
<p><strong>Última ejecución:</strong> {_e(ultimo_ciclo['fecha_fin']) if ultimo_ciclo else "sin datos aún"}</p>
<p><strong>Próxima ejecución aproximada:</strong> {_e(_proxima_ejecucion_aproximada(ultimo_ciclo)) or "sin datos aún"}</p>
<p><strong>Noticias nuevas en última ejecución:</strong> {ultimo_ciclo['total_noticias_nuevas'] if ultimo_ciclo else "sin datos aún"}</p>
<p><strong>Última noticia local recibida:</strong> {_e(db.ultima_noticia_relevante_fecha()) or "sin datos aún"}</p>
<p><strong>Ollama:</strong> {_e(_estado_ollama())}</p>
"""

    if alertas:
        seccion_alertas = "<h3>Alertas activas</h3>\n" + "\n".join(_alerta_html(a) for a in alertas)
    else:
        seccion_alertas = "<h3>Alertas activas</h3>\n<p>Sin alertas activas.</p>"

    if fuentes:
        filas = "\n".join(_fila_fuente(f, alertas_por_fuente) for f in fuentes)
        tabla_fuentes = f"""<h3>Estado de cada fuente</h3>
<table>
<tr><th>Fuente</th><th>Estado</th><th>Última consulta</th><th>Elementos</th>
<th>Noticias nuevas</th><th>Última noticia</th><th>Fallos consecutivos</th><th>Último error</th></tr>
{filas}
</table>"""
    else:
        tabla_fuentes = "<h3>Estado de cada fuente</h3>\n<p>El motor continuo todavía no ejecutó ningún ciclo.</p>"

    seccion_agenda = _seccion_agenda_automatica_html(db)

    return _pagina(
        "Estado del sistema — Ledesma Participa", resumen + seccion_alertas + tabla_fuentes + seccion_agenda
    )


def _antiguedad_legible(fecha_recoleccion: Optional[str], ahora: Optional[datetime] = None) -> str:
    if not fecha_recoleccion:
        return "—"
    try:
        fecha = datetime.fromisoformat(fecha_recoleccion)
    except ValueError:
        return "—"
    ahora = ahora or datetime.now(timezone.utc)
    horas = (ahora - fecha).total_seconds() / 3600
    if horas < 1:
        return "menos de 1 h"
    return f"{int(horas)} h"


def _acciones_agenda(noticia_id: int) -> str:
    return f"""<form class="acciones-en-linea" method="post" action="/noticia?id={noticia_id}">
<button type="submit" name="accion" value="aprobar">Aprobar</button>
<button type="submit" name="accion" value="rechazar">Rechazar</button>
</form> <a href="/noticia?id={noticia_id}">Ver</a>"""


def _fila_agenda(item: dict, db: Database) -> str:
    etiqueta_hora = _e(item["hora"]) if item["hora"] else '<span class="etiqueta-urgente">URGENTE</span>'

    if not item["noticia_id"]:
        return f"""<tr>
<td>{etiqueta_hora}</td>
<td><em>(sin candidato)</em></td>
<td>—</td><td>—</td><td>—</td><td>—</td>
<td>sin_candidato</td>
<td>—</td>
<td></td>
</tr>"""

    noticia = db.obtener(item["noticia_id"])
    if not noticia:
        return f"""<tr>
<td>{etiqueta_hora}</td>
<td colspan="8"><em>Noticia #{item['noticia_id']} no encontrada.</em></td>
</tr>"""

    candidato = noticia["titulo_preparado"] or noticia["titulo_original"]
    riesgo = "SÍ" if noticia["requiere_revision_especial"] else "no"
    urgente = "sí" if noticia["urgente"] else "no"
    return f"""<tr>
<td>{etiqueta_hora}</td>
<td>{_e(candidato)}{_etiqueta_manual(noticia)}</td>
<td>{_e(item['territorio'])}</td>
<td>{_e(noticia['nombre_fuente'])}</td>
<td>{_antiguedad_legible(noticia['fecha_recoleccion'])}</td>
<td>{riesgo}</td>
<td>{_e(noticia['revision_estado'])}</td>
<td>{urgente}</td>
<td>{_acciones_agenda(noticia['id'])}</td>
</tr>"""


def _agenda_html(db: Database, fecha: str) -> str:
    items = db.listar_agenda(fecha)

    if not items:
        cuerpo = f"""
<h2>Agenda Editorial — {_e(fecha)}</h2>
<p>Todavía no se generó la agenda para esta fecha. Ejecutá
<code>python generar_agenda.py --fecha {_e(fecha)}</code> desde la terminal.</p>
"""
        return _pagina("Agenda Editorial — Ledesma Participa", cuerpo)

    filas = "\n".join(_fila_agenda(item, db) for item in items)
    cuerpo = f"""
<h2>Agenda Editorial — {_e(fecha)}</h2>
<table>
<tr><th>Hora</th><th>Candidato</th><th>Territorio</th><th>Fuente</th>
<th>Antigüedad</th><th>Riesgo</th><th>Estado</th><th>Urgente</th><th>Acciones</th></tr>
{filas}
</table>
"""
    return _pagina("Agenda Editorial — Ledesma Participa", cuerpo)


CAMPOS_FORMULARIO_MANUAL = (
    "fuente",
    "url",
    "titulo",
    "texto",
    "fecha_origen",
    "localidad_informada",
    "imagen_url",
    "observacion_interna",
)


def _formulario_carga_manual_html(mensaje_error: Optional[str] = None, valores: Optional[dict] = None) -> str:
    valores = valores or {}
    v = {campo: _e(valores.get(campo, "")) for campo in CAMPOS_FORMULARIO_MANUAL}
    urgente_marcado = "checked" if valores.get("urgente") else ""
    aviso_error = f'<p class="error-formulario">{_e(mensaje_error)}</p>' if mensaje_error else ""

    cuerpo = f"""
<h2>Cargar noticia</h2>
<p>Para noticias de fuentes que hoy no se pueden automatizar de forma
estable (Ledesma Soy, FM Imagen, Canal 6, radios locales, Facebook,
WhatsApp, comunicados, vecinos, etc.). Pegá el texto y, si lo tenés, el
enlace — el sistema no descarga ni scrapea nada, solo guarda la
referencia. La noticia pasa por el mismo circuito editorial que las
automáticas: no se publica nada.</p>
{aviso_error}
<form method="post" action="/cargar-noticia">
<label>Fuente (obligatorio):<br>
<span class="ayuda-campo">Ej: Ledesma Soy, FM Imagen, Canal 6, Vecino, Municipalidad, Policía, Otro.</span><br>
<input type="text" name="fuente" maxlength="150" value="{v['fuente']}" required></label>

<label>URL de origen (opcional):<br>
<span class="ayuda-campo">Enlace de Facebook, sitio web, publicación o comunicado. Solo se guarda como referencia.</span><br>
<input type="text" name="url" maxlength="2000" value="{v['url']}"></label>

<label>Título original (opcional):<br>
<input type="text" name="titulo" maxlength="500" value="{v['titulo']}"></label>

<label>Texto original (obligatorio):<br>
<textarea name="texto" maxlength="20000" required>{v['texto']}</textarea></label>

<label>Fecha/hora de la información (opcional):<br>
<span class="ayuda-campo">Si no la sabés, dejá vacío: se va a registrar la fecha/hora de esta carga.</span><br>
<input type="text" name="fecha_origen" maxlength="100" value="{v['fecha_origen']}"
placeholder="Ej: 12/08/2026 18:30"></label>

<label>Localidad (opcional):<br>
<span class="ayuda-campo">Pista editorial para auditoría. Ej: Libertador General San Martín, Calilegua,
Caimancito, Fraile Pintado, Yuto, otra. No fuerza la clasificación automática.</span><br>
<input type="text" name="localidad_informada" maxlength="150" value="{v['localidad_informada']}"></label>

<label>Imagen — URL directa (opcional):<br>
<span class="ayuda-campo">Solo si tenés un enlace de imagen directamente usable. No se descarga.
Si no hay, se usa la placa automática existente.</span><br>
<input type="text" name="imagen_url" maxlength="2000" value="{v['imagen_url']}"></label>

<label><input type="checkbox" name="urgente" value="1" {urgente_marcado}> Urgente</label>

<label>Observación interna (opcional):<br>
<span class="ayuda-campo">Privada, para revisión — no se muestra públicamente ni entra al texto preparado.
Ej: "confirmar con otra fuente", "dato recibido por WhatsApp".</span><br>
<textarea name="observacion_interna" maxlength="2000">{v['observacion_interna']}</textarea></label>

<br>
<button type="submit">Guardar</button>
</form>
"""
    return _pagina("Cargar noticia — Ledesma Participa", cuerpo)


def _resultado_carga_manual_html(resultado: ResultadoIngresoManual) -> str:
    if resultado.duplicado:
        cuerpo = """
<h2>Cargar noticia</h2>
<p class="error-formulario">Esta noticia ya existe o coincide con una noticia ingresada anteriormente.</p>
<p class="acciones-resultado"><a href="/cargar-noticia">Cargar otra noticia</a></p>
"""
        return _pagina("Cargar noticia — Ledesma Participa", cuerpo)

    riesgo = "SÍ" if resultado.requiere_revision_especial else "no"
    urgente = "sí" if resultado.urgente else "no"

    if resultado.estado == Estado.PREPARADA.value:
        estado_legible = f"preparada — revisión: {_e(resultado.revision_estado)}"
        acciones_extra = f'<a href="/noticia?id={resultado.noticia_id}">Ver noticia</a><a href="/?filtro=pendientes">Ir a Revisión</a><a href="/agenda">Ir a Agenda Editorial</a>'
        motivo_html = ""
    else:
        estado_legible = "descartada (no elegible)"
        acciones_extra = ""
        motivo_html = (
            f"<p><strong>Motivo:</strong> {_e(resultado.motivo_territorio)}</p>"
            if resultado.territorio == "sin_clasificar"
            else "<p><strong>Motivo:</strong> no superó el control mínimo de calidad editorial "
            "(contenido insuficiente, publicitario o no periodístico).</p>"
        )

    advertencia_agenda = ""
    if resultado.agenda_actualizada is False:
        advertencia_agenda = (
            '<p class="error-formulario">La noticia se guardó correctamente, pero no se pudo '
            f"actualizar la Agenda Editorial automáticamente: {_e(resultado.agenda_mensaje_error)}. "
            "Podés actualizarla manualmente desde <code>generar_agenda.py</code>.</p>"
        )
    en_agenda = "sí" if resultado.agenda_actualizada else ("no" if resultado.agenda_actualizada is False else "—")

    cuerpo = f"""
<h2>Cargar noticia — resultado</h2>
<div class="resultado-carga">
<p><strong>Noticia guardada</strong> <span class="etiqueta-manual">MANUAL</span></p>
<p><strong>Fuente:</strong> {_e(resultado.fuente)}</p>
<p><strong>Origen:</strong> MANUAL</p>
<p><strong>Título:</strong> {_e(resultado.titulo_original)}</p>
<p><strong>Territorio detectado:</strong> {_e(resultado.territorio)}</p>
<p><strong>Estado:</strong> {estado_legible}</p>
<p><strong>Riesgo editorial:</strong> {riesgo}</p>
<p><strong>Urgente:</strong> {urgente}</p>
<p><strong>¿Entró a la Agenda Editorial?:</strong> {en_agenda}</p>
{motivo_html}
</div>
{advertencia_agenda}
<p class="acciones-resultado">
{acciones_extra}
<a href="/cargar-noticia">Cargar otra noticia</a>
</p>
"""
    return _pagina("Cargar noticia — Ledesma Participa", cuerpo)


class PanelHandler(BaseHTTPRequestHandler):
    db_path = DB_PATH_DEFAULT
    lock_path = LOCK_PATH_DEFAULT
    # Redactor para la carga manual: mismo mecanismo que `cli.py` y
    # `continuo_runner.py` (`crear_redactor`), nunca un circuito aparte — una
    # noticia manual usa el redactor configurado, igual que una automática.
    # El default de clase es explícitamente "mock" (sin leer config ni
    # depender del entorno, para no instanciar nada al solo importar este
    # módulo); `iniciar_servidor()` es quien resuelve la configuración real
    # (config/redaccion.json, con el override de --redactor si se pasó) al
    # arrancar el proceso, y la asigna ahí de forma explícita.
    redactor = crear_redactor("mock")

    def _db(self) -> Database:
        return Database(self.db_path)

    def _responder_html(self, cuerpo: str, status: int = 200) -> None:
        cuerpo_bytes = cuerpo.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo_bytes)))
        self.end_headers()
        self.wfile.write(cuerpo_bytes)

    def _redirigir(self, ubicacion: str) -> None:
        self.send_response(303)
        self.send_header("Location", ubicacion)
        self.end_headers()

    def _no_encontrada(self) -> None:
        self._responder_html(_pagina("No encontrada", "<p>Página no encontrada.</p>"), status=404)

    def do_GET(self):
        partes = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(partes.query)
        db = self._db()
        try:
            if partes.path == "/":
                filtro = query.get("filtro", ["pendientes"])[0]
                if filtro not in FILTROS_VALIDOS:
                    filtro = "pendientes"
                self._responder_html(_lista_html(db, filtro))
                return

            if partes.path == "/estado":
                self._responder_html(_estado_sistema_html(db, self.lock_path))
                return

            if partes.path == "/agenda":
                fecha = query.get("fecha", [None])[0] or datetime.now(ZONA_JUJUY).strftime("%Y-%m-%d")
                self._responder_html(_agenda_html(db, fecha))
                return

            if partes.path == "/noticia":
                id_texto = query.get("id", [None])[0]
                noticia = db.obtener(int(id_texto)) if id_texto and id_texto.isdigit() else None
                if not noticia or noticia["estado"] != Estado.PREPARADA.value:
                    self._responder_html(
                        _pagina("No encontrada", "<p>Noticia no encontrada.</p>"), status=404
                    )
                else:
                    self._responder_html(_detalle_html(noticia))
                return

            if partes.path == "/cargar-noticia":
                self._responder_html(_formulario_carga_manual_html())
                return

            if partes.path == "/facebook":
                id_texto = query.get("id", [None])[0]
                noticia = db.obtener(int(id_texto)) if id_texto and id_texto.isdigit() else None
                if not noticia or noticia["estado"] != Estado.PREPARADA.value:
                    self._responder_html(
                        _pagina("No encontrada", "<p>Noticia no encontrada.</p>"), status=404
                    )
                    return
                try:
                    contenido = preparar_publicacion(noticia, dry_run=True, db=db)
                except ErrorPreparacionFacebook as error:
                    self._responder_html(
                        _pagina("No disponible", f"<p>{_e(str(error))}</p>"), status=400
                    )
                    return
                self._responder_html(_facebook_preview_html(noticia, contenido))
                return

            self._no_encontrada()
        finally:
            db.close()

    def do_POST(self):
        partes = urllib.parse.urlsplit(self.path)

        if partes.path == "/cargar-noticia":
            self._post_cargar_noticia()
            return

        if partes.path != "/noticia":
            self._no_encontrada()
            return

        query = urllib.parse.parse_qs(partes.query)
        id_texto = query.get("id", [None])[0]
        if not id_texto or not id_texto.isdigit():
            self._responder_html(_pagina("Error", "<p>ID de noticia inválido.</p>"), status=400)
            return
        id_noticia = int(id_texto)

        longitud = int(self.headers.get("Content-Length", 0))
        cuerpo_peticion = self.rfile.read(longitud).decode("utf-8") if longitud else ""
        datos = urllib.parse.parse_qs(cuerpo_peticion)

        accion = datos.get("accion", [""])[0]
        titulo_revisado = datos.get("titulo_revisado", [""])[0].strip()
        texto_revisado = datos.get("texto_revisado", [""])[0].strip()

        db = self._db()
        try:
            noticia = db.obtener(id_noticia)
            if not noticia or noticia["estado"] != Estado.PREPARADA.value:
                self._responder_html(
                    _pagina("Error", "<p>Noticia no encontrada.</p>"), status=404
                )
                return

            if accion == "aprobar":
                nuevo_estado = RevisionEstado.APROBADA.value
                fecha_revision = datetime.now(timezone.utc).isoformat()
            elif accion == "rechazar":
                nuevo_estado = RevisionEstado.RECHAZADA.value
                fecha_revision = datetime.now(timezone.utc).isoformat()
            else:
                nuevo_estado = noticia["revision_estado"]
                fecha_revision = noticia["fecha_revision"]

            db.actualizar_revision(
                id_noticia,
                nuevo_estado,
                titulo_revisado=titulo_revisado or None,
                texto_revisado=texto_revisado or None,
                fecha_revision=fecha_revision,
            )
            self._redirigir(f"/noticia?id={id_noticia}")
        finally:
            db.close()

    def _post_cargar_noticia(self) -> None:
        longitud = int(self.headers.get("Content-Length", 0) or 0)
        if longitud <= 0 or longitud > LONGITUD_MAXIMA_CUERPO_POST_CARGA:
            self._responder_html(
                _pagina("Error", "<p>Formulario inválido o demasiado grande.</p>"), status=413
            )
            return

        cuerpo_peticion = self.rfile.read(longitud).decode("utf-8", errors="replace")
        datos = urllib.parse.parse_qs(cuerpo_peticion)

        def _campo(nombre: str) -> str:
            return datos.get(nombre, [""])[0].strip()

        valores = {campo: _campo(campo) for campo in CAMPOS_FORMULARIO_MANUAL}
        valores["urgente"] = _campo("urgente") == "1"

        db = self._db()
        try:
            try:
                resultado = cargar_noticia_manual(
                    db,
                    self.redactor,
                    fuente=valores["fuente"],
                    texto=valores["texto"],
                    url=valores["url"] or None,
                    titulo=valores["titulo"] or None,
                    fecha_origen=valores["fecha_origen"] or None,
                    localidad_informada=valores["localidad_informada"] or None,
                    imagen_url=valores["imagen_url"] or None,
                    urgente=valores["urgente"],
                    observacion_interna=valores["observacion_interna"] or None,
                )
            except ErrorIngresoManual as error:
                self._responder_html(_formulario_carga_manual_html(str(error), valores), status=400)
                return

            self._responder_html(_resultado_carga_manual_html(resultado))
        finally:
            db.close()

    def log_message(self, format, *args):
        # Silencia el log de acceso por defecto de BaseHTTPRequestHandler.
        pass


def iniciar_servidor(db_path=None, redactor=None):
    """Punto de arranque real del panel: acá (y no al importar el módulo) se
    resuelve el redactor configurado, si quien llama no pasó ya uno
    explícito (p.ej. `run_panel.py` pasando el override de --redactor)."""
    PanelHandler.db_path = db_path or DB_PATH_DEFAULT
    PanelHandler.redactor = redactor if redactor is not None else crear_redactor()
    servidor = HTTPServer((HOST, PORT), PanelHandler)
    print("Panel Ledesma Participa:")
    print(f"http://{HOST}:{PORT}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
