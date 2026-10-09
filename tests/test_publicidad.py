from collections import Counter
from pathlib import Path

import pytest
from PIL import Image

from motor_noticias.meta.cliente import ErrorClienteMeta, ResultadoFotoFacebook
from motor_noticias.publicidad import (
    DatabasePublicidad,
    cargar_config,
    elegir_comercio,
    generar_texto,
    publicar_publicidad_del_dia,
)

RAIZ = Path(__file__).resolve().parent.parent


class ClienteFalso:
    def __init__(self, fallar_ig=False):
        self.fallar_ig = fallar_ig
        self.llamadas = Counter()

    def publicar_foto_facebook(self, contenido, ruta, dry_run=True):
        assert "ESPACIO COMERCIAL" in contenido.post_principal
        assert Path(ruta).exists()
        self.llamadas["facebook"] += 1
        return ResultadoFotoFacebook(photo_id="ph1", post_id="post1")

    def obtener_url_publica_foto(self, photo_id):
        return f"https://cdn.example/{photo_id}.jpg"

    def publicar_instagram(self, caption, url, dry_run=True):
        if self.fallar_ig:
            raise ErrorClienteMeta("fallo IG")
        self.llamadas["instagram"] += 1
        return "ig1"

    def alojar_imagen_para_story(self, ruta, dry_run=True):
        with Image.open(ruta) as im:
            assert im.size == (1080, 1920)
        return "ph_story"

    def publicar_instagram_story(self, url, dry_run=True):
        self.llamadas["story"] += 1
        return "story1"

    def verificar_publicacion(self, meta_id):
        return True


@pytest.fixture
def config():
    return cargar_config()


def _publicar(tmp_path, db, fecha, cliente, config):
    return publicar_publicidad_del_dia(
        db, fecha, cliente, cliente, config=config, raiz=RAIZ,
        directorio_salida=tmp_path / "salida", historias_habilitadas=True,
    )


def test_rotacion_equitativa_entre_los_tres(tmp_path, config):
    db = DatabasePublicidad(tmp_path / "p.db")
    cliente = ClienteFalso()
    comercios = [_publicar(tmp_path, db, f"2026-10-{d:02d}", cliente, config).comercio_id for d in range(1, 10)]
    assert comercios[:3] == ["dosis_jeans", "un_clasico", "wifi_lumetto"]
    assert Counter(comercios) == {"dosis_jeans": 3, "un_clasico": 3, "wifi_lumetto": 3}
    imagenes = [f["imagen"] for f in db.historial() if f["comercio_id"] == "dosis_jeans"]
    assert imagenes == ["dosis_01.jpg", "dosis_02.jpg", "dosis_03.jpg"]


def test_una_sola_publicacion_por_dia_e_idempotente(tmp_path, config):
    db = DatabasePublicidad(tmp_path / "p.db")
    cliente = ClienteFalso()
    r1 = _publicar(tmp_path, db, "2026-10-02", cliente, config)
    r2 = _publicar(tmp_path, db, "2026-10-02", cliente, config)
    assert [r.estado for r in r1.redes] == ["publicado"] * 3
    assert r1.comercio_id == r2.comercio_id
    assert cliente.llamadas == {"facebook": 1, "instagram": 1, "story": 1}
    metricas = db.metricas()
    assert metricas == [dict(metricas[0], turnos=1, facebook=1, instagram=1, instagram_story=1, errores=0)]


def test_falla_instagram_no_duplica_facebook(tmp_path, config):
    db = DatabasePublicidad(tmp_path / "p.db")
    cliente = ClienteFalso(fallar_ig=True)
    r = _publicar(tmp_path, db, "2026-10-02", cliente, config)
    assert dict((x.red_social, x.estado) for x in r.redes)["instagram"] == "error"
    cliente.fallar_ig = False
    r = _publicar(tmp_path, db, "2026-10-02", cliente, config)
    assert [x.estado for x in r.redes] == ["publicado"] * 3
    assert cliente.llamadas["facebook"] == 1


def test_texto_identifica_espacio_comercial(config):
    for comercio in config["comercios"]:
        texto = generar_texto(comercio, config)
        assert texto.startswith("📢 ESPACIO COMERCIAL")
        assert "primer comentario" not in texto.lower()


def test_imagenes_de_entrada_existen(config):
    for comercio in config["comercios"]:
        for imagen in comercio["imagenes"]:
            assert (RAIZ / config["directorio_imagenes"] / imagen).exists()


def test_eleccion_sin_historial_es_el_primero(config):
    assert elegir_comercio(config, [])["id"] == "dosis_jeans"
