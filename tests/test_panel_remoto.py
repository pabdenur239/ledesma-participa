import http.client
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from motor_noticias.db import Database
from motor_noticias.models import RevisionEstado
from motor_noticias.panel import remoto
from motor_noticias.panel.remoto import (
    COOKIE_PRELOGIN,
    COOKIE_SESION,
    EstadoAuth,
    PanelRemotoHandler,
    codigo_totp,
    generar_hash_password,
    generar_secreto_totp,
    verificar_password,
    verificar_totp,
)
from motor_noticias.pipeline import CATEGORIA_SIN_REDACCION_PROPIA
from motor_noticias.redaccion.mock import RedactorMock
from tests.test_canal_rapido_local import TEXTO_LIBERTADOR, TEXTO_SENSIBLE, URL_FB, RedactorCaido

PASSWORD = "clave-de-prueba-larga-123"
ORIGEN = "https://panel.ledesmaparticipa.com.ar"
HASH = generar_hash_password(PASSWORD)


class Reloj:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


class TestPrimitivas(unittest.TestCase):
    def test_totp_vector_rfc6238(self):
        secreto = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # "12345678901234567890"
        self.assertEqual(codigo_totp(secreto, 59 // 30), "287082")

    def test_totp_no_se_reutiliza(self):
        secreto = generar_secreto_totp()
        codigo = codigo_totp(secreto, 1000)
        contador = verificar_totp(secreto, codigo, 1000 * 30 + 5, -1)
        self.assertEqual(contador, 1000)
        self.assertIsNone(verificar_totp(secreto, codigo, 1000 * 30 + 5, contador))
        self.assertIsNone(verificar_totp(secreto, "12345", 1000 * 30, -1))

    def test_hash_password(self):
        self.assertTrue(verificar_password(PASSWORD, HASH))
        self.assertFalse(verificar_password(PASSWORD + "x", HASH))
        self.assertFalse(verificar_password(PASSWORD, "basura"))
        self.assertNotIn(PASSWORD, HASH)


class TestPanelRemotoHTTP(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        Database(self.db_path).close()
        self.reloj = Reloj()
        self.secreto = generar_secreto_totp()
        self.auth = EstadoAuth(HASH, self.secreto, reloj=self.reloj)
        self.parches = [
            patch.object(PanelRemotoHandler, "db_path", self.db_path),
            patch.object(PanelRemotoHandler, "auth", self.auth),
            patch.object(PanelRemotoHandler, "origen", ORIGEN),
            patch.object(PanelRemotoHandler, "redactor", RedactorMock()),
        ]
        for p in self.parches:
            p.start()
        self.servidor = HTTPServer(("127.0.0.1", 0), PanelRemotoHandler)
        self.puerto = self.servidor.server_address[1]
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=5)
        for p in self.parches:
            p.stop()
        self.tmpdir.cleanup()

    # -- utilidades
    def _pedir(self, metodo, ruta, datos=None, cookies=None, origen=ORIGEN, ip="203.0.113.7"):
        conn = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        encabezados = {"Content-Type": "application/x-www-form-urlencoded", "CF-Connecting-IP": ip}
        if origen:
            encabezados["Origin"] = origen
        if cookies:
            encabezados["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
        conn.request(metodo, ruta, body=urlencode(datos) if datos is not None else None, headers=encabezados)
        resp = conn.getresponse()
        texto = resp.read().decode("utf-8")
        conn.close()
        return resp, texto

    @staticmethod
    def _cookie(resp, nombre):
        for valor in resp.headers.get_all("Set-Cookie") or []:
            if valor.startswith(nombre + "="):
                return valor
        return None

    def _codigo(self, desplazamiento=0):
        return codigo_totp(self.secreto, int(self.reloj() // 30) + desplazamiento)

    def _login(self, password=PASSWORD, codigo=None, ip="203.0.113.7"):
        resp, _ = self._pedir("GET", "/login", ip=ip)
        prelogin = self._cookie(resp, COOKIE_PRELOGIN).split(";")[0].split("=", 1)[1]
        return self._pedir(
            "POST", "/login",
            {"prelogin": prelogin, "password": password, "codigo": codigo if codigo is not None else self._codigo()},
            cookies={COOKIE_PRELOGIN: prelogin}, ip=ip,
        )

    def _sesion(self):
        self.reloj.t += 30  # cada login usa un código TOTP nuevo
        resp, _ = self._login()
        self.assertEqual(resp.status, 303)
        token = self._cookie(resp, COOKIE_SESION).split(";")[0].split("=", 1)[1]
        cookies = {COOKIE_SESION: token}
        _, html = self._pedir("GET", "/cargar-noticia-local", cookies=cookies)
        csrf = html.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        return cookies, csrf

    def _noticias(self):
        db = Database(self.db_path)
        try:
            return db.listar()
        finally:
            db.close()

    # -- acceso sin login
    def test_sin_login_redirige_y_no_procesa(self):
        for ruta in ("/cargar-noticia-local", "/noticia?id=1"):
            resp, _ = self._pedir("GET", ruta)
            self.assertEqual(resp.status, 303)
            self.assertEqual(resp.headers["Location"], "/login")
        resp, _ = self._pedir("POST", "/cargar-noticia-local", {"fuente": "Ledesma Soy", "url": URL_FB, "texto": TEXTO_LIBERTADOR})
        self.assertEqual(resp.status, 303)
        self.assertEqual(self._noticias(), [])

    def test_cookie_falsa_no_da_acceso(self):
        resp, _ = self._pedir("GET", "/cargar-noticia-local", cookies={COOKIE_SESION: "inventada"})
        self.assertEqual(resp.status, 303)

    # -- login
    def test_password_incorrecta_denegada(self):
        resp, _ = self._login(password="otra-clave-cualquiera-999")
        self.assertEqual(resp.status, 401)
        self.assertIsNone(self._cookie(resp, COOKIE_SESION))

    def test_totp_incorrecto_denegado(self):
        resp, _ = self._login(codigo="000000" if self._codigo() != "000000" else "111111")
        self.assertEqual(resp.status, 401)
        self.assertIsNone(self._cookie(resp, COOKIE_SESION))

    def test_totp_reutilizado_denegado(self):
        codigo = self._codigo()
        self.assertEqual(self._login(codigo=codigo)[0].status, 303)
        self.assertEqual(self._login(codigo=codigo)[0].status, 401)

    def test_login_sin_token_prelogin_rechazado(self):
        resp, _ = self._pedir("POST", "/login", {"password": PASSWORD, "codigo": self._codigo()})
        self.assertEqual(resp.status, 403)

    def test_sin_credenciales_configuradas_falla_cerrado(self):
        with patch.object(PanelRemotoHandler, "auth", EstadoAuth(None, None, reloj=self.reloj)):
            resp, _ = self._login()
        self.assertEqual(resp.status, 503)
        self.assertIsNone(self._cookie(resp, COOKIE_SESION))

    def test_sesion_valida_y_cookie_segura(self):
        resp, _ = self._login()
        self.assertEqual(resp.status, 303)
        cookie = self._cookie(resp, COOKIE_SESION)
        for atributo in ("Secure", "HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(atributo, cookie)
        cookies, _ = self._sesion()
        resp, html = self._pedir("GET", "/cargar-noticia-local", cookies=cookies)
        self.assertEqual(resp.status, 200)
        self.assertIn("PROCESAR", html)
        for ruta in ("/estado", "/agenda", "/crecimiento", 'href="/"'):
            self.assertNotIn(ruta, html)
        self.assertEqual(resp.headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", resp.headers["Content-Security-Policy"])
        self.assertEqual(resp.headers["Cache-Control"], "no-store")

    def test_sesion_vence_por_inactividad(self):
        cookies, _ = self._sesion()
        self.reloj.t += remoto.SESION_INACTIVIDAD_SEGUNDOS + 1
        self.assertEqual(self._pedir("GET", "/cargar-noticia-local", cookies=cookies)[0].status, 303)

    def test_logout_invalida_sesion(self):
        cookies, csrf = self._sesion()
        resp, _ = self._pedir("POST", "/logout", {"csrf": csrf}, cookies=cookies)
        self.assertEqual(resp.status, 303)
        self.assertEqual(self._pedir("GET", "/cargar-noticia-local", cookies=cookies)[0].status, 303)

    def test_reinicio_invalida_sesiones(self):
        cookies, _ = self._sesion()
        with patch.object(PanelRemotoHandler, "auth", EstadoAuth(HASH, self.secreto, reloj=self.reloj)):
            self.assertEqual(self._pedir("GET", "/cargar-noticia-local", cookies=cookies)[0].status, 303)

    # -- rutas
    def test_rutas_administrativas_404(self):
        cookies, csrf = self._sesion()
        for ruta in ("/", "/estado", "/agenda", "/crecimiento", "/cargar-noticia", "/facebook?id=1", "/placas/placa_ab.png", "/config"):
            for c in (None, cookies):
                self.assertEqual(self._pedir("GET", ruta, cookies=c)[0].status, 404, ruta)
            self.assertEqual(self._pedir("POST", ruta, {"csrf": csrf}, cookies=cookies)[0].status, 404, ruta)

    def test_carga_local_con_sesion(self):
        cookies, csrf = self._sesion()
        resp, html = self._pedir(
            "POST", "/cargar-noticia-local",
            {"csrf": csrf, "fuente": "Ledesma Soy", "url": URL_FB, "texto": TEXTO_LIBERTADOR}, cookies=cookies,
        )
        self.assertEqual(resp.status, 200)
        self.assertIn("resultado", html)
        self.assertEqual(len(self._noticias()), 1)
        resp, html = self._pedir("GET", f"/noticia?id={self._noticias()[0]['id']}", cookies=cookies)
        self.assertEqual(resp.status, 200)
        self.assertNotIn('value="aprobar"', html)
        self.assertNotIn('value="rechazar"', html)
        self.assertNotIn('value="guardar"', html)

    # -- CSRF
    def test_csrf_faltante_o_incorrecto(self):
        cookies, csrf = self._sesion()
        datos = {"fuente": "Ledesma Soy", "url": URL_FB, "texto": TEXTO_LIBERTADOR}
        self.assertEqual(self._pedir("POST", "/cargar-noticia-local", datos, cookies=cookies)[0].status, 403)
        self.assertEqual(self._pedir("POST", "/cargar-noticia-local", {**datos, "csrf": "x"}, cookies=cookies)[0].status, 403)
        self.assertEqual(
            self._pedir("POST", "/cargar-noticia-local", {**datos, "csrf": csrf}, cookies=cookies, origen="https://otro.sitio")[0].status,
            403,
        )
        self.assertEqual(
            self._pedir("POST", "/cargar-noticia-local", {**datos, "csrf": csrf}, cookies=cookies, origen=None)[0].status, 403
        )
        self.assertEqual(self._noticias(), [])

    # -- modo limitado
    def test_aprobar_nota_sensible_bloqueado(self):
        cookies, csrf = self._sesion()
        self._pedir("POST", "/cargar-noticia-local",
                    {"csrf": csrf, "fuente": "Ledesma Soy", "url": URL_FB, "texto": TEXTO_SENSIBLE}, cookies=cookies)
        noticia = self._noticias()[0]
        self.assertTrue(noticia["requiere_revision_especial"])
        for accion in ("aprobar", "rechazar", "guardar"):
            resp, _ = self._pedir("POST", f"/noticia?id={noticia['id']}",
                                  {"csrf": csrf, "accion": accion, "texto_revisado": "x"}, cookies=cookies)
            self.assertEqual(resp.status, 403, accion)
        despues = self._noticias()[0]
        self.assertEqual(despues["revision_estado"], RevisionEstado.PENDIENTE.value)
        self.assertIsNone(despues["texto_revisado"])

    def test_reintentar_redaccion_desde_remoto(self):
        cookies, csrf = self._sesion()
        with patch.object(PanelRemotoHandler, "redactor", RedactorCaido()):
            self._pedir("POST", "/cargar-noticia-local",
                        {"csrf": csrf, "fuente": "Ledesma Soy", "url": URL_FB, "texto": TEXTO_LIBERTADOR}, cookies=cookies)
        noticia = self._noticias()[0]
        self.assertEqual(noticia["categoria_riesgo"], CATEGORIA_SIN_REDACCION_PROPIA)
        _, html = self._pedir("GET", f"/noticia?id={noticia['id']}", cookies=cookies)
        self.assertIn('value="reintentar_redaccion"', html)
        resp, _ = self._pedir("POST", f"/noticia?id={noticia['id']}",
                              {"csrf": csrf, "accion": "reintentar_redaccion"}, cookies=cookies)
        self.assertEqual(resp.status, 200)
        self.assertIsNone(self._noticias()[0]["categoria_riesgo"])

    # -- límite de intentos
    def test_bloqueo_por_intentos_por_ip(self):
        for _ in range(remoto.INTENTOS_POR_IP):
            self.assertEqual(self._login(password="mala-mala-mala-mala")[0].status, 401)
        resp, _ = self._login()  # credenciales correctas, pero bloqueada
        self.assertEqual(resp.status, 429)
        self.assertIsNone(self._cookie(resp, COOKIE_SESION))
        self.assertEqual(self._login(ip="198.51.100.9")[0].status, 303)  # otra IP no afectada
        self.reloj.t += remoto.BLOQUEO_IP_SEGUNDOS + 1
        self.assertEqual(self._login()[0].status, 303)

    def test_bloqueo_global(self):
        for i in range(remoto.INTENTOS_GLOBALES):
            self._login(password="mala-mala-mala-mala", ip=f"192.0.2.{i}")
        self.assertEqual(self._login(ip="198.51.100.20")[0].status, 429)

    # -- logs
    def test_logs_sin_secretos(self):
        with self.assertLogs("panel_remoto", level="INFO") as registro:
            self._login(password="mala-mala-mala-mala", codigo="123456")
            cookies, csrf = self._sesion()
        texto = "\n".join(registro.output)
        self.assertIn("login fallido", texto)
        self.assertIn("login ok", texto)
        for secreto in (PASSWORD, "mala-mala-mala-mala", "123456", self.secreto, cookies[COOKIE_SESION], csrf):
            self.assertNotIn(secreto, texto)


if __name__ == "__main__":
    unittest.main()
