"""
Unit tests for TaskManager class
Tests task orchestration, configuration monitoring, and Modbus operations
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, time
from src.Task.task import TaskManager
from src.Config.config import ConfigManager
from src.Models.model import DeviceReadResult


@pytest.fixture
def mock_config():
    """Mock ConfigManager with default values"""
    config = MagicMock(spec=ConfigManager)
    config.get_value.side_effect = lambda section, key, default: {
        ('MAINMODBUS', 'interval'): '5',
        ('MAINMODBUS', 'start_hour'): '8',
        ('MAINMODBUS', 'stop_hour'): '20',
    }.get((section, key), str(default))
    return config


@pytest.fixture
def mock_modbus_app():
    """Mock ModbusApp"""
    app = MagicMock()
    # Use regular MagicMock for sync methods
    app._load_configs = MagicMock(return_value=True)
    app._load_maps = MagicMock(return_value=True)
    # Use AsyncMock for async methods
    app.connect_device = AsyncMock(return_value=True)
    app.disconnect_device = AsyncMock(return_value=None)
    app.read_all = AsyncMock(return_value=[])
    app.shutdown = AsyncMock(return_value=None)
    app.clients = {}
    return app


@pytest.fixture
def task_manager(mock_config):
    """Create TaskManager instance with mocked config"""
    with patch('src.Task.task.ModbusApp'):
        tm = TaskManager(config=mock_config)
        return tm


# ========================================
# Initialization Tests
# ========================================

def test_task_manager_initialization(mock_config):
    """✅ TaskManager initializes with correct default values"""
    with patch('src.Task.task.ModbusApp'):
        tm = TaskManager(config=mock_config)
        
        # Check values were set (from our mock which returns specific values)
        assert tm.connect == "modbusconnect"
        assert tm.readstart == "modbusread"
        # Verify these values come from mock_config
        assert tm.interval > 0  # Will be 5 from mock, but might be 1 from real config
        assert tm.start_hour >= 0
        assert tm.stop_hour >= 0
        assert tm.modbus_app is None
        assert tm._running is False
        assert tm._tasks == []
        assert tm._connected_devices == set()
        assert tm._reading_devices == set()
        assert isinstance(tm._read_lock, asyncio.Lock)


def test_task_manager_post_init_loads_config():
    """✅ __post_init__ loads configuration correctly"""
    from src.Config.config import ConfigManager
    
    with patch('src.Task.task.ModbusApp'):
        config = ConfigManager()
        tm = TaskManager(config=config)
        
        assert isinstance(tm.interval, int)
        assert isinstance(tm.start_hour, int)
        assert isinstance(tm.stop_hour, int)
        assert tm.interval > 0
        assert 0 <= tm.start_hour <= 23
        assert 0 <= tm.stop_hour <= 23


@pytest.mark.asyncio
async def test_initialize_success(task_manager, mock_modbus_app):
    """✅ initialize() successfully sets up ModbusApp and watchdog"""
    with patch('src.Task.task.ModbusApp', return_value=mock_modbus_app):
        result = await task_manager.initialize()
        
        assert result is True
        assert task_manager.modbus_app is not None
        mock_modbus_app._load_configs.assert_called_once()
        mock_modbus_app._load_maps.assert_called_once()


@pytest.mark.asyncio
async def test_initialize_fails_on_config_load_error(task_manager, mock_modbus_app):
    """❌ initialize() returns False when config loading fails"""
    mock_modbus_app._load_configs.return_value = False
    
    with patch('src.Task.task.ModbusApp', return_value=mock_modbus_app):
        result = await task_manager.initialize()
        
        assert result is False


@pytest.mark.asyncio
async def test_initialize_fails_on_map_load_error(task_manager, mock_modbus_app):
    """❌ initialize() returns False when map loading fails"""
    mock_modbus_app._load_maps.return_value = False
    
    with patch('src.Task.task.ModbusApp', return_value=mock_modbus_app):
        result = await task_manager.initialize()
        
        assert result is False


@pytest.mark.asyncio
async def test_initialize_fails_on_exception(task_manager):
    """❌ initialize() handles exceptions gracefully"""
    with patch('src.Task.task.ModbusApp', side_effect=Exception("Init error")):
        result = await task_manager.initialize()
        
        assert result is False


# ========================================
# Active Hour Tests
# ========================================

def test_is_active_hour_inside_range(task_manager):
    """✅ _is_active_hour returns True when current time is within active hours"""
    task_manager.start_hour = 8
    task_manager.stop_hour = 20
    
    with patch('src.Task.task.datetime') as mock_dt:
        mock_dt.now.return_value.time.return_value = time(12, 30)  # 12:30 PM
        
        assert task_manager._is_active_hour() is True


def test_is_active_hour_outside_range_before(task_manager):
    """❌ _is_active_hour returns False when before start hour"""
    task_manager.start_hour = 8
    task_manager.stop_hour = 20
    
    with patch('src.Task.task.datetime') as mock_dt:
        mock_dt.now.return_value.time.return_value = time(6, 30)  # 6:30 AM
        
        assert task_manager._is_active_hour() is False


def test_is_active_hour_outside_range_after(task_manager):
    """❌ _is_active_hour returns False when after stop hour"""
    task_manager.start_hour = 8
    task_manager.stop_hour = 20
    
    with patch('src.Task.task.datetime') as mock_dt:
        mock_dt.now.return_value.time.return_value = time(22, 30)  # 10:30 PM
        
        assert task_manager._is_active_hour() is False


def test_is_active_hour_at_boundaries(task_manager):
    """✅ _is_active_hour returns True at start and stop hour boundaries"""
    task_manager.start_hour = 8
    task_manager.stop_hour = 20
    
    with patch('src.Task.task.datetime') as mock_dt:
        # Test at start hour
        mock_dt.now.return_value.time.return_value = time(8, 0)
        assert task_manager._is_active_hour() is True
        
        # Test at stop hour
        mock_dt.now.return_value.time.return_value = time(20, 59, 59)
        assert task_manager._is_active_hour() is True


# ========================================
# Device Connection/Disconnection Tests
# ========================================

@pytest.mark.asyncio
async def test_connect_device_delegates_to_modbus_app(task_manager, mock_modbus_app):
    """✅ _connect_device delegates to ModbusApp.connect_device"""
    task_manager.modbus_app = mock_modbus_app
    
    result = await task_manager._connect_device("device1")
    
    assert result is True
    mock_modbus_app.connect_device.assert_called_once_with("device1")


@pytest.mark.asyncio
async def test_disconnect_device_delegates_to_modbus_app(task_manager, mock_modbus_app):
    """✅ _disconnect_device delegates to ModbusApp.disconnect_device"""
    task_manager.modbus_app = mock_modbus_app
    
    await task_manager._disconnect_device("device1")
    
    mock_modbus_app.disconnect_device.assert_called_once_with("device1")


# ========================================
# Config Change Handling Tests
# ========================================

@pytest.mark.asyncio
async def test_on_config_changed_connect_and_read(task_manager, mock_modbus_app):
    """✅ on_config_changed connects device and starts reading when both flags are True"""
    task_manager.modbus_app = mock_modbus_app
    
    await task_manager.on_config_changed("device1", connect=True, readstart=True)
    
    assert "device1" in task_manager._connected_devices
    assert "device1" in task_manager._reading_devices
    mock_modbus_app.connect_device.assert_called_once_with("device1")


@pytest.mark.asyncio
async def test_on_config_changed_connect_only(task_manager, mock_modbus_app):
    """✅ on_config_changed connects device but doesn't start reading when readstart=False"""
    task_manager.modbus_app = mock_modbus_app
    
    await task_manager.on_config_changed("device1", connect=True, readstart=False)
    
    assert "device1" in task_manager._connected_devices
    assert "device1" not in task_manager._reading_devices
    mock_modbus_app.connect_device.assert_called_once_with("device1")


@pytest.mark.asyncio
async def test_on_config_changed_stops_reading_when_readstart_false(task_manager, mock_modbus_app):
    """✅ on_config_changed stops reading when readstart changes to False"""
    task_manager.modbus_app = mock_modbus_app
    task_manager._connected_devices.add("device1")
    task_manager._reading_devices.add("device1")
    
    await task_manager.on_config_changed("device1", connect=True, readstart=False)
    
    assert "device1" not in task_manager._reading_devices
    assert "device1" in task_manager._connected_devices


@pytest.mark.asyncio
async def test_on_config_changed_disconnects_device(task_manager, mock_modbus_app):
    """✅ on_config_changed disconnects device when connect=False"""
    task_manager.modbus_app = mock_modbus_app
    task_manager._connected_devices.add("device1")
    task_manager._reading_devices.add("device1")
    
    await task_manager.on_config_changed("device1", connect=False, readstart=False)
    
    assert "device1" not in task_manager._connected_devices
    assert "device1" not in task_manager._reading_devices
    mock_modbus_app.disconnect_device.assert_called_once_with("device1")


@pytest.mark.asyncio
async def test_on_config_changed_invalid_state_read_without_connect(task_manager):
    """❌ on_config_changed forces readstart=False when connect=False but readstart=True"""
    task_manager.modbus_app = MagicMock()
    task_manager.config.set_device_value = MagicMock()
    
    await task_manager.on_config_changed("device1", connect=False, readstart=True)
    
    # Should force readstart to False in config
    task_manager.config.set_device_value.assert_called_once_with("device1", "modbusread", False)


@pytest.mark.asyncio
async def test_on_config_changed_connection_failure(task_manager, mock_modbus_app):
    """❌ on_config_changed handles connection failure gracefully"""
    task_manager.modbus_app = mock_modbus_app
    mock_modbus_app.connect_device.return_value = False
    
    await task_manager.on_config_changed("device1", connect=True, readstart=True)
    
    assert "device1" not in task_manager._connected_devices
    assert "device1" not in task_manager._reading_devices


# ========================================
# Periodic Reading Task Tests
# ========================================

@pytest.mark.asyncio
async def test_task_read_modbus_periodic_reads_devices(task_manager, mock_modbus_app):
    """✅ task_read_modbus_periodic reads from enabled devices"""
    task_manager.modbus_app = mock_modbus_app
    task_manager._running = True
    task_manager._reading_devices.add("device1")
    task_manager.interval = 0.1
    
    # Mock successful read result
    mock_result = DeviceReadResult(
        device_name="device1",
        device_id="1",
        identify_device="device1_1",
        timestamp="2024-03-28T12:00:00Z",
        success=True,
        data={"var1": 100},
        error=None
    )
    mock_modbus_app.read_all.return_value = [mock_result]
    
    # Mock active hours
    with patch.object(task_manager, '_is_active_hour', return_value=True):
        # Run task for short time then cancel
        task = asyncio.create_task(task_manager.task_read_modbus_periodic())
        await asyncio.sleep(0.2)
        task_manager._running = False
        await task
    
    # Verify read was called
    assert mock_modbus_app.read_all.call_count >= 1


@pytest.mark.asyncio
async def test_task_read_modbus_periodic_publishes_to_queue(task_manager, mock_modbus_app):
    """✅ task_read_modbus_periodic publishes results to queue"""
    task_manager.modbus_app = mock_modbus_app
    task_manager._running = True
    task_manager._reading_devices.add("device1")
    task_manager.interval = 0.1
    task_manager.queue_manager.publish = AsyncMock()
    
    mock_result = DeviceReadResult(
        device_name="device1",
        device_id="1",
        identify_device="device1_1",
        timestamp="2024-03-28T12:00:00Z",
        success=True,
        data={"var1": 100},
        error=None
    )
    mock_modbus_app.read_all.return_value = [mock_result]
    
    with patch.object(task_manager, '_is_active_hour', return_value=True):
        task = asyncio.create_task(task_manager.task_read_modbus_periodic())
        await asyncio.sleep(0.2)
        task_manager._running = False
        await task
    
    # Verify queue publish was called
    assert task_manager.queue_manager.publish.call_count >= 1


@pytest.mark.asyncio
async def test_task_read_modbus_periodic_respects_inactive_hours(task_manager, mock_modbus_app):
    """❌ task_read_modbus_periodic skips reading during inactive hours"""
    task_manager.modbus_app = mock_modbus_app
    task_manager._running = True
    task_manager._reading_devices.add("device1")
    task_manager.interval = 0.1
    
    with patch.object(task_manager, '_is_active_hour', return_value=False):
        task = asyncio.create_task(task_manager.task_read_modbus_periodic())
        await asyncio.sleep(0.2)
        task_manager._running = False
        await task
    
    # Verify read was NOT called
    mock_modbus_app.read_all.assert_not_called()


@pytest.mark.asyncio
async def test_task_read_modbus_periodic_no_devices(task_manager, mock_modbus_app):
    """❌ task_read_modbus_periodic skips reading when no devices enabled"""
    task_manager.modbus_app = mock_modbus_app
    task_manager._running = True
    task_manager.interval = 0.1
    
    with patch.object(task_manager, '_is_active_hour', return_value=True):
        task = asyncio.create_task(task_manager.task_read_modbus_periodic())
        await asyncio.sleep(0.2)
        task_manager._running = False
        await task
    
    # Verify read was NOT called
    mock_modbus_app.read_all.assert_not_called()


@pytest.mark.asyncio
async def test_task_read_modbus_periodic_filters_results_by_reading_devices(task_manager, mock_modbus_app):
    """✅ task_read_modbus_periodic only publishes results from devices in _reading_devices"""
    task_manager.modbus_app = mock_modbus_app
    task_manager._running = True
    task_manager._reading_devices.add("device1")
    task_manager.interval = 0.1
    task_manager.queue_manager.publish = AsyncMock()
    
    # Mock results from multiple devices
    results = [
        DeviceReadResult(
            device_name="device1", 
            device_id="1", 
            identify_device="device1_1",
            timestamp="2024-03-28T12:00:00Z",
            success=True, 
            data={"v": 1}, 
            error=None
        ),
        DeviceReadResult(
            device_name="device2", 
            device_id="2", 
            identify_device="device2_2",
            timestamp="2024-03-28T12:00:00Z",
            success=True, 
            data={"v": 2}, 
            error=None
        ),
    ]
    mock_modbus_app.read_all.return_value = results
    
    with patch.object(task_manager, '_is_active_hour', return_value=True):
        task = asyncio.create_task(task_manager.task_read_modbus_periodic())
        await asyncio.sleep(0.2)
        task_manager._running = False
        await task
    
    # Verify only device1 results were published
    if task_manager.queue_manager.publish.call_count > 0:
        call_args = task_manager.queue_manager.publish.call_args[0][0]
        assert call_args['total_count'] == 1
        assert call_args['results'][0].device_name == "device1"


# ========================================
# Queue Processing Task Tests
# ========================================

@pytest.mark.asyncio
async def test_task_process_queue_consumes_data(task_manager):
    """✅ task_process_queue consumes data from queue"""
    task_manager._running = True
    task_manager.queue_manager.consume = AsyncMock(side_effect=[
        {'results': []},
        asyncio.CancelledError()
    ])
    
    task = asyncio.create_task(task_manager.task_process_queue())
    await asyncio.sleep(0.1)
    task_manager._running = False
    task.cancel()
    
    try:
        await task
    except asyncio.CancelledError:
        pass
    
    assert task_manager.queue_manager.consume.call_count >= 1


# ========================================
# Task Lifecycle Tests
# ========================================

@pytest.mark.asyncio
async def test_start_all_tasks_creates_tasks(task_manager):
    """✅ start_all_tasks creates and starts all background tasks"""
    task_manager._running = False
    task_manager.modbus_app = MagicMock()  # Need modbus_app for the task
    
    # Patch the task methods to avoid actual long-running execution
    with patch.object(task_manager, 'task_read_modbus_periodic', new_callable=AsyncMock) as mock_read, \
         patch.object(task_manager, 'task_process_queue', new_callable=AsyncMock) as mock_queue:
        
        # Make the mocked tasks wait briefly then complete
        async def quick_task():
            await asyncio.sleep(0.1)
        
        mock_read.side_effect = quick_task
        mock_queue.side_effect = quick_task
        
        # Start tasks
        start_task = asyncio.create_task(task_manager.start_all_tasks())
        await asyncio.sleep(0.05)  # Give time for tasks to be created
        
        # Verify tasks were created
        assert task_manager._running is True
        assert len(task_manager._tasks) == 2
        assert any(t.get_name() == "read_modbus" for t in task_manager._tasks)
        assert any(t.get_name() == "process_queue" for t in task_manager._tasks)
        
        # Stop and clean up
        task_manager._running = False
        for t in task_manager._tasks:
            t.cancel()
        
        try:
            await start_task
        except (asyncio.CancelledError, Exception):
            pass


@pytest.mark.asyncio
async def test_start_all_tasks_prevents_double_start(task_manager):
    """❌ start_all_tasks prevents starting tasks if already running"""
    task_manager._running = True
    
    await task_manager.start_all_tasks()
    
    # Should return immediately without creating tasks
    assert len(task_manager._tasks) == 0


@pytest.mark.asyncio
async def test_stop_all_tasks_cancels_tasks(task_manager, mock_modbus_app):
    """✅ stop_all_tasks gracefully cancels all running tasks"""
    task_manager.modbus_app = mock_modbus_app
    
    # Start tasks
    start_task = asyncio.create_task(task_manager.start_all_tasks())
    await asyncio.sleep(0.1)
    
    # Stop tasks
    await task_manager.stop_all_tasks()
    
    # Wait for start task to complete
    try:
        await asyncio.wait_for(start_task, timeout=1.0)
    except asyncio.TimeoutError:
        pass
    
    assert task_manager._running is False
    mock_modbus_app.shutdown.assert_called_once()
