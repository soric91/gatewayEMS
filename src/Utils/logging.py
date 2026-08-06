import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from src.Config.config import ConfigManager

def _setup_logging() -> None:
        try:
            
            config = ConfigManager()
            
            loglevel = config.config["DEFAULT"].get("loglevel", "INFO")
            logstdout = config.config["DEFAULT"].getboolean("logstdout", False)
            logfile = config.config["DEFAULT"].get("logfile", None)
            max_size_bytes = config.config["DEFAULT"].getint("max_size_bytes", 1485760)
            backup_count = config.config["DEFAULT"].getint("backup_count", 2)

            level = getattr(logging, loglevel.upper(), logging.WARN)

            handlers = []

            if logfile:
                try:
                    # En un equipo recién clonado el directorio de logs no existe
                    # (sólo se versionan los .py). Sin esto el handler revienta y
                    # el proceso se queda SIN logging: basicConfig no se llega a
                    # llamar y el root logger queda en WARNING sin formato.
                    Path(logfile).parent.mkdir(parents=True, exist_ok=True)
                    handlers.append(
                        RotatingFileHandler(
                            logfile, maxBytes=max_size_bytes, backupCount=backup_count
                        )
                    )
                except OSError as e:
                    print(f"No se pudo abrir el fichero de log '{logfile}': {e}")

            if logstdout or not handlers:
                # Sin fichero, la consola es el único sitio donde mirar.
                handlers.append(logging.StreamHandler())

            logging.basicConfig(
                level=level,
                format="%(asctime)s - %(module)s - %(levelname)s - %(message)s",
                handlers=handlers,
            )

            if config.config["DEFAULT"].getboolean("sampleslog", False):
                logging.getLogger(__name__).info("Samples log is enabled.")
        except Exception as e:
            print(f"Failed to configure logging: {e}")

def get_logger(name: str = None) -> logging.Logger:
    """
    Obtiene un logger con el nombre especificado.
    Si no se proporciona nombre, usa el nombre del módulo que llama.
    """
    if name is None:
        import inspect
        frame = inspect.currentframe().f_back
        name = frame.f_globals.get('__name__', 'unknown')
    
    return logging.getLogger(name)

_setup_logging()