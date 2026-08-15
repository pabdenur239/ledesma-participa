import itertools
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from motor_noticias.db import Database
from motor_noticias.models import Estado, Noticia
from motor_noticias.motor_editorial import (
    ANTIGUEDAD_MAXIMA_HORAS,
    HORARIOS_DEFAULT,
    ZONA_JUJUY,
    generar_agenda,
)
from motor_noticias.verificacion_fuente import ResultadoVerificacionLocal

AHORA = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
_CONTADOR = itertools.count(1)


def _verificador(impacto_local: bool):
    """Verificador de impacto provincial falso para pruebas offline: nunca
    hace red real, devuelve siempre el mismo resultado inyectado."""

    def _fake(titulo_original, url_fuente):
        return ResultadoVerificacionLocal(impacto_local, "prueba")

    return _fake


def _iso(delta: timedelta = timedelta()) -> str:
    return (AHORA - delta).isoformat()


def _crear_noticia(
    db: Database,
    territorio: str,
    fecha_recoleccion: str = None,
    revision_estado: str = "pendiente",
    urgente: bool = False,
    estado: str = Estado.PREPARADA.value,
    titulo: str = None,
) -> Noticia:
    n = next(_CONTADOR)
    titulo = titulo or f"Noticia de prueba {territorio} #{n}"
    noticia = Noticia(
        id=None,
        titulo_original=titulo,
        texto_original="Texto de prueba con contenido suficiente para publicar.",
        url_fuente=f"https://ejemplo.test/{territorio}-{n}",
        url_normalizada=f"https://ejemplo.test/{territorio}-{n}",
        nombre_fuente="Fuente de prueba",
        fecha_fuente="",
        fecha_recoleccion=fecha_recoleccion or _iso(),
        estado=estado,
        hash_contenido=f"hash-{territorio}-{n}",
        relevancia_local=territorio in ("local", "departamental"),
        territorio=territorio,
        motivo_territorio="Clasificación de prueba.",
        revision_estado=revision_estado,
        titulo_preparado=titulo,
        texto_preparado="Texto preparado de prueba.",
        urgente=urgente,
    )
    db.guardar(noticia)
    return noticia


class BaseAgendaTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.db")

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()


class TestCascadaTerritorial(BaseAgendaTest):
    def test_local_antes_que_departamental(self):
        local = _crear_noticia(self.db, "local")
        _crear_noticia(self.db, "departamental")

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        self.assertEqual(entradas[0].noticia_id, local.id)
        self.assertEqual(entradas[0].territorio, "local")

    def test_departamental_antes_que_provincial(self):
        departamental = _crear_noticia(self.db, "departamental")
        _crear_noticia(self.db, "provincial")

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        self.assertEqual(entradas[0].noticia_id, departamental.id)
        self.assertEqual(entradas[0].territorio, "departamental")

    def test_provincial_verificado_se_elige_por_falta_de_local_o_departamental(self):
        provincial = _crear_noticia(self.db, "provincial")

        entradas = generar_agenda(
            self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA,
            verificar_impacto_provincial=_verificador(True),
        )

        self.assertEqual(entradas[0].noticia_id, provincial.id)
        self.assertEqual(entradas[0].territorio, "provincial")

    def test_provincial_sin_verificar_deja_la_franja_vacia(self):
        _crear_noticia(self.db, "provincial")

        entradas = generar_agenda(
            self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA,
            verificar_impacto_provincial=_verificador(False),
        )

        self.assertEqual(entradas[0].estado, "sin_candidato")
        self.assertIsNone(entradas[0].noticia_id)

    def test_nacional_nunca_se_elige_automaticamente(self):
        _crear_noticia(self.db, "nacional")

        entradas = generar_agenda(
            self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA,
            verificar_impacto_provincial=_verificador(True),
        )

        self.assertEqual(entradas[0].estado, "sin_candidato")
        self.assertIsNone(entradas[0].noticia_id)

    def test_provincial_rechazado_no_se_reverifica_en_otra_franja_vacia(self):
        _crear_noticia(self.db, "provincial")
        llamadas = []

        def _verificador_contador(titulo_original, url_fuente):
            llamadas.append(url_fuente)
            return ResultadoVerificacionLocal(False, "prueba")

        generar_agenda(
            self.db, fecha="2026-08-12", horarios=("08:00", "10:30", "13:00"), ahora=AHORA,
            verificar_impacto_provincial=_verificador_contador,
        )

        self.assertEqual(len(llamadas), 1)

    def test_nacional_vacio_sin_ningun_otro_nivel_da_sin_candidato(self):
        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        self.assertEqual(entradas[0].estado, "sin_candidato")
        self.assertIsNone(entradas[0].noticia_id)

    def test_no_elige_nivel_inferior_habiendo_superior_disponible(self):
        # 3 locales y 10 provinciales: deben priorizarse las locales.
        locales = [_crear_noticia(self.db, "local") for _ in range(3)]
        for _ in range(10):
            _crear_noticia(self.db, "provincial")

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=HORARIOS_DEFAULT[:3], ahora=AHORA)

        ids_locales = {n.id for n in locales}
        for entrada in entradas:
            self.assertIn(entrada.noticia_id, ids_locales)
            self.assertEqual(entrada.territorio, "local")


class TestExclusiones(BaseAgendaTest):
    def test_noticia_vieja_excluida(self):
        _crear_noticia(
            self.db, "local", fecha_recoleccion=_iso(timedelta(hours=ANTIGUEDAD_MAXIMA_HORAS + 1))
        )

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        self.assertEqual(entradas[0].estado, "sin_candidato")

    def test_noticia_dentro_de_la_antiguedad_maxima_se_usa(self):
        reciente = _crear_noticia(
            self.db, "local", fecha_recoleccion=_iso(timedelta(hours=ANTIGUEDAD_MAXIMA_HORAS - 1))
        )

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        self.assertEqual(entradas[0].noticia_id, reciente.id)

    def test_noticia_descartada_nunca_es_candidata(self):
        _crear_noticia(self.db, "sin_clasificar", estado=Estado.DESCARTADA.value)

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        self.assertEqual(entradas[0].estado, "sin_candidato")

    def test_noticia_usada_anteriormente_excluida(self):
        local_1 = _crear_noticia(self.db, "local", fecha_recoleccion=_iso(timedelta(minutes=1)))
        local_2 = _crear_noticia(self.db, "local", fecha_recoleccion=_iso(timedelta(minutes=2)))

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00", "10:30"), ahora=AHORA)

        ids_elegidos = {e.noticia_id for e in entradas}
        self.assertEqual(ids_elegidos, {local_1.id, local_2.id})  # ninguna se repite

    def test_noticia_rechazada_no_vuelve_a_proponerse(self):
        _crear_noticia(self.db, "local", revision_estado="rechazada")

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        self.assertEqual(entradas[0].estado, "sin_candidato")


class TestSeisEspacios(BaseAgendaTest):
    def test_seis_espacios_con_candidatos_disponibles(self):
        for _ in range(len(HORARIOS_DEFAULT)):
            _crear_noticia(self.db, "local")

        entradas = generar_agenda(self.db, fecha="2026-08-12", ahora=AHORA)

        self.assertEqual(len(entradas), len(HORARIOS_DEFAULT))
        self.assertTrue(all(e.noticia_id for e in entradas))
        self.assertEqual({e.hora for e in entradas}, set(HORARIOS_DEFAULT))

    def test_sin_candidato_cuando_no_hay_contenido_disponible(self):
        entradas = generar_agenda(self.db, fecha="2026-08-12", ahora=AHORA)

        self.assertEqual(len(entradas), len(HORARIOS_DEFAULT))
        self.assertTrue(all(e.estado == "sin_candidato" for e in entradas))


class TestPersistenciaYDecisionesHumanas(BaseAgendaTest):
    def test_persistencia_de_la_agenda_en_sqlite(self):
        db_path = Path(self.tmpdir.name) / "persistencia.db"
        db1 = Database(db_path)
        _crear_noticia(db1, "local")
        generar_agenda(db1, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)
        db1.close()

        db2 = Database(db_path)
        try:
            items = db2.listar_agenda("2026-08-12")
            self.assertEqual(len(items), 1)
            self.assertIsNotNone(items[0]["noticia_id"])
        finally:
            db2.close()

    def test_aprobada_no_se_reemplaza_al_regenerar(self):
        _crear_noticia(self.db, "local", fecha_recoleccion=_iso(timedelta(hours=2)))
        generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        item = self.db.obtener_agenda_item("2026-08-12", "08:00")
        self.db.actualizar_revision(item["noticia_id"], "aprobada")

        # aparece una noticia local MÁS FRESCA después de aprobar la primera
        mas_fresca = _crear_noticia(self.db, "local", fecha_recoleccion=_iso())

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        self.assertEqual(entradas[0].noticia_id, item["noticia_id"])
        self.assertNotEqual(entradas[0].noticia_id, mas_fresca.id)
        aprobada = self.db.obtener(item["noticia_id"])
        self.assertEqual(aprobada["revision_estado"], "aprobada")

    def test_rechazada_no_se_reemplaza_al_regenerar(self):
        _crear_noticia(self.db, "local", fecha_recoleccion=_iso(timedelta(hours=2)))
        generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        item = self.db.obtener_agenda_item("2026-08-12", "08:00")
        self.db.actualizar_revision(item["noticia_id"], "rechazada")

        mas_fresca = _crear_noticia(self.db, "local", fecha_recoleccion=_iso())

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        # el espacio sigue apuntando a la misma noticia (rechazada) — el
        # sistema no la reemplaza automáticamente por otra.
        self.assertEqual(entradas[0].noticia_id, item["noticia_id"])
        self.assertNotEqual(entradas[0].noticia_id, mas_fresca.id)


class TestReemplazoAutomaticoDePropuestasPendientes(BaseAgendaTest):
    """Una propuesta sin decisión humana (revision_estado='pendiente') puede
    mejorarse automáticamente al regenerar; aprobada/rechazada/publicada no."""

    def test_candidato_asignado_automaticamente_queda_persistido_como_pendiente(self):
        # No existe un estado "propuesta" separado en el modelo de datos: una
        # candidata elegida por la cascada, antes de cualquier decisión
        # humana, se persiste con revision_estado="pendiente" (el mismo valor
        # que ya usaba el resto del panel). El motor la trata como
        # reemplazable automáticamente precisamente porque no es ni
        # "aprobada" ni "rechazada" (lista de protegidos), no porque exista
        # un valor "propuesta" explícito.
        local = _crear_noticia(self.db, "local")

        generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        item = self.db.obtener_agenda_item("2026-08-12", "08:00")
        self.assertEqual(item["noticia_id"], local.id)
        guardada = self.db.obtener(item["noticia_id"])
        self.assertEqual(guardada["revision_estado"], "pendiente")

    def test_propuesta_provincial_reemplazada_por_local(self):
        provincial = _crear_noticia(self.db, "provincial", fecha_recoleccion=_iso(timedelta(hours=2)))
        generar_agenda(
            self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA,
            verificar_impacto_provincial=_verificador(True),
        )
        item_antes = self.db.obtener_agenda_item("2026-08-12", "10:30")
        self.assertEqual(item_antes["noticia_id"], provincial.id)

        local = _crear_noticia(self.db, "local", fecha_recoleccion=_iso())

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)

        self.assertEqual(entradas[0].noticia_id, local.id)
        self.assertEqual(entradas[0].territorio, "local")
        self.assertEqual(entradas[0].estado, "actualizado")

    def test_nacional_nunca_ocupa_la_franja_departamental_la_toma(self):
        _crear_noticia(self.db, "nacional", fecha_recoleccion=_iso(timedelta(hours=2)))
        antes = generar_agenda(self.db, fecha="2026-08-12", horarios=("19:00",), ahora=AHORA)
        self.assertEqual(antes[0].estado, "sin_candidato")

        departamental = _crear_noticia(self.db, "departamental", fecha_recoleccion=_iso())

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("19:00",), ahora=AHORA)

        self.assertEqual(entradas[0].noticia_id, departamental.id)
        self.assertEqual(entradas[0].territorio, "departamental")

    def test_propuesta_local_no_reemplazada_por_provincial(self):
        local = _crear_noticia(self.db, "local", fecha_recoleccion=_iso(timedelta(hours=2)))
        generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        _crear_noticia(self.db, "provincial", fecha_recoleccion=_iso())  # más fresca, pero nivel inferior

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        self.assertEqual(entradas[0].noticia_id, local.id)
        self.assertEqual(entradas[0].territorio, "local")
        self.assertEqual(entradas[0].estado, "existente")

    def test_propuesta_del_mismo_territorio_reemplazada_por_otra_mas_reciente(self):
        # Horario futuro respecto de AHORA (09:00 Jujuy): una franja pasada
        # queda congelada y no se puede usar para probar el reemplazo.
        _crear_noticia(self.db, "local", fecha_recoleccion=_iso(timedelta(hours=2)))
        generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)

        mas_reciente = _crear_noticia(self.db, "local", fecha_recoleccion=_iso())

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)

        self.assertEqual(entradas[0].noticia_id, mas_reciente.id)
        self.assertEqual(entradas[0].estado, "actualizado")

    def test_aprobada_no_reemplazada_aunque_aparezca_mejor_candidato(self):
        provincial = _crear_noticia(self.db, "provincial", fecha_recoleccion=_iso(timedelta(hours=2)))
        generar_agenda(
            self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA,
            verificar_impacto_provincial=_verificador(True),
        )
        item = self.db.obtener_agenda_item("2026-08-12", "10:30")
        self.db.actualizar_revision(item["noticia_id"], "aprobada")

        _crear_noticia(self.db, "local", fecha_recoleccion=_iso())

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)

        self.assertEqual(entradas[0].noticia_id, provincial.id)
        self.assertEqual(entradas[0].estado, "existente")

    def test_rechazada_no_reemplazada_aunque_aparezca_mejor_candidato(self):
        provincial = _crear_noticia(self.db, "provincial", fecha_recoleccion=_iso(timedelta(hours=2)))
        generar_agenda(
            self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA,
            verificar_impacto_provincial=_verificador(True),
        )
        item = self.db.obtener_agenda_item("2026-08-12", "10:30")
        self.db.actualizar_revision(item["noticia_id"], "rechazada")

        _crear_noticia(self.db, "local", fecha_recoleccion=_iso())

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)

        self.assertEqual(entradas[0].noticia_id, provincial.id)
        self.assertEqual(entradas[0].estado, "existente")

    def test_publicada_no_reemplazada_aunque_aparezca_mejor_candidato(self):
        publicada = _crear_noticia(
            self.db, "provincial", fecha_recoleccion=_iso(timedelta(hours=2)), estado=Estado.PUBLICADA.value
        )
        creada_en = _iso(timedelta(hours=2))
        self.db.guardar_agenda_item("2026-08-12", "10:30", "normal", "provincial", publicada.id, creada_en)

        _crear_noticia(self.db, "local", fecha_recoleccion=_iso())

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)

        self.assertEqual(entradas[0].noticia_id, publicada.id)
        self.assertEqual(entradas[0].estado, "existente")

    def test_sin_candidato_pasa_a_propuesta_cuando_aparece_noticia_valida(self):
        entradas_antes = generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)
        self.assertEqual(entradas_antes[0].estado, "sin_candidato")

        departamental = _crear_noticia(self.db, "departamental")

        entradas_despues = generar_agenda(self.db, fecha="2026-08-12", horarios=("10:30",), ahora=AHORA)

        self.assertEqual(entradas_despues[0].noticia_id, departamental.id)
        self.assertEqual(entradas_despues[0].estado, "actualizado")

    def test_regeneracion_identica_no_produce_cambios_innecesarios(self):
        _crear_noticia(self.db, "local")
        generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)
        item_antes = self.db.obtener_agenda_item("2026-08-12", "08:00")

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        item_despues = self.db.obtener_agenda_item("2026-08-12", "08:00")
        self.assertEqual(entradas[0].estado, "existente")
        self.assertEqual(item_antes["noticia_id"], item_despues["noticia_id"])
        self.assertEqual(item_antes["actualizada_en"], item_despues["actualizada_en"])

    def test_regeneracion_identica_sin_candidato_no_produce_cambios(self):
        generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)
        item_antes = self.db.obtener_agenda_item("2026-08-12", "08:00")

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        item_despues = self.db.obtener_agenda_item("2026-08-12", "08:00")
        self.assertEqual(entradas[0].estado, "sin_candidato")
        self.assertEqual(item_antes["actualizada_en"], item_despues["actualizada_en"])


class TestUrgentes(BaseAgendaTest):
    def test_urgente_local_aparece_fuera_de_las_franjas_normales(self):
        urgente = _crear_noticia(self.db, "local", urgente=True)

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        urgentes = [e for e in entradas if e.tipo == "urgente"]
        self.assertEqual(len(urgentes), 1)
        self.assertEqual(urgentes[0].noticia_id, urgente.id)
        self.assertIsNone(urgentes[0].hora)

    def test_urgente_no_se_publica_automaticamente(self):
        urgente = _crear_noticia(self.db, "local", urgente=True)

        generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        noticia = self.db.obtener(urgente.id)
        self.assertEqual(noticia["estado"], Estado.PREPARADA.value)
        self.assertEqual(noticia["revision_estado"], "pendiente")

    def test_urgente_no_local_ni_departamental_no_se_propone_como_urgente(self):
        _crear_noticia(self.db, "provincial", urgente=True)

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        self.assertFalse(any(e.tipo == "urgente" for e in entradas))


class TestFechaYZonaHoraria(BaseAgendaTest):
    def test_fecha_especifica_se_respeta(self):
        _crear_noticia(self.db, "local")

        entradas = generar_agenda(self.db, fecha="2026-08-05", horarios=("08:00",), ahora=AHORA)

        self.assertTrue(all(e.fecha == "2026-08-05" for e in entradas))

    def test_zona_horaria_jujuy_es_utc_menos_3_fija(self):
        self.assertEqual(ZONA_JUJUY.utcoffset(None), timedelta(hours=-3))

    def test_fecha_por_defecto_usa_huso_de_jujuy_no_utc(self):
        # 2026-08-13 01:30 UTC son las 2026-08-12 22:30 en Jujuy (UTC-3):
        # la fecha por defecto de la agenda debe ser la de Jujuy, no la UTC.
        justo_despues_de_medianoche_utc = datetime(2026, 8, 13, 1, 30, tzinfo=timezone.utc)
        _crear_noticia(self.db, "local", fecha_recoleccion=justo_despues_de_medianoche_utc.isoformat())

        entradas = generar_agenda(
            self.db, horarios=("08:00",), ahora=justo_despues_de_medianoche_utc
        )

        self.assertEqual(entradas[0].fecha, "2026-08-12")


class TestIntegracionConMotorContinuo(BaseAgendaTest):
    def test_noticias_recolectadas_por_el_motor_continuo_llegan_a_la_agenda(self):
        from unittest.mock import patch

        from motor_noticias.ciclo_continuo import ejecutar_ciclo
        from motor_noticias.redaccion.mock import RedactorMock

        class ErrorFuenteDePrueba(RuntimeError):
            pass

        def _colector_ok(items):
            class _ColectorDePrueba:
                def recolectar(self):
                    return items

            return _ColectorDePrueba

        item_local = {
            "titulo": "Obras en Libertador General San Martín continúan esta semana",
            "texto": "El municipio informó el avance de las obras en distintos barrios de la ciudad.",
            "url": "https://ejemplo.test/integracion-local",
            "fuente": "Fuente de prueba",
            "fecha": "",
        }
        fuentes_prueba = (("fuente-integracion", _colector_ok([item_local]), ErrorFuenteDePrueba),)

        # agenda_automatica=False: este test aísla el pipeline del motor
        # continuo de la actualización automática de agenda (que tiene su
        # propia cobertura en test_ciclo_continuo.py) para no depender de la
        # fecha/hora real del entorno donde corren los tests.
        with patch("motor_noticias.ciclo_continuo.FUENTES_CONTINUAS", fuentes_prueba):
            ejecutar_ciclo(self.db, RedactorMock(), agenda_automatica=False)

        entradas = generar_agenda(self.db, fecha="2026-08-12", horarios=("08:00",), ahora=AHORA)

        self.assertEqual(entradas[0].estado, "creado")
        self.assertEqual(entradas[0].territorio, "local")
        noticia = self.db.obtener(entradas[0].noticia_id)
        self.assertEqual(noticia["titulo_original"], item_local["titulo"])


if __name__ == "__main__":
    unittest.main()
