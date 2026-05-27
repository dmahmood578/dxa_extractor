#!/usr/bin/env python3
"""
Legacy wrapper — delegates to the unified master runner.
Equivalent: python scripts/run_full_pipeline.py --step paddle
"""
import subprocess, sys
print("[legacy] Delegating to run_full_pipeline.py --step paddle")
sys.exit(subprocess.run([sys.executable, "scripts/run_full_pipeline.py", "--step", "paddle"]).returncode)
