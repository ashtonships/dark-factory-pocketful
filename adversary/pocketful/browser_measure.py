import os
import subprocess


if __name__ == "__main__":
    env = dict(os.environ, TMPDIR="/tmp")
    result = subprocess.run(["sh", "run-drill.sh"], env=env)
    raise SystemExit(result.returncode)
