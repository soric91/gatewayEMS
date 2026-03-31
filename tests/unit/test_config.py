"""
Tests unitarios para ConfigManager
"""
import pytest
from pathlib import Path
from src.Config.config import ConfigManager

class TestConfigManager:
    """Tests para la clase ConfigManager"""
    
    def test_init_creates_default_config_if_not_exists(self, temp_dir):
        """Debe crear config por defecto si no existe"""
        config = ConfigManager(config_file=str(temp_dir / "new_config.ini"))
        assert config.config_path.exists()
        # DEFAULT es sección implícita en ConfigParser, verificar valores
        assert config.config['DEFAULT'].get('loglevel') == 'INFO'
    
    def test_load_existing_config(self, sample_config_ini):
        """Debe cargar config existente correctamente"""
        config = ConfigManager(config_file=str(sample_config_ini))
        assert config.get_value('MAINMODBUS', 'interval') == '1'
        assert 'TEST_DEVICE_1' in config.get_sections()
    
    def test_get_sections(self, sample_config_ini):
        """Debe retornar todas las secciones"""
        config = ConfigManager(config_file=str(sample_config_ini))
        sections = config.get_sections()
        assert 'MAINMODBUS' in sections
        assert 'TEST_DEVICE_1' in sections
        assert 'TEST_DEVICE_2' in sections
    
    def test_get_value(self, sample_config_ini):
        """Debe obtener valores específicos"""
        config = ConfigManager(config_file=str(sample_config_ini))
        value = config.get_value('TEST_DEVICE_1', 'baudrate')
        assert value == '9600'
    
    def test_get_value_with_fallback(self, sample_config_ini):
        """Debe usar fallback si la clave no existe"""
        config = ConfigManager(config_file=str(sample_config_ini))
        value = config.get_value('TEST_DEVICE_1', 'nonexistent', fallback='default')
        assert value == 'default'
    
    def test_get_section_dict(self, sample_config_ini):
        """Debe retornar sección como diccionario"""
        config = ConfigManager(config_file=str(sample_config_ini))
        section = config.get_section_dict('TEST_DEVICE_1')
        assert isinstance(section, dict)
        assert section['baudrate'] == '9600'
        assert section['protocol'] == 'RTU'
    
    def test_add_device_section(self, sample_config_ini):
        """Debe agregar nueva sección de dispositivo"""
        config = ConfigManager(config_file=str(sample_config_ini))
        device_data = {
            'protocol': 'TCP',
            'host': '192.168.1.50',
            'port': '502'
        }
        result = config.add_device_section('NEW_DEVICE', device_data)
        assert result is True
        assert config.device_exists('DEVICE_NEW_DEVICE')
    
    def test_remove_device_section(self, sample_config_ini):
        """Debe eliminar sección de dispositivo"""
        config = ConfigManager(config_file=str(sample_config_ini))
        result = config.remove_device_section('TEST_DEVICE_1')
        assert result is True
        assert not config.device_exists('TEST_DEVICE_1')
    
    def test_remove_nonexistent_section(self, sample_config_ini):
        """No debe fallar al eliminar sección inexistente"""
        config = ConfigManager(config_file=str(sample_config_ini))
        result = config.remove_device_section('NONEXISTENT')
        assert result is False
    
    def test_device_exists(self, sample_config_ini):
        """Debe verificar existencia de dispositivo"""
        config = ConfigManager(config_file=str(sample_config_ini))
        assert config.device_exists('TEST_DEVICE_1') is True
        assert config.device_exists('NONEXISTENT') is False
    
    def test_set_device_value(self, sample_config_ini):
        """Debe establecer valor en dispositivo existente"""
        config = ConfigManager(config_file=str(sample_config_ini))
        result = config.set_device_value('TEST_DEVICE_1', 'modbusconnect', 'true')
        assert result is True
        assert config.get_value('TEST_DEVICE_1', 'modbusconnect') == 'true'
    
    def test_set_device_value_nonexistent_section(self, sample_config_ini):
        """No debe establecer valor en sección inexistente"""
        config = ConfigManager(config_file=str(sample_config_ini))
        result = config.set_device_value('NONEXISTENT', 'key', 'value')
        assert result is False
    
    def test_reload_config(self, sample_config_ini):
        """Debe recargar configuración desde disco"""
        config = ConfigManager(config_file=str(sample_config_ini))
        initial_value = config.get_value('TEST_DEVICE_1', 'baudrate')
        
        # Modificar archivo directamente
        with open(sample_config_ini, 'a') as f:
            f.write('\n[NEW_SECTION]\nkey = value\n')
        
        config.reload()
        assert 'NEW_SECTION' in config.get_sections()
