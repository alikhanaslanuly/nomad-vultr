HARNESS = """import json
import os
import pathlib
import subprocess
import sys

entry = pathlib.Path('/home/user/work/artifact') / os.environ['AIRLOCK_ARTIFACT_ENTRY']
os.chdir(entry.parent)
kind = os.environ['AIRLOCK_ARTIFACT_KIND']
if kind == 'npm':
    data = json.loads(entry.read_text())
    for hook in ('preinstall', 'install', 'postinstall'):
        command = data.get('scripts', {}).get(hook)
        if command:
            result = subprocess.run(['/bin/sh', '-c', command], check=False)
            if result.returncode:
                sys.exit(result.returncode)
else:
    interpreter = {'python': 'python3', 'node': 'node', 'bash': 'bash'}[kind]
    os.execvp(interpreter, [interpreter, entry.name])
"""


def pick(artifact_kind: str) -> dict:
    if artifact_kind not in {"python", "node", "bash", "npm"}:
        raise ValueError("Unsupported artifact kind")
    return {
        "files": [{"path": "work/harness.py", "content": HARNESS}],
        "entrypoint": ["python3", "work/harness.py"],
        "template": artifact_kind,
    }
