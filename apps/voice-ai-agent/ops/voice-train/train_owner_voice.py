"""Fine-tune a Piper (VITS) voice on the owner's recordings. Runs on a Kaggle T4,
fully OFFLINE (the account has no kernel internet), from two private datasets:

  alimalirzayev/divan-owner-voice   wavs/ + metadata.csv  (build_voice_dataset.py)
  alimalirzayev/divan-voice-deps    wheels/ (piper-tts[train] minus torch), base/
                                    (rhasspy tr_TR dfki medium ckpt), src/core.pyx

piper-tts bundles espeak-ng and its `az` voice, so no apt is needed.
Output: /kaggle/working/az_AZ-owner-medium.onnx (+ .onnx.json).
EXTRA_EPOCHS: small for a smoke run, ~1000+ for the real one.
"""
import glob, os, shutil, subprocess, sys

EXTRA_EPOCHS = int(os.environ.get("EXTRA_EPOCHS", "__EXTRA__"))
BASE_EPOCH = 5679
sh = lambda c: subprocess.run(c, shell=True, check=True)
# The rhasspy checkpoints predate torch 2.6 weights_only loading (they pickle a
# PosixPath). The file comes from the official rhasspy dataset, so load it fully.
os.environ["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] = "1"
find = lambda pat: glob.glob(f"/kaggle/input/**/{pat}", recursive=True)

wheels = os.path.dirname(find("wheels/piper_tts-*.whl")[0])
sh(f"{sys.executable} -m pip install -q --no-index --find-links {wheels} 'piper-tts[train]' onnxscript")
import piper  # noqa: E402
ma = os.path.join(os.path.dirname(piper.__file__), "train/vits/monotonic_align")
shutil.copy(find("src/core.pyx")[0], ma)
sh(f"cd {ma} && mkdir -p monotonic_align && cythonize -q -i core.pyx && mv core*.so monotonic_align/")

# The rhasspy checkpoints predate torch 2.6 weights_only loading: they pickle
# pathlib.PosixPath inside the hyper-parameters, and Lightning loads with
# weights_only=True. Load once fully (official rhasspy file, trusted), turn every
# path into a plain string and save a clean copy that the safe loader accepts.
import pathlib, torch  # noqa: E402
def _plain(o):
    if isinstance(o, pathlib.PurePath): return str(o)
    if isinstance(o, dict): return {k: _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return type(o)(_plain(v) for v in o)
    return o
_ck = torch.load(find("base/**/*.ckpt")[0], map_location="cpu", weights_only=False)
_ck = {k: (_plain(v) if k != "state_dict" else v) for k, v in _ck.items()
       # old piper_train hyper-parameters (sample_bytes, dataset paths ...) are not
       # options of the new piper.train CLI; the CLI flags below define the model.
       if k not in ("hyper_parameters", "datamodule_hyper_parameters", "callbacks")}
torch.save(_ck, "/kaggle/working/base.ckpt")
print("base keys:", list(_ck)[:8], flush=True)
del _ck
base = "/kaggle/working/base.ckpt"
data = find("metadata.csv")[0]
root = os.path.dirname(data)
print("clips:", sum(1 for _ in open(data)), "base:", base, flush=True)
# Offline: the UTMOS judge (torch.hub) cannot load, so val_mos is never logged and
# piper's default val_mos ModelCheckpoint raises; a --config callback list is
# APPENDED to the defaults, not swapped. So launch piper's own CLI class with our
# trainer defaults: one ModelCheckpoint on val_mel.
LAUNCHER = """
import logging, torch
from lightning.pytorch.callbacks import ModelCheckpoint
from piper.train.__main__ import VitsLightningCLI
from piper.train.vits.dataset import VitsDataModule
from piper.train.vits.lightning import VitsModel
logging.basicConfig(level=logging.INFO)
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True
VitsLightningCLI(VitsModel, VitsDataModule, trainer_defaults={"max_epochs": -1, "callbacks": [
    ModelCheckpoint(monitor="val_mel", mode="min", save_top_k=3, save_last=True,
                    filename="epoch={epoch}-val_mel={val_mel:.4f}", auto_insert_metric_name=False)]})
"""
open("/kaggle/working/train_cli.py", "w").write(LAUNCHER)
try:
    sh(f"""{sys.executable} /kaggle/working/train_cli.py fit \
      --model.mos_metric none \
      --data.voice_name az_AZ-owner-medium \
      --data.csv_path {data} \
      --data.audio_dir {root}/wavs \
      --model.sample_rate 22050 \
      --data.espeak_voice az \
      --data.cache_dir /kaggle/working/cache \
      --data.config_path /kaggle/working/az_AZ-owner-medium.onnx.json \
      --data.batch_size 16 \
      --trainer.max_epochs {EXTRA_EPOCHS} \
      --trainer.default_root_dir /kaggle/working/run \
      --model.warmstart_ckpt {base}""")

    ckpts = sorted(glob.glob("/kaggle/working/run/**/*.ckpt", recursive=True), key=os.path.getmtime)
    print("checkpoints:", ckpts[-2:], flush=True)
    # torch >= 2.9 exports through dynamo by default, which trips an assert inside the
    # VITS spline; piper was written for the classic TorchScript exporter.
    open("/kaggle/working/export_cli.py", "w").write(
        "import runpy, sys, torch\n"
        "_orig = torch.onnx.export\n"
        "torch.onnx.export = lambda *a, **k: _orig(*a, **{**k, 'dynamo': False})\n"
        "runpy.run_module('piper.train.export_onnx', run_name='__main__')\n")
    sh(f"{sys.executable} /kaggle/working/export_cli.py --checkpoint '{ckpts[-1]}' "
       f"--output-file /kaggle/working/az_AZ-owner-medium.onnx")
    print("DONE", os.listdir("/kaggle/working"))
finally:
    # Only the ONNX voice leaves the kernel; the 845 MB base copy, the cache and the
    # Lightning run dir would otherwise land in the output even after a failure.
    for junk in ("/kaggle/working/base.ckpt", "/kaggle/working/train_cli.py", "/kaggle/working/export_cli.py"):
        if os.path.exists(junk): os.remove(junk)
    shutil.rmtree("/kaggle/working/cache", ignore_errors=True)
    shutil.rmtree("/kaggle/working/run", ignore_errors=True)
