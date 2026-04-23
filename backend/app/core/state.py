import threading

data_ready = threading.Event()
loading_status: dict = {"state": "idle", "message": ""}
