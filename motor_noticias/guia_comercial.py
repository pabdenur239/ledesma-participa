"""GUÍA COMERCIAL LEDESMA PARTICIPA (Etapa 1, 9/10/2026): listado de
comercios y ficha individual para web y app. Contenido comercial separado
por completo del periodístico (no pasa por el feed ni por la clasificación
editorial). Solo datos reales de `config/guia_comercial.json`: lo que no
se tiene queda en null y no se muestra."""
import json
import re
from pathlib import Path
from typing import List, Optional

RAIZ = Path(__file__).resolve().parent.parent
CONFIG_PATH_DEFAULT = RAIZ / "config" / "guia_comercial.json"

CAMPOS = (
    "slug", "nombre", "rubro", "logo", "descripcion", "imagenes", "direccion", "whatsapp",
    "telefono", "instagram", "facebook", "horarios", "promociones",
)


def cargar_config(path: Optional[Path] = None) -> dict:
    with open(path or CONFIG_PATH_DEFAULT, encoding="utf-8") as f:
        return json.load(f)


def _solo_digitos(valor: Optional[str]) -> str:
    return re.sub(r"\D", "", valor or "")


def url_whatsapp(numero: Optional[str]) -> Optional[str]:
    """wa.me con formato internacional argentino (54 9 + característica +
    número). Un número sin 10 dígitos locales no se transforma (no se
    adivina)."""
    digitos = _solo_digitos(numero)
    if len(digitos) == 10:
        return f"https://wa.me/549{digitos}"
    if digitos.startswith("549") and len(digitos) == 13:
        return f"https://wa.me/{digitos}"
    return None


def url_instagram(usuario: Optional[str]) -> Optional[str]:
    usuario = (usuario or "").strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", usuario):
        return None
    return f"https://www.instagram.com/{usuario.lower()}/"


def contacto(comercio: dict) -> Optional[dict]:
    """Botón de contacto: WhatsApp, si no teléfono, si no Instagram/Facebook."""
    if url_whatsapp(comercio.get("whatsapp")):
        return {"tipo": "whatsapp", "etiqueta": "Escribir por WhatsApp", "url": url_whatsapp(comercio["whatsapp"])}
    if _solo_digitos(comercio.get("telefono")):
        return {"tipo": "telefono", "etiqueta": "Llamar", "url": f"tel:{_solo_digitos(comercio['telefono'])}"}
    if url_instagram(comercio.get("instagram")):
        return {"tipo": "instagram", "etiqueta": "Ver Instagram", "url": url_instagram(comercio["instagram"])}
    if comercio.get("facebook"):
        return {"tipo": "facebook", "etiqueta": "Ver Facebook", "url": comercio["facebook"]}
    return None


def comercios(config: Optional[dict] = None) -> List[dict]:
    """Comercios normalizados (todos los campos presentes, null si faltan;
    las imágenes que no existen en disco se omiten)."""
    config = config or cargar_config()
    directorio = RAIZ / config.get("directorio_imagenes", "publicidad/entrada")
    resultado = []
    for crudo in config.get("comercios", []):
        if not crudo.get("slug") or not crudo.get("nombre"):
            continue
        comercio = {campo: crudo.get(campo) for campo in CAMPOS}
        comercio["imagenes"] = [img for img in (crudo.get("imagenes") or []) if (directorio / img).is_file()]
        comercio["promociones"] = [p for p in (crudo.get("promociones") or []) if p]
        comercio["instagram_url"] = url_instagram(crudo.get("instagram"))
        comercio["whatsapp_url"] = url_whatsapp(crudo.get("whatsapp"))
        comercio["contacto"] = contacto(crudo)
        resultado.append(comercio)
    return resultado


def ruta_imagen(nombre: str, config: Optional[dict] = None) -> Path:
    config = config or cargar_config()
    return RAIZ / config.get("directorio_imagenes", "publicidad/entrada") / nombre
