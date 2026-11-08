import os
import tarfile
import json
import logging
import subprocess
from typing import Optional, Tuple, Dict, Any

log = logging.getLogger(__name__)


class NPMFetcher:
    @staticmethod
    def fetch_npm_package(ref: str, target_dir: str) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Runs `npm pack <ref> --ignore-scripts` to download tarball without executing lifecycle scripts.
        Unpacks it to target_dir/work/package and extracts package.json scripts.
        """
        os.makedirs(target_dir, exist_ok=True)
        try:
            # Safe npm pack with script execution strictly disabled
            cmd = ["npm", "pack", ref, "--ignore-scripts"]
            log.info("Fetching npm package: %s in %s", ref, target_dir)
            proc = subprocess.run(
                cmd,
                cwd=target_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                text=True
            )
            if proc.returncode != 0:
                return False, f"npm pack failed: {proc.stderr}", {}

            tar_name = proc.stdout.strip().split("\n")[-1].strip()
            tar_path = os.path.join(target_dir, tar_name)
            if not os.path.exists(tar_path):
                return False, f"Downloaded tarball not found: {tar_name}", {}

            # Unpack safely
            pkg_extract_dir = os.path.join(target_dir, "package")
            os.makedirs(pkg_extract_dir, exist_ok=True)
            with tarfile.open(tar_path, "r:gz") as tar:
                # safe extraction avoiding path traversal
                for member in tar.getmembers():
                    if member.name.startswith("/") or ".." in member.name:
                        continue
                    tar.extract(member, path=target_dir)

            pkg_json_path = os.path.join(pkg_extract_dir, "package.json")
            scripts = {}
            if os.path.exists(pkg_json_path):
                with open(pkg_json_path, "r", encoding="utf-8") as f:
                    pkg_data = json.load(f)
                    scripts = pkg_data.get("scripts", {})

            return True, tar_path, scripts
        except Exception as e:
            log.error("NPM fetch failed for %s: %s", ref, e)
            return False, str(e), {}

