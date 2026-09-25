"""Fine-tune a Piper (VITS) voice on the owner's recordings. Runs on a Kaggle T4,
fully OFFLINE (the account has no kernel internet), from two private datasets:

  alimalirzayev/divan-owner-voice   wavs/ + metadata.csv  (build_voice_dataset.py)
  alimalirzayev/divan-voice-deps    wheels/ (piper-tts[train] minus torch), base/
                                    (rhasspy tr_TR dfki medium ckpt), src/core.pyx

piper-tts bundles espeak-ng and its `az` voice, so no apt is needed.
Output: /kaggle/working/az_AZ-owner-medium.onnx (+ .onnx.json), last.ckpt.
EXTRA_EPOCHS: small for a smoke run, ~1000+ for the real one.
"""
import glob, os, shutil, subprocess, sys

EXTRA_EPOCHS = int(os.environ.get("EXTRA_EPOCHS", "__EXTRA__"))
BASE_EPOCH = 5679
sh = lambda c: subprocess.run(c, shell=True, check=True)
find = lambda pat: glob.glob(f"/kaggle/input/**/{pat}", recursive=True)

wheels = os.path.dirname(find("wheels/piper_tts-*.whl")[0])
sh(f"{sys.executable} -m pip install -q --no-index --find-links {wheels} 'piper-tts[train]'")
import piper  # noqa: E402
ma = os.path.join(os.path.dirname(piper.__file__), "train/vits/monotonic_align")
shutil.copy(find("src/core.pyx")[0], ma)
sh(f"cd {ma} && mkdir -p monotonic_align && cythonize -q -i core.pyx && mv core*.so monotonic_align/")

base = find("base/**/*.ckpt")[0]
data = find("metadata.csv")[0]
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
