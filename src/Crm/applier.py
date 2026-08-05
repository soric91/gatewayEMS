"""
Traduce la configuración del CRM a los archivos que este gateway ya usa.

El CRM manda un JSON neutro; aquí se convierte en `config.ini` y en los mapas
de `src/Modbus/maps/`. Nada más de la aplicación conoce ese formato.

Tres reglas que gobiernan el módulo:

1. **Validar antes de escribir.** Si algo no cuadra no se toca ni un archivo:
   un gateway con configuración vieja pero leyendo es mucho mejor que uno con
   configuración rota.
2. **Escritura atómica.** `tmp` + `os.replace`. Un corte de luz a mitad no
   puede dejar un `.ini` o un `.json` truncados.
3. **Backup y rollback.** La configuración anterior se guarda antes de pisarla,
   para poder volver si el reload falla.
"""
import configparser
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.Models.model import DATATYPE, ProtocolCom, RemoteConfig, RemoteDevice
from src.Utils.logging import get_logger

logger = get_logger(__name__)

# Claves de [DEFAULT] que el CRM no manda y que hay que conservar tal cual.
DEFAULT_PRESERVADAS = ("logstdout", "logfile", "max_size_bytes", "backup_count",
                       "sampleslog")

# register_type de una variable -> código de función Modbus.
FUNCION_POR_REGISTRO = {"holding": 3, "input": 4}

# El cliente Modbus abre el puerto serie sólo con port y baudrate: 8N1 fijo.
SERIE_ASUMIDA = {"parity": "N", "bytesize": 8, "stopbits": 1}


class ConfigInvalida(Exception):
    """La configuración del CRM no se puede aplicar. No se escribió nada."""


@dataclass
class ConfigApplier:
    """Escribe, respalda y restaura la configuración local del gateway."""

    config_path: Path = field(
        default_factory=lambda: Path("src/Config/config.ini").resolve()
    )
    maps_dir: Path = field(
        default_factory=lambda: Path("src/Modbus/maps").resolve()
    )
    state_dir: Path = field(
        default_factory=lambda: Path("src/Config/remote").resolve()
    )

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def current_file(self) -> Path:
        return self.state_dir / "current.json"

    @property
    def backups_dir(self) -> Path:
        return self.state_dir / "backups"

    # --- estado ----------------------------------------------------------

    def load_state(self) -> Dict[str, Any]:
        """Qué versión está aplicada hoy. Vacío la primera vez."""
        try:
            return json.loads(self.state_file.read_text())
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            logger.warning("⚠️ state.json ilegible, se trata como primera vez")
            return {}

    def save_state(self, **campos: Any) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        estado = self.load_state()
        estado.update(campos)
        self._write_atomic(self.state_file, json.dumps(estado, indent=2))

    # --- validación ------------------------------------------------------

    def validate(self, config: RemoteConfig) -> None:
        """
        Comprueba que la configuración se puede aplicar. Lanza `ConfigInvalida`.

        Se ejecuta con el documento en memoria, antes de tocar el disco.
        """
        if not config.devices:
            raise ConfigInvalida("La configuración no trae ningún dispositivo")

        nombres = [d.name for d in config.devices]
        repetidos = {n for n in nombres if nombres.count(n) > 1}
        if repetidos:
            raise ConfigInvalida(f"Nombres de dispositivo repetidos: {sorted(repetidos)}")

        for device in config.devices:
            self._validate_device(device)

    def _validate_device(self, device: RemoteDevice) -> None:
        etiqueta = f"dispositivo '{device.name}'"

        if not device.name.strip() or "/" in device.name or "\\" in device.name:
            raise ConfigInvalida(f"Nombre inválido: '{device.name}'")

        protocolo = (device.protocol or "").upper()
        if protocolo not in (ProtocolCom.RTU, ProtocolCom.TCP):
            raise ConfigInvalida(f"{etiqueta}: protocolo no soportado '{device.protocol}'")

        if protocolo == ProtocolCom.RTU:
            if not device.serialport:
                raise ConfigInvalida(f"{etiqueta}: RTU sin serialport")
            if not device.baudrate:
                raise ConfigInvalida(f"{etiqueta}: RTU sin baudrate")
        else:
            if not device.host or not device.port:
                raise ConfigInvalida(f"{etiqueta}: TCP necesita host y port")

        if not device.map:
            raise ConfigInvalida(f"{etiqueta}: mapa vacío, no habría nada que leer")

        # Una sola función Modbus por dispositivo: el gateway lee todo el mapa
        # con el mismo código de función.
        tipos = {v.register_type for v in device.map.values()}
        desconocidos = tipos - set(FUNCION_POR_REGISTRO)
        if desconocidos:
            raise ConfigInvalida(f"{etiqueta}: register_type desconocido {sorted(desconocidos)}")
        if len(tipos) > 1:
            raise ConfigInvalida(
                f"{etiqueta}: mezcla {sorted(tipos)} en el mismo mapa; "
                f"el gateway usa una única función Modbus por dispositivo"
            )

        for nombre, variable in device.map.items():
            try:
                int(variable.address, 16)
            except (ValueError, TypeError):
                raise ConfigInvalida(
                    f"{etiqueta}, variable '{nombre}': dirección no hexadecimal "
                    f"'{variable.address}'"
                ) from None

            try:
                DATATYPE(variable.data_type)
            except ValueError:
                raise ConfigInvalida(
                    f"{etiqueta}, variable '{nombre}': data_type '{variable.data_type}' "
                    f"no soportado ({[d.value for d in DATATYPE]})"
                ) from None

            try:
                float(variable.gain)
            except (ValueError, TypeError):
                raise ConfigInvalida(
                    f"{etiqueta}, variable '{nombre}': gain no numérico '{variable.gain}'"
                ) from None

        self._warn_campos_ignorados(device)

    @staticmethod
    def _warn_campos_ignorados(device: RemoteDevice) -> None:
        """
        Avisa cuando llega un parámetro serie que el gateway no sabe aplicar.

        `ModbusClientFactory` abre el puerto sólo con port y baudrate, así que
        una paridad distinta de la asumida haría fallar las lecturas sin que
        nada lo explique.
        """
        for campo, asumido in SERIE_ASUMIDA.items():
            valor = getattr(device, campo, None)
            if valor is not None and valor != asumido:
                logger.warning(
                    f"⚠️ '{device.name}': {campo}={valor} llega del CRM pero el "
                    f"cliente Modbus asume {campo}={asumido}. Se ignora."
                )

    # --- traducción ------------------------------------------------------

    def build_ini(self, config: RemoteConfig) -> configparser.ConfigParser:
        """Arma el config.ini nuevo conservando lo que el CRM no gobierna."""
        anterior = configparser.ConfigParser()
        if self.config_path.exists():
            anterior.read(self.config_path)

        nuevo = configparser.ConfigParser()

        nuevo["DEFAULT"] = {"loglevel": config.log.loglevel}
        for clave in DEFAULT_PRESERVADAS:
            if clave in anterior.defaults():
                nuevo["DEFAULT"][clave] = anterior.defaults()[clave]

        nuevo["MAINMODBUS"] = {
            "devicesnames": ", ".join(d.name for d in config.devices),
            "interval": str(config.mainmodbus.interval),
            "start_hour": str(config.mainmodbus.start_hour),
            "stop_hour": str(config.mainmodbus.stop_hour),
        }

        for device in config.devices:
            nuevo[device.name] = self._device_section(device)

        return nuevo

    def _device_section(self, device: RemoteDevice) -> Dict[str, str]:
        tipos = {v.register_type for v in device.map.values()}
        funcion = FUNCION_POR_REGISTRO[next(iter(tipos))]

        seccion = {
            "identify_device": str(device.identify_device),
            "device_type": device.device_type,
            "protocol": device.protocol.upper(),
            "mapfile": str(self._map_relpath(device.name)),
            "device_id": str(device.device_id),
            "modbus_function": str(funcion),
            "blockreading": str(device.blockreading).lower(),
            "modbusconnect": str(device.modbusconnect).lower(),
            "modbusread": str(device.modbusread).lower(),
        }

        if device.protocol.upper() == ProtocolCom.RTU:
            seccion["serialport"] = device.serialport
            seccion["baudrate"] = str(device.baudrate)
        else:
            seccion["host"] = device.host
            seccion["port"] = str(device.port)

        return seccion

    def _map_relpath(self, device_name: str) -> Path:
        """Ruta del mapa tal como se escribe en config.ini (relativa al repo)."""
        return Path("src/Modbus/maps") / f"{device_name}.json"

    @staticmethod
    def build_map(device: RemoteDevice) -> Dict[str, Dict[str, Any]]:
        """
        Mapa en el formato de `src/Modbus/maps/*.json`.

        `unit` y `register_type` se conservan: `ModbusRegister` sólo lee
        address, data_type y gain, así que sobran sin molestar y le sirven a
        quien mire el archivo.
        """
        return {
            nombre: variable.model_dump(exclude_none=True)
            for nombre, variable in device.map.items()
        }

    # --- escritura -------------------------------------------------------

    @staticmethod
    def _write_atomic(destino: Path, contenido: str) -> None:
        """Escribe por tmp + replace: nunca deja el archivo a medias."""
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(destino.suffix + ".tmp")
        tmp.write_text(contenido, encoding="utf-8")
        os.replace(tmp, destino)

    def backup(self, version: str) -> Optional[Path]:
        """Guarda la configuración vigente antes de pisarla."""
        if not self.config_path.exists():
            logger.info("📦 Sin configuración previa: no hay backup que hacer")
            return None

        destino = self.backups_dir / (version or "previa")
        (destino / "maps").mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.config_path, destino / "config.ini")

        for mapa in self._mapas_referenciados():
            if mapa.exists():
                shutil.copy2(mapa, destino / "maps" / mapa.name)

        logger.info(f"📦 Backup de la configuración anterior en {destino}")
        return destino

    def _mapas_referenciados(self) -> List[Path]:
        """Mapas que menciona el config.ini vigente."""
        parser = configparser.ConfigParser()
        if not self.config_path.exists():
            return []
        parser.read(self.config_path)

        rutas = []
        for seccion in parser.sections():
            mapfile = parser[seccion].get("mapfile")
            if mapfile:
                rutas.append(Path(mapfile).resolve())
        return rutas

    def apply(self, config: RemoteConfig) -> Tuple[Path, List[Path]]:
        """
        Valida, respalda y escribe. Devuelve (config.ini, mapas escritos).

        Si la validación falla no se escribe nada y se propaga
        `ConfigInvalida`: la configuración vigente queda intacta.
        """
        self.validate(config)

        estado = self.load_state()
        self.backup(estado.get("applied_version", ""))

        # Los mapas primero: si uno falla, config.ini todavía no apunta a él.
        escritos = []
        for device in config.devices:
            ruta = self.maps_dir / f"{device.name}.json"
            self._write_atomic(
                ruta, json.dumps(self.build_map(device), indent=2, ensure_ascii=False)
            )
            escritos.append(ruta)

        ini = self.build_ini(config)
        from io import StringIO

        buffer = StringIO()
        ini.write(buffer)
        self._write_atomic(self.config_path, buffer.getvalue())

        self._write_atomic(
            self.current_file, config.model_dump_json(indent=2)
        )

        logger.info(
            f"💾 Configuración escrita: {len(escritos)} mapa(s) y config.ini "
            f"(versión {config.config_version[:12]}…)"
        )
        return self.config_path, escritos

    def mark_applied(self, config: RemoteConfig, etag: Optional[str]) -> None:
        """Registra la versión que quedó viva."""
        self.save_state(
            applied_version=config.config_version,
            etag=etag,
            applied_at=datetime.now(timezone.utc).isoformat(),
            devices=[d.name for d in config.devices],
        )

    # --- rollback --------------------------------------------------------

    def rollback(self, version: Optional[str] = None) -> bool:
        """
        Restaura el backup indicado (por defecto, el de la versión aplicada).

        :return: True si se restauró algo.
        """
        estado = self.load_state()
        objetivo = version or estado.get("applied_version", "")
        origen = self.backups_dir / (objetivo or "previa")

        if not (origen / "config.ini").exists():
            logger.error(f"❌ No hay backup que restaurar en {origen}")
            return False

        shutil.copy2(origen / "config.ini", self.config_path)

        mapas = origen / "maps"
        if mapas.is_dir():
            self.maps_dir.mkdir(parents=True, exist_ok=True)
            for mapa in mapas.glob("*.json"):
                shutil.copy2(mapa, self.maps_dir / mapa.name)

        logger.warning(f"↩️ Configuración restaurada desde {origen}")
        return True
