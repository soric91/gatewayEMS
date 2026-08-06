"""
Arranque de un gateway sin aprovisionar (MAINMODBUS.devicesnames vacío).

Un gateway recién instalado no tiene equipos: se los tiene que mandar el CRM.
Antes, `_load_configs` trataba eso como error fatal y el proceso moría sin
llegar a `start_all_tasks`, así que el plano de control —lo único capaz de
traer la primera configuración— nunca arrancaba.

Se cubren las cuatro piezas de esa cadena:
  1. cargar configs y mapas vacíos no es un error,
  2. pero un dispositivo declarado sin mapa utilizable sigue siéndolo,
  3. `initialize()` llega hasta el final y levanta las tareas del CRM,
  4. y desde ese estado vacío una configuración del CRM deja el equipo cargado.
"""
import asyncio
import configparser
import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.Config.config import ConfigManager
from src.Crm.applier import ConfigApplier
from src.Models.model import RemoteConfig
from src.Modbus.app import ModbusApp
from src.Task.task import TaskManager

pytestmark = pytest.mark.integration

RAIZ = Path(__file__).resolve().parents[2]

INI_VACIO = (
    "[DEFAULT]\n"
    "loglevel = INFO\n"
    "logstdout = True\n"
    "logfile = src/Log/gateway_ems.log\n"
    "max_size_bytes = 1485760\n"
    "backup_count = 5\n"
    "sampleslog = False\n"
    "\n"
    "[MAINMODBUS]\n"
    "devicesnames = \n"
    "interval = 1\n"
    "start_hour = 0\n"
    "stop_hour = 23\n"
)

CONFIG_CRM = {
    "gateway_uuid": "00000000-0000-0000-0000-000000000000",
    "config_version": "c" * 64,
    "log": {"loglevel": "INFO"},
    "mainmodbus": {"interval": 5, "start_hour": 6, "stop_hour": 22},
    "devices": [
        {
            "name": "Medidor",
            "identify_device": "178aa9d5-37b0-41a4-a4ae-34d5ce71231d",
            "device_type": "CT_Meter",
            "protocol": "RTU",
            "serialport": "/dev/ttyRS485",
            "baudrate": 9600,
            "device_id": 11,
            "modbusconnect": True,
            "modbusread": True,
            "blockreading": True,
            "map": {
                "Voltaje A": {"address": "0x2000", "data_type": "f", "gain": "1",
                              "unit": "V", "register_type": "holding"},
            },
        }
    ],
}


def manager(ruta: Path) -> ConfigManager:
    """ConfigManager apuntando a un config.ini de prueba."""
    cm = ConfigManager()
    cm.config = configparser.ConfigParser()
    cm.config_path = ruta
    cm.config.read(ruta)
    return cm


@pytest.fixture
def ini_vacio(tmp_path: Path) -> Path:
    ruta = tmp_path / "config.ini"
    ruta.write_text(INI_VACIO)
    return ruta


# ---------------------------------------------------------------------------
# 1. Sin dispositivos no es un error
# ---------------------------------------------------------------------------

def test_gateway_virgen_carga_configs_y_mapas(ini_vacio):
    app = ModbusApp(manager(ini_vacio))

    assert app._load_configs() is True
    assert app.device_configs == {}
    assert app._load_maps() is True
    assert app.device_maps == {}


def test_devicesnames_solo_con_comas_tambien_es_vacio(tmp_path):
    ruta = tmp_path / "config.ini"
    ruta.write_text(INI_VACIO.replace("devicesnames = \n", "devicesnames = , ,\n"))

    app = ModbusApp(manager(ruta))

    assert app._load_configs() is True
    assert app.device_configs == {}


# ---------------------------------------------------------------------------
# 2. Guarda: con dispositivos declarados, el fallo sigue siendo fallo
# ---------------------------------------------------------------------------

def test_dispositivo_declarado_sin_mapa_sigue_fallando(tmp_path):
    """Aflojar el caso vacío no puede tapar una configuración rota de verdad."""
    ruta = tmp_path / "config.ini"
    ruta.write_text(
        INI_VACIO.replace("devicesnames = \n", "devicesnames = Medidor\n")
        + "\n[Medidor]\n"
        "identify_device = uuid-1\n"
        "device_type = CT_Meter\n"
        "protocol = RTU\n"
        "serialport = /dev/ttyRS485\n"
        "baudrate = 9600\n"
        f"mapfile = {tmp_path / 'no_existe.json'}\n"
        "device_id = 11\n"
        "modbusconnect = false\n"
        "modbusread = false\n"
    )

    app = ModbusApp(manager(ruta))

    assert app._load_configs() is True
    assert list(app.device_configs) == ["Medidor"]
    assert app._load_maps() is False, "un mapa ilegible tiene que abortar el arranque"


# ---------------------------------------------------------------------------
# 3. initialize() y las tareas del plano de control
# ---------------------------------------------------------------------------

@pytest.fixture
def gateway_virgen(ini_vacio):
    """TaskManager sobre un config.ini vacío, sin red ni InfluxDB."""
    cm = manager(ini_vacio)

    with patch("src.Task.task.MQTTManager") as mqtt_cls, \
         patch("src.Task.task.ModbusService") as service_cls, \
         patch("src.Task.task.CrmClient") as crm_cls:
        mqtt_cls.return_value = AsyncMock()
        service_cls.return_value = AsyncMock()
        crm_cls.return_value = AsyncMock()
        crm_cls.return_value.heartbeat = AsyncMock(
            return_value={"config_habilitada": False}
        )

        tm = TaskManager(cm)
        # BaseWatchdog.__init__ se fabrica su propio ConfigManager (lee el
        # config.ini real del repo); aquí lo apuntamos al de prueba.
        tm.config = cm
        yield tm


async def test_initialize_arranca_sin_dispositivos(gateway_virgen):
    tm = gateway_virgen

    assert await tm.initialize() is True, "un gateway virgen tiene que poder arrancar"
    assert tm.modbus_app.device_configs == {}
    assert tm.crm_client is not None

    await tm.stop()


async def test_las_tareas_del_crm_se_levantan_sin_dispositivos(gateway_virgen):
    """El plano de control es justo lo que no puede faltar en un gateway virgen."""
    tm = gateway_virgen
    assert await tm.initialize() is True

    arranque = asyncio.create_task(tm.start_all_tasks())
    await asyncio.sleep(0.1)

    nombres = {t.get_name() for t in tm._tasks}
    assert nombres == {
        "read_modbus", "process_queue", "publish_mqtt",
        "listen_mqtt", "fetch_config", "apply_config", "heartbeat",
    }

    await tm.stop_all_tasks()
    arranque.cancel()
    await asyncio.gather(arranque, return_exceptions=True)


# ---------------------------------------------------------------------------
# 4. De vacío a configurado
# ---------------------------------------------------------------------------

def test_la_configuracion_del_crm_deja_el_gateway_cargado(tmp_path, monkeypatch):
    """Aprovisionamiento completo: del .ini vacío a un dispositivo con mapa."""
    monkeypatch.chdir(tmp_path)          # el applier resuelve rutas contra el cwd
    ini = tmp_path / "src" / "Config" / "config.ini"
    ini.parent.mkdir(parents=True)
    ini.write_text(INI_VACIO)

    app = ModbusApp(manager(ini))
    assert app._load_configs() is True and app.device_configs == {}

    ConfigApplier().apply(RemoteConfig.model_validate(CONFIG_CRM))

    recargado = ModbusApp(manager(ini))
    assert recargado._load_configs() is True
    assert list(recargado.device_configs) == ["Medidor"]
    assert recargado._load_maps() is True
    assert list(recargado.device_maps) == ["Medidor"]

    mapa = json.loads((tmp_path / "src/Modbus/maps/Medidor.json").read_text())
    assert list(mapa) == ["Voltaje A"]


# ---------------------------------------------------------------------------
# 5. Salida limpia cuando initialize() falla
# ---------------------------------------------------------------------------

def _cargar_main():
    """main.py vive en la raíz del repo, fuera de los paquetes de src/."""
    spec = importlib.util.spec_from_file_location("gateway_main", RAIZ / "main.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


async def test_si_initialize_falla_se_cierran_las_conexiones():
    """Sin esto queda abierta la sesión aiohttp: el 'Unclosed connector'."""
    modulo = _cargar_main()

    tm = MagicMock()
    tm.initialize = AsyncMock(return_value=False)
    tm.start_all_tasks = AsyncMock()
    tm.stop_all_tasks = AsyncMock()

    with patch.object(modulo, "TaskManager", return_value=tm):
        await modulo.main()

    tm.stop_all_tasks.assert_awaited_once()
    tm.start_all_tasks.assert_not_awaited()
