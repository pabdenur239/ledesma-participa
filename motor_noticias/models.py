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


class OrigenIngreso(str, Enum):
    AUTOMATICO = "automatico"
    MANUAL = "manual"
    INSTITUCIONAL = "institucional"
    RESUMEN_DIARIO = "resumen_diario"
    CONTENIDO_PROPIO = "contenido_propio"


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
    tiene_imagen_original: bool = False
    imagen_publicacion_ruta: Optional[str] = None
    imagen_generada_automaticamente: bool = False
    territorio: Optional[str] = None
    motivo_territorio: Optional[str] = None
    urgente: bool = False
    origen_ingreso: str = OrigenIngreso.AUTOMATICO.value
    localidad_informada: Optional[str] = None
    observacion_interna: Optional[str] = None
    revision_automatica: bool = False
    categoria_tematica: Optional[str] = None
