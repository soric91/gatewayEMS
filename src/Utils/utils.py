import asyncio
import inspect
from dataclasses import dataclass, is_dataclass, asdict
from src.Utils.logging import get_logger
from src.Core.config import settings
import aiomqtt
import threading
from typing import Callable, Any, Dict, Optional
import json

logger = get_logger(__name__)


DEFAULT_QUEUE_MAXSIZE = 1000


class QueueManager:
    """
    Bus de fan-out: cada suscriptor tiene su propia cola y recibe TODOS
    los lotes publicados.

    Con una sola asyncio.Queue compartida, cada lote llegaba a un único
    consumidor (InfluxDB o MQTT, nunca a los dos).

    Si la cola de un suscriptor se llena (sink caído o lento) se descarta
    el lote más antiguo de ESE suscriptor, para que no bloquee la lectura
    Modbus ni a los demás sinks.
    """

    def __init__(self, maxsize: int = DEFAULT_QUEUE_MAXSIZE):
        self._maxsize = maxsize
        self._subscribers: Dict[str, asyncio.Queue] = {}
        self._dropped: Dict[str, int] = {}

    def subscribe(self, name: str) -> asyncio.Queue:
        """Registra (o recupera) la cola de un suscriptor. Idempotente."""
        if name not in self._subscribers:
            self._subscribers[name] = asyncio.Queue(maxsize=self._maxsize)
            self._dropped[name] = 0
            logger.info(f"📬 Suscriptor '{name}' registrado en la cola")
        return self._subscribers[name]

    def unsubscribe(self, name: str) -> None:
        self._subscribers.pop(name, None)
        self._dropped.pop(name, None)

    @property
    def subscribers(self) -> list:
        return list(self._subscribers.keys())

    def dropped_count(self, name: str) -> int:
        """Lotes descartados por cola llena para ese suscriptor."""
        return self._dropped.get(name, 0)

    def qsize(self, name: str) -> int:
        queue = self._subscribers.get(name)
        return queue.qsize() if queue else 0

    async def publish(self, data):
        """Entrega el mismo lote a todos los suscriptores."""
        if not self._subscribers:
            logger.warning("⚠️ Publicación sin suscriptores, lote descartado")
            return

        for name, queue in self._subscribers.items():
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.task_done()
                except asyncio.QueueEmpty:
                    pass
                queue.put_nowait(data)
                self._dropped[name] += 1
                logger.warning(
                    f"⚠️ Cola de '{name}' llena ({self._maxsize}), "
                    f"descartado el lote más antiguo (total descartados: {self._dropped[name]})"
                )

    async def consume(self, name: str):
        """Espera el siguiente lote del suscriptor indicado."""
        return await self.subscribe(name).get()


def _to_serializable(obj: Any) -> Any:
    """Convierte objetos, listas y dicts a algo que json.dumps entienda."""
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [_to_serializable(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    if hasattr(obj, "model_dump"):      # Pydantic v2
        return obj.model_dump()
    return obj


class MQTTManager:

    def __init__(self):
        self._client: Optional[aiomqtt.Client] = None
        # topic -> qos, para poder re-suscribir tras una reconexión
        self._subscriptions: Dict[str, int] = {}
        # (filtro de topic, handler) — el filtro admite comodines + y #
        self._handlers: list[tuple[str, Callable[[str, Any], Any]]] = []


    async def connect(self):
        try:
            self._client = aiomqtt.Client(
                hostname=settings.MQTT_HOST,
                port=settings.MQTT_PORT,
                username=settings.MQTT_USER,
                password=settings.MQTT_PASSWORD,
                identifier=settings.MQTT_CLIENT_ID
            )
            await self._client.__aenter__()
            logger.info("Connected to MQTT broker")
            await self._resubscribe()
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            raise e
    
       
    async def disconnect(self):
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None
            logger.info("Disconnected from MQTT broker")
            
    @staticmethod
    def _serialize(payload: Any) -> str:
        """Normaliza cualquier payload a una cadena lista para publicar."""
        message = _to_serializable(payload)
        if isinstance(message, str):
            return message
        return json.dumps(message, ensure_ascii=False, default=str)

    async def _publish_raw(self,topic: str, message: str) -> None:
        await self._client.publish(topic, message, qos=settings.MQTT_QOS)
        logger.info(
            f"Published message to topic {topic}: {len(message)} bytes"
        )

    async def publish(self, topic: str, payload: dict[str, Any]):
        if not self._client:
            logger.error("MQTT client is not connected. Cannot publish message.")
            return

        # Fuera del try: un fallo de serialización no debe disparar reconexión.
        message = self._serialize(payload)

        try:
            await self._publish_raw(topic, message)
        except aiomqtt.MqttError:
            logger.warning("⚠️ Conexión MQTT perdida, reconectando...")
            await self._reconnect()
            await self._publish_raw(topic, message)


    # ------------------------------------------------------------------
    # Recepción
    # ------------------------------------------------------------------

    async def subscribe(self, topic: str, qos: Optional[int] = None) -> None:
        """
        Se suscribe a un topic (admite comodines: `gateway/+/cmd`, `gateway/#`).

        La suscripción queda registrada, así que se restaura automáticamente
        tras una reconexión. Puede llamarse antes de `connect()`: se aplicará
        al conectar.
        """
        qos = settings.MQTT_QOS if qos is None else qos
        self._subscriptions[topic] = qos

        if not self._client:
            logger.info(f"📥 Suscripción a '{topic}' registrada (pendiente de conexión)")
            return

        await self._client.subscribe(topic, qos=qos)
        logger.info(f"📥 Suscrito a '{topic}' (qos={qos})")

    async def unsubscribe(self, topic: str) -> None:
        """Cancela la suscripción a un topic."""
        self._subscriptions.pop(topic, None)
        if self._client:
            await self._client.unsubscribe(topic)
            logger.info(f"📤 Desuscrito de '{topic}'")

    async def _resubscribe(self) -> None:
        """Reaplica todas las suscripciones registradas (tras reconectar)."""
        for topic, qos in self._subscriptions.items():
            try:
                await self._client.subscribe(topic, qos=qos)
                logger.info(f"📥 Re-suscrito a '{topic}' (qos={qos})")
            except Exception as e:
                logger.error(f"❌ No se pudo re-suscribir a '{topic}': {e}")

    def on_message(self, topic_filter: str, handler: Callable[[str, Any], Any]) -> None:
        """
        Registra un handler para los mensajes que casen con `topic_filter`.

        El handler recibe `(topic, payload)` y puede ser síncrono o async.
        Un mismo mensaje se entrega a todos los handlers que casen.
        """
        self._handlers.append((topic_filter, handler))
        logger.info(f"🎯 Handler registrado para '{topic_filter}'")

    @staticmethod
    def _decode(payload: Any) -> Any:
        """
        Decodifica el payload recibido: JSON si lo es, texto si no,
        bytes crudos si ni siquiera es texto.
        """
        if isinstance(payload, (bytes, bytearray)):
            try:
                payload = payload.decode("utf-8")
            except UnicodeDecodeError:
                logger.warning("⚠️ Payload MQTT no es UTF-8, se entrega como bytes")
                return bytes(payload)

        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                return payload

        return payload

    async def messages(self):
        """
        Iterador crudo de mensajes: `async for topic, payload in mqtt.messages()`.

        Alternativa a `listen()` cuando se prefiere procesar en línea en vez
        de con handlers registrados.
        """
        if not self._client:
            raise RuntimeError("MQTT client is not connected. Cannot receive messages.")

        async for message in self._client.messages:
            yield str(message.topic), self._decode(message.payload)

    async def _dispatch(self, message) -> None:
        """Entrega un mensaje a todos los handlers cuyo filtro case."""
        topic = str(message.topic)
        payload = self._decode(message.payload)

        entregado = False
        for topic_filter, handler in self._handlers:
            if not message.topic.matches(topic_filter):
                continue

            entregado = True
            try:
                resultado = handler(topic, payload)
                if inspect.isawaitable(resultado):
                    await resultado
            except Exception as e:
                # Un handler roto no puede tumbar el bucle ni a los demás
                logger.exception(f"❌ Error en handler de '{topic_filter}' para '{topic}': {e}")

        if not entregado:
            logger.debug(f"📭 Mensaje en '{topic}' sin handler registrado")

    async def listen(self, reconnect_delay: float = 5.0) -> None:
        """
        Bucle de recepción: despacha cada mensaje a sus handlers y se
        reconecta (re-suscribiéndose) si se cae la conexión.

        Pensado para correr como tarea asyncio; se detiene al cancelarla.
        """
        logger.info("👂 Escucha MQTT iniciada")
        try:
            while True:
                try:
                    if not self._client:
                        await self.connect()

                    async for message in self._client.messages:
                        await self._dispatch(message)

                    logger.warning("⚠️ Flujo de mensajes MQTT terminado, reconectando...")

                except aiomqtt.MqttError as e:
                    logger.warning(f"⚠️ Conexión MQTT perdida durante la escucha: {e}")

                await asyncio.sleep(reconnect_delay)
                await self._reconnect()

        except asyncio.CancelledError:
            logger.info("⏹️ Escucha MQTT cancelada")
            raise

    async def _reconnect(self):
        try:
            await self.disconnect()
        except Exception:
            self._client = None
        await self.connect()
        
        
        