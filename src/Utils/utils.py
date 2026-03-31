import asyncio
from dataclasses import dataclass
from src.Utils.logging import get_logger


logger = get_logger(__name__)


@dataclass
class QueueManager:
    queue = asyncio.Queue()
    
    def __init__(self):        
        self.queue = asyncio.Queue()

    async def publish(self, data):
        await self.queue.put(data)
    async def consume(self):
        return await self.queue.get()
    
    
