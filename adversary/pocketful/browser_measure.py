import os
from pathlib import Path
import subprocess


if __name__ == "__main__":
    env = dict(os.environ, TMPDIR="/tmp")
    env["NODE_OPTIONS"] = "--require " + str(Path(__file__).with_name("chrome_cleanup.js"))
    result = subprocess.run(["sh", "run-drill.sh"], env=env)
    raise SystemExit(result.returncode)
