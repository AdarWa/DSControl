import logging
import shutil
import subprocess, threading, socketserver, http.server
import time
from typing import Optional
from multiprocessing import Process
import cv2
import numpy as np
from .win_utils import get_screen_size,get_taskbar_size,activate_driverstation_window

# --- CONFIG ---
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

FFMPEG_RESTART_INITIAL_DELAY = 1.0
FFMPEG_RESTART_MAX_DELAY = 10.0


def frame_reader(proc, stop_event: threading.Event):
    """Continuously read MJPEG frames from FFmpeg stdout."""
    global latest_frame
    buffer = b""
    stdout = proc.stdout
    if stdout is None:
        logging.error("FFmpeg stdout pipe is unavailable; stopping frame reader.")
        return
    try:
        while not stop_event.is_set():
            chunk = stdout.read(4096)
            if not chunk:
                if stop_event.is_set():
                    logging.debug("Frame reader stopping due to shutdown request.")
                else:
                    return_code = proc.poll()
                    if return_code is None:
                        logging.warning("FFmpeg stopped producing output.")
                    else:
                        logging.warning("FFmpeg exited with code %s.", return_code)
                break

            buffer += chunk
            # Find JPEG frame end marker
            while b"\xff\xd9" in buffer:
                frame, buffer = buffer.split(b"\xff\xd9", 1)
                with lock:
                    latest_frame = frame + b"\xff\xd9"
    finally:
        try:
            stdout.close()
        except Exception:
            pass

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
            self.wfile.write(b"Error 404 - Not found\nNavigate to /mjpeg")
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


def run_server_process(host: str, port: int):
    """Start FFmpeg and MJPEG HTTP server together in a subprocess."""
    stop_event = threading.Event()
    ffmpeg_lock = threading.Lock()
    ffmpeg_proc: Optional[subprocess.Popen] = None

    def launch_ffmpeg() -> subprocess.Popen:
        logging.info("Launching FFmpeg capture pipeline.")
        return subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

    def supervise_ffmpeg():
        nonlocal ffmpeg_proc
        global latest_frame
        backoff = FFMPEG_RESTART_INITIAL_DELAY

        while not stop_event.is_set():
            try:
                proc = launch_ffmpeg()
            except Exception as exc:
                logging.exception("Failed to start FFmpeg process: %s", exc)
                time.sleep(backoff)
                backoff = min(backoff * 2, FFMPEG_RESTART_MAX_DELAY)
                continue

            with ffmpeg_lock:
                ffmpeg_proc = proc
            threading.Thread(target=frame_reader, args=(proc, stop_event), daemon=True).start()

            backoff = FFMPEG_RESTART_INITIAL_DELAY
            return_code = proc.wait()

            if stop_event.is_set():
                break

            with lock:
                latest_frame = None
            logging.warning(
                "FFmpeg stopped (code %s). Restarting in %.1f seconds.",
                return_code,
                backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, FFMPEG_RESTART_MAX_DELAY)

        logging.info("FFmpeg supervisor exiting.")

    supervisor_thread = threading.Thread(target=supervise_ffmpeg, daemon=True)
    supervisor_thread.start()

    server = ThreadedHTTPServer((host, port), MJPEGHandler)
    logging.info(f"Serving MJPEG on http://{host}:{port}/mjpeg")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        try:
            server.shutdown()
        except Exception:
            pass
        server.server_close()

        with ffmpeg_lock:
            proc = ffmpeg_proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

        supervisor_thread.join(timeout=5)
        logging.info("FFmpeg terminated and server stopped.")


def start_ffmpeg_server(host: str, port: int):
    """Launch the MJPEG streamer as a background process."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFMPEG not found, run this shit: winget install \"FFmpeg (Essentials Build)\"")
    activate_driverstation_window()
    p = threading.Thread(target=run_server_process, daemon=True, args=(host, port))
    p.start()
    logging.info(f"Started MJPEG streaming thread")
    return p
