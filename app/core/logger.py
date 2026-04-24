# app/core/logger.py
from loguru import logger
import sys
from app.utils.request_id import get_request_id


logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>req_id={extra[request_id]}</cyan> | <white>{message}</white>",
    level="INFO",
    enqueue=True,
    backtrace=True,
    diagnose=False,
)

logger.add(
    "logs/app_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    compression="gz",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | req_id={extra[request_id]} | {message}",
    level="DEBUG",
    enqueue=True,
    backtrace=True,
    diagnose=False,
)

def get_logger(name: str = None):
    rid = get_request_id() or 'N/A'
    bound_logger = logger.bind(request_id=rid)
    if name:
        bound_logger=bound_logger.bind(name=name)
    return bound_logger

