"""
Integration tests for src/Core/watchdog.py

Tests para BaseWatchdog:
- Detección de cambios en config.ini
- Notificación de cambios
- Start/Stop del monitoreo
- Manejo de archivos reales
"""

import pytest
import asyncio
from pathlib import Path
from src.Core.watchdog import BaseWatchdog
from src.Config.config import ConfigManager


class WatchdogForTesting(BaseWatchdog):
    """Implementación concreta de BaseWatchdog para testing"""
    
    def __init__(self, config=None, *args, **kwargs):
        # Definir atributos antes de llamar __init__
        self.connect = "modbusconnect"
        self.readstart = "modbusread"
        self.changes_detected = []
        
        # Llamar __init__ de BaseWatchdog
        super().__init__(*args, **kwargs)
        
        # Sobreescribir config si se proporciona
        if config:
            self.config = config
    
    async def on_config_changed(self, device_name: str, connect: bool, readstart: bool):
        """Captura cambios para verificar en tests"""
        self.changes_detected.append({
            'device': device_name,
            'connect': connect,
            'readstart': readstart
        })


class TestBaseWatchdog:
    """Tests de integración para BaseWatchdog"""
    
    @pytest.mark.asyncio
    async def test_watchdog_detects_config_change(self, tmp_path):
        """✅ Detecta cambios en modbusconnect y modbusread"""
        # Crear archivo config inicial
        config_file = tmp_path / "config.ini"
        config_file.write_text("""[DEFAULT]
loglevel = INFO

[MAINMODBUS]
devicesnames = DEVICE_TEST1

[DEVICE_TEST1]
modbusconnect = False
modbusread = False
""")
        
        # Crear ConfigManager y Watchdog
        config = ConfigManager(config_file=str(config_file))
        watchdog = WatchdogForTesting(config=config, poll_interval=0.1)
        
        # Iniciar watchdog
        await watchdog.start()
        
        # Esperar un poco para la carga inicial
        await asyncio.sleep(0.15)
        
        # Modificar config.ini
        config_file.write_text("""[DEFAULT]
loglevel = INFO

[MAINMODBUS]
devicesnames = DEVICE_TEST1

[DEVICE_TEST1]
modbusconnect = True
modbusread = True
""")
        
        # Esperar a que detecte el cambio
        await asyncio.sleep(0.25)
        
        # Detener watchdog
        await watchdog.stop()
        
        # Verificar que detectó cambios
        assert len(watchdog.changes_detected) > 0
        
        # Verificar el último cambio detectado
        last_change = watchdog.changes_detected[-1]
        assert last_change['device'] == 'DEVICE_TEST1'
        assert last_change['connect'] is True
        assert last_change['readstart'] is True
    
    @pytest.mark.asyncio
    async def test_watchdog_detects_partial_change(self, tmp_path):
        """✅ Detecta cambios parciales (solo connect, no read)"""
        config_file = tmp_path / "config.ini"
        config_file.write_text("""[DEFAULT]
loglevel = INFO

[MAINMODBUS]
devicesnames = DEVICE_TEST1

[DEVICE_TEST1]
modbusconnect = False
modbusread = False
""")
        
        config = ConfigManager(config_file=str(config_file))
        watchdog = WatchdogForTesting(config=config, poll_interval=0.1)
        
        await watchdog.start()
        await asyncio.sleep(0.15)
        
        # Cambiar solo modbusconnect
        config_file.write_text("""[DEFAULT]
loglevel = INFO

[MAINMODBUS]
devicesnames = DEVICE_TEST1

[DEVICE_TEST1]
modbusconnect = True
modbusread = False
""")
        
        await asyncio.sleep(0.25)
        await watchdog.stop()
        
        # Verificar cambio parcial
        assert len(watchdog.changes_detected) > 0
        last_change = watchdog.changes_detected[-1]
        assert last_change['connect'] is True
        assert last_change['readstart'] is False
    
    @pytest.mark.asyncio
    async def test_watchdog_multiple_devices(self, tmp_path):
        """✅ Detecta cambios en múltiples dispositivos"""
        config_file = tmp_path / "config.ini"
        config_file.write_text("""[DEFAULT]
loglevel = INFO

[MAINMODBUS]
devicesnames = DEVICE_1, DEVICE_2

[DEVICE_1]
modbusconnect = False
modbusread = False

[DEVICE_2]
modbusconnect = False
modbusread = False
""")
        
        config = ConfigManager(config_file=str(config_file))
        watchdog = WatchdogForTesting(config=config, poll_interval=0.1)
        
        await watchdog.start()
        await asyncio.sleep(0.15)
        
        # Cambiar ambos dispositivos
        config_file.write_text("""[DEFAULT]
loglevel = INFO

[MAINMODBUS]
devicesnames = DEVICE_1, DEVICE_2

[DEVICE_1]
modbusconnect = True
modbusread = True

[DEVICE_2]
modbusconnect = True
modbusread = False
""")
        
        await asyncio.sleep(0.25)
        await watchdog.stop()
        
        # Debe haber detectado cambios en ambos
        devices_changed = [c['device'] for c in watchdog.changes_detected]
        assert 'DEVICE_1' in devices_changed
        assert 'DEVICE_2' in devices_changed
    
    @pytest.mark.asyncio
    async def test_watchdog_no_changes_no_notifications(self, tmp_path):
        """✅ Sin cambios no debe notificar"""
        config_file = tmp_path / "config.ini"
        config_file.write_text("""[DEFAULT]
loglevel = INFO

[MAINMODBUS]
devicesnames = DEVICE_1

[DEVICE_1]
modbusconnect = False
modbusread = False
""")
        
        config = ConfigManager(config_file=str(config_file))
        watchdog = WatchdogForTesting(config=config, poll_interval=0.1)
        
        await watchdog.start()
        await asyncio.sleep(0.15)
        
        initial_changes = len(watchdog.changes_detected)
        
        # NO modificar el archivo
        # Esperar varios ciclos de polling
        await asyncio.sleep(0.35)
        
        await watchdog.stop()
        
        # No debe haber nuevos cambios (solo el inicial si lo hay)
        # Puede tener 1 cambio inicial pero no más
        assert len(watchdog.changes_detected) <= initial_changes + 1
    
    @pytest.mark.asyncio
    async def test_watchdog_stop_prevents_further_checks(self, tmp_path):
        """✅ Stop detiene el monitoreo"""
        config_file = tmp_path / "config.ini"
        config_file.write_text("""[DEFAULT]
loglevel = INFO

[MAINMODBUS]
devicesnames = DEVICE_1

[DEVICE_1]
modbusconnect = False
modbusread = False
""")
        
        config = ConfigManager(config_file=str(config_file))
        watchdog = WatchdogForTesting(config=config, poll_interval=0.1)
        
        await watchdog.start()
        await asyncio.sleep(0.15)
        
        # Detener inmediatamente
        await watchdog.stop()
        
        initial_count = len(watchdog.changes_detected)
        
        # Modificar archivo DESPUÉS de detener
        config_file.write_text("""[DEFAULT]
loglevel = INFO

[MAINMODBUS]
devicesnames = DEVICE_1

[DEVICE_1]
modbusconnect = True
modbusread = True
""")
        
        # Esperar (pero watchdog está detenido)
        await asyncio.sleep(0.3)
        
        # No debe haber detectado el cambio
        assert len(watchdog.changes_detected) == initial_count
