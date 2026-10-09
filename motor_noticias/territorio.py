import re
import unicodedata
from typing import Optional
from urllib.parse import urlparse

from .relevancia import cargar_config as cargar_config_localidades
from .relevancia import clasificar_relevancia

TERRITORIOS = ("local", "departamental", "provincial", "nacional", "internacional", "sin_clasificar")


def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def _contiene_alguna(texto_norm: str, terminos: list) -> Optional[str]:
    for termino in terminos:
        if _sin_acentos(termino) in texto_norm:
            return termino
    return None


def _contiene_alguna_palabra(texto_norm: str, terminos: list) -> Optional[str]:
    """Como `_contiene_alguna`, pero exige límites de palabra: evita falsos
    positivos de subcadena (p.ej. que 'Nación' matchee dentro de
    'combinación'). Se usa para los marcadores nacionales/internacionales,
    que son términos más cortos y genéricos que las localidades."""
    for termino in terminos:
        patron = r"\b" + re.escape(_sin_acentos(termino)) + r"\b"
        if re.search(patron, texto_norm):
            return termino
    return None


def _primer_segmento_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    segmentos = [s for s in urlparse(url).path.split("/") if s]
    return segmentos[0] if segmentos else None


def _es_medio_nacional(nombre_fuente: Optional[str], config: dict) -> bool:
    if not nombre_fuente:
        return False
    medios = {_sin_acentos(m) for m in config.get("medios_nacionales", [])}
    return _sin_acentos(nombre_fuente) in medios


def _evidencia_internacional(
    contenido_norm: str, categoria: Optional[str], url: Optional[str], config: dict
) -> Optional[str]:
    """Evidencia determinística de que el contenido es de alcance
    internacional (no argentino): mención explícita de país/región
    extranjera en el texto, o sección/categoría/URL correspondiente a
    cobertura internacional."""
    termino = _contiene_alguna_palabra(contenido_norm, config.get("internacional", []))
    if termino:
        return f"menciona '{termino}'"

    secciones = {_sin_acentos(s) for s in config.get("secciones_internacionales", [])}

    segmento = _primer_segmento_url(url)
    if segmento and _sin_acentos(segmento) in secciones:
        return f"sección de URL '{segmento}'"

    if categoria and _sin_acentos(categoria) in secciones:
        return f"categoría '{categoria}'"

    return None


def _seccion_ambigua(categoria: Optional[str], url: Optional[str], config: dict) -> Optional[str]:
    """Secciones como deportes/espectáculos suelen incluir contenido
    extranjero (clubes, selecciones, figuras de otros países) sin que el
    texto mencione un país reconocible en `config["internacional"]`. Para
    esas secciones el fallback nacional (paso C) no alcanza por sí solo:
    se exige evidencia explícita (marcador nacional del paso A) en vez de
    asumir alcance argentino por defecto."""
    ambiguas = {_sin_acentos(s) for s in config.get("secciones_ambiguas", [])}

    segmento = _primer_segmento_url(url)
    if segmento and _sin_acentos(segmento) in ambiguas:
        return f"sección de URL '{segmento}'"

    if categoria and _sin_acentos(categoria) in ambiguas:
        return f"categoría '{categoria}'"

    return None


def _nivel_desde_termino(termino: Optional[str], config: dict) -> Optional[str]:
    if termino is None:
        return None
    if termino in config.get("maxima_prioridad", []):
        return "local"
    if termino in config.get("prioridad_alta", []):
        return "departamental"
    if termino in config.get("jujuy", []):
        return "provincial"
    return None


def _neutralizar_marcas(texto: str, nombre_fuente: Optional[str], config: dict) -> str:
    """Texto normalizado (minúsculas, sin acentos) sin las firmas de medios
    (p.ej. "Jujuy al día ®" al inicio de cada nota de ese medio, o "El
    Tribuno de Jujuy"): el nombre de un medio no es la ubicación del hecho.
    Bug real: toda nota de Jujuy al día —incluida la inflación nacional del
    INDEC— quedaba "provincial" por su propia firma."""
    texto_norm = _sin_acentos(_neutralizar_apellidos(texto or "", config))
    marcas = list(config.get("marcas_medios", {}).get("terminos", []))
    marcas += config.get("expresiones_no_geograficas", {}).get("terminos", [])
    toponimos = config.get("maxima_prioridad", []) + config.get("prioridad_alta", []) + config.get("jujuy", [])
    if nombre_fuente and _contiene_alguna_palabra(_sin_acentos(nombre_fuente), toponimos):
        marcas.append(nombre_fuente)
    for marca in sorted(marcas, key=len, reverse=True):
        marca_norm = _sin_acentos(marca).strip()
        if marca_norm:
            texto_norm = re.sub(r"\b" + re.escape(marca_norm) + r"\b", " ", texto_norm)
    return texto_norm


_RE_NOMBRE_ANTES_DE_TOPONIMO = re.compile(r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)\s+(Ledesma|Libertador)\b")


def _neutralizar_apellidos(texto: str, config: dict) -> str:
    """"Carlos Ledesma", "Juan Libertador": un nombre propio capitalizado
    seguido del topónimo es un apellido, no el lugar (bug real: notas sobre
    personas apellidadas Ledesma quedaban "departamentales"). Se respetan
    las palabras que sí introducen el lugar ("Departamento Ledesma",
    "Ingenio Ledesma", "En Ledesma"…, ver `prefijos_toponimo` en
    localidades.json). Trabaja sobre el texto original (necesita las
    mayúsculas) antes de normalizar."""
    permitidos = {p.lower() for p in config.get("prefijos_toponimo", {}).get("terminos", [])}

    def _reemplazo(m):
        if m.group(1).lower() in permitidos:
            return m.group(0)
        return f"{m.group(1)} apellido"

    return _RE_NOMBRE_ANTES_DE_TOPONIMO.sub(_reemplazo, texto)


def _fuente_regional(nombre_fuente: Optional[str], config: dict) -> bool:
    if not nombre_fuente:
        return False
    regionales = config.get("medios_provinciales", {}).get("terminos", []) + config.get(
        "medios_locales", {}
    ).get("terminos", [])
    return _sin_acentos(nombre_fuente) in {_sin_acentos(m) for m in regionales}


def _contexto_jujeno(contenido_norm: str, config: dict) -> Optional[str]:
    terminos = (
        config.get("jujuy", [])
        + config.get("localidades_inequivocas", {}).get("terminos", [])
        + config.get("contexto_jujeno", {}).get("terminos", [])
    )
    return _contiene_alguna_palabra(contenido_norm, terminos)


def _localidad_confirmada(termino: str, contenido_norm: str, nombre_fuente: Optional[str], config: dict) -> bool:
    """Nunca se decide la localidad por una coincidencia aislada: un
    topónimo ambiguo ("Libertador", "Libertador General San Martín" —que
    también es un departamento de Misiones, Chaco y San Luis—, "Ledesma"
    —pueblo de Salamanca, apellido, empresa—) solo cuenta si la fuente es
    regional (medio jujeño o local) o el contenido trae contexto jujeño
    (Jujuy, otra localidad de la provincia o del departamento, Ruta 34…).
    Bug real: "Chau anegamientos… entre las avenidas Figueroa Alcorta y Del
    Libertador" (La Nación, CABA) quedó como Libertador General San Martín
    y salió como urgente local. Las localidades inequívocas (solo existen
    en Jujuy: Calilegua, Fraile Pintado, Yuto…) no necesitan confirmación."""
    inequivocas = {_sin_acentos(t) for t in config.get("localidades_inequivocas", {}).get("terminos", [])}
    if _sin_acentos(termino) in inequivocas:
        return True
    if _fuente_regional(nombre_fuente, config) or _contexto_jujeno(contenido_norm, config) is not None:
        return True
    # El nombre completo ("Libertador General San Martín") es una
    # combinación casi inequívoca: vale salvo que el contenido ubique el
    # hecho en otra provincia u otro país (departamentos homónimos de
    # Misiones, Chaco, San Luis…). "Libertador" solo o "Libertador San
    # Martín" (también ciudad de Entre Ríos) siempre exigen confirmación.
    completos = {_sin_acentos(t) for t in config.get("nombres_completos_locales", {}).get("terminos", [])}
    if _sin_acentos(termino) in completos:
        ajeno = _contiene_alguna_palabra(
            contenido_norm, config.get("otras_provincias", []) + config.get("internacional", [])
        )
        return ajeno is None
    return False


def _relevancia_confirmada(
    titulo_norm: str, texto_norm: str, nombre_fuente: Optional[str], config: dict, contexto_norm: str
):
    """`clasificar_relevancia` + confirmación contextual: si el topónimo
    local/departamental hallado no se confirma, se lo quita del texto y se
    vuelve a buscar (otra localidad, Jujuy, o nada)."""
    agrupados = {
        "local": config.get("maxima_prioridad", []),
        "departamental": config.get("prioridad_alta", []),
    }
    for _ in range(4):
        resultado = clasificar_relevancia(titulo_norm, texto_norm, config=config)
        nivel = _nivel_desde_termino(resultado["localidad"], config)
        if nivel not in ("local", "departamental"):
            return nivel, resultado
        if _localidad_confirmada(resultado["localidad"], contexto_norm, nombre_fuente, config):
            return nivel, resultado
        termino = _sin_acentos(resultado["localidad"])
        variantes = [_sin_acentos(t) for t in agrupados[nivel] if termino in _sin_acentos(t) or _sin_acentos(t) in termino]
        for variante in sorted(set(variantes) | {termino}, key=len, reverse=True):
            patron = r"\b" + re.escape(variante) + r"\b"
            titulo_norm = re.sub(patron, " ", titulo_norm)
            texto_norm = re.sub(patron, " ", texto_norm)
    return None, clasificar_relevancia("", "", config=config)


def _resultado(territorio: str, motivo: str, localidad: Optional[str], motivo_relevancia: Optional[str] = None) -> dict:
    return {
        "territorio": territorio,
        "motivo_territorio": motivo,
        # `relevancia_local` conserva su significado: relación directa con
        # Libertador o el Departamento Ledesma.
        "relevante": territorio in ("local", "departamental"),
        "motivo_relevancia": motivo_relevancia or motivo,
        "localidad": localidad,
    }


def clasificar_territorio(
    titulo: str,
    texto: str,
    localidad_fuente: Optional[str] = None,
    config: Optional[dict] = None,
    nombre_fuente: Optional[str] = None,
    url: Optional[str] = None,
    categoria: Optional[str] = None,
) -> dict:
    """Clasificación territorial determinística (sin IA) en seis niveles:
    local (Libertador), departamental (resto de Ledesma), provincial (resto
    de Jujuy), nacional (Argentina), internacional y sin_clasificar.

    Orden de evidencia (corregido 2/10/2026, antes cualquier mención en el
    cuerpo decidía y ganaba la de mayor prioridad):
    1. Localidad institucional de la fuente (collectors 100% locales).
    2. El TÍTULO: es donde está el lugar del hecho. Una localidad de
       Libertador/Ledesma en el título decide; si el título no menciona
       Jujuy pero sí otro país u otra provincia, eso decide (internacional /
       nacional) aunque el cuerpo nombre a Jujuy de pasada (bug real:
       "nevadas en Antofagasta" → provincial por "viaje de Jujuy a la
       cordillera"; "heridos en Yuto" → local por "derivados al hospital de
       Libertador").
    3. Título + cuerpo, sin las firmas de medios (`marcas_medios` y el
       propio `nombre_fuente`). Una mención de Jujuy solo en el cuerpo no
       vuelve provincial una nota cuyo título es nacional (INDEC, Milei…).
    4. Marcadores nacionales; evidencia internacional; fallback de medio
       nacional (sin evidencia internacional ni sección ambigua)."""
    config = config or cargar_config_localidades()

    if localidad_fuente:
        por_fuente = clasificar_relevancia("", "", localidad=localidad_fuente, config=config)
        nivel = _nivel_desde_termino(por_fuente["localidad"], config)
        if nivel:
            return _resultado(nivel, por_fuente["motivo"], por_fuente["localidad"])

    titulo_norm = _neutralizar_marcas(titulo, nombre_fuente, config)
    texto_norm = _neutralizar_marcas(texto, nombre_fuente, config)
    contenido_norm = f"{titulo_norm} {texto_norm}"

    nivel_titulo, por_titulo = _relevancia_confirmada(titulo_norm, "", nombre_fuente, config, contenido_norm)
    if nivel_titulo in ("local", "departamental"):
        return _resultado(nivel_titulo, por_titulo["motivo"], por_titulo["localidad"])

    nacional_en_titulo = _contiene_alguna_palabra(titulo_norm, config.get("nacional", []))
    if nivel_titulo is None:
        extranjero = _contiene_alguna_palabra(titulo_norm, config.get("internacional", []))
        if extranjero and not nacional_en_titulo:
            return _resultado(
                "internacional", f"El título ubica el hecho fuera de Argentina ('{extranjero}').", None
            )
        otra_provincia = _contiene_alguna_palabra(titulo_norm, config.get("otras_provincias", []))
        if otra_provincia:
            return _resultado(
                "nacional", f"El título ubica el hecho en otra provincia ('{otra_provincia}').", None
            )
        if nacional_en_titulo:
            return _resultado(
                "nacional", f"El título menciona '{nacional_en_titulo}' (alcance nacional).", None
            )

    nivel, completo = _relevancia_confirmada(titulo_norm, texto_norm, nombre_fuente, config, contenido_norm)
    if nivel:
        return _resultado(nivel, completo["motivo"], completo["localidad"])

    termino_nacional = _contiene_alguna_palabra(contenido_norm, config.get("nacional", []))
    if termino_nacional:
        return _resultado("nacional", f"Menciona '{termino_nacional}' (alcance nacional).", None)

    evidencia_internacional = _evidencia_internacional(contenido_norm, categoria, url, config)

    if _es_medio_nacional(nombre_fuente, config):
        seccion_ambigua = None if evidencia_internacional else _seccion_ambigua(categoria, url, config)
        if not evidencia_internacional and not seccion_ambigua:
            return _resultado(
                "nacional",
                f"Medio nacional configurado ('{nombre_fuente}'), sin evidencia de contenido "
                "internacional y sin clasificación local/departamental/provincial: se asume "
                "sección argentina/general del medio.",
                None,
            )
        if seccion_ambigua:
            return _resultado(
                "sin_clasificar",
                f"Medio nacional configurado ('{nombre_fuente}'), pero la sección es ambigua "
                f"({seccion_ambigua}, propensa a contenido extranjero) y no hay ningún marcador "
                "nacional explícito en el contenido.",
                None,
            )

    medios_provinciales = {_sin_acentos(m) for m in config.get("medios_provinciales", {}).get("terminos", [])}
    # Solo cuando el texto original nombraba Jujuy (típicamente vía la firma
    # del medio): conserva exactamente el alcance previo de "provincial"
    # para esas notas, pero ahora después de descartar evidencia nacional /
    # de otra provincia / internacional. No amplía el pool: una nota de un
    # medio jujeño que nunca nombra Jujuy sigue sin_clasificar, como antes.
    nombraba_jujuy = _contiene_alguna_palabra(_sin_acentos(f"{titulo} {texto}"), ["Jujuy"])
    if (
        not evidencia_internacional
        and nombraba_jujuy
        and nombre_fuente
        and _sin_acentos(nombre_fuente) in medios_provinciales
    ):
        return _resultado(
            "provincial",
            f"Medio jujeño configurado ('{nombre_fuente}') sin evidencia local, nacional, de otra "
            "provincia ni internacional: se asume alcance provincial.",
            "Jujuy",
        )

    if evidencia_internacional:
        return _resultado(
            "internacional",
            f"Contenido internacional ({evidencia_internacional}) sin impacto argentino explícito.",
            None,
        )

    return _resultado(
        "sin_clasificar",
        "Sin relación identificable con Libertador General San Martín, el "
        "Departamento Ledesma, la provincia de Jujuy ni referencias nacionales explícitas.",
        None,
    )
