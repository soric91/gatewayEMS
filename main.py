import asyncio
from src.Config.config import ConfigManager
from src.Task.task import TaskManager
from src.Utils.logging import get_logger

logger = get_logger(__name__)


async def main():
    """Ejemplo de uso del TaskManager"""
    
    # Crear TaskManager
    task_manager = TaskManager(ConfigManager())
    
    # Inicializar
    if not await task_manager.initialize():
        logger.error("No se pudo inicializar")
        return
    
    # Opción 1: Ejecutar todas las tareas (loop infinito)
    try:
        await task_manager.start_all_tasks()
    except KeyboardInterrupt:
        logger.info("Interrupción detectada")
    finally:
        await task_manager.stop_all_tasks()


if __name__ == "__main__":
    asyncio.run(main())
