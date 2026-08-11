from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Estado(str, Enum):
    ENCONTRADA = "encontrada"
    DESCARTADA = "descartada"
    PREPARADA = "preparada"
    PUBLICADA = "publicada"


class RevisionEstado(str, Enum):
    PENDIENTE = "pendiente"
    APROBADA = "aprobada"
    RECHAZADA = "rechazada"


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
    revision_estado: str = RevisionEstado.PENDIENTE.value
    fecha_revision: Optional[str] = None
    titulo_revisado: Optional[str] = None
    texto_revisado: Optional[str] = None
    requiere_revision_especial: bool = False
    motivo_revision_especial: Optional[str] = None
    categoria_riesgo: Optional[str] = None
