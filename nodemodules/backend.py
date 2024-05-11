from iotnode.module import NodeModule
import json
import socketio
import logging


class BackendModule(NodeModule):
    def __init__(self, *args, **kwargs):
        super(BackendModule, self).__init__(*args, **kwargs)
        self.connect()

    def connect(self):
        config = self.cache["config"]["backend"]
        self.client_socket = socketio.Client()
        self.client_socket.connect(f"{config['host']}:{config['port']}")

    def cleanup(self):
        self.client_socket.disconnect()

    def callback_transcription(self, data):
        data["data"]["location"] = self.cache["config"]["backend"]["location"]
        logging.info(data["data"])
        self.client_socket.emit("transcription", json.dumps(data["data"]))
