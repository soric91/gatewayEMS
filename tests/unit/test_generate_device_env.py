"""Los tres valores que el equipo genera al instalarse.

Lo que se fija aquí es sobre todo lo que NO debe pasar: pisar un valor ya
cargado, reordenar el `.env`, dejarlo a medias, o imprimir un secreto en la
terminal. Un `.env` roto se descubre en el arranque siguiente, que puede ser
semanas después y en una sede lejana.
"""

from pathlib import Path

import pytest

from src.Core import device_secrets

CLAVES = ("MQTT_CLIENT_ID", "INFLUXDB_ADMIN_PASSWORD", "INFLUXDB_TOKEN")

ENV_BASE = """\
INFLUXDB_URL=http://localhost:8086
INFLUXDB_ORG=gateway_ems
INFLUXDB_BUCKET=modbus_data

MQTT_HOST=mqtt.example.org
MQTT_PORT=8883
GATEWAY_UUID=8f14e45f-ea0e-4f2b-9c1a-2b3c4d5e6f70
"""


def _valores(path: Path) -> dict[str, str]:
    """Las claves del archivo, como diccionario."""
    pares: dict[str, str] = {}
    for linea in path.read_text(encoding="utf-8").splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#") or "=" not in limpia:
            continue
        clave, _, valor = limpia.partition("=")
        pares[clave.strip()] = valor.strip()
    return pares


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    path = tmp_path / ".env"
    path.write_text(ENV_BASE, encoding="utf-8")
    return path


class TestGeneracion:
    def test_escribe_las_tres_claves(self, env_file: Path):
        generados, conservados = device_secrets.generar_en(env_file)

        assert set(generados) == set(CLAVES)
        assert conservados == []
        valores = _valores(env_file)
        for clave in CLAVES:
            assert valores[clave] == generados[clave]
            assert valores[clave] != ""

    def test_el_client_id_es_distinto_en_cada_equipo(self, env_file: Path):
        """Dos gateways con el mismo client id se echan del broker en bucle."""
        primero = device_secrets.generar_en(env_file)[0]["MQTT_CLIENT_ID"]
        segundo = device_secrets.generar_en(env_file, force=True)[0]["MQTT_CLIENT_ID"]

        assert primero != segundo

    def test_los_valores_llevan_el_prefijo_de_siempre(self, env_file: Path):
        """Los equipos ya instalados usan estas formas: se mantienen."""
        generados = device_secrets.generar_en(env_file)[0]

        assert generados["MQTT_CLIENT_ID"].startswith(device_secrets.CLIENT_ID_PREFIX)
        assert generados["INFLUXDB_ADMIN_PASSWORD"].startswith(
            device_secrets.ADMIN_PASSWORD_PREFIX
        )

    def test_ningun_valor_sale_entre_comillas(self, env_file: Path):
        """docker-compose pasa las comillas literales al contenedor."""
        device_secrets.generar_en(env_file)

        for valor in _valores(env_file).values():
            assert not valor.startswith(("'", '"'))

    def test_los_secretos_son_largos(self, env_file: Path):
        generados = device_secrets.generar_en(env_file)[0]

        assert len(generados["INFLUXDB_TOKEN"]) >= 64
        assert len(generados["INFLUXDB_ADMIN_PASSWORD"]) >= 16

    def test_la_contrasena_evita_los_caracteres_que_se_confunden(self, env_file: Path):
        """Se teclea en la interfaz de InfluxDB y a veces se dicta."""
        password = device_secrets.generar_en(env_file)[0]["INFLUXDB_ADMIN_PASSWORD"]
        cuerpo = password[len(device_secrets.ADMIN_PASSWORD_PREFIX) :]

        assert not set(cuerpo) & set("0O1lI")


class TestIdempotencia:
    def test_una_segunda_ejecucion_no_cambia_nada(self, env_file: Path):
        device_secrets.generar_en(env_file)
        despues_de_la_primera = env_file.read_text(encoding="utf-8")

        generados, conservados = device_secrets.generar_en(env_file)

        assert generados == {}
        assert set(conservados) == set(CLAVES)
        assert env_file.read_text(encoding="utf-8") == despues_de_la_primera

    def test_force_regenera_todas(self, env_file: Path):
        primeros = device_secrets.generar_en(env_file)[0]

        segundos, conservados = device_secrets.generar_en(env_file, force=True)

        assert conservados == []
        assert all(segundos[clave] != primeros[clave] for clave in CLAVES)
        assert _valores(env_file)["INFLUXDB_TOKEN"] == segundos["INFLUXDB_TOKEN"]

    def test_una_clave_presente_pero_vacia_se_rellena(self, env_file: Path):
        env_file.write_text(ENV_BASE + "INFLUXDB_TOKEN=\n", encoding="utf-8")

        generados, _ = device_secrets.generar_en(env_file)

        assert generados["INFLUXDB_TOKEN"] != ""
        assert _valores(env_file)["INFLUXDB_TOKEN"] == generados["INFLUXDB_TOKEN"]

    def test_una_clave_cargada_a_mano_se_respeta(self, env_file: Path):
        env_file.write_text(
            ENV_BASE + "MQTT_CLIENT_ID=gatewayems_002\n", encoding="utf-8"
        )

        generados, conservados = device_secrets.generar_en(env_file)

        assert "MQTT_CLIENT_ID" not in generados
        assert conservados == ["MQTT_CLIENT_ID"]
        assert _valores(env_file)["MQTT_CLIENT_ID"] == "gatewayems_002"

    def test_los_espacios_alrededor_del_igual_tambien_cuentan(self, env_file: Path):
        env_file.write_text(
            ENV_BASE + "  INFLUXDB_TOKEN = ya-cargado\n", encoding="utf-8"
        )

        generados, conservados = device_secrets.generar_en(env_file)

        assert "INFLUXDB_TOKEN" not in generados
        assert conservados == ["INFLUXDB_TOKEN"]


class TestElRestoDelArchivo:
    def test_las_demas_lineas_quedan_intactas(self, env_file: Path):
        device_secrets.generar_en(env_file)

        lineas = env_file.read_text(encoding="utf-8").splitlines()
        assert lineas[: len(ENV_BASE.splitlines())] == ENV_BASE.splitlines()

    def test_una_clave_existente_se_reescribe_en_su_sitio(self, env_file: Path):
        """Moverla al final haría ilegible el diff del archivo."""
        env_file.write_text(
            "MQTT_CLIENT_ID=viejo\nMQTT_PORT=8883\n", encoding="utf-8"
        )

        device_secrets.generar_en(env_file, force=True)

        lineas = env_file.read_text(encoding="utf-8").splitlines()
        assert lineas[0].startswith("MQTT_CLIENT_ID=")
        assert lineas[1] == "MQTT_PORT=8883"

    def test_el_bloque_anadido_dice_de_donde_salio(self, env_file: Path):
        device_secrets.generar_en(env_file)

        assert device_secrets.BLOQUE_TITULO in env_file.read_text(encoding="utf-8")

    def test_conserva_los_permisos_del_archivo(self, env_file: Path):
        env_file.chmod(0o600)

        device_secrets.generar_en(env_file)

        assert env_file.stat().st_mode & 0o777 == 0o600

    def test_no_deja_ningun_temporal(self, env_file: Path):
        device_secrets.generar_en(env_file)

        assert list(env_file.parent.iterdir()) == [env_file]


class TestSinArchivo:
    def test_un_env_ausente_es_un_error_no_un_archivo_nuevo(self, tmp_path: Path):
        """Un `.env` con sólo estas tres claves parece configurado y no arranca."""
        ausente = tmp_path / ".env"

        with pytest.raises(device_secrets.EnvFileMissingError, match="No existe"):
            device_secrets.generar_en(ausente)

        assert not ausente.exists()


class TestDryRun:
    def test_no_escribe_nada(self, env_file: Path):
        antes = env_file.read_text(encoding="utf-8")

        generados, _ = device_secrets.generar_en(env_file, dry_run=True)

        assert set(generados) == set(CLAVES)
        assert env_file.read_text(encoding="utf-8") == antes


class TestLineaDeComandos:
    """El script de `scripts/`, que es sólo la interfaz."""

    @staticmethod
    def _script():
        import importlib.util

        ruta = (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "generate_device_env.py"
        )
        spec = importlib.util.spec_from_file_location("generate_device_env", ruta)
        assert spec is not None and spec.loader is not None
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo

    def test_rellena_el_archivo_e_informa(self, env_file: Path, capsys):
        codigo = self._script().main(["--env-file", str(env_file)])

        assert codigo == 0
        salida = capsys.readouterr().out
        assert all(clave in salida for clave in CLAVES)
        assert all(_valores(env_file)[clave] for clave in CLAVES)

    def test_los_secretos_no_llegan_a_la_terminal(self, env_file: Path, capsys):
        """Impresos quedarían en el scrollback y en el log de la sesión."""
        self._script().main(["--env-file", str(env_file)])

        salida = capsys.readouterr().out
        valores = _valores(env_file)
        assert valores["INFLUXDB_TOKEN"] not in salida
        assert valores["INFLUXDB_ADMIN_PASSWORD"] not in salida
        # El client id sí: es lo que identifica al equipo en el broker.
        assert valores["MQTT_CLIENT_ID"] in salida

    def test_un_env_ausente_se_informa_sin_reventar(self, tmp_path: Path, capsys):
        codigo = self._script().main(["--env-file", str(tmp_path / ".env")])

        assert codigo == 1
        assert "No existe" in capsys.readouterr().out

    def test_la_segunda_vez_dice_que_no_hay_nada_que_hacer(
        self, env_file: Path, capsys
    ):
        script = self._script()
        script.main(["--env-file", str(env_file)])
        capsys.readouterr()

        codigo = script.main(["--env-file", str(env_file)])

        assert codigo == 0
        assert "Nada que generar" in capsys.readouterr().out

    def test_por_defecto_apunta_al_env_del_proyecto(self):
        assert device_secrets.DEFAULT_ENV_PATH.name == ".env"
        assert (device_secrets.DEFAULT_ENV_PATH.parent / "pyproject.toml").is_file()
