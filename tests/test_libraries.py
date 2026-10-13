from airwaves.libraries import library_path

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
