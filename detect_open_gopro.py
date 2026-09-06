"""Compatibility entry point; the working competition script owns the engine."""
from importlib import import_module

_engine = import_module("中興AI競賽.detect_open_gopro")
DEFAULT_MODEL = _engine.DEFAULT_MODEL
DEFAULT_TRACKER = _engine.DEFAULT_TRACKER
DEFAULT_ARDUINO_PORT = _engine.DEFAULT_ARDUINO_PORT
DEFAULT_GOPRO_SERIAL = _engine.DEFAULT_GOPRO_SERIAL
GOPRO_WEBCAM_RESOLUTION = _engine.GOPRO_WEBCAM_RESOLUTION
GOPRO_WEBCAM_FOV = _engine.GOPRO_WEBCAM_FOV
LANE_RANGES = _engine.LANE_RANGES
resolve_ng_priority_pins = _engine.resolve_ng_priority_pins
run_detection = _engine.run_detection

if __name__ == "__main__":
    run_detection()
