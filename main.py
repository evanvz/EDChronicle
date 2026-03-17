from edc.app import run
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)

logging.info("Logging initialized")

if __name__ == "__main__":
    run()
