import base64
import io
import json
import stat
import zipfile

import pytest

from app.artifacts import ArtifactError, prepare_artifact


def archive(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as output:
        for path, content in files.items():
            output.writestr(path, content)
    return base64.b64encode(data.getvalue()).decode()


def test_python_filename_and_type_are_preserved():
    artifact = prepare_artifact("paste", "print('hello')", "script.py")
    assert artifact.filename == artifact.entrypoint == "script.py"
    assert artifact.kind == "python"
    assert artifact.manifest_files()[0]["path"] == "work/artifact/script.py"


def test_zip_files_and_package_lock_are_preserved_without_host_execution():
    data = archive(
        {
            "package.json": json.dumps({"scripts": {"install": "node index.js"}}),
            "index.js": "console.log('test')",
            "package-lock.json": "{}",
        }
    )
    artifact = prepare_artifact("zip", data, "package.zip")
    assert artifact.filename == "package.zip" and artifact.kind == "npm"
    assert set(artifact.files) == {"package.json", "index.js", "package-lock.json"}


@pytest.mark.parametrize(
    "path", ["../../etc/test", "/etc/test", "a/../main.py", "a\\main.py", "C:/test.py"]
)
def test_zip_rejects_unsafe_paths(path):
    with pytest.raises(ArtifactError):
        prepare_artifact("zip", archive({path: "print('test')"}), "input.zip")


def test_zip_rejects_links_duplicates_and_too_many_files():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as output:
        entry = zipfile.ZipInfo("main.py")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        output.writestr(entry, "/etc/test")
    with pytest.raises(ArtifactError):
        prepare_artifact("zip", base64.b64encode(data.getvalue()).decode(), "input.zip")
    with pytest.raises(ArtifactError):
        prepare_artifact(
            "zip", archive({f"{index}.py": "x" for index in range(129)}), "input.zip"
        )


def test_npm_reference_is_explicitly_unavailable():
    with pytest.raises(ArtifactError) as result:
        prepare_artifact("npm", "", "package.json", "left-pad@1.3.0")
    assert (
        result.value.status == 501 and result.value.code == "unsupported_npm_reference"
    )
