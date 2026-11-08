import base64
import binascii
import hashlib
import io
import json
import re
import stat
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import PurePosixPath


MAX_ARCHIVE = 2 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024
MAX_FILES = 128


class ArtifactError(ValueError):
    def __init__(self, message: str, code: str = "invalid_artifact", status: int = 422):
        super().__init__(message)
        self.code, self.status = code, status


def safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or len(value) > 240
        or "\\" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(ord(char) < 32 for char in value)
        or ":" in value
    ):
        raise ArtifactError("Artifact filename/path is forbidden")
    return value


def kind_from_filename(filename: str, content: bytes) -> str:
    suffix = PurePosixPath(filename).suffix.lower()
    if PurePosixPath(filename).name == "package.json":
        try:
            data = json.loads(content)
            scripts = data.get("scripts", {})
            if not isinstance(scripts, dict) or not all(
                isinstance(value, str) for value in scripts.values()
            ):
                raise ValueError("Invalid scripts")
            if not any(
                scripts.get(hook) for hook in ("preinstall", "install", "postinstall")
            ):
                raise ValueError("No lifecycle scripts")
        except (ValueError, AttributeError, TypeError, UnicodeDecodeError):
            raise ArtifactError(
                "package.json must contain a supported lifecycle script"
            ) from None
        return "npm"
    if suffix == ".py" or content.startswith(
        (b"#!/usr/bin/env python", b"#!/usr/bin/python")
    ):
        return "python"
    if suffix in {".js", ".cjs", ".mjs"}:
        return "node"
    if suffix in {".sh", ".bash"} or content.startswith((b"#!/bin/sh", b"#!/bin/bash")):
        return "bash"
    if suffix in {"", ".txt"} and re.match(
        rb"\s*(?:import |from |def |class )", content
    ):
        return "python"
    if suffix in {"", ".txt"} and b"\x00" not in content:
        return "bash"
    raise ArtifactError(
        "Unsupported entrypoint; use Python, JavaScript, shell, or a package ZIP"
    )


@dataclass
class Artifact:
    filename: str
    entrypoint: str
    kind: str
    files: dict[str, bytes]
    sha256: str

    def manifest_files(self) -> list[dict]:
        return [
            {
                "path": f"work/artifact/{path}",
                "content_b64": base64.b64encode(content).decode(),
            }
            for path, content in self.files.items()
        ]

    def source_files(self) -> list[dict]:
        files = []
        languages = {
            ".py": "python",
            ".sh": "bash",
            ".js": "javascript",
            ".json": "json",
        }
        for path, content in self.files.items():
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if "\x00" not in text:
                files.append(
                    {
                        "path": path,
                        "content": text,
                        "language": languages.get(PurePosixPath(path).suffix, "text"),
                    }
                )
        return files


def prepare_artifact(
    input_type: str, content: str, filename: str, ref: str | None = None
) -> Artifact:
    filename = safe_path(filename)
    if input_type == "npm":
        raise ArtifactError(
            "Registry/npm references are unavailable. Submit a ZIP containing package.json and optional lockfiles; hooks run only inside the sandbox.",
            "unsupported_npm_reference",
            501,
        )
    if input_type == "paste":
        raw = content.encode("utf-8")
        if not raw or len(raw) > MAX_FILE:
            raise ArtifactError("Source text is empty or exceeds 2 MiB")
        return Artifact(
            filename,
            filename,
            kind_from_filename(filename, raw),
            {filename: raw},
            hashlib.sha256(raw).hexdigest(),
        )
    if input_type != "zip":
        raise ArtifactError("Unsupported artifact format")
    try:
        raw = base64.b64decode(content, validate=True)
    except (ValueError, binascii.Error):
        raise ArtifactError("ZIP content must be valid base64") from None
    if len(raw) > MAX_ARCHIVE:
        raise ArtifactError("ZIP exceeds 2 MiB compressed limit")
    files: dict[str, bytes] = {}
    names = set()
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if len(archive.infolist()) > MAX_FILES:
                raise ArtifactError("ZIP has too many members")
            for entry in archive.infolist():
                path = safe_path(entry.orig_filename.rstrip("/"))
                mode = entry.external_attr >> 16
                if mode and stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise ArtifactError("ZIP links and special files are forbidden")
                if path.casefold() in names:
                    raise ArtifactError("ZIP has duplicate or ambiguous paths")
                names.add(path.casefold())
                if entry.is_dir():
                    continue
                total += entry.file_size
                if (
                    entry.flag_bits & 1
                    or entry.file_size > MAX_FILE
                    or total > MAX_TOTAL
                    or entry.file_size > max(1024, entry.compress_size * 200)
                ):
                    raise ArtifactError(
                        "ZIP exceeds extraction limits or contains encrypted data"
                    )
                content_bytes = archive.read(entry)
                if len(content_bytes) != entry.file_size:
                    raise ArtifactError("ZIP member size mismatch")
                files[path] = content_bytes
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, zlib.error):
        raise ArtifactError("Invalid or unsupported ZIP archive") from None
    if not files:
        raise ArtifactError("ZIP contains no regular files")
    for path in files:
        if any(str(parent) in files for parent in PurePosixPath(path).parents):
            raise ArtifactError("ZIP file/directory path collision")
    candidates = [path for path in files if PurePosixPath(path).name == "package.json"]
    if not candidates:
        candidates = [
            path
            for path in files
            if PurePosixPath(path).name
            in {"main.py", "index.js", "main.js", "install.sh"}
        ]
    if not candidates and len(files) == 1:
        candidates = list(files)
    if len(candidates) != 1:
        raise ArtifactError(
            "ZIP requires one unambiguous main.py, index.js, install.sh, or package.json entrypoint"
        )
    entry = candidates[0]
    return Artifact(
        filename,
        entry,
        kind_from_filename(entry, files[entry]),
        files,
        hashlib.sha256(raw).hexdigest(),
    )
