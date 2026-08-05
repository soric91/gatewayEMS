"""
Tests unitarios para utilidades
"""
import pytest
import asyncio
from src.Utils.utils import QueueManager

SINK = "sink"

class TestQueueManager:
    """Tests para QueueManager (bus de fan-out: una cola por suscriptor)"""
    
    @pytest.mark.asyncio
    async def test_publish_and_consume(self):
        """Debe publicar y consumir datos"""
        qm = QueueManager()
        qm.subscribe(SINK)
        test_data = {"key": "value"}
        
        await qm.publish(test_data)
        consumed = await qm.consume(SINK)
        
        assert consumed == test_data
    
    @pytest.mark.asyncio
    async def test_multiple_publish_consume(self):
        """Debe manejar múltiples publicaciones"""
        qm = QueueManager()
        qm.subscribe(SINK)
        data1 = {"id": 1}
        data2 = {"id": 2}
        data3 = {"id": 3}
        
        await qm.publish(data1)
        await qm.publish(data2)
        await qm.publish(data3)
        
        assert (await qm.consume(SINK)) == data1
        assert (await qm.consume(SINK)) == data2
        assert (await qm.consume(SINK)) == data3
    
    @pytest.mark.asyncio
    async def test_consume_blocks_when_empty(self):
        """Consume debe bloquear cuando la cola está vacía"""
        qm = QueueManager()
        qm.subscribe(SINK)
        
        async def delayed_publish():
            await asyncio.sleep(0.1)
            await qm.publish({"delayed": True})
        
        # Iniciar publicación retrasada
        asyncio.create_task(delayed_publish())
        
        # Consume debe esperar
        result = await qm.consume(SINK)
        assert result == {"delayed": True}
    
    @pytest.mark.asyncio
    async def test_queue_order_fifo(self):
        """La cola debe ser FIFO (First In First Out)"""
        qm = QueueManager()
        qm.subscribe(SINK)
        
        for i in range(10):
            await qm.publish({"order": i})
        
        for i in range(10):
            result = await qm.consume(SINK)
            assert result["order"] == i
