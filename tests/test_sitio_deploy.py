import subprocess
import unittest

from motor_noticias.sitio.deploy import RAMA_DEPLOY, desplegar_sitio


def _cp(args, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args, returncode=returncode, stdout=stdout, stderr=stderr)


class FakeGit:
    """Simulador de `git` para pruebas 100% offline: nunca ejecuta un
    proceso real ni toca la red. `respuestas` mapea el primer argumento de
    subcomando (p.ej. "add", "commit", "push") a un `CompletedProcess`."""

    def __init__(self, rama=RAMA_DEPLOY, hay_cambios=True, respuestas=None):
        self.rama = rama
        self.hay_cambios = hay_cambios
        self.respuestas = respuestas or {}
        self.llamadas = []

    @staticmethod
    def _subcomando(cmd):
        # cmd = ["git", "-C", repo_root, (-c clave=valor)*, <subcomando>, ...]
        i = 3
        while i + 1 < len(cmd) and cmd[i] == "-c":
            i += 2
        return cmd[i]

    def __call__(self, cmd, **kwargs):
        self.llamadas.append(cmd)
        subcomando = self._subcomando(cmd)
        if subcomando == "rev-parse":
            return _cp(cmd, stdout=self.rama + "\n")
        if subcomando == "diff":
            # --quiet: código 1 si hay diferencias, 0 si no hay.
            return _cp(cmd, returncode=1 if self.hay_cambios else 0)
        if subcomando in self.respuestas:
            return self.respuestas[subcomando]
        return _cp(cmd)  # éxito por defecto (add, commit, push)


class TestDesplegarSitio(unittest.TestCase):
    def test_sin_cambios_no_commitea_ni_empuja(self):
        fake = FakeGit(hay_cambios=False)

        resultado = desplegar_sitio(repo_root="/repo", ejecutar=fake)

        self.assertEqual(resultado.resultado, "sin_cambios")
        subcomandos = [FakeGit._subcomando(c) for c in fake.llamadas]
        self.assertNotIn("commit", subcomandos)
        self.assertNotIn("push", subcomandos)

    def test_con_cambios_commitea_y_empuja(self):
        fake = FakeGit(hay_cambios=True)

        resultado = desplegar_sitio(repo_root="/repo", ejecutar=fake)

        self.assertEqual(resultado.resultado, "desplegado")
        subcomandos = [FakeGit._subcomando(c) for c in fake.llamadas]
        self.assertIn("add", subcomandos)
        self.assertIn("commit", subcomandos)
        self.assertIn("push", subcomandos)
        # el add y el diff quedan acotados a la carpeta de salida (docs)
        add_cmd = next(c for c in fake.llamadas if FakeGit._subcomando(c) == "add")
        self.assertIn("docs", add_cmd)

    def test_commit_usa_identidad_dedicada_no_la_del_sistema(self):
        fake = FakeGit(hay_cambios=True)
        desplegar_sitio(repo_root="/repo", ejecutar=fake)

        commit_cmd = next(c for c in fake.llamadas if FakeGit._subcomando(c) == "commit")
        self.assertIn("user.name=Ledesma Participa (automático)", " ".join(commit_cmd))
        self.assertIn("user.email=ledesmaparticipa@gmail.com", " ".join(commit_cmd))

    def test_rama_distinta_de_main_no_despliega(self):
        fake = FakeGit(rama="una-rama-de-trabajo", hay_cambios=True)

        resultado = desplegar_sitio(repo_root="/repo", ejecutar=fake)

        self.assertEqual(resultado.resultado, "rama_incorrecta")
        subcomandos = [FakeGit._subcomando(c) for c in fake.llamadas]
        self.assertNotIn("add", subcomandos)
        self.assertNotIn("commit", subcomandos)
        self.assertNotIn("push", subcomandos)

    def test_fallo_de_push_se_reporta_como_error_sin_lanzar_excepcion(self):
        fake = FakeGit(hay_cambios=True, respuestas={
            "push": _cp(["git", "push"], returncode=1, stderr="no se pudo conectar con el remoto"),
        })

        resultado = desplegar_sitio(repo_root="/repo", ejecutar=fake)

        self.assertEqual(resultado.resultado, "error")
        self.assertIn("no se pudo conectar", resultado.detalle)

    def test_fallo_de_commit_se_reporta_como_error(self):
        fake = FakeGit(hay_cambios=True, respuestas={
            "commit": _cp(["git", "commit"], returncode=1, stderr="nothing to commit"),
        })

        resultado = desplegar_sitio(repo_root="/repo", ejecutar=fake)

        self.assertEqual(resultado.resultado, "error")

    def test_timeout_de_git_no_propaga_excepcion(self):
        def ejecutar_con_timeout(cmd, **kwargs):
            if FakeGit._subcomando(cmd) == "push":
                raise subprocess.TimeoutExpired(cmd, 60)
            return FakeGit()(cmd, **kwargs)

        resultado = desplegar_sitio(repo_root="/repo", ejecutar=ejecutar_con_timeout)

        self.assertEqual(resultado.resultado, "error")

    def test_git_no_encontrado_no_propaga_excepcion(self):
        def ejecutar_sin_git(cmd, **kwargs):
            raise FileNotFoundError("git no está instalado")

        resultado = desplegar_sitio(repo_root="/repo", ejecutar=ejecutar_sin_git)

        self.assertEqual(resultado.resultado, "rama_incorrecta")  # falla ya en rev-parse

    def test_segunda_corrida_idempotente_no_duplica_despliegue(self):
        # Primera corrida: hay cambios, despliega. Segunda corrida sobre el
        # mismo estado (sin cambios nuevos desde el commit anterior): no
        # vuelve a commitear ni a empujar.
        fake_primera = FakeGit(hay_cambios=True)
        resultado_1 = desplegar_sitio(repo_root="/repo", ejecutar=fake_primera)
        self.assertEqual(resultado_1.resultado, "desplegado")

        fake_segunda = FakeGit(hay_cambios=False)
        resultado_2 = desplegar_sitio(repo_root="/repo", ejecutar=fake_segunda)
        self.assertEqual(resultado_2.resultado, "sin_cambios")


if __name__ == "__main__":
    unittest.main()
