import configparser
from whisper import Client, TranscriptionTeeClient
from backend import Service
from manager import QueueManager
from queue import Queue

queue = Queue()

config = configparser.ConfigParser()
config.read("config.ini")

# Start camptions backend websocket service
backend_service = Service(
    host=config["backend"]["host"],
    port=config["backend"]["port"],
    location=config["backend"]["location"],
)

# Start transcription server websocket service
caption_client = Client(
    host=config["server"]["host"],
    port=config["server"]["port"],
    queue=queue,
    lang="en",
    translate=False,
    model="small",
    use_vad=True,
)

# Start queue manager thread
QueueManager(queue=queue, backend=backend_service)

# Start main thread to record from microphone
TranscriptionTeeClient([caption_client])()
