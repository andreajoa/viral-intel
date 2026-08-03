"""Lean private-cloud entrypoint for Streamlit Community Cloud."""

from __future__ import annotations

import os
import runpy

os.environ["ENABLE_TRANSCRIPTION"] = "false"
os.environ["EPHEMERAL_MODE"] = "true"
os.environ["MAX_UPLOAD_MB"] = "100"
os.environ["COMMAND_TIMEOUT_SECONDS"] = "120"

runpy.run_module("app.ui.dashboard", run_name="__main__")
