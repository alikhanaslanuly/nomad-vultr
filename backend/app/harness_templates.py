BASH_HARNESS = """#!/bin/bash
set +e
cd /home/user/work
export HOME=/home/user
echo "[harness] profile=$PROFILE"
bash artifact/install.sh
echo "[harness] exit=$?"
"""

NPM_HARNESS = """#!/bin/bash
set +e
cd /home/user/work
export HOME=/home/user
for hook in preinstall install postinstall; do
  if grep -q "\\"$hook\\"" artifact/package.json; then
    echo "[harness] hook=$hook"
    cmd=$(python3 -c "import json;print(json.load(open('artifact/package.json'))['scripts'].get('$hook',''))")
    [ -n "$cmd" ] && bash -c "$cmd"
  fi
done
echo "[harness] exit=$?"
"""

PYTHON_HARNESS = """#!/bin/bash
set +e
cd /home/user/work
export HOME=/home/user
python3 artifact/main.py
echo "[harness] exit=$?"
"""


def pick(artifact_kind: str) -> dict:
    """Return {"files": [...], "entrypoint": [...], "template": name}."""
    if artifact_kind == "npm":
        return {"files": [{"path": "work/harness.sh", "content": NPM_HARNESS}],
                "entrypoint": ["bash", "work/harness.sh"], "template": "npm"}
    if artifact_kind == "python":
        return {"files": [{"path": "work/harness.sh", "content": PYTHON_HARNESS}],
                "entrypoint": ["bash", "work/harness.sh"], "template": "python"}
    return {"files": [{"path": "work/harness.sh", "content": BASH_HARNESS}],
            "entrypoint": ["bash", "work/harness.sh"], "template": "bash"}