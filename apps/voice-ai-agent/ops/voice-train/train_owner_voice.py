"""Fine-tune a Piper (VITS) voice on the owner's recordings. Runs on a Kaggle T4.

Input:  Kaggle dataset alimalirzayev/divan-owner-voice (wavs/ + metadata.csv).
Base:   rhasspy/piper-checkpoints tr_TR dfki medium (closest Turkic phonology).
Output: /kaggle/working/az_AZ-owner-medium.onnx (+ .onnx.json), last.ckpt.
EXTRA_EPOCHS is set by the launcher (small for a smoke run, ~1000+ for the real one).
"""
import glob, json, os, shutil, subprocess, sys

EXTRA_EPOCHS = int(os.environ.get("EXTRA_EPOCHS", "__EXTRA__"))
BASE_EPOCH = 5679
sh = lambda c: subprocess.run(c, shell=True, check=True)

sh("apt-get -qq update && apt-get -qq install -y espeak-ng > /dev/null")
sh("espeak-ng --voices=az | head -3")
if not os.path.isdir("piper1-gpl"):
    sh("git clone -q https://github.com/OHF-voice/piper1-gpl.git")
os.chdir("piper1-gpl")
sh(f"{sys.executable} -m pip install -q -e '.[train]'")
sh("./build_monotonic_align.sh")
sh(f"{sys.executable} setup.py build_ext --inplace > /dev/null")

from huggingface_hub import hf_hub_download
base = hf_hub_download("rhasspy/piper-checkpoints", "tr/tr_TR/dfki/medium/epoch=5679-step=1489110.ckpt",
                       repo_type="dataset")
data = glob.glob("/kaggle/input/**/metadata.csv", recursive=True)[0]
root = os.path.dirname(data)
print("clips:", sum(1 for _ in open(data)), "base:", base, flush=True)

sh(f"""{sys.executable} -m piper.train fit \
  --data.voice_name az_AZ-owner-medium \
  --data.csv_path {data} \
  --data.audio_dir {root}/wavs \
  --model.sample_rate 22050 \
  --data.espeak_voice az \
  --data.cache_dir /kaggle/working/cache \
  --data.config_path /kaggle/working/az_AZ-owner-medium.onnx.json \
  --data.batch_size 16 \
  --trainer.max_epochs {BASE_EPOCH + EXTRA_EPOCHS} \
  --trainer.default_root_dir /kaggle/working/run \
  --ckpt_path {base}""")

ckpts = sorted(glob.glob("/kaggle/working/run/**/*.ckpt", recursive=True), key=os.path.getmtime)
print("checkpoints:", ckpts[-2:], flush=True)
sh(f"{sys.executable} -m piper.train.export_onnx --checkpoint '{ckpts[-1]}' "
   f"--output-file /kaggle/working/az_AZ-owner-medium.onnx")
shutil.copy(ckpts[-1], "/kaggle/working/last.ckpt")
shutil.rmtree("/kaggle/working/cache", ignore_errors=True)
shutil.rmtree("/kaggle/working/run", ignore_errors=True)
print("DONE", os.listdir("/kaggle/working"))
