import pytest

from airwaves import config


def test_percent_sign_in_the_file_reads_as_text():
	with open(config.FILE_NAME, "w", encoding="utf-8") as file:
		file.write("[presets]\n1 = 100% jazz\n")
	assert config.presets() == {1: "100% jazz"}


def test_percent_sign_saves_and_reads_back():
	config.save("1", "100% jazz", config.PRESETS)
	config.save("2", "50%(off)", config.PRESETS)
	assert config.presets() == {1: "100% jazz", 2: "50%(off)"}


DAMAGED_FILES = (
	"[presets]\n1 = jazz\n1 = rock\n2 = news\n",
	"volume = 5\n[presets]\n1 = jazz\n",
	"[presets]\n1 = jazz\njunk\n2 = news\n",
)


@pytest.mark.parametrize("text", DAMAGED_FILES)
def test_a_damaged_file_is_left_as_it_is(text):
	with open(config.FILE_NAME, "w", encoding="utf-8") as file:
		file.write(text)
	with pytest.raises(OSError, match="line"):
		config.save("volume", 30)
	with pytest.raises(OSError, match="line"):
		config.remove("1", config.PRESETS)
	with open(config.FILE_NAME, encoding="utf-8") as file:
		assert file.read() == text


def test_a_damaged_file_still_reads_up_to_the_error():
	with open(config.FILE_NAME, "w", encoding="utf-8") as file:
		file.write(DAMAGED_FILES[0])
	assert config.presets() == {1: "jazz"}
