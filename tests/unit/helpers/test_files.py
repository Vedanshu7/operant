import pathlib

import pydantic
import pytest

import operant.helpers.files as files

# #############################################################################
# Doc
# #############################################################################


class Doc(pydantic.BaseModel):
    name: str
    count: int = 0


def test_write_model_is_atomic_and_round_trips(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "nested" / "doc.json"
    files.write_model(path, Doc(name="a", count=2))
    assert files.read_model(path, Doc) == Doc(name="a", count=2)
    assert not path.with_name(".doc.json.tmp").exists()
    assert path.read_text().endswith("\n")


def test_write_json_and_read_json(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "plain.json"
    files.write_json(path, {"b": 1, "a": [1, 2]})
    assert files.read_json(path) == {"b": 1, "a": [1, 2]}


def test_locked_serialises_read_modify_write(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "counter.json"
    files.write_json(path, {"n": 0})
    with files.locked(path):
        doc = files.read_json(path)
        files.write_json(path, {"n": doc["n"] + 1})
    assert files.read_json(path) == {"n": 1}
    assert path.with_name(".counter.json.lock").exists()


def test_locked_times_out_when_held(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "held.json"
    with (
        files.locked(path),
        pytest.raises(files.filelock.Timeout),
        files.locked(path, timeout_s=0.05),
    ):
        pass
