"""One-batch CPU training/render check. Uses synthetic audio and never contacts a pedal."""

import argparse
import json
import os
import platform
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("portable", type=Path)
parser.add_argument("work", type=Path)
args = parser.parse_args()
root = args.portable.resolve(strict=True)
work = args.work.resolve()
work.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(root / "tools"))

import numpy as np
import soundfile as sf
from nam2zoom import adapt
from nam2zoom.compact import inspect

rate = 44100
audio = 0.1 * np.sin(np.arange(rate * 2) * (2 * np.pi * 440 / rate))
dry, wet = work / "dry.wav", work / "wet.wav"
sf.write(dry, audio, rate, subtype="FLOAT")
sf.write(wet, audio * 0.5, rate, subtype="FLOAT")
adapt.VALIDATION_SECONDS = 0.25
data, model, learning = adapt.prepare_configs(dry, wet, work, 1)
config = json.loads(learning.read_text())
config["train_dataloader"].update(batch_size=2, drop_last=False)
config["trainer"].update(accelerator="cpu", limit_train_batches=1,
                         limit_val_batches=1, num_sanity_val_steps=0)
learning.write_text(json.dumps(config))
training = work / "training"
training.mkdir()
env = os.environ.copy()
env.update(MPLBACKEND="Agg", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2",
           NAM2ZOOM_TEXT_PROGRESS="1", PYTHONUNBUFFERED="1",
           MPLCONFIGDIR=str(work / "mpl-cache"))
subprocess.run([sys.executable, "-m", "nam.cli", str(data), str(model),
                str(learning), str(training), "--no-show", "--no-plots"],
               env=env, check=True)
exports = list(training.glob("*/model.nam"))
if len(exports) != 1:
    raise RuntimeError("training did not export exactly one NAM")
inspect(json.loads(exports[0].read_text()))
rendered = work / "rendered.wav"
renderer_name = "core_render.exe" if platform.system() == "Windows" else "core_render"
subprocess.run([str(root / "reference/nam_a2/build-core-ninja" / renderer_name),
                str(exports[0]), str(dry), str(rendered)], check=True)
output, output_rate = sf.read(rendered)
assert output_rate == rate and len(output) == len(audio) and np.isfinite(output).all()
print("Portable CPU training, student shape, and native rendering: PASS")
