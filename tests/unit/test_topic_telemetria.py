"""
Topic de telemetría por equipo: `<base>/<device_id>/<identify_device>`.

El objetivo del formato es que quien escucha pueda quedarse con UN equipo.
Por eso, además de la forma del topic, se comprueba contra el emparejador real
de aiomqtt que los comodines seleccionan lo que tienen que seleccionar.
"""
import pytest
from aiomqtt import Topic

from src.Core.config import settings

BASE = settings.MQTT_TOPIC_TLM
UUID_EQUIPO = "7d8704bd-5fe0-4686-972e-a71febc718d7"


def test_forma_del_topic():
    assert (
        settings.topic_telemetria(74, UUID_EQUIPO)
        == f"{BASE}/74/{UUID_EQUIPO}"
    )


def test_la_base_con_barra_final_no_duplica_el_separador(monkeypatch):
    monkeypatch.setattr(settings, "MQTT_TOPIC_TLM", "gatewayems/modbus/", raising=False)

    assert settings.topic_telemetria(74, UUID_EQUIPO) == (
        f"gatewayems/modbus/74/{UUID_EQUIPO}"
    )


@pytest.mark.parametrize("valor", ["a/b", "a+b", "a#b"])
def test_los_caracteres_que_romperian_el_topic_se_sustituyen(valor):
    """Un '/' añadiría un nivel; '+' y '#' convertirían el topic en un filtro."""
    topic = settings.topic_telemetria(74, valor)

    assert topic == f"{BASE}/74/a_b"
    assert topic.count("/") == BASE.count("/") + 2


def test_sin_identificador_no_queda_un_nivel_vacio():
    assert settings.topic_telemetria(74, None) == f"{BASE}/74/desconocido"
    assert settings.topic_telemetria("", UUID_EQUIPO) == (
        f"{BASE}/desconocido/{UUID_EQUIPO}"
    )


# --- lo que puede escuchar el que consume ---------------------------------


def test_un_equipo_se_escucha_sin_recibir_los_demas():
    mio = Topic(settings.topic_telemetria(74, UUID_EQUIPO))
    ajeno = Topic(settings.topic_telemetria(11, "bf6a469f-4c2a-4402-9438-49a491ad2238"))

    filtro = f"{BASE}/+/{UUID_EQUIPO}"

    assert mio.matches(filtro)
    assert not ajeno.matches(filtro), "el filtro por equipo dejó pasar otro equipo"


def test_el_comodin_de_todo_sigue_recibiendo_ambos():
    mio = Topic(settings.topic_telemetria(74, UUID_EQUIPO))
    ajeno = Topic(settings.topic_telemetria(11, "bf6a469f-4c2a-4402-9438-49a491ad2238"))

    assert mio.matches(f"{BASE}/#")
    assert ajeno.matches(f"{BASE}/#")


def test_el_topic_antiguo_ya_no_recibe_nada():
    """La base a secas dejó de ser un topic de publicación."""
    assert not Topic(settings.topic_telemetria(74, UUID_EQUIPO)).matches(BASE)
