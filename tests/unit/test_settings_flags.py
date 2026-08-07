"""
Los dos interruptores nuevos y la validación de las credenciales del servidor.

`Settings` se instancia aquí a mano (no se usa el singleton `settings`) porque
lo que se comprueba es justo lo que pasa AL CONSTRUIRLO: qué valores toma por
defecto y cuándo se niega a existir.

`_env_file=None` en cada caso es deliberado: sin eso, pydantic-settings leería
el `.env` de la máquina que corre los tests y el resultado dependería de cómo
tenga configurado su gateway quien los lanza.
"""
import pytest
from pydantic import ValidationError

from src.Core.config import Settings

pytestmark = pytest.mark.unit

# Lo mínimo que Settings exige para existir; los interruptores se añaden encima.
BASE = {
    "INFLUXDB_TOKEN": "t",
    "INFLUXDB_ADMIN_USER": "u",
    "INFLUXDB_ADMIN_PASSWORD": "p",
    "INFLUXDB_ORG": "org",
    "INFLUXDB_BUCKET": "bucket",
    "INFLUXDB_RETENTION": "90d",
    "INFLUXDB_URL": "http://localhost:8086",
    "MQTT_USER": "u",
    "MQTT_PASSWORD": "p",
    "MQTT_HOST": "localhost",
    "MQTT_PORT": 1883,
    "MQTT_TOPIC_TLM": "gatewayems/modbus",
    "MQTT_TOPIC_CRM": "crm/gateways",
    "MQTT_QOS": 1,
    "MQTT_CLIENT_ID": "gw-01",
    "GATEWAY_UUID": "00000000-0000-0000-0000-000000000000",
    "CRM_API_URL": "http://localhost:8000/api/v1",
    "GATEWAY_CREDENTIAL": "c",
}

SERVIDOR_COMPLETO = {
    "INFLUXDB_SERVER_ACTIVE": True,
    "INFLUXDB_SERVER_URL": "https://central:8086",
    "INFLUXDB_SERVER_TOKEN": "token-servidor",
    "INFLUXDB_SERVER_ORG": "org-servidor",
    "INFLUXDB_SERVER_BUCKET": "telemetry_server",
}


def construir(**extra) -> Settings:
    return Settings(_env_file=None, **{**BASE, **extra})


# --- valores por defecto ---------------------------------------------------


def test_por_defecto_todo_se_comporta_como_antes():
    """Un .env que no mencione los interruptores no cambia nada."""
    ajustes = construir()

    assert ajustes.MQTT_ACTIVE is True
    assert ajustes.INFLUXDB_SERVER_ACTIVE is False
    assert ajustes.INFLUXDB_SERVER_INTERVAL_MINUTES == 15


@pytest.mark.parametrize("valor", ["false", "False", "0", "no", "off"])
def test_las_formas_de_apagar_mqtt_que_se_escriben_en_un_env(valor):
    """En un .env se escribe texto, no un bool de Python."""
    assert construir(MQTT_ACTIVE=valor).MQTT_ACTIVE is False


@pytest.mark.parametrize("valor", ["true", "True", "1", "yes", "on"])
def test_las_formas_de_encender_la_replica(valor):
    ajustes = construir(**{**SERVIDOR_COMPLETO, "INFLUXDB_SERVER_ACTIVE": valor})

    assert ajustes.INFLUXDB_SERVER_ACTIVE is True


# --- la validación del servidor central ------------------------------------


def test_con_la_replica_apagada_no_se_piden_credenciales():
    """El caso de todos los gateways de hoy: ni se mencionan las variables."""
    ajustes = construir(INFLUXDB_SERVER_ACTIVE=False)

    assert ajustes.INFLUXDB_SERVER_URL == ""


def test_la_replica_completa_es_valida():
    ajustes = construir(**SERVIDOR_COMPLETO)

    assert ajustes.INFLUXDB_SERVER_BUCKET == "telemetry_server"


@pytest.mark.parametrize(
    "ausente",
    [
        "INFLUXDB_SERVER_URL",
        "INFLUXDB_SERVER_TOKEN",
        "INFLUXDB_SERVER_ORG",
        "INFLUXDB_SERVER_BUCKET",
    ],
)
def test_encender_la_replica_sin_credenciales_no_arranca(ausente):
    """
    Falla al construir Settings, o sea al arrancar el proceso.

    Sin esto el fallo aparecería en el primer ciclo de replicación, quince
    minutos después, enterrado en la traza de una tarea de fondo.
    """
    incompleto = {**SERVIDOR_COMPLETO, ausente: ""}

    with pytest.raises(ValidationError) as fallo:
        construir(**incompleto)

    # El mensaje tiene que nombrar la variable que falta: es lo único que
    # convierte el error en algo accionable a las tres de la mañana.
    assert ausente in str(fallo.value)


def test_el_mensaje_nombra_todas_las_que_faltan_de_una_vez():
    with pytest.raises(ValidationError) as fallo:
        construir(INFLUXDB_SERVER_ACTIVE=True)

    mensaje = str(fallo.value)
    for variable in (
        "INFLUXDB_SERVER_URL",
        "INFLUXDB_SERVER_TOKEN",
        "INFLUXDB_SERVER_ORG",
        "INFLUXDB_SERVER_BUCKET",
    ):
        assert variable in mensaje


def test_credenciales_en_blanco_no_cuentan_como_puestas():
    """Espacios en un .env son un despiste, no una credencial."""
    with pytest.raises(ValidationError):
        construir(**{**SERVIDOR_COMPLETO, "INFLUXDB_SERVER_TOKEN": "   "})


@pytest.mark.parametrize("intervalo", [0, -5])
def test_un_intervalo_no_positivo_no_arranca(intervalo):
    """Un intervalo de 0 sería un bucle de replicación sin pausa."""
    with pytest.raises(ValidationError):
        construir(**SERVIDOR_COMPLETO, INFLUXDB_SERVER_INTERVAL_MINUTES=intervalo)


def test_el_intervalo_solo_se_valida_con_la_replica_encendida():
    """Un valor absurdo heredado no debe impedir arrancar si nadie lo usa."""
    ajustes = construir(INFLUXDB_SERVER_ACTIVE=False, INFLUXDB_SERVER_INTERVAL_MINUTES=0)

    assert ajustes.INFLUXDB_SERVER_INTERVAL_MINUTES == 0
