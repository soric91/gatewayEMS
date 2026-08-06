"""
Tests del traductor de configuración del CRM a los archivos del gateway.

Lo que se prueba, en orden de importancia:
1. Que una configuración inválida NO escribe nada.
2. Que el mapeo produce exactamente las claves que el código ya lee.
3. Que la escritura es atómica y el rollback devuelve la anterior.
"""
import configparser
import json
from pathlib import Path

import pytest

from src.Crm.applier import ConfigApplier, ConfigInvalida
from src.Models.model import RemoteConfig

pytestmark = pytest.mark.unit


PAYLOAD = {
    "gateway_uuid": "4f50cc89-8030-4654-a2cc-4a1ec34ab37a",
    "numero_serie": "gateway iot -s1",
    "firmware_version": "1.0.0",
    "generated_at": "2026-08-05T21:38:49.260470Z",
    "config_version": "2b26ca9b106b8c463d7d590e31cbeca4ca12fd13b892a0b73c9e68adc7e5b8a7",
    "log": {"loglevel": "INFO"},
    "mainmodbus": {"interval": 1, "start_hour": 0, "stop_hour": 23},
    "devices": [
        {
            "name": "Modbus_DTUS666",
            "identify_device": "178aa9d5-37b0-41a4-a4ae-34d5ce71231d",
            "device_type": "CT_Meter",
            "protocol": "RTU",
            "serialport": "/dev/ttyRS485",
            "baudrate": 9600,
            "parity": "N",
            "bytesize": 8,
            "stopbits": 1,
            "host": None,
            "port": None,
            "device_id": 11,
            "modbusconnect": True,
            "modbusread": True,
            "blockreading": True,
            "map": {
                "Voltaje A": {
                    "address": "0x2000", "data_type": "f", "gain": "1",
                    "unit": "V", "register_type": "holding",
                },
                "Voltaje B": {
                    "address": "0x2002", "data_type": "f", "gain": "1",
                    "unit": "V", "register_type": "holding",
                },
            },
        }
    ],
}


def config_desde(payload: dict) -> RemoteConfig:
    return RemoteConfig.model_validate(payload)


@pytest.fixture
def applier(tmp_path: Path) -> ConfigApplier:
    return ConfigApplier(
        config_path=tmp_path / "config.ini",
        maps_dir=tmp_path / "maps",
        state_dir=tmp_path / "remote",
    )


# --------------------------------------------------------------------------
# Mapeo
# --------------------------------------------------------------------------

def test_escribe_config_ini_con_las_claves_que_el_gateway_lee(applier):
    applier.apply(config_desde(PAYLOAD))

    ini = configparser.ConfigParser()
    ini.read(applier.config_path)

    assert ini["MAINMODBUS"]["devicesnames"] == "Modbus_DTUS666"
    assert ini["MAINMODBUS"]["interval"] == "1"
    assert ini["DEFAULT"]["loglevel"] == "INFO"

    seccion = ini["Modbus_DTUS666"]
    assert seccion["protocol"] == "RTU"
    assert seccion["serialport"] == "/dev/ttyRS485"
    assert seccion["baudrate"] == "9600"
    assert seccion["device_id"] == "11"
    assert seccion["identify_device"] == "178aa9d5-37b0-41a4-a4ae-34d5ce71231d"
    assert seccion["device_type"] == "CT_Meter"
    assert seccion["modbusconnect"] == "true"
    assert seccion["modbusread"] == "true"
    assert seccion["blockreading"] == "true"
    assert seccion["mapfile"] == "src/Modbus/maps/Modbus_DTUS666.json"


def test_deriva_modbus_function_del_register_type(applier):
    """El CRM manda register_type por variable; el gateway usa una función."""
    applier.apply(config_desde(PAYLOAD))
    ini = configparser.ConfigParser()
    ini.read(applier.config_path)
    assert ini["Modbus_DTUS666"]["modbus_function"] == "3"   # holding

    payload = json.loads(json.dumps(PAYLOAD))
    for variable in payload["devices"][0]["map"].values():
        variable["register_type"] = "input"

    applier.apply(config_desde(payload))
    ini.read(applier.config_path)
    assert ini["Modbus_DTUS666"]["modbus_function"] == "4"   # input


def test_escribe_el_mapa_en_el_formato_del_gateway(applier):
    applier.apply(config_desde(PAYLOAD))

    mapa = json.loads((applier.maps_dir / "Modbus_DTUS666.json").read_text())

    # Las claves van sin espacios: acaban siendo fields de InfluxDB
    assert set(mapa) == {"Voltaje_A", "Voltaje_B"}
    assert mapa["Voltaje_A"]["address"] == "0x2000"
    assert mapa["Voltaje_A"]["data_type"] == "f"
    assert mapa["Voltaje_A"]["gain"] == "1"


def test_el_mapa_escrito_lo_entiende_ModbusDeviceMap(applier):
    """La prueba que de verdad importa: que el mapa sirva para leer."""
    from src.Modbus.modbusmap import ModbusDeviceMap

    applier.apply(config_desde(PAYLOAD))
    ruta = applier.maps_dir / "Modbus_DTUS666.json"

    device_map = ModbusDeviceMap(
        device_name="Modbus_DTUS666", map_file_path=str(ruta), block_reading=True
    )
    assert device_map.load_map() is True
    bloques = device_map.build_read_blocks()

    assert bloques, "no se construyó ningún bloque de lectura"
    assert sorted(device_map.get_variables_list()) == ["Voltaje_A", "Voltaje_B"]


# --------------------------------------------------------------------------
# Nombres de variable y direcciones
# --------------------------------------------------------------------------

def _con_variable(nombre: str, **campos) -> dict:
    """PAYLOAD con una sola variable, para probar su nombre o su dirección."""
    payload = json.loads(json.dumps(PAYLOAD))
    variable = {"address": "0x2000", "data_type": "f", "gain": "1",
                "unit": "V", "register_type": "holding"}
    variable.update(campos)
    payload["devices"][0]["map"] = {nombre: variable}
    return payload


@pytest.mark.parametrize(
    "nombre,clave",
    [
        ("Voltaje A", "Voltaje_A"),
        ("Potencia Activa Ints", "Potencia_Activa_Ints"),
        ("  Voltaje   A  ", "Voltaje_A"),      # espacios de sobra y repetidos
        ("Voltaje\tA", "Voltaje_A"),           # tabulador
        ("VoltajeA", "VoltajeA"),              # sin espacios, intacto
    ],
)
def test_las_claves_del_mapa_van_sin_espacios(applier, nombre, clave):
    applier.apply(config_desde(_con_variable(nombre)))

    mapa = json.loads((applier.maps_dir / "Modbus_DTUS666.json").read_text())
    assert list(mapa) == [clave]


def test_dos_nombres_que_colisionan_se_rechazan(applier):
    """'Voltaje A' y 'Voltaje  A' serían la misma clave: perdería una lectura."""
    payload = _con_variable("Voltaje A")
    payload["devices"][0]["map"]["Voltaje  A"] = {
        "address": "0x2002", "data_type": "f", "gain": "1",
        "unit": "V", "register_type": "holding",
    }

    with pytest.raises(ConfigInvalida, match="misma variable"):
        applier.apply(config_desde(payload))

    assert not applier.config_path.exists()


@pytest.mark.parametrize(
    "address,escrito",
    [
        ("0x2000", "0x2000"),     # hex explícito, como hasta ahora
        ("42514", "0xA612"),      # decimal: el CRM lo manda en su propia base
        ("0", "0x0000"),
        ("65535", "0xFFFF"),
    ],
)
def test_la_direccion_se_escribe_siempre_en_hexadecimal(applier, address, escrito):
    """`ModbusDeviceMap` lee el mapa en base 16: un decimal crudo sería otro registro."""
    applier.apply(config_desde(_con_variable("Voltaje A", address=address)))

    mapa = json.loads((applier.maps_dir / "Modbus_DTUS666.json").read_text())
    assert mapa["Voltaje_A"]["address"] == escrito


def test_el_registro_que_acaba_leyendo_el_gateway_es_el_que_pidio_el_crm(applier):
    """La prueba de verdad: 42514 decimal se lee como 42514, no como 0x42514."""
    from src.Modbus.modbusmap import ModbusDeviceMap

    applier.apply(config_desde(_con_variable("Voltaje A", address="42514")))

    device_map = ModbusDeviceMap(
        device_name="Modbus_DTUS666",
        map_file_path=str(applier.maps_dir / "Modbus_DTUS666.json"),
        block_reading=True,
    )
    assert device_map.load_map() is True
    direcciones, _ = device_map.get_read_params()

    assert direcciones == [42514]


@pytest.mark.parametrize("address", ["70000", "0x1FFFF", "-1", "", "  ", "ZZZZ"])
def test_direccion_fuera_de_rango_o_ilegible_no_escribe_nada(applier, address):
    with pytest.raises(ConfigInvalida):
        applier.apply(config_desde(_con_variable("Voltaje A", address=address)))

    assert not applier.config_path.exists()


def test_conserva_las_claves_de_DEFAULT_que_el_crm_no_manda(applier):
    applier.config_path.parent.mkdir(parents=True, exist_ok=True)
    applier.config_path.write_text(
        "[DEFAULT]\n"
        "loglevel = DEBUG\n"
        "logstdout = True\n"
        "logfile = src/Log/gateway_ems.log\n"
        "backup_count = 5\n"
        "\n[MAINMODBUS]\ndevicesnames =\n"
    )

    applier.apply(config_desde(PAYLOAD))

    ini = configparser.ConfigParser()
    ini.read(applier.config_path)
    assert ini["DEFAULT"]["loglevel"] == "INFO"          # lo gobierna el CRM
    assert ini["DEFAULT"]["logstdout"] == "True"         # local, se conserva
    assert ini["DEFAULT"]["logfile"] == "src/Log/gateway_ems.log"
    assert ini["DEFAULT"]["backup_count"] == "5"


def test_ignora_campos_que_el_gateway_no_conoce(applier):
    """Un campo nuevo del CRM se descarta, no rompe."""
    payload = json.loads(json.dumps(PAYLOAD))
    payload["telemetria_avanzada"] = {"algo": 1}
    payload["devices"][0]["campo_futuro"] = "x"
    payload["devices"][0]["map"]["Voltaje A"]["escala_nueva"] = 2

    applier.apply(config_desde(payload))

    mapa = json.loads((applier.maps_dir / "Modbus_DTUS666.json").read_text())
    assert "escala_nueva" not in mapa["Voltaje_A"]


def test_dispositivo_tcp(applier):
    payload = json.loads(json.dumps(PAYLOAD))
    payload["devices"][0].update(
        protocol="TCP", host="192.168.1.50", port=502, serialport=None, baudrate=None
    )

    applier.apply(config_desde(payload))

    ini = configparser.ConfigParser()
    ini.read(applier.config_path)
    seccion = ini["Modbus_DTUS666"]
    assert seccion["host"] == "192.168.1.50"
    assert seccion["port"] == "502"
    assert "serialport" not in seccion


# --------------------------------------------------------------------------
# Validación: fallar cerrado
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "mutacion,motivo",
    [
        (lambda p: p["devices"].clear(), "sin dispositivos"),
        (lambda p: p["devices"][0].update(protocol="ASCII"), "protocolo"),
        (lambda p: p["devices"][0].update(serialport=None), "RTU sin serialport"),
        (lambda p: p["devices"][0].update(baudrate=None), "RTU sin baudrate"),
        (lambda p: p["devices"][0]["map"].clear(), "mapa vacío"),
        (lambda p: p["devices"][0]["map"]["Voltaje A"].update(address="ZZZZ"), "hex"),
        (lambda p: p["devices"][0]["map"]["Voltaje A"].update(data_type="q"), "data_type"),
        (lambda p: p["devices"][0]["map"]["Voltaje A"].update(gain="mucho"), "gain"),
        (lambda p: p["devices"][0]["map"]["Voltaje A"].update(register_type="input"),
         "mezcla holding/input"),
        (lambda p: p["devices"][0]["map"]["Voltaje A"].update(register_type="coil"),
         "register_type desconocido"),
        (lambda p: p["devices"][0].update(name="../escape"), "nombre inválido"),
    ],
)
def test_configuracion_invalida_no_escribe_nada(applier, mutacion, motivo):
    payload = json.loads(json.dumps(PAYLOAD))
    mutacion(payload)

    with pytest.raises(ConfigInvalida):
        applier.apply(config_desde(payload))

    assert not applier.config_path.exists(), f"escribió pese a: {motivo}"
    assert not applier.maps_dir.exists() or not list(applier.maps_dir.glob("*.json"))


def test_nombres_repetidos_se_rechazan(applier):
    payload = json.loads(json.dumps(PAYLOAD))
    payload["devices"].append(json.loads(json.dumps(payload["devices"][0])))

    with pytest.raises(ConfigInvalida, match="repetidos"):
        applier.apply(config_desde(payload))


def test_avisa_de_los_parametros_serie_que_ignora(applier, caplog):
    """parity/bytesize/stopbits no llegan al cliente Modbus: hay que decirlo."""
    payload = json.loads(json.dumps(PAYLOAD))
    payload["devices"][0]["parity"] = "E"

    with caplog.at_level("WARNING"):
        applier.apply(config_desde(payload))

    assert any("parity=E" in r.message for r in caplog.records)


# --------------------------------------------------------------------------
# Backup, estado y rollback
# --------------------------------------------------------------------------

def test_guarda_backup_y_rollback_restaura(applier):
    applier.apply(config_desde(PAYLOAD))
    applier.mark_applied(config_desde(PAYLOAD), etag='"abc"')
    primera = applier.config_path.read_text()

    payload = json.loads(json.dumps(PAYLOAD))
    payload["config_version"] = "b" * 64
    payload["mainmodbus"]["interval"] = 30
    applier.apply(config_desde(payload))

    assert "interval = 30" in applier.config_path.read_text()

    assert applier.rollback() is True
    assert applier.config_path.read_text() == primera


def test_rollback_sin_backup_no_revienta(applier):
    assert applier.rollback() is False


def test_el_estado_recuerda_la_version_aplicada(applier):
    assert applier.load_state() == {}          # primera vez

    config = config_desde(PAYLOAD)
    applier.apply(config)
    applier.mark_applied(config, etag='"v1"')

    estado = applier.load_state()
    assert estado["applied_version"] == config.config_version
    assert estado["etag"] == '"v1"'
    assert estado["devices"] == ["Modbus_DTUS666"]


def test_state_json_corrupto_se_trata_como_primera_vez(applier):
    applier.state_dir.mkdir(parents=True, exist_ok=True)
    applier.state_file.write_text("{ no es json")

    assert applier.load_state() == {}


def test_la_escritura_es_atomica(applier, monkeypatch):
    """Si falla a mitad, el archivo anterior queda intacto (no truncado)."""
    applier.apply(config_desde(PAYLOAD))
    original = applier.config_path.read_text()

    def replace_que_falla(src, dst):
        raise OSError("disco lleno")

    monkeypatch.setattr("src.Crm.applier.os.replace", replace_que_falla)

    payload = json.loads(json.dumps(PAYLOAD))
    payload["mainmodbus"]["interval"] = 99
    with pytest.raises(OSError):
        applier.apply(config_desde(payload))

    assert applier.config_path.read_text() == original
