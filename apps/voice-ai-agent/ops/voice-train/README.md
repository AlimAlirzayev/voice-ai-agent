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

## Automated
`/usr/local/bin/divan-voice-train` (copy in this folder) runs the whole loop and reports through the
Divan bot; cron 02:30 UTC daily, it starts only when recordings reach GOAL_MINUTES and grew since the
last run. `--force --epochs N` to run by hand.

## Smoke run 2026-09-26 (1.5 min of recordings, 5 epochs)
Pipeline verified end to end: offline install, warmstart from tr_TR dfki, val_mel 0.60 -> 0.50,
63 MB ONNX, CPU inference RTF 0.24. Benchmark: WER 0.43 (Microsoft 0.11), likeness 0.65
(Microsoft 0.46) -> gate FAIL, correctly not installed. Quality needs the 30 minutes.
Kaggle traps met on the way: no kernel internet; torch 2.6 weights_only vs PosixPath in the
old checkpoint; old hyper-parameters and callback state (val_mos) in the checkpoint; --config
callbacks are appended, not swapped; dynamo ONNX export trips the VITS spline (use dynamo=False);
the kaggle CLI output download is killed on an 845 MB file (only .onnx/.json/.log leave the kernel).
