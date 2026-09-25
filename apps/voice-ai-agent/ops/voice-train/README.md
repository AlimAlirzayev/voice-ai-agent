# Owner voice fine-tune (Kaggle T4, offline)

1. `.venv/bin/python scripts/build_voice_dataset.py --out /opt/divan/voice-dataset`
2. `kaggle datasets version -p /opt/divan/voice-dataset -r zip -m "<n> min"` (dataset alimalirzayev/divan-owner-voice)
3. Deps dataset alimalirzayev/divan-voice-deps (built once): `pip download "piper-tts[train]"` wheels
   minus torch/nvidia/triton, the rhasspy tr_TR dfki medium checkpoint under base/, and
   piper1-gpl `core.pyx` under src/ (the wheel ships no Cython source).
4. Push this kernel with `__EXTRA__` replaced (5 = smoke, 1000+ = real run); the account has no
   kernel internet, so everything comes from the two datasets.
5. `kaggle kernels output` → copy the .onnx/.onnx.json to data/voices/owner.onnx(.json) → run
   `python -m app.evals.voice_bench --engines edge,owner-model`; it goes live only if the gate passes.
