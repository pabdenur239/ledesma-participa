"""Etapa 1: volumen del portal web/app, regla de imágenes, Guía Comercial,
videos y piezas visuales Versión C."""
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from motor_noticias import portal
from motor_noticias.db import Database
from motor_noticias.guia_comercial import comercios, contacto, url_instagram, url_whatsapp
from motor_noticias.meta import identidad_visual as iv
from motor_noticias.models import Estado, Noticia
from motor_noticias.motor_editorial import ZONA_JUJUY
from motor_noticias.regla_imagenes import evaluar_imagen
from motor_noticias.videos import cargar_videos, id_youtube

AHORA = datetime(2026, 10, 9, 21, 0, tzinfo=ZONA_JUJUY)


def _guardar(db, n, titulo, territorio="nacional", estado=Estado.PREPARADA.value, horas=2, **extra):
    momento = (AHORA - timedelta(hours=horas)).astimezone(timezone.utc).isoformat()
    datos = dict(
        id=None, titulo_original=titulo, texto_original=f"{titulo}. Texto con información suficiente para la nota número {n}.",
        url_fuente=f"https://medio.test/nota-{n}", url_normalizada=f"https://medio.test/nota-{n}",
        nombre_fuente="Infobae", fecha_fuente="", fecha_recoleccion=momento, estado=estado,
        hash_contenido=f"h{n}", titulo_preparado=titulo,
        texto_preparado=f"{titulo}. Texto con información suficiente para la nota número {n}.", territorio=territorio,
    )
    datos.update(extra)
    return db.guardar(Noticia(**datos))


class TestVolumenPortal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_completa_hasta_25_por_dia_sin_rellenar(self):
        temas = ["inflación", "jubilaciones", "ruta", "escuela", "hospital", "elecciones", "lluvias", "precios", "fútbol",
                 "teatro", "salarios", "tránsito", "vacunas", "turismo", "becas", "puentes", "colectivos", "museo",
                 "energía", "agua", "industria", "comercio", "empleo", "créditos", "viviendas", "parques", "música",
                 "ciencia", "minería", "campo"]
        for i, tema in enumerate(temas):
            territorio = "provincial" if i % 2 else "nacional"
            lugar = "en Jujuy" if territorio == "provincial" else "en Argentina"
            _guardar(self.db, i, f"Cambios en {tema} {lugar}", territorio=territorio)
        portal.completar_seleccion(self.db, AHORA)
        seleccion = self.db.portal_seleccion_por_fecha([AHORA.date().isoformat()])[AHORA.date().isoformat()]
        self.assertLessEqual(len(seleccion), portal.MAXIMO_POR_DIA)
        self.assertGreaterEqual(len(seleccion), 15)

    def test_pocas_validas_no_se_rellena(self):
        for i in range(3):
            _guardar(self.db, i, ["Nueva ruta en Jujuy", "Feria del libro en Jujuy", "Obras de agua en Jujuy"][i], territorio="provincial")
        portal.completar_seleccion(self.db, AHORA)
        fecha = AHORA.date().isoformat()
        self.assertEqual(len(self.db.portal_seleccion_por_fecha([fecha]).get(fecha, [])), 3)

    def test_riesgo_rechazo_e_informe_nunca_entran(self):
        _guardar(self.db, 1, "Imputaron a un funcionario por corrupción en Jujuy", territorio="provincial",
                 requiere_revision_especial=True, categoria_riesgo="judicial")
        _guardar(self.db, 2, "Nota rechazada por el editor en Jujuy", territorio="provincial", revision_estado="rechazada")
        _guardar(self.db, 3, "Clima + Dólar | Informe de la mañana", territorio="local",
                 url_normalizada="https://ledesma-participa.local/informe-diario/2026-10-09")
        portal.completar_seleccion(self.db, AHORA)
        self.assertEqual(self.db.portal_seleccion_por_fecha([AHORA.date().isoformat()]), {})

    def test_mismo_hecho_de_dos_medios_entra_una_vez(self):
        _guardar(self.db, 1, "Fuerte temporal de granizo afectó a San Salvador de Jujuy", territorio="provincial")
        _guardar(self.db, 2, "Temporal de granizo afectó a San Salvador de Jujuy esta tarde", territorio="provincial",
                 nombre_fuente="TodoJujuy")
        portal.completar_seleccion(self.db, AHORA)
        fecha = AHORA.date().isoformat()
        self.assertEqual(len(self.db.portal_seleccion_por_fecha([fecha])[fecha]), 1)

    def test_publicadas_mas_seleccionadas_en_el_listado_del_portal(self):
        _guardar(self.db, 1, "Publicada en redes desde Libertador General San Martín", territorio="local",
                 estado=Estado.PUBLICADA.value)
        _guardar(self.db, 2, "Nota solo del portal sobre obras en Jujuy", territorio="provincial")
        portal.completar_seleccion(self.db, AHORA)
        titulos = {n["titulo_original"] for n in portal.noticias_del_portal(self.db, AHORA)}
        self.assertEqual(titulos, {"Publicada en redes desde Libertador General San Martín",
                                   "Nota solo del portal sobre obras en Jujuy"})

    def test_idempotente(self):
        _guardar(self.db, 1, "Nota provincial sobre obras en Jujuy", territorio="provincial")
        portal.completar_seleccion(self.db, AHORA)
        self.assertEqual(portal.completar_seleccion(self.db, AHORA)[AHORA.date().isoformat()], 0)


class TestReglaDeImagenes(unittest.TestCase):
    def test_stock_no_es_apta(self):
        self.assertFalse(evaluar_imagen("https://www.shutterstock.com/image-photo/diarios.jpg")[0])

    def test_archivo_generico_no_es_apto(self):
        self.assertFalse(evaluar_imagen("https://medio.test/wp-content/uploads/logo-susepu.webp")[0])

    def test_foto_reutilizada_en_varias_notas_es_de_archivo(self):
        self.assertFalse(evaluar_imagen("https://medio.test/foto-taller.jpg", usos_en_otras_noticias=3)[0])

    def test_foto_propia_de_la_nota_es_apta(self):
        self.assertTrue(evaluar_imagen("https://medio.test/uploads/2026/10/corte-agua-barrio.jpg")[0])


class TestGuiaComercial(unittest.TestCase):
    def test_datos_reales_sin_inventar(self):
        por_slug = {c["slug"]: c for c in comercios()}
        dosis = por_slug["dosis-jeans"]
        self.assertEqual(dosis["direccion"], "Tucumán 314")
        self.assertEqual(dosis["whatsapp_url"], "https://wa.me/5493886576721")
        self.assertEqual(dosis["instagram_url"], "https://www.instagram.com/dosis.jeans/")
        self.assertEqual(len(dosis["promociones"]), 3)
        clasico = por_slug["un-clasico"]
        self.assertEqual(clasico["rubro"], "Drugstore y librería")
        self.assertIsNone(clasico["whatsapp"])
        self.assertIsNone(clasico["horarios"])
        self.assertIsNone(clasico["contacto"])
        lumetto = por_slug["internet-de-lumetto"]
        self.assertIsNone(lumetto["telefono"])
        self.assertIsNone(lumetto["direccion"])

    def test_contacto_y_urls(self):
        self.assertIsNone(url_whatsapp("123"))
        self.assertIsNone(url_instagram("no válido!"))
        self.assertEqual(contacto({"instagram": "@x.y"})["tipo"], "instagram")


class TestVideos(unittest.TestCase):
    def test_id_youtube(self):
        self.assertEqual(id_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(id_youtube("https://youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(id_youtube("https://www.youtube.com/shorts/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertIsNone(id_youtube("https://vimeo.com/123"))
        self.assertIsNone(id_youtube("https://www.youtube.com/watch?v=corto"))

    def test_solo_videos_validos(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "videos.json"
            ruta.write_text(json.dumps({"videos": [
                {"titulo": "Válido", "url": "https://youtu.be/dQw4w9WgXcQ", "fuente": "Canal"},
                {"titulo": "Inválido", "url": "https://ejemplo.test/video.mp4"},
                {"titulo": "", "url": "https://youtu.be/dQw4w9WgXcQ"},
            ]}), encoding="utf-8")
            videos = cargar_videos(ruta)
        self.assertEqual([v["titulo"] for v in videos], ["Válido"])
        self.assertEqual(videos[0]["embed_url"], "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")


class TestPiezasVisuales(unittest.TestCase):
    def _tamano(self, png):
        return Image.open(io.BytesIO(png)).size

    def test_feed_1080x1350_con_y_sin_foto(self):
        foto = io.BytesIO()
        Image.new("RGB", (1600, 900), (40, 80, 120)).save(foto, format="JPEG")
        datos = iv.DatosPieza("Corte de agua en el barrio Alberdi", "libertador", "Servicios", "servicio")
        self.assertEqual(self._tamano(iv.generar_pieza_feed(datos)), (1080, 1350))
        self.assertEqual(self._tamano(iv.generar_pieza_feed(datos, foto=foto.getvalue())), (1080, 1350))

    def test_story_1080x1920(self):
        self.assertEqual(self._tamano(iv.generar_story_pieza(iv.DatosPieza("Titular", "jujuy"))), (1080, 1920))

    def test_titular_placa_corto(self):
        largo = "Investigan el homicidio de un jornalero en Fraile Pintado: aprehendieron a dos hombres en un operativo nocturno"
        self.assertEqual(iv.titular_placa(largo), "Investigan el homicidio de un jornalero en Fraile Pintado")
        self.assertLessEqual(len(iv.titular_placa("uno " * 30).split()), iv.MAXIMO_PALABRAS_TITULAR)

    def test_carrusel_3_a_5_placas_y_reel_solo_si_hay_datos(self):
        datos = iv.DatosPieza("Corte de agua en Libertador", "libertador", "Servicios", "servicio")
        texto = "El corte será el martes desde las 8. Afecta a los barrios Alberdi y San Cayetano. Se recomienda reservar agua."
        carrusel = iv.generar_carrusel(datos, texto)
        self.assertTrue(3 <= len(carrusel) <= 5)
        cuadros = iv.cuadros_reel(datos, texto)
        duracion = sum(c.segundos for c in cuadros)
        self.assertTrue(10 <= duracion <= 20)
        self.assertEqual(cuadros[0].tramo, "gancho")
        self.assertEqual(cuadros[0].segundos, 2.0)
        self.assertEqual(cuadros[-1].tramo, "cierre")
        self.assertEqual(iv.cuadros_reel(datos, "Una sola oración corta."), [])

    def test_clima_dolar_no_inventa_valores(self):
        png = iv.generar_pieza_clima_dolar({"fecha_legible": "Viernes 9 de octubre", "clima": None,
                                            "oficial": {"compra": 1400, "venta": 1450}, "blue": None,
                                            "actualizado": "07:30", "fuentes": "Open-Meteo / DolarApi"})
        self.assertEqual(self._tamano(png), (1080, 1350))


if __name__ == "__main__":
    unittest.main()


class TestReelPorCuadros(unittest.TestCase):
    def test_sin_cuadros_no_hay_reel(self):
        from motor_noticias.meta.video import ErrorGeneracionVideo, generar_reel_desde_cuadros

        with patch("motor_noticias.meta.video._verificar_binarios_disponibles"):
            with self.assertRaises(ErrorGeneracionVideo):
                generar_reel_desde_cuadros([], Path(tempfile.gettempdir()) / "x.mp4")

    def test_arma_un_solo_ffmpeg_con_todos_los_cuadros(self):
        from motor_noticias.meta import video

        datos = iv.DatosPieza("Corte de agua en Libertador", "libertador", "Servicios", "servicio")
        texto = "El corte será el martes desde las 8. Afecta a los barrios Alberdi y San Cayetano. Se recomienda reservar agua."
        cuadros = iv.cuadros_reel(datos, texto)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(video, "_verificar_binarios_disponibles"), \
                patch.object(video, "_correr_ffmpeg") as ffmpeg, \
                patch.object(video, "_duracion_real_segundos", return_value=15.0):
            resultado = video.generar_reel_desde_cuadros(cuadros, Path(tmp) / "reel.mp4")
        args = ffmpeg.call_args[0][0]
        self.assertEqual(args.count("-loop"), len(cuadros))
        self.assertEqual((resultado.ancho, resultado.alto), (1080, 1920))


class TestCupoProporcional(unittest.TestCase):
    def test_de_madrugada_no_se_llena_el_dia(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            madrugada = datetime(2026, 10, 9, 1, 30, tzinfo=ZONA_JUJUY)
            temas = ["inflación", "jubilaciones", "rutas", "escuelas", "hospitales", "elecciones", "lluvias", "precios"]
            for i, tema in enumerate(temas):
                momento = (madrugada - timedelta(minutes=10 + i)).astimezone(timezone.utc).isoformat()
                _guardar(db, i, f"Cambios en {tema} en Argentina", fecha_recoleccion=momento)
            portal.completar_seleccion(db, madrugada)
            fecha = madrugada.date().isoformat()
            seleccion = db.portal_seleccion_por_fecha([fecha]).get(fecha, [])
            db.close()
        # 01:30 + 2 h de gracia = 3,5/24 del día: a lo sumo ceil(8*0.146)=2 nacionales.
        self.assertLessEqual(len(seleccion), 2)
