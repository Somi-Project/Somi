# Piper Voices

Place Piper voice files under `models/voices/`.

Required files per voice:
- `*.onnx`
- matching `*.onnx.json`

Default paths configured in `config/settings.py`:
- `PIPER_MODEL_PATH = models/voices/en_US-lessac-medium.onnx`
- `PIPER_CONFIG_PATH = models/voices/en_US-lessac-medium.onnx.json`
