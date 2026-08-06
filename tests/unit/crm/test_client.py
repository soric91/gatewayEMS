"""
Tests del cliente HTTP del CRM contra un servidor aiohttp real.

Se levanta un CRM de mentira que responde como el de verdad, en vez de doblar
`ClientSession`: así se ejercitan el ETag, el 304, el 403 y el reintento tras
401 con la semántica auténtica de HTTP.
"""
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from src.Crm.client import CrmAuthError, CrmClient, CrmError

pytestmark = pytest.mark.unit

UUID = "4f50cc89-8030-4654-a2cc-4a1ec34ab37a"
CREDENCIAL = "credencial-buena"
VERSION = "2b26ca9b106b8c463d7d590e31cbeca4ca12fd13b892a0b73c9e68adc7e5b8a7"

CONFIG = {
    "gateway_uuid": UUID,
    "numero_serie": "gateway iot -s1",
    "firmware_version": "1.0.0",
    "generated_at": "2026-08-05T21:38:49.260470Z",
    "config_version": VERSION,
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
            "device_id": 11,
            "modbusconnect": True,
            "modbusread": True,
            "blockreading": True,
            "map": {
                "Voltaje A": {
                    "address": "0x2000", "data_type": "f", "gain": "1",
                    "unit": "V", "register_type": "holding",
                }
            },
        }
    ],
}


class CrmFalso:
    """CRM de mentira con el mismo contrato que el real."""

    def __init__(self):
        self.tokens_emitidos = 0
        self.token_valido = "token-1"
        self.config_habilitada = True
        self.credencial_revocada = False
        self.acks = []
        self.peticiones = []

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/api/v1/gateway/token", self.token)
        app.router.add_post(f"/api/v1/gateway/{UUID}/heartbeat", self.heartbeat)
        app.router.add_get(f"/api/v1/gateway/{UUID}/config", self.config)
        app.router.add_post(f"/api/v1/gateway/{UUID}/config/ack", self.ack)
        return app

    def _autorizado(self, request) -> bool:
        return request.headers.get("Authorization") == f"Bearer {self.token_valido}"

    async def token(self, request):
        cuerpo = await request.json()
        if self.credencial_revocada or cuerpo.get("credential") != CREDENCIAL:
            return web.json_response({"detail": "invalid"}, status=401)
        self.tokens_emitidos += 1
        self.token_valido = f"token-{self.tokens_emitidos}"
        return web.json_response(
            {"access_token": self.token_valido, "token_type": "bearer",
             "expires_in": 86400}
        )

    async def heartbeat(self, request):
        self.peticiones.append("heartbeat")
        if not self._autorizado(request):
            return web.json_response({"detail": "expired"}, status=401)
        return web.json_response(
            {
                "gateway_uuid": UUID,
                "ultima_conexion": "2026-08-05T21:38:49Z",
                "config_habilitada": self.config_habilitada,
                "config_version_actual": VERSION,
            }
        )

    async def config(self, request):
        self.peticiones.append("config")
        if not self._autorizado(request):
            return web.json_response({"detail": "expired"}, status=401)

        if not self.config_habilitada:
            return web.json_response({"detail": "not enabled"}, status=403)

        etag = f'"{VERSION}"'
        if request.headers.get("If-None-Match") in (etag, VERSION):
            return web.Response(status=304, headers={"ETag": etag})

        return web.json_response(CONFIG, headers={"ETag": etag})

    async def ack(self, request):
        if not self._autorizado(request):
            return web.json_response({"detail": "expired"}, status=401)
        cuerpo = await request.json()
        if cuerpo["config_version"] != VERSION:
            return web.json_response({"detail": "stale version"}, status=400)
        self.acks.append(cuerpo["config_version"])
        self.config_habilitada = False        # igual que el CRM real
        return web.json_response({"config_version_aplicada": VERSION})


@pytest.fixture
async def crm():
    falso = CrmFalso()
    server = TestServer(falso.app())
    await server.start_server()
    falso.base_url = str(server.make_url("/api/v1"))
    yield falso
    await server.close()


@pytest.fixture
async def client(crm):
    cliente = CrmClient(
        base_url=crm.base_url, gateway_uuid=UUID, credential=CREDENCIAL, timeout=5
    )
    yield cliente
    await cliente.close()


# --------------------------------------------------------------------------

async def test_token_se_pide_una_vez_y_se_reutiliza(client, crm):
    await client.heartbeat()
    await client.heartbeat()
    await client.get_config()

    assert crm.tokens_emitidos == 1


async def test_descarga_la_configuracion_y_devuelve_el_etag(client):
    config, etag = await client.get_config()

    assert config.config_version == VERSION
    assert config.devices[0].name == "Modbus_DTUS666"
    assert etag == f'"{VERSION}"'


async def test_304_no_devuelve_configuracion(client):
    _, etag = await client.get_config()

    config, etag2 = await client.get_config(etag)

    assert config is None
    assert etag2 == etag


async def test_403_significa_al_dia_no_error(client, crm):
    crm.config_habilitada = False

    config, _ = await client.get_config()

    assert config is None          # sin excepción


async def test_401_pide_token_nuevo_y_reintenta_una_vez(client, crm):
    await client.heartbeat()
    assert crm.tokens_emitidos == 1

    crm.token_valido = "otro-token"      # el del cliente queda obsoleto

    respuesta = await client.heartbeat()

    assert crm.tokens_emitidos == 2
    assert respuesta["config_habilitada"] is True


async def test_credencial_revocada_lanza_CrmAuthError(client, crm):
    crm.credencial_revocada = True

    with pytest.raises(CrmAuthError):
        await client.heartbeat()


async def test_ack_confirma_la_version(client, crm):
    await client.get_config()

    await client.acknowledge(VERSION)

    assert crm.acks == [VERSION]
    assert crm.config_habilitada is False


async def test_ack_con_version_obsoleta_lanza_CrmError(client):
    with pytest.raises(CrmError, match="400"):
        await client.acknowledge("version-vieja")


async def test_heartbeat_envia_los_datos_opcionales(client, crm):
    respuesta = await client.heartbeat(firmware_version="1.0.0", ip_actual="10.0.0.5")

    assert respuesta["gateway_uuid"] == UUID


async def test_tras_el_ack_la_descarga_responde_403(client, crm):
    """El ciclo completo del CRM: descargar, confirmar, y quedar al día."""
    config, etag = await client.get_config()
    await client.acknowledge(config.config_version)

    siguiente, _ = await client.get_config(etag)

    assert siguiente is None
