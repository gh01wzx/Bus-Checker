import time
import logging
from pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BURSTS = 5          
INTERVAL_SEC = 300  

if __name__ == "__main__":
    for i in range(BURSTS):
        logger.info(f"Burst {i + 1}/{BURSTS}")
        try:
            run_pipeline()
        except Exception:
            logger.exception(f"Burst {i + 1} failed, continuing")
        if i < BURSTS - 1:
            time.sleep(INTERVAL_SEC)