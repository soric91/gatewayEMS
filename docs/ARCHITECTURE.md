# 🏛️ Arquitectura de GatewayEMS

Esta guía explica en profundidad la arquitectura, patrones de diseño y decisiones técnicas de GatewayEMS.

---

## 📑 Tabla de Contenidos

- [Visión General](#-visión-general)
- [Clean Architecture](#-clean-architecture)
- [Capas del Sistema](#-capas-del-sistema)
- [Flujo de Datos](#-flujo-de-datos)
- [Patrones de Diseño](#-patrones-de-diseño)
- [Decisiones Técnicas](#-decisiones-técnicas)
- [Módulos Principales](#-módulos-principales)

---

## 🎯 Visión General

GatewayEMS está diseñado siguiendo los principios de **Clean Architecture** (Robert C. Martin), lo que proporciona:

- 🔄 **Separación de responsabilidades** clara entre capas
- 🧪 **Alta testeabilidad** (84% de cobertura)
- 🔧 **Bajo acoplamiento** entre componentes
- 🔀 **Fácil extensibilidad** para nuevos protocolos
- 📦 **Dependencias unidireccionales** hacia el dominio

### 🎨 Principios SOLID Aplicados

| Principio | Implementación en GatewayEMS |
|-----------|------------------------------|
| **S**ingle Responsibility | Cada módulo tiene una única responsabilidad |
| **O**pen/Closed | Extensible vía config sin modificar código |
| **L**iskov Substitution | Interfaces uniformes (Repository, Service) |
| **I**nterface Segregation | Interfaces específicas por capa |
| **D**ependency Inversion | Las capas dependen de abstracciones |

---

## 🧅 Clean Architecture

GatewayEMS implementa Clean Architecture con las siguientes capas:

```
┌─────────────────────────────────────────────────────────────┐
│                    FRAMEWORKS & DRIVERS                      │
│  (Infraestructura - Detalles de implementación)             │
│                                                              │
│  • InfluxDB Client       • PyModbus                          │
│  • Watchdog              • AsyncIO                           │
│  • ConfigParser          • Pydantic                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              INTERFACE ADAPTERS (Adaptadores)               │
│  (Conversión entre formatos externos e internos)            │
│                                                              │
│  • InfluxDBRepository    • ModbusApp                         │
│  • ConfigManager         • QueueManager                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              APPLICATION (Casos de Uso)                      │
│  (Lógica de negocio - Qué hacer)                            │
│                                                              │
│  • ModbusService         • TaskManager                       │
│  • DeviceReadResult      • BaseWatchdog                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  DOMAIN (Dominio)                            │
│  (Entidades de negocio - Reglas fundamentales)              │
│                                                              │
│  • EnergyPoint           • DeviceConfig                      │
│  • DATATYPE Enums        • ProtocolCom                       │
└─────────────────────────────────────────────────────────────┘
```

### 🎯 Dependencias

Las flechas indican la dirección de las dependencias:

```
Infraestructura  ──►  Adaptadores  ──►  Aplicación  ──►  Dominio
  (detalles)         (conversión)     (casos de uso)   (reglas)
```

**Regla clave:** Las capas internas **nunca** dependen de las externas.

---

## 📚 Capas del Sistema

### 1️⃣ Capa de Dominio (Domain Layer)

**Ubicación:** `src/Models/`

**Responsabilidad:** Contiene las entidades de negocio y reglas fundamentales.

```python
# src/Models/model.py

@dataclass
class EnergyPoint:
    """Modelo de dominio para un punto de datos de energía"""
    device_id: str
    device_name: str
    device_type: str
    timestamp: datetime
    fields: Dict[str, float]
    
    @classmethod
    def from_device_read_result(cls, result: DeviceReadResult) -> 'EnergyPoint':
        """Factory method - crea EnergyPoint desde DeviceReadResult"""
        pass
    
    def to_influx_point(self) -> Point:
        """Convierte a formato InfluxDB"""
        pass
```

**Características:**
- ✅ Sin dependencias externas
- ✅ Lógica de negocio pura
- ✅ Inmutable cuando es posible
- ✅ Validación de datos con Pydantic

---

### 2️⃣ Capa de Aplicación (Application Layer)

**Ubicación:** `src/Task/`, `src/Database/service.py`

**Responsabilidad:** Orquesta los casos de uso del sistema.

```python
# src/Task/task.py

class TaskManager(BaseWatchdog):
    """Orquestador principal del sistema"""
    
    async def task_read_modbus_periodic(self):
        """Producer: Lee Modbus y publica en la cola"""
        results = await self.modbus_app.read_all()
        await self.queue_manager.publish(results)
    
    async def task_process_queue(self):
        """Consumer: Consume de la cola y guarda en DB"""
        data = await self.queue_manager.consume()
        results = data.get("results", [])
        await self.modbus_service.save_batch(results)
```

**Características:**
- ✅ Coordina flujo de datos
- ✅ Gestiona tareas asíncronas
- ✅ Implementa producer-consumer
- ✅ No conoce detalles de infraestructura

---

### 3️⃣ Capa de Adaptadores (Interface Adapters)

**Ubicación:** `src/Modbus/app.py`, `src/Database/repository.py`, `src/Config/`

**Responsabilidad:** Convierte datos entre formatos externos e internos.

```python
# src/Database/repository.py

class InfluxDBRepository:
    """Adaptador para InfluxDB - capa de acceso a datos"""
    
    def __init__(self, connection: InfluxDBConnection):
        self.connection = connection
    
    async def save_points(self, points: List[Point]) -> bool:
        """Guarda puntos en InfluxDB (cómo guardar)"""
        try:
            write_api = self.connection.client.write_api(write_options=SYNCHRONOUS)
            write_api.write(bucket=self.connection.bucket, record=points)
            return True
        except Exception as e:
            logger.error(f"Error saving to InfluxDB: {e}")
            return False
```

**Características:**
- ✅ Aísla detalles de implementación
- ✅ Provee interfaces limpias
- ✅ Maneja conversión de formatos
- ✅ Inyección de dependencias

---

### 4️⃣ Capa de Infraestructura (Infrastructure Layer)

**Ubicación:** `src/Database/connection.py`, `src/Modbus/client.py`

**Responsabilidad:** Implementa detalles técnicos y frameworks externos.

```python
# src/Database/connection.py

class InfluxDBConnection:
    """Gestiona la conexión física a InfluxDB"""
    
    def __init__(self, url: str, token: str, org: str, bucket: str):
        self.client = InfluxDBClient(url=url, token=token, org=org)
        self.bucket = bucket
    
    async def connect(self) -> bool:
        """Establece conexión persistente"""
        # Detalles de implementación de InfluxDB
        pass
```

**Características:**
- ✅ Detalles técnicos aislados
- ✅ Dependencias de terceros
- ✅ Configuración de frameworks
- ✅ Fácil de reemplazar

---

## 🔄 Flujo de Datos

### Flujo Completo: Modbus → InfluxDB

```
┌─────────────────────────────────────────────────────────────────┐
│                       MODBUS DEVICE                             │
│                   (Hardware físico)                             │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            │ Modbus RTU/TCP Protocol
                            │
                            ▼
        ┌─────────────────────────────────────────────┐
        │         MODBUS CLIENT                        │
        │  (src/Modbus/client.py)                      │
        │                                              │
        │  • ModbusClientTCP                           │
        │  • ModbusClientRTU                           │
        └──────────────────┬───────────────────────────┘
                           │
                           │ Raw Register Values
                           │
                           ▼
        ┌─────────────────────────────────────────────┐
        │         MODBUS MAP                           │
        │  (src/Modbus/modbusmap.py)                   │
        │                                              │
        │  • Parse JSON map                            │
        │  • Decode data types                         │
        │  • Apply gain/scale                          │
        └──────────────────┬───────────────────────────┘
                           │
                           │ Dict[str, Any]
                           │
                           ▼
        ┌─────────────────────────────────────────────┐
        │         MODBUS APP                           │
        │  (src/Modbus/app.py)                         │
        │                                              │
        │  read_all() → List[DeviceReadResult]        │
        └──────────────────┬───────────────────────────┘
                           │
                           │ DeviceReadResult
                           │
                           ▼
        ┌─────────────────────────────────────────────┐
        │      TASK MANAGER (Producer)                 │
        │  (src/Task/task.py)                          │
        │                                              │
        │  task_read_modbus_periodic()                 │
        └──────────────────┬───────────────────────────┘
                           │
                           │ Publish to Queue
                           │
                           ▼
        ┌─────────────────────────────────────────────┐
        │         ASYNCIO QUEUE                        │
        │  (src/Utils/utils.py)                        │
        │                                              │
        │  • Decouples producer/consumer               │
        │  • Async safe                                │
        └──────────────────┬───────────────────────────┘
                           │
                           │ Consume from Queue
                           │
                           ▼
        ┌─────────────────────────────────────────────┐
        │      TASK MANAGER (Consumer)                 │
        │  (src/Task/task.py)                          │
        │                                              │
        │  task_process_queue()                        │
        └──────────────────┬───────────────────────────┘
                           │
                           │ List[DeviceReadResult]
                           │
                           ▼
        ┌─────────────────────────────────────────────┐
        │         MODBUS SERVICE                       │
        │  (src/Database/service.py)                   │
        │                                              │
        │  save_batch(results)                         │
        └──────────────────┬───────────────────────────┘
                           │
                           │ Convert to EnergyPoint
                           │
                           ▼
        ┌─────────────────────────────────────────────┐
        │         ENERGY POINT                         │
        │  (src/Models/model.py)                       │
        │                                              │
        │  • Domain model                              │
        │  • Normalization                             │
        │  • Validation                                │
        └──────────────────┬───────────────────────────┘
                           │
                           │ to_influx_point()
                           │
                           ▼
        ┌─────────────────────────────────────────────┐
        │         INFLUXDB REPOSITORY                  │
        │  (src/Database/repository.py)                │
        │                                              │
        │  save_points(points)                         │
        └──────────────────┬───────────────────────────┘
                           │
                           │ InfluxDB Line Protocol
                           │
                           ▼
        ┌─────────────────────────────────────────────┐
        │         INFLUXDB CONNECTION                  │
        │  (src/Database/connection.py)                │
        │                                              │
        │  • Persistent connection                     │
        │  • Write API                                 │
        └──────────────────┬───────────────────────────┘
                           │
                           │ HTTP/2 (InfluxDB Protocol)
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                       INFLUXDB SERVER                           │
│                   (Time-series database)                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🎨 Patrones de Diseño

### 1. Producer-Consumer Pattern

**Problema:** Desacoplar la lectura Modbus del guardado en DB.

**Solución:** Usar AsyncIO Queue como buffer.

```python
# Producer (task_read_modbus_periodic)
async def task_read_modbus_periodic(self):
    while self._running:
        results = await self.modbus_app.read_all()
        await self.queue_manager.publish({
            "results": results,
            "timestamp": datetime.now()
        })
        await asyncio.sleep(self.interval)

# Consumer (task_process_queue)
async def task_process_queue(self):
    while self._running:
        data = await self.queue_manager.consume()
        results = data.get("results", [])
        await self.modbus_service.save_batch(results)
```

**Beneficios:**
- ✅ Desacoplamiento temporal
- ✅ Lecturas Modbus no se bloquean por escritura DB
- ✅ Backpressure automático si DB es lento

---

### 2. Repository Pattern

**Problema:** Aislar la lógica de negocio de los detalles de persistencia.

**Solución:** Capa Repository que abstrae el acceso a datos.

```python
# Service (lógica de negocio - QUÉ guardar)
class ModbusService:
    def __init__(self):
        self.repository = InfluxDBRepository(connection)
    
    async def save_batch(self, results: List[DeviceReadResult]):
        # Lógica de negocio: convertir y filtrar
        points = EnergyPoint.batch_from_results(results)
        influx_points = [p.to_influx_point() for p in points]
        
        # Delegar persistencia al repository
        await self.repository.save_points(influx_points)

# Repository (detalles de persistencia - CÓMO guardar)
class InfluxDBRepository:
    async def save_points(self, points: List[Point]) -> bool:
        # Detalles de implementación de InfluxDB
        write_api = self.connection.client.write_api(...)
        write_api.write(bucket=self.bucket, record=points)
```

**Beneficios:**
- ✅ Fácil cambio de base de datos (ej: InfluxDB → TimescaleDB)
- ✅ Lógica de negocio independiente de infraestructura
- ✅ Testeo con mocks simplificado

---

### 3. Factory Pattern

**Problema:** Crear objetos complejos desde diferentes fuentes de datos.

**Solución:** Factory methods en las entidades de dominio.

```python
class EnergyPoint:
    @classmethod
    def from_device_read_result(cls, result: DeviceReadResult) -> 'EnergyPoint':
        """Factory: crea EnergyPoint desde DeviceReadResult"""
        normalized_fields = cls._normalize_fields(result.data)
        
        return cls(
            device_id=str(result.device_id),
            device_name=result.device_name,
            device_type=result.device_type,
            timestamp=result.timestamp,
            fields=normalized_fields
        )
    
    @classmethod
    def batch_from_results(cls, results: List[DeviceReadResult]) -> List['EnergyPoint']:
        """Factory: crea múltiples puntos, filtrando fallidos"""
        return [
            cls.from_device_read_result(r)
            for r in results
            if r.success
        ]
```

**Beneficios:**
- ✅ Encapsula lógica de creación compleja
- ✅ Validación centralizada
- ✅ Conversión de tipos consistente

---

### 4. Observer Pattern (Watchdog)

**Problema:** Detectar cambios en config.ini sin reiniciar el sistema.

**Solución:** Watchdog que observa el archivo y notifica cambios.

```python
class BaseWatchdog:
    def __init__(self, poll_interval: float = 2.0):
        self._previous_state: Dict[str, Dict[str, Any]] = {}
    
    async def _check_changes(self):
        """Compara estado actual con anterior"""
        current_state = self._capture_state()
        
        for device_name in current_state:
            if device_name not in self._previous_state:
                # Nuevo dispositivo
                await self.on_config_changed(device_name, ...)
            elif current_state[device_name] != self._previous_state[device_name]:
                # Dispositivo modificado
                await self.on_config_changed(device_name, ...)
        
        self._previous_state = current_state
```

**Beneficios:**
- ✅ Hot-reload de configuración
- ✅ No requiere reinicio del sistema
- ✅ Responde a cambios en tiempo real

---

### 5. Dependency Injection

**Problema:** Alto acoplamiento entre componentes.

**Solución:** Inyectar dependencias en lugar de crearlas internamente.

```python
# ❌ Alto acoplamiento
class ModbusService:
    def __init__(self):
        self.connection = InfluxDBConnection(...)  # Crea su dependencia
        self.repository = InfluxDBRepository(self.connection)

# ✅ Dependency Injection
class ModbusService:
    def __init__(self, repository: InfluxDBRepository = None):
        self.repository = repository or self._create_default_repository()
    
    def _create_default_repository(self):
        connection = InfluxDBConnection(...)
        return InfluxDBRepository(connection)

# En tests:
mock_repo = MockRepository()
service = ModbusService(repository=mock_repo)  # Inyecta mock
```

**Beneficios:**
- ✅ Bajo acoplamiento
- ✅ Fácil testing con mocks
- ✅ Inversión de control

---

## ⚡ Decisiones Técnicas

### AsyncIO vs Threading

**Decisión:** Usar AsyncIO para todas las operaciones I/O.

**Razones:**
- ✅ Mejor performance para I/O-bound (Modbus, InfluxDB, serial)
- ✅ Menor overhead que threads
- ✅ Evita problemas de sincronización
- ✅ Escalabilidad a muchos dispositivos

```python
# Todas las operaciones I/O son async
async def read_all(self) -> List[DeviceReadResult]:
    # Lee múltiples dispositivos en paralelo
    tasks = [self._read_device(dev) for dev in devices]
    results = await asyncio.gather(*tasks)
    return results
```

---

### Conexión Persistente vs Por-Request

**Decisión:** Conexión persistente a InfluxDB durante toda la sesión.

**Razones:**
- ✅ Reduce latencia (no handshake en cada escritura)
- ✅ Reutiliza pool de conexiones HTTP/2
- ✅ Menor overhead de CPU y red
- ❌ Requiere graceful shutdown

```python
# Conexión se abre una vez
await modbus_service.initialize()  # Abre conexión

# Se reutiliza para todas las escrituras
await modbus_service.save_batch(results)
await modbus_service.save_batch(results)
await modbus_service.save_batch(results)

# Se cierra limpiamente al finalizar
await modbus_service.shutdown()  # Cierra conexión
```

---

### Batch Processing

**Decisión:** Guardar datos en lotes (batch) en lugar de uno por uno.

**Razones:**
- ✅ Mejor throughput (más datos por request)
- ✅ Menos llamadas de red
- ✅ InfluxDB optimizado para batch inserts
- ✅ Reduce carga del servidor

```python
# ✅ Batch (eficiente)
points = [p1, p2, p3, ..., p100]
await repository.save_points(points)  # 1 request

# ❌ Individual (ineficiente)
for point in points:
    await repository.save_point(point)  # 100 requests
```

---

### Pydantic para Validación

**Decisión:** Usar Pydantic para todos los modelos de datos.

**Razones:**
- ✅ Validación automática de tipos
- ✅ Conversión de tipos transparente
- ✅ Serialización/deserialización built-in
- ✅ Type hints para IDEs

```python
from pydantic import BaseModel, Field

class Settings(BaseModel):
    INFLUXDB_URL: str = Field(..., description="InfluxDB URL")
    INFLUXDB_TOKEN: str = Field(..., min_length=16)
    INFLUXDB_BUCKET: str = Field(default="modbus_data")

# Validación automática
settings = Settings(
    INFLUXDB_URL="http://localhost:8086",
    INFLUXDB_TOKEN="abc123"  # ❌ Error: min_length=16
)
```

---

## 📦 Módulos Principales

### TaskManager (`src/Task/task.py`)

**Responsabilidad:** Orquestador principal del sistema.

**Funciones clave:**
- Gestiona el loop AsyncIO
- Coordina producer-consumer
- Implementa watchdog de config.ini
- Controla horarios de lectura

**Dependencias:**
- `ModbusApp` - Para lectura Modbus
- `ModbusService` - Para guardado en InfluxDB
- `QueueManager` - Para cola async
- `ConfigManager` - Para configuración

---

### ModbusApp (`src/Modbus/app.py`)

**Responsabilidad:** Gestiona comunicación Modbus.

**Funciones clave:**
- Carga configuración de dispositivos
- Establece conexiones TCP/RTU
- Lee registros según mapas JSON
- Retorna `DeviceReadResult`

**Dependencias:**
- `ModbusClientFactory` - Crea clientes
- `ModbusDeviceMap` - Parse mapas JSON
- `read_registers` - Lee datos

---

### ModbusService (`src/Database/service.py`)

**Responsabilidad:** Lógica de negocio para guardado de datos.

**Funciones clave:**
- Convierte `DeviceReadResult` → `EnergyPoint`
- Filtra resultados fallidos
- Normaliza tipos de datos
- Delega persistencia al repository

**Dependencias:**
- `InfluxDBRepository` - Capa de datos
- `EnergyPoint` - Modelo de dominio

---

### EnergyPoint (`src/Models/model.py`)

**Responsabilidad:** Modelo de dominio para datos de energía.

**Funciones clave:**
- Factory methods para creación
- Normalización de campos
- Conversión a InfluxDB Point
- Validación de datos

**Sin dependencias externas** (dominio puro)

---

## 🧪 Testing Strategy

```
tests/
├── unit/               # Tests aislados de componentes
│   ├── modbus/         # Tests de Modbus (sin hardware)
│   ├── database/       # Tests de DB (con mocks)
│   └── task/           # Tests de TaskManager
├── integration/        # Tests de integración entre módulos
│   ├── test_modbus_app.py
│   └── test_watchdog.py
└── fixtures/           # Datos de prueba reutilizables
    └── influxdb_fixtures.py
```

### Estrategia de Mocking

```python
# Unit test - mock de InfluxDB
@pytest.mark.asyncio
async def test_save_batch():
    mock_repo = Mock(spec=InfluxDBRepository)
    mock_repo.save_points.return_value = True
    
    service = ModbusService(repository=mock_repo)
    result = await service.save_batch(sample_results)
    
    assert result is True
    mock_repo.save_points.assert_called_once()

# Integration test - InfluxDB real
@pytest.mark.asyncio
async def test_save_batch_integration():
    connection = InfluxDBConnection(...)
    repository = InfluxDBRepository(connection)
    service = ModbusService(repository=repository)
    
    result = await service.save_batch(sample_results)
    
    assert result is True
    # Verificar datos en InfluxDB
```

---

## 📊 Métricas de Calidad

| Métrica               | Valor | Objetivo |
|-----------------------|-------|----------|
| Cobertura de código   | 84%   | > 80%    |
| Tests unitarios       | 105   | -        |
| Tests integración     | 34    | -        |
| Complejidad ciclomática | < 10 | < 15     |
| Líneas por función    | < 50  | < 100    |

---

## 🔮 Futuras Mejoras

### 1. Cache Layer

Agregar cache Redis para reducir lecturas duplicadas:

```python
class CachedModbusService(ModbusService):
    def __init__(self, redis_client):
        super().__init__()
        self.cache = redis_client
    
    async def get_device_data(self, device_id: str):
        # Check cache first
        cached = await self.cache.get(f"device:{device_id}")
        if cached:
            return cached
        
        # Fallback to database
        data = await super().get_device_data(device_id)
        await self.cache.setex(f"device:{device_id}", 60, data)
        return data
```

### 2. Event Sourcing

Implementar event log para auditoría:

```python
class EventStore:
    async def append(self, event: Event):
        await self.repository.save(event)
    
    async def replay(self, aggregate_id: str):
        events = await self.repository.get_events(aggregate_id)
        return [event.apply() for event in events]
```

### 3. CQRS (Command Query Responsibility Segregation)

Separar escritura (commands) de lectura (queries):

```python
# Write model
class SaveEnergyDataCommand:
    def execute(self, data: EnergyPoint):
        self.write_repository.save(data)

# Read model
class GetDeviceHistoryQuery:
    def execute(self, device_id: str):
        return self.read_repository.get_history(device_id)
```

---

## 📚 Referencias

- [Clean Architecture (Robert C. Martin)](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [SOLID Principles](https://en.wikipedia.org/wiki/SOLID)
- [AsyncIO Best Practices](https://docs.python.org/3/library/asyncio.html)
- [Repository Pattern](https://martinfowler.com/eaaCatalog/repository.html)

---

[⬆ Volver al README principal](../README.md)
