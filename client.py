import configparser
from iotnode.controller import Controller
import logging


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(threadName)s %(message)s"
)


config = configparser.ConfigParser()
config.read("config.ini")

modules = [
    ("BackendModule", "backend"),
    ("WhisperModule", "whisper"),
    ("RecordModule", "whisper"),
]


class Client(Controller):
    def __init__(self, *args, **kwargs):
        self.cache["config"] = config
        super(Client, self).__init__(*args, **kwargs)


if __name__ == "__main__":
    node = Client(modules)
    node.start()
