import logging
import shutil
import subprocess, threading, socketserver, http.server
from multiprocessing import Process
import cv2
import numpy as np
from .win_utils import get_screen_size,get_taskbar_size,activate_driverstation_window

# --- CONFIG ---
HOST = "0.0.0.0"
PORT = 8080
FRAMERATE = 20
QUALITY = 3
DS_HEIGHT = 200
# ---------------

SCREEN_WIDTH, SCREEN_HEIGHT = get_screen_size()
TASKBAR_HEIGHT = get_taskbar_size()

# Capture bottom region above taskbar
X, Y = 0, SCREEN_HEIGHT - (TASKBAR_HEIGHT + DS_HEIGHT)
WIDTH, HEIGHT = SCREEN_WIDTH, DS_HEIGHT

# --- FFmpeg command ---
ffmpeg_cmd = [
    "ffmpeg",
    "-hide_banner",
    "-loglevel", "error",
    "-f", "gdigrab",
    "-draw_mouse", "0",
    "-show_region", "0",
    "-framerate", str(FRAMERATE),
    "-offset_x", str(X),
    "-offset_y", str(Y),
    "-video_size", f"{WIDTH}x{HEIGHT}",
    "-i", "desktop",
    "-vf", "scale=960:-1,format=yuvj420p",   # yuvj422p causes encoder crash sometimes
    "-q:v", str(QUALITY),
    "-r", str(FRAMERATE),
    "-pix_fmt", "yuvj420p",                  # explicitly set working pixel format
    "-strict", "unofficial",                 # allow low delay safely
    "-fflags", "nobuffer",
    "-an",
    "-f", "mjpeg",
    "-"
]


# Shared latest frame
latest_frame = None
lock = threading.Lock()

def frame_reader(proc):
    """Continuously read MJPEG frames from FFmpeg stdout."""
    global latest_frame
    buffer = b""
    while True:
        chunk = proc.stdout.read(4096)
        if not chunk:
            logging.warning("FFmpeg exited or stopped producing output.")
            break

        buffer += chunk
        # Find JPEG frame end marker
        while b"\xff\xd9" in buffer:
            frame, buffer = buffer.split(b"\xff\xd9", 1)
            with lock:
                latest_frame = frame + b"\xff\xd9"

def get_latest_frame_mat():
    """
    Returns the most recent MJPEG frame as an OpenCV BGR image.
    Returns None if no frame is available yet.
    """
    global latest_frame
    with lock:
        frame = latest_frame

    if frame is None:
        return None

    # Convert JPEG bytes to numpy array
    nparr = np.frombuffer(frame, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)  # BGR format
    return img

class MJPEGHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/mjpeg":
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()

        logging.info(f"Client connected: {self.client_address}")

        try:
            while True:
                with lock:
                    frame = latest_frame
                if frame:
                    # Send multipart MJPEG frame
                    self.wfile.write(
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" +
                        frame + b"\r\n"
                    )
        except (BrokenPipeError, ConnectionResetError):
            logging.info(f"Client disconnected: {self.client_address}")
        except Exception as e:
            logging.error(f"Streaming error: {e}")

    def log_message(self, *args):
        # suppress default BaseHTTPRequestHandler logging
        pass


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def run_server_process():
    """Start FFmpeg and MJPEG HTTP server together in a subprocess."""
    ffmpeg = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    threading.Thread(target=frame_reader, args=(ffmpeg,), daemon=True).start()

    server = ThreadedHTTPServer((HOST, PORT), MJPEGHandler)
    logging.info(f"Serving MJPEG on http://{HOST}:{PORT}/mjpeg")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ffmpeg.terminate()
        logging.info("FFmpeg terminated and server stopped.")


def start_ffmpeg_server():
    """Launch the MJPEG streamer as a background process."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFMPEG not found, run this shit: winget install \"FFmpeg (Essentials Build)\"")
    activate_driverstation_window()
    p = threading.Thread(target=run_server_process, daemon=True)
    p.start()
    logging.info(f"Started MJPEG streaming thread")
    return p