import cv2
import threading
import time
from dataclasses import dataclass
from .stream_server import get_latest_frame_mat
from .pipeline_utils import crop

# ---- Constants ----
DS_STATE_CROP_REGION = (300, 70, 150, 100) # x, y, w, h

@dataclass
class PipelineOutputs:
    ds_state: str = ""


class DriverStationPipeline:
    def __init__(self):
        self.outputs = PipelineOutputs()
        self.latest_frame = None
        self.running = False
        self._thread = None
        self._lock = threading.Lock()

    def get_outputs(self):
        return self.outputs

    def get_frame(self):
        with self._lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def _update_loop(self):
        while self.running:
            frame = get_latest_frame_mat()
            if frame is None:
                continue

            # -------- Pipeline starts here --------

            ds_state_crop = crop(DS_STATE_CROP_REGION)

            # -------- Pipeline ends here --------
            with self._lock:
                self.latest_frame = ds_state_crop
            time.sleep(0.01)

    def start(self):
        if not self.running:
            self.running = True
            self._thread = threading.Thread(target=self._update_loop, daemon=True)
            self._thread.start()

    def stop(self):
        self.running = False
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def show_live(self, window_name="DriverStation Stream"):
        self.start()
        while True:
            frame = self.get_frame()
            if frame is not None:
                cv2.imshow(window_name, frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        cv2.destroyAllWindows()
