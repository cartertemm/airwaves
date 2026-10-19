import pytest

from airwaves import libraries
from airwaves.libraries import library_path, load_library

NAME = "libexample.dylib"


def test_first_folder_with_the_library_wins(tmp_path):
	first = tmp_path / "first"
	second = tmp_path / "second"
	first.mkdir()
	second.mkdir()
	folders = (str(first), str(second))
	(second / NAME).touch()
	assert library_path(NAME, folders) == str(second / NAME)
	(first / NAME).touch()
	assert library_path(NAME, folders) == str(first / NAME)


def test_bare_name_when_no_folder_has_the_library(tmp_path):
	assert library_path(NAME, (str(tmp_path),)) == NAME


@pytest.fixture
def loads(monkeypatch):
	"""Makes ctypes.CDLL load only the paths in the returned set, and records each path it tried."""
	loadable = set()
	tried = []

	def fake_cdll(path):
		tried.append(path)
		if path not in loadable:
			raise OSError(path)
		return path

	monkeypatch.setattr(libraries.ctypes, "CDLL", fake_cdll)
	return loadable, tried


def test_load_library_returns_the_first_name_that_loads(loads, tmp_path):
	loadable, tried = loads
	loadable.add("second.so")
	assert load_library(("first.so", "second.so", "third.so"), (str(tmp_path),)) == "second.so"
	assert tried == ["first.so", "second.so"]


def test_load_library_tries_the_copy_in_folders(loads, tmp_path):
	loadable, tried = loads
	(tmp_path / NAME).touch()
	loadable.add(str(tmp_path / NAME))
	assert load_library((NAME,), (str(tmp_path),)) == str(tmp_path / NAME)


def test_load_library_returns_none_when_nothing_loads(loads, tmp_path):
	assert load_library(("first.so", "second.so"), (str(tmp_path),)) is None
