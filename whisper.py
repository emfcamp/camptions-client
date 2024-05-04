"""
Based on https://github.com/collabora/WhisperLive/
Copyright (c) 2023 Vineet Suryan, Collabora Ltd.
MIT License
"""

import numpy as np
import pyaudio
import threading
import json
import websocket
import uuid
import time
from datetime import datetime, timedelta


class Client:
    """
    Handles communication with a server using WebSocket.
    """

    INSTANCES = {}
    END_OF_AUDIO = "END_OF_AUDIO"

    def __init__(
        self,
        host=None,
        port=None,
        queue=None,
        lang=None,
        translate=False,
        model="small",
        use_vad=True,
    ):
        """
        Initializes a Client instance for audio recording and streaming to a server.

        If host and port are not provided, the WebSocket connection will not be established.
        When translate is True, the task will be set to "translate" instead of "transcribe".
        he audio recording starts immediately upon initialization.

        Args:
            host (str): The hostname or IP address of the server.
            port (int): The port number for the WebSocket server.
            lang (str, optional): The selected language for transcription. Default is None.
            translate (bool, optional): Specifies if the task is translation. Default is False.
        """
        self.recording = False
        self.task = "transcribe"
        self.uid = str(uuid.uuid4())
        self.waiting = False
        self.last_response_received = None
        self.disconnect_if_no_response_for = 15
        self.language = lang
        self.model = model
        self.server_error = False
        self.use_vad = use_vad
        self.last_segment = None
        self.last_received_segment = None
        self.queue = queue
        self.client_start = datetime.now()

        if translate:
            self.task = "translate"

        if host is not None and port is not None:
            socket_url = f"ws://{host}:{port}"
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

        Client.INSTANCES[self.uid] = self

        # start websocket client in a thread
        self.ws_thread = threading.Thread(target=self.client_socket.run_forever)
        self.ws_thread.setDaemon(True)
        self.ws_thread.start()

        self.transcript = []
        print("[INFO]: * recording")

    def handle_status_messages(self, message_data):
        """Handles server status messages."""
        status = message_data["status"]
        if status == "WAIT":
            self.waiting = True
            print(
                f"[INFO]: Server is full. Estimated wait time {round(message_data['message'])} minutes."
            )
        elif status == "ERROR":
            print(f"Message from Server: {message_data['message']}")
            self.server_error = True
        elif status == "WARNING":
            print(f"Message from Server: {message_data['message']}")

    def process_segments(self, segments):
        """Processes transcript segments."""
        text = []
        for i, seg in enumerate(segments):
            if not text or text[-1] != seg["text"]:
                text.append(seg["text"])
                if i == len(segments) - 1:
                    self.last_segment = seg
                elif self.server_backend == "faster_whisper" and (
                    not self.transcript
                    or float(seg["start"]) >= float(self.transcript[-1]["end"])
                ):
                    self.transcript.append(seg)

                    ts = self.client_start + timedelta(seconds=float(seg["start"]))
                    self.queue.put(
                        {
                            "event": "segment",
                            "timestamp": ts.isoformat(),
                            "text": seg["text"],
                        }
                    )
        # update last received segment and last valid response time
        if (
            self.last_received_segment is None
            or self.last_received_segment != segments[-1]["text"]
        ):
            self.last_response_received = time.time()
            self.last_received_segment = segments[-1]["text"]

        ts = self.client_start + timedelta(seconds=float(self.last_segment["start"]))
        self.queue.put(
            {
                "event": "latest",
                "timestamp": ts.isoformat(),
                "text": self.last_segment["text"],
            }
        )

    def on_message(self, ws, message):
        message = json.loads(message)

        if self.uid != message.get("uid"):
            print("[ERROR]: invalid client uid")
            return

        if "status" in message.keys():
            self.handle_status_messages(message)
            return

        if "message" in message.keys() and message["message"] == "DISCONNECT":
            print("[INFO]: Server disconnected due to overtime.")
            self.recording = False

        if "message" in message.keys() and message["message"] == "SERVER_READY":
            self.last_response_received = time.time()
            self.recording = True
            self.server_backend = message["backend"]
            print(f"[INFO]: Server Running with backend {self.server_backend}")
            return

        if "language" in message.keys():
            self.language = message.get("language")
            lang_prob = message.get("language_prob")
            print(
                f"[INFO]: Server detected language {self.language} with probability {lang_prob}"
            )
            return

        if "segments" in message.keys():
            self.process_segments(message["segments"])

    def on_error(self, ws, error):
        print(f"[ERROR] WebSocket Error: {error}")
        self.server_error = True
        self.error_message = error

    def on_close(self, ws, close_status_code, close_msg):
        print(f"[INFO]: Websocket connection closed: {close_status_code}: {close_msg}")
        self.recording = False
        self.waiting = False

    def on_open(self, ws):
        print("[INFO]: Opened connection")
        ws.send(
            json.dumps(
                {
                    "uid": self.uid,
                    "language": self.language,
                    "task": self.task,
                    "model": self.model,
                    "use_vad": self.use_vad,
                }
            )
        )

    def send_packet_to_server(self, message):
        try:
            self.client_socket.send(message, websocket.ABNF.OPCODE_BINARY)
        except Exception as e:
            print(e)

    def close_websocket(self):
        try:
            self.client_socket.close()
        except Exception as e:
            print("[ERROR]: Error closing WebSocket:", e)

        try:
            self.ws_thread.join()
        except Exception as e:
            print("[ERROR:] Error joining WebSocket thread:", e)

    def get_client_socket(self):
        return self.client_socket


class TranscriptionTeeClient:
    def __init__(self, clients):
        self.clients = clients
        if not self.clients:
            raise Exception("At least one client is required.")
        self.chunk = 16384
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 16000
        self.frames = b""
        self.p = pyaudio.PyAudio()
        try:
            self.stream = self.p.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk,
            )
        except OSError as error:
            print(f"[WARN]: Unable to access microphone. {error}")
            self.stream = None

    def __call__(self, hls_url=None):
        print("[INFO]: Waiting for server ready ...")
        for client in self.clients:
            while not client.recording:
                if client.waiting or client.server_error:
                    self.close_all_clients()
                    return

        print("[INFO]: Server Ready!")
        if hls_url is not None:
            self.process_hls_stream(hls_url)
        else:
            self.record()

    def close_all_clients(self):
        for client in self.clients:
            client.close_websocket()

    def multicast_packet(self, packet, unconditional=False):
        for client in self.clients:
            if unconditional or client.recording:
                client.send_packet_to_server(packet)

    def record(self):
        try:
            while True:
                data = self.stream.read(self.chunk, exception_on_overflow=False)
                audio_array = self.bytes_to_float_array(data)
                self.multicast_packet(audio_array.tobytes())

        except KeyboardInterrupt:
            self.stream.stop_stream()
            self.stream.close()
            self.p.terminate()
            self.close_all_clients()

    @staticmethod
    def bytes_to_float_array(audio_bytes):
        raw_data = np.frombuffer(buffer=audio_bytes, dtype=np.int16)
        return raw_data.astype(np.float32) / 32768.0


class TranscriptionClient(TranscriptionTeeClient):
    def __init__(
        self,
        host="localhost",
        port=9090,
        lang=None,
        translate=False,
        model="small",
        use_vad=True,
    ):
        self.client = Client(
            host=host,
            port=port,
            lang=lang,
            translate=translate,
            model=model,
            use_vad=use_vad,
        )
        TranscriptionTeeClient.__init__(self, [self.client])
