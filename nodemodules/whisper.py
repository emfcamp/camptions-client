"""
Based on https://github.com/collabora/WhisperLive/
Copyright (c) 2023 Vineet Suryan, Collabora Ltd.
MIT License
"""

from iotnode.module import NodeModule
import numpy as np
import pyaudio
import json
import websocket
import threading
import uuid
import time
import logging
from datetime import datetime, timedelta


class WhisperModule(NodeModule):
    INSTANCES = {}

    def __init__(self, *args, **kwargs):
        super(WhisperModule, self).__init__(*args, **kwargs)

        self.uid = str(uuid.uuid4())
        WhisperModule.INSTANCES[self.uid] = self
        self.language = "en"
        self.translate = False
        self.model = self.cache["config"]["server"]["model"]
        self.task = "transcribe"
        self.use_vad = True
        self.client_start = datetime.now()
        self.connected = False
        self.last_segment = None
        self.last_received_segment = None

        self.connect()

    def connect(self):
        self.transcript = []
        config = self.cache["config"]["server"]
        socket_url = f"ws://{config['host']}:{config['port']}"
        self.client_socket = websocket.WebSocketApp(
            socket_url,
            on_open=lambda ws: self.on_open(ws),
            on_reconnect=lambda ws: self.on_open(ws),
            on_close=lambda ws, s, m: self.on_close(ws),
            on_error=lambda ws, e: self.on_error(ws),
            on_message=lambda ws, message: self.on_message(ws, message),
        )
        self.sockthread = threading.Thread(target=self.thread_function)
        self.sockthread.name = 'ServerWebSocket'
        self.sockthread.setDaemon(True)
        self.sockthread.start()

    def thread_function(self):
        while True:
            self.client_socket.run_forever();
            time.sleep(2)

    def cleanup(self):
        self.client_socket.close()

    def callback_audio(self, data):
        if self.connected:
            self.client_socket.send(
                data["data"].tobytes(), websocket.ABNF.OPCODE_BINARY
            )

    def handle_status_messages(self, message_data):
        """Handles server status messages."""
        status = message_data["status"]
        if status == "WAIT":
            logging.info(
                f"Server is full. Estimated wait time {round(message_data['message'])} minutes."
            )
        elif status == "ERROR":
            logging.error(f"Message from Server: {message_data['message']}")
            self.server_error = True
        elif status == "WARNING":
            logging.error(f"Message from Server: {message_data['message']}")

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
                    self.push(
                        {
                            "type": "transcription",
                            "data": {
                                "event": "segment",
                                "timestamp": ts.isoformat(),
                                "text": seg["text"],
                            },
                        }
                    )
        if (
            self.last_received_segment is None
            or self.last_received_segment != segments[-1]["text"]
        ):
            self.last_response_received = time.time()
            self.last_received_segment = segments[-1]["text"]

        ts = self.client_start + timedelta(seconds=float(self.last_segment["start"]))
        self.push(
            {
                "type": "transcription",
                "data": {
                    "event": "latest",
                    "timestamp": ts.isoformat(),
                    "text": self.last_segment["text"],
                },
            }
        )

    def on_message(self, ws, message):
        message = json.loads(message)

        if self.uid != message.get("uid"):
            logging.error("invalid client uid")
            return

        if "status" in message.keys():
            self.handle_status_messages(message)
            return

        if "message" in message.keys() and message["message"] == "DISCONNECT":
            logging.info("Server disconnected due to overtime.")
            self.recording = False

        if "message" in message.keys() and message["message"] == "SERVER_READY":
            self.last_response_received = time.time()
            self.recording = True
            self.server_backend = message["backend"]
            logging.info(f"Server Running with backend {self.server_backend}")
            return

        if "language" in message.keys():
            self.language = message.get("language")
            lang_prob = message.get("language_prob")
            logging.info(
                f"Server detected language {self.language} with probability {lang_prob}"
            )
            return

        if "segments" in message.keys():
            self.process_segments(message["segments"])

    def on_error(self,ws):
        logging.error(f"An error has occured")

    def on_open(self, ws):
        self.connected = True
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
        self.push({"type": "server_status", "data": "connected"})

    def on_close(self, ws):
        self.connected = False
        self.push({"type": "server_status", "data": "disconnected"})
        self.cleanup()


class RecordModule(NodeModule):

    def __init__(self, *args, **kwargs):
        self.chunk = 16384
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 16000
        self.frames = b""
        self.p = pyaudio.PyAudio()
        super(RecordModule, self).__init__(*args, **kwargs)
        self.connect()

    def connect(self):
        try:
            self.stream = self.p.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk,
            )
        except OSError as error:
            logging.warning(f"Unable to access microphone. {error}")
            self.stream = None

    def tick(self):
        data = self.stream.read(self.chunk, exception_on_overflow=False)
        audio_array = self.bytes_to_float_array(data)
        self.push({"type": "audio", "data": audio_array})

    def cleanup(self):
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()
        exit()

    @staticmethod
    def bytes_to_float_array(audio_bytes):
        raw_data = np.frombuffer(buffer=audio_bytes, dtype=np.int16)
        return raw_data.astype(np.float32) / 32768.0
