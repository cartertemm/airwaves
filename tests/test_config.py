from airwaves import config


def test_percent_sign_in_the_file_reads_as_text():
	with open(config.FILE_NAME, "w", encoding="utf-8") as file:
		file.write("[presets]\n1 = 100% jazz\n")
	assert config.presets() == {1: "100% jazz"}


def test_percent_sign_saves_and_reads_back():
	config.save("1", "100% jazz", config.PRESETS)
	config.save("2", "50%(off)", config.PRESETS)
	assert config.presets() == {1: "100% jazz", 2: "50%(off)"}
