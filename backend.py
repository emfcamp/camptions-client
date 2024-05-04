import json
import socketio
import threading


class Service:
    def __init__(
        self,
        host=None,
        port=None,
        location=None,
    ):
        self.location = location

        if host is not None and port is not None:
            self.client_socket = socketio.Client()
            self.client_socket.connect(f"http://{host}:{port}")
        else:
            print("[ERROR]: No host or port specified.")
            return

        self.thread = threading.Thread(target=self.client_socket.wait)
        self.thread.setDaemon(True)
        self.thread.start()

    def push(self, message):
        message["location"] = self.location
        self.client_socket.emit("transcription`", json.dumps(message))
