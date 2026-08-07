"""
TLS del cliente MQTT.

El síntoma que lo motiva: con mosquitto escuchando TLS y el cliente hablando en
claro, el gateway manda su CONNECT, el broker espera un ClientHello que no llega
y los dos se quedan esperando hasta `aiomqtt.MqttError: timed out`. Ni "handshake
failed" ni "certificado inválido": para llegar a esos errores hay que INTENTAR el
handshake, y el cliente ni lo intentaba.

El test que de verdad importa es `test_se_valida_que_el_certificado_sea_del_broker`:
`CERT_REQUIRED` por sí solo comprueba que la cadena del certificado sea buena, no
que el certificado sea el de NUESTRO broker. Sin `check_hostname`, cualquiera que
pueda desviar el tráfico y traiga un certificado válido de un dominio suyo —que
cuesta cero— es aceptado.
"""
import ssl

import pytest

from src.Core.config import settings
from src.Utils.utils import MQTTManager

pytestmark = pytest.mark.unit


def test_sin_tls_no_se_pasan_parametros(monkeypatch):
    """None es lo que aiomqtt espera para hablar en claro."""
    monkeypatch.setattr(settings, "MQTT_USE_TLS", False)

    assert MQTTManager._build_tls_params() is None


def test_con_tls_se_exige_certificado(monkeypatch):
    monkeypatch.setattr(settings, "MQTT_USE_TLS", True)

    params = MQTTManager._build_tls_params()

    assert params is not None
    assert params.cert_reqs == ssl.CERT_REQUIRED


def test_se_valida_que_el_certificado_sea_del_broker(monkeypatch):
    """
    Comprobar la cadena no basta: hay que comprobar el NOMBRE.

    `ssl.PROTOCOL_TLS` crea un contexto con `check_hostname=False`, y paho sólo
    fuerza ese valor cuando se pide `CERT_NONE`; en el resto de casos respeta el
    del contexto. Con él, un certificado perfectamente válido de otro dominio
    pasa la validación.
    """
    monkeypatch.setattr(settings, "MQTT_USE_TLS", True)

    params = MQTTManager._build_tls_params()

    # Se comprueba sobre el contexto real, que es lo que acaba decidiendo,
    # y no sobre la constante que le pasamos.
    contexto = ssl.SSLContext(params.tls_version)
    assert contexto.check_hostname is True, (
        "sin check_hostname vale el certificado de cualquiera"
    )
    assert contexto.verify_mode == ssl.CERT_REQUIRED


def test_no_se_usa_el_protocolo_deprecado(monkeypatch):
    """`ssl.PROTOCOL_TLS` está deprecado desde Python 3.10."""
    monkeypatch.setattr(settings, "MQTT_USE_TLS", True)

    assert MQTTManager._build_tls_params().tls_version != ssl.PROTOCOL_TLS


async def test_el_cliente_se_construye_con_los_parametros_tls(monkeypatch):
    """La conexión real: que los parámetros lleguen a aiomqtt.Client."""
    monkeypatch.setattr(settings, "MQTT_USE_TLS", True)

    recibidos = {}

    class ClienteFalso:
        def __init__(self, **kwargs):
            recibidos.update(kwargs)

        async def __aenter__(self):
            return self

    monkeypatch.setattr("src.Utils.utils.aiomqtt.Client", ClienteFalso)

    await MQTTManager().connect()

    assert recibidos["tls_params"] is not None
    assert recibidos["tls_params"].cert_reqs == ssl.CERT_REQUIRED


async def test_sin_tls_el_cliente_se_construye_en_claro(monkeypatch):
    monkeypatch.setattr(settings, "MQTT_USE_TLS", False)

    recibidos = {}

    class ClienteFalso:
        def __init__(self, **kwargs):
            recibidos.update(kwargs)

        async def __aenter__(self):
            return self

    monkeypatch.setattr("src.Utils.utils.aiomqtt.Client", ClienteFalso)

    await MQTTManager().connect()

    assert recibidos["tls_params"] is None


async def test_las_suscripciones_se_reaplican_al_conectar(monkeypatch):
    """
    Guarda contra una pérdida fácil al tocar `connect()`.

    Si `_resubscribe()` desaparece de aquí, el topic de configuración del CRM no
    vuelve tras una reconexión: el gateway sigue vivo, publicando, y deja de
    recibir configuración para siempre. Y no lo dice ningún log.
    """
    monkeypatch.setattr(settings, "MQTT_USE_TLS", False)

    class ClienteFalso:
        def __init__(self, **kwargs):
            self.suscritos = []

        async def __aenter__(self):
            return self

        async def subscribe(self, topic, qos=None):
            self.suscritos.append(topic)

    monkeypatch.setattr("src.Utils.utils.aiomqtt.Client", ClienteFalso)

    manager = MQTTManager()
    await manager.subscribe("crm/gateways/uuid/config")   # antes de conectar
    await manager.connect()

    assert manager._client.suscritos == ["crm/gateways/uuid/config"]
