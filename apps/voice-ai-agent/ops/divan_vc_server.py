"""divan-vc: turns any Azerbaijani speech into the owner's timbre (OpenVoice v2 tone
color converter, CPU). Loaded once; POST /convert with WAV bytes -> WAV bytes.

Why a separate process: torch lives in its own venv (/opt/divan/vc/.venv) so the
council API stays light, and the model is loaded once instead of per turn.
Measured 2026-09-25 on the VPS: a 6 s clip converts in about 5 s; the owner
embedding comes from his Voice Lab recordings (owner_se.pth).
"""
import io, os, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import torch
from openvoice.api import ToneColorConverter

CKPT = "/opt/divan/vc/ckpt/converter"
OWNER = torch.load(os.environ.get("OWNER_SE", "/opt/divan/vc/owner_se.pth"))
TAU = float(os.environ.get("VC_TAU", "0.3"))
torch.set_num_threads(int(os.environ.get("VC_THREADS", "3")))
tc = ToneColorConverter(f"{CKPT}/config.json", device="cpu")
tc.load_ckpt(f"{CKPT}/checkpoint.pth")
lock = threading.Lock()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")

    def do_POST(self):
        data = self.rfile.read(int(self.headers.get("content-length", 0)))
        try:
            with tempfile.TemporaryDirectory() as d, lock:
                src, out = f"{d}/src.wav", f"{d}/out.wav"
                open(src, "wb").write(data)
                se = tc.extract_se([src])
                tc.convert(audio_src_path=src, src_se=se, tgt_se=OWNER, output_path=out, tau=TAU)
                body = open(out, "rb").read()
            self.send_response(200); self.send_header("content-type", "audio/wav")
            self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body)
        except Exception as exc:  # noqa: BLE001
            self.send_response(500); self.end_headers(); self.wfile.write(str(exc)[:300].encode())


ThreadingHTTPServer(("127.0.0.1", 8941), H).serve_forever()
