from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import quote_plus


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
    env_file=(".env.local", ".env"),
        env_ignore_empty=True,
        extra="ignore",
    )

    INFLUXDB_TOKEN: str
    INFLUXDB_ADMIN_USER: str
    INFLUXDB_ADMIN_PASSWORD: str
    INFLUXDB_ORG: str
    INFLUXDB_BUCKET: str
    INFLUXDB_RETENTION: str
    INFLUXDB_URL: str
    
    MQTT_USER: str
    MQTT_PASSWORD: str
    MQTT_HOST: str
    MQTT_PORT: int
    MQTT_TOPIC_TLM: str
    MQTT_TOPIC_CRM: str
    MQTT_QOS: int
    MQTT_CLIENT_ID: str
    GATEWAY_UUID: str

    # --- CRM -----------------------------------------------------------
    # Credencial de larga vida que el CRM enseña una sola vez al emitirla.
    # Se cambia por un token corto en POST /gateway/token.
    CRM_API_URL: str
    GATEWAY_CREDENTIAL: str
    CRM_HEARTBEAT_SECONDS: int = 60
    CRM_HTTP_TIMEOUT: int = 30

    @property
    def MQTT_TOPIC_CONFIG(self) -> str:
        """Donde el CRM avisa a ESTE gateway de que tiene configuración."""
        return f"{self.MQTT_TOPIC_CRM.rstrip('/')}/{self.GATEWAY_UUID}/config"

    @property
    def MQTT_TOPIC_STATUS(self) -> str:
        """Donde este gateway reporta su presencia al CRM."""
        return f"{self.MQTT_TOPIC_CRM.rstrip('/')}/{self.GATEWAY_UUID}/status"

    def topic_telemetria(self, device_id, identify_device) -> str:
        """
        Topic de telemetría de UN equipo: `<base>/<device_id>/<uuid>`.

        Un topic por equipo para que quien escuche pueda quedarse sólo con el
        suyo. Con todo en un topic único había que recibir las lecturas de
        todos los equipos y filtrarlas en el cliente.

        Comodines útiles para el que consume:
            <base>/+/<uuid>   un equipo, sea cual sea su esclavo
            <base>/74/+       el esclavo 74
            <base>/#          todo
        """
        return (
            f"{self.MQTT_TOPIC_TLM.rstrip('/')}"
            f"/{self._segmento(device_id)}/{self._segmento(identify_device)}"
        )

    @staticmethod
    def _segmento(valor) -> str:
        """
        Deja un valor listo para ser UN nivel del topic.

        `/`, `+` y `#` cambiarían la estructura o convertirían el topic en un
        filtro: se sustituyen. Un valor vacío pasa a 'desconocido' para no
        generar un nivel vacío, que el broker sí acepta pero nadie espera.
        """
        texto = "" if valor is None else str(valor).strip()
        for prohibido in ("/", "+", "#"):
            texto = texto.replace(prohibido, "_")
        return texto or "desconocido"


settings = Settings()