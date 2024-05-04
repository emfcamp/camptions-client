import threading
from time import sleep


class QueueManager:

    def __init__(self, queue, backend):
        self.queue = queue
        self.backend = backend
        self.thread = threading.Thread(target=self.process_queue)
        self.thread.setDaemon(True)
        self.thread.start()

    def process_queue(self):
        while True:
            try:
                while not self.queue.empty():
                    message = self.queue.get()
                    self.backend.push(message)

                sleep(0.1)
            except Exception:
                pass
