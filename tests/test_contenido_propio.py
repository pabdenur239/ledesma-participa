import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from motor_noticias.contenido_propio import (
    NOMBRE_FUENTE_PROPIA,
    _extraer_agenda,
    _extraer_datos_contexto,
    _extraer_explicador,
    _extraer_servicio,
    detectar_oportunidades,
    detectar_reelaboraciones,
    generar_contenido_propio,
)
from motor_noticias.db import Database
from motor_noticias.models import Estado, Noticia, OrigenIngreso, RevisionEstado
from motor_noticias.redaccion.base import Redactor


class _RedactorFake(Redactor):
    """Simula un redactor que reescribe (no copia) sin llamar a la red."""

    def redactar(self, noticia):
        return (
            f"{noticia.titulo_original} (reescrito)",
            f"Reescritura propia: {(noticia.texto_original or '')[:120]}",
        )


def _guardar_noticia_medio(db, n, nombre_fuente, titulo, texto, territorio="provincial",
                           fecha_recoleccion=None, requiere_revision_especial=False,
                           estado=Estado.PREPARADA.value):
    noticia = Noticia(
        id=None,
        titulo_original=titulo,
        texto_original=texto,
        url_fuente=f"https://{nombre_fuente.lower().replace(' ', '')}.test/nota-{n}",
        url_normalizada=f"https://{nombre_fuente.lower().replace(' ', '')}.test/nota-{n}",
        nombre_fuente=nombre_fuente,
        fecha_fuente="",
        fecha_recoleccion=(fecha_recoleccion or datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)).isoformat(),
        estado=estado,
        hash_contenido=f"hash-medio-{n}",
        territorio=territorio,
        titulo_preparado=titulo,
        texto_preparado=texto,
        requiere_revision_especial=requiere_revision_especial,
    )
    return db.guardar(noticia)

AHORA = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)

CONFIG_PRUEBA = {
    "fuentes_primarias": ["Municipio de Prueba", "Gobierno de Prueba"],
    "max_notas_por_dia": 3,
    "ventana_horas": 48,
    "palabras_clave_servicio": ["corte de", "cronograma", "vencimiento", "trámite"],
}


def _guardar_noticia_fuente(db, n, nombre_fuente, titulo, texto, fecha_recoleccion=None, localidad=None):
    noticia = Noticia(
        id=None,
        titulo_original=titulo,
        texto_original=texto,
        url_fuente=f"https://fuente-oficial.test/nota-{n}",
        url_normalizada=f"https://fuente-oficial.test/nota-{n}",
        nombre_fuente=nombre_fuente,
        fecha_fuente="",
        fecha_recoleccion=(fecha_recoleccion or AHORA).isoformat(),
        estado=Estado.PREPARADA.value,
        hash_contenido=f"hash-{n}",
        localidad=localidad,
    )
    return db.guardar(noticia)


class TestExtractores(unittest.TestCase):
    """Cada extractor: no inventa — si el patrón no está, devuelve None."""

    def test_extraer_servicio_encuentra_palabra_clave_y_cita_la_oracion(self):
        texto = (
            "El municipio informa novedades generales. Se realizará un corte de agua programado "
            "el jueves en el barrio Centro por trabajos de mantenimiento. Se pide disculpas."
        )
        resultado = _extraer_servicio("Aviso a vecinos", texto, ["corte de"])
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["etiqueta"], "Corte de servicio")
        self.assertIn("corte de agua programado", resultado["oracion"])

    def test_extraer_servicio_sin_palabra_clave_devuelve_none(self):
        texto = "El intendente participó de una reunión de gabinete junto a su equipo."
        self.assertIsNone(_extraer_servicio("Reunión de gabinete", texto, ["corte de", "vencimiento"]))

    def test_extraer_agenda_con_fecha_explicita(self):
        resultado = _extraer_agenda(
            "Mesa de trabajo sobre discapacidad",
            "Será el 25 de agosto en la sede central, con participación de instituciones.",
        )
        self.assertIsNotNone(resultado)
        self.assertIn("25 de agosto", resultado["cuando"])

    def test_extraer_agenda_con_dia_de_semana_y_hora(self):
        resultado = _extraer_agenda(
            "Entrenamiento abierto",
            "El equipo entrenará este sábado en el estadio municipal, de 10 a 12 horas, entrada libre.",
        )
        self.assertIsNotNone(resultado)
        self.assertIn("sábado", resultado["cuando"].lower())
        self.assertIsNotNone(resultado["hora"])

    def test_extraer_agenda_sin_fecha_devuelve_none(self):
        self.assertIsNone(_extraer_agenda("Nueva oficina", "Se inauguró una nueva oficina de atención."))

    def test_extraer_datos_contexto_calcula_porcentaje_real(self):
        texto = "La tarifa del servicio aumentó de $1000 a $1250 a partir del nuevo cuadro tarifario."
        resultado = _extraer_datos_contexto(texto)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["valor_anterior"], 1000.0)
        self.assertEqual(resultado["valor_nuevo"], 1250.0)
        self.assertAlmostEqual(resultado["variacion_pct"], 25.0, places=3)

    def test_extraer_datos_contexto_sin_dos_cifras_devuelve_none(self):
        self.assertIsNone(_extraer_datos_contexto("El presupuesto municipal fue aprobado por unanimidad."))

    def test_extraer_explicador_con_frase_de_vigencia(self):
        texto = "La nueva ordenanza rige desde el 1 de septiembre para todos los comercios de la ciudad."
        resultado = _extraer_explicador(texto)
        self.assertIsNotNone(resultado)
        self.assertIn("1 de septiembre", resultado["fecha"])

    def test_extraer_explicador_sin_frase_de_vigencia_devuelve_none(self):
        self.assertIsNone(_extraer_explicador("El intendente anunció obras para el próximo año."))


class TestDetectarOportunidades(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_ignora_fuentes_que_no_son_primarias(self):
        _guardar_noticia_fuente(
            self.db, 1, "Un Medio Cualquiera",
            "Corte de luz programado", "Habrá un corte de agua este jueves en el centro.",
        )
        candidatas = detectar_oportunidades(self.db, ahora=AHORA, config=CONFIG_PRUEBA)
        self.assertEqual(candidatas, [])

    def test_detecta_servicio_de_fuente_primaria(self):
        _guardar_noticia_fuente(
            self.db, 1, "Municipio de Prueba",
            "Aviso a vecinos", "Se realizará un corte de agua programado el jueves en el barrio Centro.",
        )
        candidatas = detectar_oportunidades(self.db, ahora=AHORA, config=CONFIG_PRUEBA)
        self.assertEqual(len(candidatas), 1)
        self.assertEqual(candidatas[0].tipo, "servicio")
        self.assertIn("corte de agua programado", candidatas[0].texto)
        self.assertIn("fuente-oficial.test/nota-1", candidatas[0].texto)  # cita la URL real

    def test_una_noticia_sin_ningun_patron_no_genera_nada(self):
        _guardar_noticia_fuente(
            self.db, 1, "Municipio de Prueba",
            "Reunión de gabinete", "El intendente participó de una reunión de gabinete con su equipo.",
        )
        candidatas = detectar_oportunidades(self.db, ahora=AHORA, config=CONFIG_PRUEBA)
        self.assertEqual(candidatas, [])

    def test_agenda_compila_varios_items_en_una_sola_nota(self):
        _guardar_noticia_fuente(
            self.db, 1, "Municipio de Prueba", "Torneo local",
            "Se disputará este sábado en el polideportivo municipal, entrada libre.",
        )
        _guardar_noticia_fuente(
            self.db, 2, "Gobierno de Prueba", "Feria de ciencias",
            "Se realizará el 25 de agosto en el centro cultural provincial.",
        )
        candidatas = detectar_oportunidades(self.db, ahora=AHORA, config=CONFIG_PRUEBA)
        agenda = [c for c in candidatas if c.tipo == "agenda"]
        self.assertEqual(len(agenda), 1)
        self.assertIn("Torneo local", agenda[0].texto)
        self.assertIn("Feria de ciencias", agenda[0].texto)

    def test_respeta_prioridad_territorial_local_antes_que_provincial(self):
        _guardar_noticia_fuente(
            self.db, 1, "Gobierno de Prueba", "Trámite provincial",
            "Nuevo trámite disponible en la oficina provincial.",
            fecha_recoleccion=AHORA,
        )
        _guardar_noticia_fuente(
            self.db, 2, "Municipio de Prueba", "Trámite municipal",
            "Nuevo trámite disponible en la oficina municipal.",
            fecha_recoleccion=AHORA - timedelta(minutes=1),
        )
        candidatas = detectar_oportunidades(self.db, ahora=AHORA, config=CONFIG_PRUEBA)
        # El municipal (fuente LOCAL) va primero aunque sea levemente más viejo.
        self.assertEqual(candidatas[0].fuente_real_nombre, "Municipio de Prueba")

    def test_no_reutiliza_una_noticia_fuente_ya_usada_en_una_nota_previa(self):
        _guardar_noticia_fuente(
            self.db, 1, "Municipio de Prueba", "Aviso a vecinos",
            "Se realizará un corte de agua programado el jueves en el barrio Centro.",
        )
        primera = detectar_oportunidades(self.db, ahora=AHORA, config=CONFIG_PRUEBA)
        self.assertEqual(len(primera), 1)
        # Simula que ya se generó la nota real (misma URL de identidad determinística).
        noticia_propia = Noticia(
            id=None, titulo_original=primera[0].titulo, texto_original=primera[0].texto,
            url_fuente=primera[0].url_identidad, url_normalizada=primera[0].url_identidad,
            nombre_fuente=NOMBRE_FUENTE_PROPIA, fecha_fuente="", fecha_recoleccion=AHORA.isoformat(),
            estado=Estado.PREPARADA.value, hash_contenido="hash-propia-1",
            origen_ingreso=OrigenIngreso.CONTENIDO_PROPIO.value,
        )
        self.db.guardar(noticia_propia)

        segunda = detectar_oportunidades(self.db, ahora=AHORA, config=CONFIG_PRUEBA)
        self.assertEqual(segunda, [])


class TestGenerarContenidoPropio(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_genera_nota_marcada_contenido_propio_y_pendiente_de_revision(self):
        _guardar_noticia_fuente(
            self.db, 1, "Municipio de Prueba", "Aviso a vecinos",
            "Se realizará un corte de agua programado el jueves en el barrio Libertador General San Martín.",
        )
        resultados = generar_contenido_propio(self.db, ahora=AHORA, config=CONFIG_PRUEBA)
        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0].resultado, "preparada")

        noticia = self.db.obtener(resultados[0].noticia_id)
        self.assertEqual(noticia["origen_ingreso"], OrigenIngreso.CONTENIDO_PROPIO.value)
        # Nunca se aprueba sola: mismo circuito de revisión humana que cualquier otra noticia.
        self.assertEqual(noticia["revision_estado"], RevisionEstado.PENDIENTE.value)
        self.assertEqual(noticia["estado"], Estado.PREPARADA.value)

    def test_no_supera_el_tope_diario_acumulado_entre_corridas(self):
        # Fuentes locales -> las notas quedan `preparada` (útiles): el cupo
        # diario cuenta esas, no los borradores descartados.
        for n in range(1, 6):
            _guardar_noticia_fuente(
                self.db, n, "Municipio de Prueba", f"Aviso {n}",
                f"Se realizará un corte de agua programado el jueves en Libertador "
                f"General San Martín, sector {n}.",
            )
        primera_corrida = generar_contenido_propio(self.db, ahora=AHORA, config=CONFIG_PRUEBA)
        self.assertEqual(
            sum(1 for r in primera_corrida if r.resultado == "preparada"), 3
        )  # tope de la config de prueba

        segunda_corrida = generar_contenido_propio(self.db, ahora=AHORA, config=CONFIG_PRUEBA)
        self.assertEqual(segunda_corrida, [])  # ya se alcanzó el tope del día, no genera una 4ta

    def test_sin_candidatas_no_genera_nada(self):
        _guardar_noticia_fuente(
            self.db, 1, "Municipio de Prueba", "Reunión de gabinete",
            "El intendente participó de una reunión de gabinete con su equipo.",
        )
        resultados = generar_contenido_propio(self.db, ahora=AHORA, config=CONFIG_PRUEBA)
        self.assertEqual(resultados, [])

    def test_compite_normalmente_en_la_cascada_sin_franja_reservada(self):
        # A diferencia de institucional/resumen del día, una nota propia no
        # tiene territorio reservado: usa la clasificación territorial real
        # del pipeline, como cualquier otra noticia.
        _guardar_noticia_fuente(
            self.db, 1, "Municipio de Prueba", "Aviso a vecinos",
            "Se realizará un corte de agua programado el jueves en Libertador General San Martín.",
            localidad="Libertador General San Martín",
        )
        resultados = generar_contenido_propio(self.db, ahora=AHORA, config=CONFIG_PRUEBA)
        noticia = self.db.obtener(resultados[0].noticia_id)
        self.assertNotEqual(noticia["territorio"], "institucional")
        self.assertIsNotNone(noticia["territorio"])


CONFIG_MEDIOS = {
    "fuentes_primarias": ["Municipio de Prueba"],
    "fuentes_medios": ["Medio Provincial", "Medio Nacional", "Medio Local"],
    "reelaboracion_habilitada": True,
    "max_notas_por_dia": 12,
    "ventana_horas": 48,
    "palabras_clave_servicio": ["corte de"],
}
AHORA_MEDIOS = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)


class TestDetectarReelaboraciones(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_toma_una_nota_provincial_de_un_medio(self):
        _guardar_noticia_medio(self.db, 1, "Medio Provincial", "Suba de tarifas en Jujuy",
                               "El Gobierno provincial confirmó un aumento del transporte. " * 4)
        cs = detectar_reelaboraciones(self.db, ahora=AHORA_MEDIOS, config=CONFIG_MEDIOS)
        self.assertEqual(len(cs), 1)
        self.assertEqual(cs[0].tipo, "reelaboracion")
        self.assertEqual(cs[0].fuente_real_nombre, "Medio Provincial")
        self.assertIn("medioprovincial.test/nota-1", cs[0].fuente_real_url)

    def test_ignora_local_y_departamental(self):
        _guardar_noticia_medio(self.db, 1, "Medio Local", "Obra en Libertador",
                               "Vecinos de Libertador reclaman. " * 4, territorio="local")
        self.assertEqual(detectar_reelaboraciones(self.db, ahora=AHORA_MEDIOS, config=CONFIG_MEDIOS), [])

    def test_ignora_riesgo_editorial_obligatorio(self):
        _guardar_noticia_medio(self.db, 1, "Medio Provincial", "Caso judicial en Jujuy",
                               "El imputado fue detenido. " * 4, requiere_revision_especial=True)
        self.assertEqual(detectar_reelaboraciones(self.db, ahora=AHORA_MEDIOS, config=CONFIG_MEDIOS), [])

    def test_ignora_fuente_que_no_es_medio_configurado(self):
        _guardar_noticia_medio(self.db, 1, "Blog Random", "Algo", "Texto largo. " * 6)
        self.assertEqual(detectar_reelaboraciones(self.db, ahora=AHORA_MEDIOS, config=CONFIG_MEDIOS), [])

    def test_ignora_contenido_de_apuestas_o_seo(self):
        _guardar_noticia_medio(self.db, 1, "Medio Provincial",
                               "Los mejores casinos con ruleta en 2026",
                               "Analizamos los sitios de apuestas y su código promocional. " * 4)
        self.assertEqual(detectar_reelaboraciones(self.db, ahora=AHORA_MEDIOS, config=CONFIG_MEDIOS), [])

    def test_ignora_politica_partidaria_y_temas_fuera_del_allowlist(self):
        _guardar_noticia_medio(self.db, 1, "Medio Provincial",
                               "Internas del PJ: la Justicia Electoral definió el cronograma",
                               "El peronismo provincial discute la interna partidaria de cara a los comicios. " * 3)
        _guardar_noticia_medio(self.db, 2, "Medio Provincial",
                               "Choque en la esquina del centro",
                               "Un auto y una moto colisionaron esta madrugada sin heridos de gravedad. " * 3)
        self.assertEqual(detectar_reelaboraciones(self.db, ahora=AHORA_MEDIOS, config=CONFIG_MEDIOS), [])

    def test_no_reelabora_dos_notas_del_mismo_hecho_con_titulos_distintos(self):
        _guardar_noticia_medio(self.db, 1, "Medio Provincial",
                               "Así se vio el eclipse lunar en Jujuy",
                               "El eclipse total de luna se observó con cielo despejado en toda la provincia de Jujuy. " * 3)
        _guardar_noticia_medio(self.db, 2, "Medio Provincial",
                               "Fotos de la luna de sangre",
                               "El eclipse total de luna se observó con cielo despejado en toda la provincia de Jujuy anoche. " * 3)
        cs = detectar_reelaboraciones(self.db, ahora=AHORA_MEDIOS, config=CONFIG_MEDIOS)
        self.assertEqual(len(cs), 1)

    def test_no_reelabora_dos_veces_la_misma_nota(self):
        _guardar_noticia_medio(self.db, 1, "Medio Provincial", "Suba de tarifas en Jujuy",
                               "Aumento confirmado del transporte provincial. " * 4)
        with patch("motor_noticias.contenido_propio.crear_redactor", return_value=_RedactorFake()):
            generar_contenido_propio(self.db, ahora=AHORA_MEDIOS, config=CONFIG_MEDIOS)
        self.assertEqual(detectar_reelaboraciones(self.db, ahora=AHORA_MEDIOS, config=CONFIG_MEDIOS), [])

    def test_no_reelabora_un_hecho_ya_en_la_agenda_de_hoy(self):
        src = _guardar_noticia_medio(self.db, 1, "Medio Provincial",
                                     "Suba de tarifas de colectivo en Jujuy",
                                     "Aumento del boleto confirmado por el Gobierno. " * 4)
        self.db.guardar_agenda_item("2026-08-21", "15:00", "normal", "provincial", src,
                                    AHORA_MEDIOS.isoformat())
        self.assertEqual(detectar_reelaboraciones(self.db, ahora=AHORA_MEDIOS, config=CONFIG_MEDIOS), [])


class TestGenerarReelaboracion(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_genera_nota_propia_con_atribucion_y_traza_sin_duplicar_la_original(self):
        src = _guardar_noticia_medio(
            self.db, 1, "Medio Provincial", "Aumento en el boleto de colectivo en Jujuy",
            "El Gobierno provincial confirmó la actualización de la tarifa del transporte urbano. " * 3,
            territorio="provincial",
        )
        with patch("motor_noticias.contenido_propio.crear_redactor", return_value=_RedactorFake()):
            resultados = generar_contenido_propio(self.db, ahora=AHORA_MEDIOS, config=CONFIG_MEDIOS)

        reelab = [r for r in resultados if r.tipo == "reelaboracion"]
        self.assertEqual(len(reelab), 1)
        self.assertEqual(reelab[0].resultado, "preparada")  # no la trató como duplicado de la original
        nota = self.db.obtener(reelab[0].noticia_id)
        self.assertEqual(nota["origen_ingreso"], OrigenIngreso.CONTENIDO_PROPIO.value)
        self.assertIn("(reescrito)", nota["titulo_preparado"])
        self.assertIn("Fuente: Medio Provincial", nota["texto_preparado"])
        self.assertEqual(nota["url_fuente"], self.db.obtener(src)["url_fuente"])  # atribución real
        self.assertEqual(nota["observacion_interna"], f"reelaboracion_de:{src}")
        self.assertIn(src, self.db.ids_fuente_reelaborados())

    def test_redactor_no_disponible_no_rompe_la_corrida(self):
        _guardar_noticia_medio(self.db, 1, "Medio Provincial", "Nueva tarifa de transporte",
                               "El Gobierno provincial confirmó la actualizacion de la tarifa del colectivo. " * 4)
        from motor_noticias.redaccion.ollama import ErrorRedaccionOllama

        class _RedactorCaido(Redactor):
            def redactar(self, noticia):
                raise ErrorRedaccionOllama("Ollama no responde")

        with patch("motor_noticias.contenido_propio.crear_redactor", return_value=_RedactorCaido()):
            resultados = generar_contenido_propio(self.db, ahora=AHORA_MEDIOS, config=CONFIG_MEDIOS)
        self.assertEqual([r for r in resultados if r.tipo == "reelaboracion"], [])


if __name__ == "__main__":
    unittest.main()
