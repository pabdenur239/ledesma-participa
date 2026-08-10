import hashlib
import html
import html.parser
import json
import re
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional

from .base import Collector

CONFIG_PATH_DEFAULT = Path(__file__).resolve().parent.parent.parent / "config" / "fuentes.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LedesmaParticipa/1.0; RSS Reader)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

MARCADOR_BLOQUE = "Actividades sr. Intendente Ing. Oscar Jayat"
ENCABEZADO_TAGS = ("h1", "h2", "h3", "h4")
TAGS_EXCLUIDOS = {"nav", "footer", "header", "script", "style", "iframe", "noscript"}
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img",
    "input", "link", "meta", "param", "source", "track", "wbr",
}
LONGITUD_MINIMA_RESUMEN = 15
LONGITUD_MAXIMA_TITULO = 90
PATRONES_EXCLUSION = (
    "domicilio",
    "teléfono",
    "telefono",
    "tel:",
    "e-mail",
    "email",
    "correo electrónico",
    "correo electronico",
    "@",
    "todos los derechos reservados",
    "copyright",
)


class ErrorRecoleccionHTML(RuntimeError):
    """Error controlado al recolectar la página municipal."""


def _cargar_config(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)["municipio_libertador"]


def _limpiar_espacios(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _es_texto_excluido(texto: str) -> bool:
    texto_normalizado = texto.lower()
    return any(patron in texto_normalizado for patron in PATRONES_EXCLUSION)


def _normalizar_para_hash(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto.lower())
    sin_acentos = "".join(c for c in normalizado if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", sin_acentos).strip("-")


def _fragmento_estable(titulo: str) -> str:
    normalizado = _normalizar_para_hash(titulo)
    hash_corto = hashlib.sha1(normalizado.encode("utf-8")).hexdigest()[:10]
    return f"lp-{hash_corto}"


class _ParserPaginaMunicipal(html.parser.HTMLParser):
    """Recorre la página ya decodificada (sin HTML escapado) y produce una
    secuencia lineal de eventos: encabezados ("h") y bloques de texto ("t").

    Ignora el contenido de navegación, encabezado de sitio, pie de página,
    scripts, estilos e iframes (videos embebidos)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.eventos: List[tuple] = []

        self._pila: List[str] = []
        self._omitir_desde: Optional[int] = None

        self._en_encabezado = False
        self._profundidad_encabezado = 0
        self._buffer_encabezado: List[str] = []
        self._buffer_texto: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            return
        self._pila.append(tag)

        if self._omitir_desde is not None:
            return

        if tag in TAGS_EXCLUIDOS:
            self._omitir_desde = len(self._pila)
            return

        if not self._en_encabezado and tag in ENCABEZADO_TAGS:
            self._flush_texto()
            self._en_encabezado = True
            self._profundidad_encabezado = len(self._pila)
            self._buffer_encabezado = []

    def handle_startendtag(self, tag, attrs):
        return

    def handle_endtag(self, tag):
        if not self._pila or self._pila[-1] != tag:
            return
        self._pila.pop()

        if self._omitir_desde is not None:
            if len(self._pila) < self._omitir_desde:
                self._omitir_desde = None
            return

        if self._en_encabezado and len(self._pila) < self._profundidad_encabezado:
            self._cerrar_encabezado()

    def handle_data(self, data):
        if self._omitir_desde is not None:
            return
        texto = data.strip()
        if not texto:
            return
        if self._en_encabezado:
            self._buffer_encabezado.append(texto)
        else:
            self._buffer_texto.append(texto)

    def _cerrar_encabezado(self):
        texto = _limpiar_espacios(" ".join(self._buffer_encabezado))
        if texto:
            self.eventos.append(("h", texto))
        self._en_encabezado = False
        self._buffer_encabezado = []

    def _flush_texto(self):
        texto = _limpiar_espacios(" ".join(self._buffer_texto))
        if texto:
            self.eventos.append(("t", texto))
        self._buffer_texto = []

    def close(self):
        super().close()
        self._flush_texto()


def extraer_actividades(
    html_crudo: str, url_base: str, nombre_fuente: str, localidad: Optional[str] = None
) -> List[dict]:
    """Decodifica el contenido HTML escapado embebido en la página y extrae
    las actividades listadas a continuación del bloque
    "Actividades sr. Intendente Ing. Oscar Jayat".

    El sitio no distingue de forma confiable títulos de texto descriptivo:
    ambos pueden aparecer en etiquetas de encabezado (h1-h4). Se trata como
    título a un encabezado corto (<= LONGITUD_MAXIMA_TITULO caracteres); un
    encabezado o bloque de texto más largo que aparezca a continuación se
    asocia como resumen de esa actividad en lugar de crear una nueva.
    """
    contenido_decodificado = html.unescape(html_crudo)

    parser = _ParserPaginaMunicipal()
    parser.feed(contenido_decodificado)
    parser.close()
    eventos = parser.eventos

    inicio = None
    for indice, (tipo, texto) in enumerate(eventos):
        if tipo == "h" and texto == MARCADOR_BLOQUE:
            inicio = indice + 1
            break
    if inicio is None:
        return []

    actividades = []
    fragmentos_usados = set()
    for tipo, texto in eventos[inicio:]:
        if texto == MARCADOR_BLOQUE or _es_texto_excluido(texto):
            continue

        es_titulo = tipo == "h" and len(texto) <= LONGITUD_MAXIMA_TITULO
        if es_titulo:
            fragmento = _fragmento_estable(texto)
            fragmento_final = fragmento
            sufijo = 2
            while fragmento_final in fragmentos_usados:
                fragmento_final = f"{fragmento}-{sufijo}"
                sufijo += 1
            fragmentos_usados.add(fragmento_final)

            actividades.append(
                {
                    "titulo": texto,
                    "texto": "",
                    "url": f"{url_base}#{fragmento_final}",
                    "fuente": nombre_fuente,
                    "fecha": "",
                    "localidad": localidad,
                }
            )
            continue

        if actividades and len(texto) >= LONGITUD_MINIMA_RESUMEN and not actividades[-1]["texto"]:
            actividades[-1]["texto"] = texto

    return actividades


class MunicipioLibertadorHTMLCollector(Collector):
    """Collector HTML real de la Municipalidad de Libertador General San Martín.

    Requiere acceso saliente a internet; no se ejecuta durante las pruebas
    automáticas, que usan un fixture HTML local en su lugar.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        nombre_fuente: Optional[str] = None,
        localidad: Optional[str] = None,
        timeout: int = 20,
        config_path: Optional[Path] = None,
    ):
        config = _cargar_config(config_path)
        self.url = url or config["url"]
        self.nombre_fuente = nombre_fuente or config["nombre_fuente"]
        self.localidad = localidad or config.get("localidad")
        self.timeout = timeout

    def recolectar(self) -> List[dict]:
        peticion = urllib.request.Request(self.url, headers=HEADERS)
        try:
            with urllib.request.urlopen(peticion, timeout=self.timeout) as respuesta:
                contenido = respuesta.read()
        except urllib.error.HTTPError as error:
            raise ErrorRecoleccionHTML(
                f"Municipio Libertador respondió HTTP {error.code} ({error.reason}) al pedir {self.url}"
            ) from error
        except urllib.error.URLError as error:
            raise ErrorRecoleccionHTML(
                f"No se pudo conectar al Municipio Libertador ({self.url}): {error.reason}"
            ) from error
        html_crudo = contenido.decode("utf-8", errors="replace")
        return extraer_actividades(html_crudo, self.url, self.nombre_fuente, self.localidad)
