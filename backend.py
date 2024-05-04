import threading
import json
import websocket
import uuid


class Service:
    INSTANCES = {}

    def __init__(
        self,
        host=None,
        port=None,
        location=None,
    ):
        self.uid = str(uuid.uuid4())
        self.waiting = False
        self.last_response_received = None
        self.disconnect_if_no_response_for = 15
        self.server_error = False
        self.location = location

        if host is not None and port is not None:
            socket_url = f"ws://{host}:{port}/ingestion/{location}"
            self.client_socket = websocket.WebSocketApp(
                socket_url,
                on_open=lambda ws: self.on_open(ws),
                on_message=lambda ws, message: self.on_message(ws, message),
                on_error=lambda ws, error: self.on_error(ws, error),
                on_close=lambda ws, close_status_code, close_msg: self.on_close(
                    ws, close_status_code, close_msg
                ),
            )
        else:
            print("[ERROR]: No host or port specified.")
            return

        Service.INSTANCES[self.uid] = self

        self.ws_thread = threading.Thread(target=self.client_socket.run_forever)
        self.ws_thread.setDaemon(True)
        self.ws_thread.start()

    def on_message(self, ws, message):
        message = json.loads(message)
        print(f"[INFO] Backend message: {message}")

    def on_error(self, ws, error):
        print(f"[ERROR] Backend WebSocket Error: {error}")
        self.server_error = True
        self.error_message = error

    def on_close(self, ws, close_status_code, close_msg):
        print(
            f"[INFO]: Backend Websocket connection closed: {close_status_code}: {close_msg}"
        )
        self.recording = False
        self.waiting = False

    def on_open(self, ws):
        print("[INFO]: Opened Backend connection")
        ws.send(
            json.dumps(
                {
                    "uid": self.uid,
                }
            )
        )

    def push(self, message):
        self.client_socket.send(json.dumps(message))

    def close_websocket(self):
        try:
            self.client_socket.close()
        except Exception as e:
            print("[ERROR]: Error closing Backend WebSocket:", e)

        try:
            self.ws_thread.join()
        except Exception as e:
            print("[ERROR:] Error joining Backend WebSocket thread:", e)

    def get_client_socket(self):
        return self.client_socket
