import logging
from pywinauto import Desktop
import subprocess
import shutil


def make_cmd(host="0.0.0.0", port=9999, region=(0, 0, 1280, 720), framerate=30):
    left, top, width, height = region

    cmd = " ".join([
        "ffmpeg",
        "-f", "gdigrab",
        "-framerate", str(framerate),
        "-offset_x", str(left),
        "-offset_y", str(top),
        "-video_size", f"{width}x{height}",
        "-i", "desktop",
        "-vcodec", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-f", "mpegts",
        f"tcp://{host}:{port}?listen"
    ])
    return cmd


def start_ffmpeg_stream(host="0.0.0.0", port=9999, region=None, framerate=30):
    if not shutil.which("ffmpeg"):
        raise ValueError("FFMPEG not found, run this shit: winget install \"FFmpeg (Essentials Build)\"")
    subprocess.run(["cmd", "/c", make_cmd(host=host, port=port,region=region,framerate=framerate)], text=True)