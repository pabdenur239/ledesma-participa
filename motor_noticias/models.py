from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Estado(str, Enum):
    ENCONTRADA = "encontrada"
    DESCARTADA = "descartada"
    PREPARADA = "preparada"
    PUBLICADA = "publicada"


@dataclass
class Noticia:
    id: Optional[int]
    titulo_original: str
    texto_original: str
    url_fuente: str
    nombre_fuente: str
    fecha_fuente: str
    fecha_recoleccion: str
    estado: str
    hash_contenido: str
    url_normalizada: Optional[str] = None
    localidad: Optional[str] = None
    relevancia_local: Optional[bool] = None
    motivo_relevancia: Optional[str] = None
    titulo_preparado: Optional[str] = None
    texto_preparado: Optional[str] = None
