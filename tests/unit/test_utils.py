"""
Tests unitarios para utilidades
"""
import pytest
import asyncio
from src.Utils.utils import QueueManager

class TestQueueManager:
    """Tests para QueueManager"""
    
    @pytest.mark.asyncio
    async def test_publish_and_consume(self):
        """Debe publicar y consumir datos"""
        qm = QueueManager()
        test_data = {"key": "value"}
        
        await qm.publish(test_data)
        consumed = await qm.consume()
        
        assert consumed == test_data
    
    @pytest.mark.asyncio
    async def test_multiple_publish_consume(self):
        """Debe manejar múltiples publicaciones"""
        qm = QueueManager()
        data1 = {"id": 1}
        data2 = {"id": 2}
        data3 = {"id": 3}
        
        await qm.publish(data1)
        await qm.publish(data2)
        await qm.publish(data3)
        
        assert (await qm.consume()) == data1
        assert (await qm.consume()) == data2
        assert (await qm.consume()) == data3
    
    @pytest.mark.asyncio
    async def test_consume_blocks_when_empty(self):
        """Consume debe bloquear cuando la cola está vacía"""
        qm = QueueManager()
        
        async def delayed_publish():
            await asyncio.sleep(0.1)
            await qm.publish({"delayed": True})
        
        # Iniciar publicación retrasada
        asyncio.create_task(delayed_publish())
        
        # Consume debe esperar
        result = await qm.consume()
        assert result == {"delayed": True}
    
    @pytest.mark.asyncio
    async def test_queue_order_fifo(self):
        """La cola debe ser FIFO (First In First Out)"""
        qm = QueueManager()
        
        for i in range(10):
            await qm.publish({"order": i})
        
        for i in range(10):
            result = await qm.consume()
            assert result["order"] == i
