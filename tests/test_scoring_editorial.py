"""Scoring editorial único (2/10/2026): selección de franjas por puntaje,
circuito inmediato (local fuerte / provincial-nacional extraordinaria) e
identidad visual roja reservada a URGENTES."""
import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from motor_noticias.db import Database
from motor_noticias.meta import imagen as modulo_imagen
from motor_noticias.meta.imagen import COLOR_MARCA, generar_placa, generar_placa_urgente
from motor_noticias.meta.preparacion import preparar_publicacion
from motor_noticias.models import Estado
from motor_noticias.motor_editorial import (
    HORA_INFORME_DIARIO,
    HORA_INSTITUCIONAL_RESERVADA,
    HORARIOS_DEFAULT,
    generar_agenda,
)
from motor_noticias.pipeline import ejecutar_pipeline
from motor_noticias.redaccion.mock import RedactorMock
from motor_noticias.scoring_editorial import evaluar_noticia
from tests.test_motor_editorial import AHORA, _crear_noticia

FECHA = "2026-08-12"

LOCAL_FUERTE = "Corte total de ruta 34 en Libertador General San Martín por un choque grave con heridos"
LOCAL_DEBIL = "El intendente de Libertador General San Martín recibió a una delegación en una reunión protocolar"
NACIONAL_EXTRAORDINARIA = "El Gobierno nacional anunció una devaluación del peso y salto del dólar en todo el país"
NACIONAL_COMUN = "El Gobierno nacional presentó un informe de gestión del ministerio"
PROVINCIAL_RELEVANTE = "El gobierno de Jujuy confirmó aumento de tarifas de luz desde el mes próximo"
PROVINCIAL_EXTRAORDINARIA = "Alerta naranja por tormentas fuertes y granizo en toda la provincia de Jujuy"


def _noticia_dict(titulo, territorio, horas=1, origen="automatico"):
    return {
        "titulo_original": titulo, "texto_original": "", "territorio": territorio,
        "fecha_recoleccion": (AHORA - timedelta(hours=horas)).isoformat(), "origen_ingreso": origen,
    }


def _proporcion_roja(png_o_ruta, caja=None) -> float:
    img = Image.open(png_o_ruta if isinstance(png_o_ruta, (str, Path)) else io.BytesIO(png_o_ruta)).convert("RGB")
    if caja:
        img = img.crop(caja)
    img = img.resize((100, 100))
    datos = img.tobytes()
    pixeles = [datos[i:i + 3] for i in range(0, len(datos), 3)]
    return sum(1 for r, g, b in pixeles if r > 150 and g < 60 and b < 60) / len(pixeles)


class BaseScoring(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")
        self.parche_placas = patch.object(modulo_imagen, "DIRECTORIO_PLACAS_DEFAULT", Path(self.tmpdir.name))
        self.parche_placas.start()

    def tearDown(self):
        self.parche_placas.stop()
        self.db.close()
        self.tmpdir.cleanup()

    def _agenda(self, horarios=("23:00",), solo_prioritarios=True):
        with patch("motor_noticias.motor_editorial._solo_territorios_prioritarios", return_value=solo_prioritarios):
            return generar_agenda(self.db, fecha=FECHA, horarios=horarios, ahora=AHORA)


class TestCircuitoInmediato(BaseScoring):
    def _ingresar(self, titulo, url):
        item = {"titulo": titulo, "texto": titulo + ". Información confirmada por la fuente.",
                "url": url, "fuente": "Fuente de prueba", "fecha": ""}

        class _Colector:
            def recolectar(self_inner):
                return [item]

        return ejecutar_pipeline(self.db, _Colector(), RedactorMock())[0]

    # 1
    def test_local_fuerte_entra_al_circuito_inmediato(self):
        noticia, resultado = self._ingresar(LOCAL_FUERTE, "https://ejemplo.test/fuerte")
        self.assertEqual(resultado, "preparada")
        self.assertEqual(noticia.territorio, "local")
        self.assertTrue(noticia.urgente)
        evaluacion = evaluar_noticia(_noticia_dict(LOCAL_FUERTE, "local"), AHORA)
        self.assertEqual(evaluacion["clasificacion"], "urgente")
        self.assertGreaterEqual(evaluacion["base"], 70)

    # 2
    def test_local_debil_no_entra_inmediatamente(self):
        noticia, resultado = self._ingresar(LOCAL_DEBIL, "https://ejemplo.test/debil")
        self.assertEqual(resultado, "preparada")
        self.assertEqual(noticia.territorio, "local")
        self.assertFalse(noticia.urgente)
        self.assertEqual(evaluar_noticia(_noticia_dict(LOCAL_DEBIL, "local"), AHORA)["clasificacion"], "normal")

    def test_local_debil_marcada_urgente_por_regla_anterior_no_sale_de_inmediato(self):
        _crear_noticia(self.db, "local", urgente=True, titulo=LOCAL_DEBIL)
        self.assertFalse(any(e.tipo == "urgente" for e in self._agenda()))

    # 8
    def test_nacional_comun_no_se_clasifica_urgente(self):
        self.assertNotEqual(evaluar_noticia(_noticia_dict(NACIONAL_COMUN, "nacional"), AHORA)["clasificacion"], "urgente")
        _crear_noticia(self.db, "nacional", urgente=True, titulo=NACIONAL_COMUN)
        self.assertFalse(any(e.tipo == "urgente" for e in self._agenda()))

    def test_policial_comun_no_es_urgente(self):
        evaluacion = evaluar_noticia(_noticia_dict("Robo en un comercio de Libertador", "local"), AHORA)
        self.assertNotEqual(evaluacion["clasificacion"], "urgente")

    # 9
    def test_nacional_extraordinaria_puede_salir_inmediatamente(self):
        evaluacion = evaluar_noticia(_noticia_dict(NACIONAL_EXTRAORDINARIA, "nacional"), AHORA)
        self.assertEqual(evaluacion["clasificacion"], "urgente")
        noticia = _crear_noticia(self.db, "nacional", urgente=True, titulo=NACIONAL_EXTRAORDINARIA)
        urgentes = [e for e in self._agenda() if e.tipo == "urgente"]
        self.assertEqual([e.noticia_id for e in urgentes], [noticia.id])

    def test_provincial_relevante_es_importante_pero_no_urgente(self):
        evaluacion = evaluar_noticia(_noticia_dict(PROVINCIAL_RELEVANTE, "provincial"), AHORA)
        self.assertEqual(evaluacion["clasificacion"], "importante")

    def test_provincial_extraordinaria_puede_salir_inmediatamente(self):
        evaluacion = evaluar_noticia(_noticia_dict(PROVINCIAL_EXTRAORDINARIA, "provincial"), AHORA)
        self.assertEqual(evaluacion["clasificacion"], "urgente")

    # 6
    def test_noticia_publicada_inmediatamente_no_vuelve_a_salir(self):
        urgente = _crear_noticia(self.db, "local", urgente=True, titulo=LOCAL_FUERTE)
        primera = self._agenda()
        self.assertEqual([e.noticia_id for e in primera if e.tipo == "urgente"], [urgente.id])
        self.db.actualizar_estado_noticia(urgente.id, Estado.PUBLICADA.value)

        segunda = self._agenda(horarios=HORARIOS_DEFAULT)
        self.assertFalse(any(e.tipo == "urgente" for e in segunda))
        self.assertNotIn(urgente.id, [e.noticia_id for e in segunda if e.tipo == "normal"])
        self.assertEqual(len([i for i in self.db.listar_agenda(FECHA) if i["tipo"] == "urgente"]), 1)

    def test_urgente_no_preparada_no_reentra_aunque_siga_en_agenda(self):
        # Reintentos: una urgente ya reservada queda en `usados` y nunca se
        # vuelve a proponer como nueva.
        _crear_noticia(self.db, "local", urgente=True, titulo=LOCAL_FUERTE)
        self._agenda()
        self._agenda()
        self.assertEqual(len([i for i in self.db.listar_agenda(FECHA) if i["tipo"] == "urgente"]), 1)

    # 7
    def test_deduplicacion_sigue_funcionando(self):
        _, primero = self._ingresar(LOCAL_FUERTE, "https://ejemplo.test/dup")
        _, segundo = self._ingresar(LOCAL_FUERTE, "https://ejemplo.test/dup")
        self.assertEqual(primero, "preparada")
        self.assertEqual(segundo, "duplicado")


class TestSeleccionDeFranjas(BaseScoring):
    # 3
    def test_nacional_muy_importante_supera_a_local_mediocre(self):
        _crear_noticia(self.db, "local", titulo=LOCAL_DEBIL)
        nacional = _crear_noticia(self.db, "nacional", titulo=NACIONAL_EXTRAORDINARIA)
        normales = [e for e in self._agenda() if e.tipo == "normal"]
        self.assertEqual(normales[0].noticia_id, nacional.id)

    # 4
    def test_provincial_muy_relevante_supera_a_local_menor(self):
        _crear_noticia(self.db, "local", titulo=LOCAL_DEBIL)
        provincial = _crear_noticia(self.db, "provincial", titulo=PROVINCIAL_RELEVANTE)
        entradas = self._agenda()
        self.assertEqual(entradas[0].noticia_id, provincial.id)

    # 5
    def test_a_relevancia_similar_gana_la_cercania(self):
        local = _crear_noticia(self.db, "local", titulo="Nueva edición de la feria de artesanos en Libertador")
        _crear_noticia(self.db, "provincial", titulo="Nueva edición de la feria de artesanos en Purmamarca")
        _crear_noticia(self.db, "nacional", titulo="Nueva edición de la feria de artesanos en Mendoza")
        entradas = self._agenda(solo_prioritarios=False)
        self.assertEqual(entradas[0].noticia_id, local.id)

    def test_nacional_comun_sigue_sin_rellenar_en_la_prueba_editorial(self):
        _crear_noticia(self.db, "nacional", titulo=NACIONAL_COMUN)
        self.assertEqual(self._agenda(solo_prioritarios=True)[0].estado, "sin_candidato")

    def test_cada_franja_toma_la_mejor_disponible_en_orden(self):
        debil = _crear_noticia(self.db, "local", titulo=LOCAL_DEBIL)
        nacional = _crear_noticia(self.db, "nacional", titulo=NACIONAL_EXTRAORDINARIA)
        provincial = _crear_noticia(self.db, "provincial", titulo=PROVINCIAL_RELEVANTE)
        entradas = self._agenda(horarios=("21:00", "22:00", "23:00"))
        self.assertEqual([e.noticia_id for e in entradas], [nacional.id, provincial.id, debil.id])

    # 14
    def test_las_6_franjas_existentes_continuan_funcionando(self):
        self.assertEqual(HORARIOS_DEFAULT, ("09:00", "12:00", "16:00", "19:00"))
        self.assertEqual(HORA_INFORME_DIARIO, "07:30")
        self.assertEqual(HORA_INSTITUCIONAL_RESERVADA, "20:30")
        for i in range(len(HORARIOS_DEFAULT)):
            _crear_noticia(self.db, "local", titulo=f"Actividad vecinal número {i} en Libertador")
        ahora = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)  # 06:00 en Jujuy
        with patch("motor_noticias.motor_editorial._solo_territorios_prioritarios", return_value=True):
            entradas = generar_agenda(self.db, fecha=FECHA, ahora=ahora)
        normales = [e for e in entradas if e.tipo == "normal"]
        self.assertEqual([e.hora for e in normales], list(HORARIOS_DEFAULT))
        self.assertTrue(all(e.noticia_id for e in normales))
        self.assertEqual(len({e.noticia_id for e in normales}), len(HORARIOS_DEFAULT))


class TestIdentidadVisualUrgente(BaseScoring):
    def _noticia_aprobada(self, titulo, imagen=None, generada=False):
        return {
            "id": None, "titulo_original": titulo, "texto_original": "Texto de la noticia con datos.",
            "titulo_preparado": titulo, "texto_preparado": "Texto de la noticia con datos.",
            "url_fuente": "https://ejemplo.test/nota", "nombre_fuente": "Fuente de prueba",
            "revision_estado": "aprobada", "requiere_revision_especial": 0, "localidad": "Libertador",
            "imagen_publicacion_ruta": imagen, "tiene_imagen_original": bool(imagen) and not generada,
            "imagen_generada_automaticamente": generada,
        }

    # 10
    def test_noticia_importante_no_urgente_no_usa_rojo(self):
        self.assertEqual(evaluar_noticia(_noticia_dict(PROVINCIAL_RELEVANTE, "provincial"), AHORA)["clasificacion"], "importante")
        contenido = preparar_publicacion(self._noticia_aprobada(PROVINCIAL_RELEVANTE))
        self.assertNotIn("urgente_", Path(contenido.imagen_url).name)
        self.assertLess(_proporcion_roja(contenido.imagen_url), 0.05)

    # 11
    def test_urgente_con_imagen_incorpora_senal_roja_y_conserva_la_foto(self):
        foto = Path(self.tmpdir.name) / "foto.png"
        Image.new("RGB", (1600, 900), (20, 90, 200)).save(foto)
        contenido = preparar_publicacion(self._noticia_aprobada(LOCAL_FUERTE, imagen=str(foto)), urgente=True)
        ruta = contenido.imagen_url
        self.assertTrue(Path(ruta).name.startswith("urgente_"))
        self.assertGreater(_proporcion_roja(ruta, (0, 0, 1080, 230)), 0.6)  # banda roja URGENTE
        centro = Image.open(ruta).convert("RGB").getpixel((540, 500))
        self.assertEqual(centro, (20, 90, 200))  # la foto se conserva

    def test_urgente_con_foto_remota_inaccesible_cae_a_placa_roja(self):
        def _falla(url):
            raise OSError("sin red")

        ruta = generar_placa_urgente(LOCAL_FUERTE, "Fuente", "https://ejemplo.test/foto.jpg", descargar=_falla)
        self.assertGreater(_proporcion_roja(ruta), 0.5)

    # 12
    def test_urgente_sin_imagen_genera_placa_roja(self):
        contenido = preparar_publicacion(self._noticia_aprobada(LOCAL_FUERTE), urgente=True)
        self.assertTrue(Path(contenido.imagen_url).name.startswith("urgente_"))
        self.assertGreater(_proporcion_roja(contenido.imagen_url), 0.5)

    def test_urgente_ignora_placa_normal_generada_y_usa_placa_roja(self):
        placa_normal = generar_placa("Titulo", "Resumen")
        contenido = preparar_publicacion(
            self._noticia_aprobada(LOCAL_FUERTE, imagen=str(placa_normal), generada=True), urgente=True
        )
        self.assertGreater(_proporcion_roja(contenido.imagen_url), 0.5)

    # 13
    def test_noticia_normal_conserva_diseno_habitual(self):
        contenido = preparar_publicacion(self._noticia_aprobada(LOCAL_DEBIL))
        img = Image.open(contenido.imagen_url).convert("RGB")
        self.assertTrue(Path(contenido.imagen_url).name.startswith("placa_"))
        color_marca = tuple(int(COLOR_MARCA[i:i + 2], 16) for i in (1, 3, 5))
        self.assertEqual(img.getpixel((5, 5)), color_marca)
        self.assertLess(_proporcion_roja(contenido.imagen_url), 0.05)

    def test_publicador_usa_rojo_solo_en_clave_urgente(self):
        from motor_noticias.meta import publicador

        llamadas = []

        def _espia(noticia, **kwargs):
            llamadas.append(kwargs.get("urgente"))
            raise publicador.ErrorPreparacionFacebook("corte del test")

        noticia = _crear_noticia(self.db, "local", titulo=LOCAL_FUERTE, revision_estado="aprobada")
        with patch.object(publicador, "preparar_publicacion", side_effect=_espia), \
                patch.object(publicador, "aprobar_si_elegible", side_effect=lambda db, n, ahora=None: n):
            publicador._publicar_noticia_en_clave(self.db, FECHA, "urgente-1", noticia.id, None, None, AHORA)
            publicador._publicar_noticia_en_clave(self.db, FECHA, "09:00", noticia.id, None, None, AHORA)
        self.assertEqual(llamadas, [True, False])


class TestCalibracionUrgentes(unittest.TestCase):
    """Falsos positivos vistos en la app (fútbol, promoción turística,
    teatro como URGENTE) y urgencias reales que deben seguir saliendo."""

    def _clasif(self, titulo, territorio="local", texto="", url="https://ejemplo.test/nota", categoria=None):
        noticia = _noticia_dict(titulo, territorio)
        noticia.update(texto_original=texto, url_fuente=url, categoria_tematica=categoria)
        return evaluar_noticia(noticia, AHORA)

    def test_no_urgentes_aunque_sean_locales(self):
        casos = [
            "Gran final del torneo de fútbol en Libertador",
            "Promocionan escapadas turísticas a Calilegua y el Parque Nacional",
            "Obra de teatro en el Centro Cultural de Libertador",
            "El intendente de Libertador se reunió con vecinos del barrio Norte",
            "Robo en un comercio del centro de Libertador",
            "Se suspendió el partido en Libertador por un corte de luz en el estadio",
            "Festival folclórico en Fraile Pintado con corte de calle",
            "Recomendaciones para evitar cortes de luz en verano en Libertador",
        ]
        for titulo in casos:
            with self.subTest(titulo=titulo):
                self.assertNotEqual(self._clasif(titulo)["clasificacion"], "urgente")

    def test_seccion_de_url_deportiva_impide_urgente(self):
        evaluacion = self._clasif(
            "Barracas Central del apagón el día que inauguraba las luces de su estadio",
            territorio="nacional", url="https://www.lanacion.com.ar/deportes/futbol/nota-nid1/",
        )
        self.assertNotEqual(evaluacion["clasificacion"], "urgente")
        self.assertEqual(evaluacion["tematica"], "deportes")

    def test_bajada_cultural_detectada_con_dos_terminos(self):
        evaluacion = self._clasif(
            "Gran noche en Libertador", texto="Un recital y una muestra de danza reunieron a cientos de vecinos."
        )
        self.assertEqual(evaluacion["tematica"], "cultura")

    def test_urgencias_reales_siguen_siendo_urgentes(self):
        casos = [
            ("Corte de luz en todo Libertador General San Martín hasta la noche", "local"),
            ("Anuncian cortes de energía por tareas de mantenimiento en Fraile Pintado", "departamental"),
            ("Intensa búsqueda de un adolescente desaparecido en Libertador", "local"),
            (LOCAL_FUERTE, "local"),
            ("Suspensión de clases en Libertador por falta de agua", "local"),
            (PROVINCIAL_EXTRAORDINARIA, "provincial"),
            (NACIONAL_EXTRAORDINARIA, "nacional"),
        ]
        for titulo, territorio in casos:
            with self.subTest(titulo=titulo):
                self.assertEqual(self._clasif(titulo, territorio)["clasificacion"], "urgente")

    def test_emergencia_real_en_destino_turistico_sigue_urgente(self):
        evaluacion = self._clasif(
            "Alerta naranja por temporal: evacuan turistas en Purmamarca", territorio="provincial"
        )
        self.assertEqual(evaluacion["clasificacion"], "urgente")


if __name__ == "__main__":
    unittest.main()
