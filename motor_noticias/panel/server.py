import base64
import html
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

from ..db import Database
from ..meta.preparacion import ErrorPreparacionFacebook, preparar_publicacion
from ..models import Estado, RevisionEstado

# El panel es exclusivamente local: se enlaza siempre a 127.0.0.1, nunca a
# 0.0.0.0 ni a una dirección configurable, para que no sea accesible desde
# fuera de esta máquina.
HOST = "127.0.0.1"
PORT = 8000

DB_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "ledesma_participa.db"

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
</style>
</head>
<body>
<h1><a href="/" style="text-decoration:none;color:inherit;">Ledesma Participa — Panel de revisión</a></h1>
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


def _tarjeta_noticia(n: dict) -> str:
    return f"""<div class="noticia">
{_advertencia_riesgo(n)}
<p><strong>Título original:</strong> {_e(n['titulo_original'])}</p>
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


class PanelHandler(BaseHTTPRequestHandler):
    db_path = DB_PATH_DEFAULT

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

    def log_message(self, format, *args):
        # Silencia el log de acceso por defecto de BaseHTTPRequestHandler.
        pass


def iniciar_servidor(db_path=None):
    PanelHandler.db_path = db_path or DB_PATH_DEFAULT
    servidor = HTTPServer((HOST, PORT), PanelHandler)
    print("Panel Ledesma Participa:")
    print(f"http://{HOST}:{PORT}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
