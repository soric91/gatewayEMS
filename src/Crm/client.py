"""
Cliente HTTP del CRM.

Habla los cuatro endpoints que el backend expone al firmware y nada más:
token, heartbeat, configuración y acuse de recibo. No escribe archivos ni sabe
qué se hace con lo que descarga — de eso se encarga `src/Crm/applier.py`.

Reglas del contrato (app/api/v1/gateway_config.py del CRM):

- 401  el token venció o la credencial fue revocada. Se pide token nuevo y se
       reintenta UNA vez; si vuelve a fallar, la credencial ya no sirve.
- 403  la descarga no está habilitada: el gateway ya está al día. No es error.
- 304  la versión que se tiene es la vigente. No se reescribe nada.
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import aiohttp

from src.Core.config import settings
from src.Models.model import RemoteConfig
from src.Utils.logging import get_logger

logger = get_logger(__name__)

# Margen para renovar el token antes de que expire de verdad.
TOKEN_MARGEN_SEGUNDOS = 60


class CrmError(Exception):
    """Fallo hablando con el CRM que no encaja en los casos previstos."""


class CrmAuthError(CrmError):
    """La credencial no sirve: no hay reintento que lo arregle."""


@dataclass
class CrmClient:
    """
    Cliente del CRM con token cacheado.

    La sesión aiohttp se crea al primer uso y se reutiliza; hay que cerrarla
    con `close()` al apagar el sistema.
    """

    base_url: str = field(default_factory=lambda: settings.CRM_API_URL.rstrip("/"))
    gateway_uuid: str = field(default_factory=lambda: settings.GATEWAY_UUID)
    credential: str = field(default_factory=lambda: settings.GATEWAY_CREDENTIAL)
    timeout: int = field(default_factory=lambda: settings.CRM_HTTP_TIMEOUT)

    _session: Optional[aiohttp.ClientSession] = field(init=False, default=None)
    _token: Optional[str] = field(init=False, default=None)
    _token_expira: float = field(init=False, default=0.0)

    # --- infraestructura -------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    async def _authorized(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Cabeceras con el token, fusionadas con las que pida quien llama."""
        headers = {"Authorization": f"Bearer {await self._ensure_token()}"}
        if extra:
            headers.update(extra)
        return headers

    # --- token -----------------------------------------------------------

    async def _ensure_token(self) -> str:
        """Devuelve un token válido, pidiéndolo si hace falta."""
        ahora = asyncio.get_running_loop().time()
        if self._token and ahora < self._token_expira:
            return self._token
        return await self.issue_token()

    async def issue_token(self) -> str:
        """Cambia la credencial de larga vida por un token corto."""
        session = await self._get_session()
        async with session.post(
            self._url("/gateway/token"),
            json={"gateway_uuid": self.gateway_uuid, "credential": self.credential},
        ) as response:
            if response.status == 401:
                raise CrmAuthError("Credencial de gateway inválida o revocada")
            if response.status >= 400:
                raise CrmError(f"POST /gateway/token → {response.status}")

            data = await response.json()

        self._token = data["access_token"]
        vida = int(data.get("expires_in", 3600))
        self._token_expira = (
            asyncio.get_running_loop().time() + max(vida - TOKEN_MARGEN_SEGUNDOS, 0)
        )
        logger.info(f"🔑 Token del CRM obtenido (vigencia {vida}s)")
        return self._token

    async def _request(self, method: str, path: str, **kwargs) -> aiohttp.ClientResponse:
        """
        Hace la petición autenticada y reintenta una vez ante un 401.

        Un 401 es la señal de que el token venció; el CRM lo documenta así para
        que el firmware no tenga que llevar la cuenta del tiempo.
        """
        session = await self._get_session()
        extra = kwargs.pop("headers", None)

        response = await session.request(
            method, self._url(path), headers=await self._authorized(extra), **kwargs
        )
        if response.status != 401:
            return response

        response.release()
        logger.info("🔑 Token rechazado, pidiendo uno nuevo y reintentando")
        self._token = None
        await self.issue_token()

        return await session.request(
            method, self._url(path), headers=await self._authorized(extra), **kwargs
        )

    # --- endpoints -------------------------------------------------------

    async def heartbeat(
        self, firmware_version: Optional[str] = None, ip_actual: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Reporta que el equipo está vivo.

        La respuesta dice si hay configuración esperando, así que este es el
        camino que funciona aunque el broker MQTT esté caído.
        """
        payload: Dict[str, Any] = {}
        if firmware_version:
            payload["firmware_version"] = firmware_version
        if ip_actual:
            payload["ip_actual"] = ip_actual

        response = await self._request(
            "POST", f"/gateway/{self.gateway_uuid}/heartbeat", json=payload
        )
        async with response:
            if response.status == 401:
                raise CrmAuthError("Credencial rechazada en el heartbeat")
            if response.status >= 400:
                raise CrmError(f"POST /heartbeat → {response.status}")
            return await response.json()

    async def get_config(
        self, etag: Optional[str] = None
    ) -> Tuple[Optional[RemoteConfig], Optional[str]]:
        """
        Descarga la configuración.

        :return: (config, etag). `(None, None)` cuando no hay nada que aplicar,
                 sea porque no cambió (304) o porque la descarga está apagada
                 tras un acuse de recibo previo (403).
        """
        headers = {"If-None-Match": etag} if etag else None

        response = await self._request(
            "GET", f"/gateway/{self.gateway_uuid}/config", headers=headers
        )
        async with response:
            if response.status == 304:
                logger.info("✅ Configuración sin cambios (304)")
                return None, etag

            if response.status == 403:
                logger.info("✅ Descarga no habilitada: el gateway ya está al día")
                return None, etag

            if response.status == 401:
                raise CrmAuthError("Credencial rechazada al pedir la configuración")

            if response.status >= 400:
                raise CrmError(f"GET /config → {response.status}")

            data = await response.json()
            nuevo_etag = response.headers.get("ETag", etag)

        config = RemoteConfig.model_validate(data)
        logger.info(
            f"📥 Configuración descargada: versión {config.config_version[:12]}…, "
            f"{len(config.devices)} dispositivo(s)"
        )
        return config, nuevo_etag

    async def acknowledge(self, config_version: str) -> Dict[str, Any]:
        """
        Avisa al CRM de que la configuración quedó aplicada.

        El CRM exige la versión que está sirviendo ahora mismo: si cambió entre
        la descarga y este acuse, responde 400 y hay que volver a descargar.
        """
        response = await self._request(
            "POST",
            f"/gateway/{self.gateway_uuid}/config/ack",
            json={"config_version": config_version},
        )
        async with response:
            if response.status == 401:
                raise CrmAuthError("Credencial rechazada en el ack")
            if response.status >= 400:
                detalle = await response.text()
                raise CrmError(f"POST /config/ack → {response.status}: {detalle[:200]}")

            logger.info(f"✅ Configuración {config_version[:12]}… confirmada al CRM")
            return await response.json()
