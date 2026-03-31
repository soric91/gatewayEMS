# Tests - Gateway EMS

Estructura de tests para el proyecto Gateway EMS.

## Estructura de Directorios

```
tests/
├── conftest.py                    # Fixtures globales
├── fixtures/                      # Datos de prueba
│   ├── config_samples.py
│   └── modbus_data.py
├── unit/                          # Tests unitarios
│   ├── test_config.py            # ConfigManager
│   ├── test_models.py            # Modelos Pydantic
│   ├── test_utils.py             # QueueManager
│   └── modbus/
│       ├── test_util.py          # Utilidades Modbus
│       └── test_modbusmap.py     # Mapas Modbus
├── integration/                   # Tests de integración
│   └── (por crear)
└── e2e/                          # Tests end-to-end
    └── (por crear)
```

## Instalación de Dependencias

### Con UV (recomendado)

```bash
# Instalar dependencias de test
uv pip install -e ".[test]"

# O instalar todo junto
uv sync --extra test
```

### Con pip tradicional

```bash
pip install -e ".[test]"
```

## Ejecutar Tests

### Ejecutar todos los tests

```bash
# Con UV
uv run pytest

# Sin UV
pytest
```

### Ejecutar tests específicos

```bash
# Solo tests unitarios
uv run pytest tests/unit/

# Solo un archivo
uv run pytest tests/unit/test_config.py

# Solo una clase
uv run pytest tests/unit/test_config.py::TestConfigManager

# Solo un test específico
uv run pytest tests/unit/test_config.py::TestConfigManager::test_load_existing_config
```

### Con marcadores

```bash
# Solo tests unitarios
uv run pytest -m unit

# Solo tests de integración
uv run pytest -m integration

# Solo tests rápidos (excluir lentos)
uv run pytest -m "not slow"
```

### Con cobertura

```bash
# Reporte en terminal
uv run pytest --cov=src --cov-report=term-missing

# Generar reporte HTML
uv run pytest --cov=src --cov-report=html

# Ver reporte HTML
firefox htmlcov/index.html
```

### Modo verbose

```bash
# Más detalles
uv run pytest -v

# Mucho más detalle
uv run pytest -vv

# Mostrar print statements
uv run pytest -s
```

### Ejecutar en paralelo (más rápido)

```bash
# Instalar plugin
uv pip install pytest-xdist

# Ejecutar en 4 procesos
uv run pytest -n 4
```

## Comandos Útiles

```bash
# Ver lista de tests sin ejecutar
uv run pytest --collect-only

# Ejecutar solo tests que fallaron la última vez
uv run pytest --lf

# Ejecutar primero los que fallaron
uv run pytest --ff

# Detener en el primer fallo
uv run pytest -x

# Detener después de N fallos
uv run pytest --maxfail=3

# Modo interactivo (debugger)
uv run pytest --pdb
```

## Configuración

La configuración de pytest está en `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]              # Dónde buscar tests
asyncio_mode = "auto"              # Auto-detectar tests async
addopts = ["-v", "--cov=src"]     # Opciones por defecto
```

## Escribir Tests

### Ejemplo básico

```python
def test_example():
    assert 1 + 1 == 2
```

### Test con fixtures

```python
def test_with_fixture(sample_config_ini):
    config = ConfigManager(config_file=str(sample_config_ini))
    assert config.get_value('MAINMODBUS', 'interval') == '1'
```

### Test asyncio

```python
@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result is True
```

### Test con mock

```python
from unittest.mock import Mock, patch

def test_with_mock():
    with patch('src.Module.function') as mock_func:
        mock_func.return_value = "mocked"
        result = call_function()
        assert result == "mocked"
```

## CI/CD

Para ejecutar en GitHub Actions u otro CI:

```yaml
- name: Run tests
  run: |
    uv pip install -e ".[test]"
    uv run pytest --cov=src --cov-report=xml
```

## Tips

1. **Usa fixtures** para evitar duplicación de código
2. **Nombra tests descriptivamente**: `test_should_do_something_when_condition()`
3. **Un assert por test** (cuando sea posible)
4. **Tests rápidos**: Los tests unitarios deben correr en milisegundos
5. **Aísla tests**: No dependas del orden de ejecución
