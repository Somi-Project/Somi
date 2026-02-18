import sounddevice as sd


def list_devices():
    return sd.query_devices()
