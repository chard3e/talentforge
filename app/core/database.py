from neo4j import GraphDatabase, Driver
from .config import get_settings
import logging

settings = get_settings()
logger = logging.getLogger(__name__)

_driver: Driver | None = None

def get_neo4j_driver() -> Driver:
    """Singleton Neo4j driver döndürür"""
    global _driver
    if _driver is None:
        try:
            _driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD)
            )
            _driver.verify_connectivity()
            logger.info("Neo4j driver başarıyla oluşturuldu")
        except Exception as e:
            logger.error(f"Neo4j bağlantı hatası: {e}")
            raise
    return _driver

def close_neo4j_driver():
    """Uygulama kapanırken driver'ı kapat"""
    global _driver
    if _driver:
        _driver.close()
        _driver = None
        logger.info("Neo4j driver kapatıldı")