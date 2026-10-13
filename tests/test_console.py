import os
import sys

import pytest

pytest.importorskip("termios")
import pty
import termios
import tty

from airwaves import sdr


@pytest.fixture
def keyboard(monkeypatch):
	"""Makes stdin a terminal. Bytes written to the returned fd arrive as typed keys."""
	master, slave = pty.openpty()
	with os.fdopen(slave) as stdin:
		monkeypatch.setattr(sys, "stdin", stdin)
		yield master
	os.close(master)


def echo_is_on():
	return bool(termios.tcgetattr(sys.stdin.fileno())[tty.LFLAG] & termios.ECHO)


def test_read_key_returns_a_typed_key(keyboard):
	with sdr.terminal_mode(line_input=False):
		os.write(keyboard, b"w")
		assert sdr.read_key() == "w"


def test_read_key_returns_none_with_no_key(keyboard):
	with sdr.terminal_mode(line_input=False):
		assert sdr.read_key() is None


def test_keys_typed_together_arrive_one_at_a_time(keyboard):
	with sdr.terminal_mode(line_input=False):
		os.write(keyboard, b"ws")
		assert sdr.read_key() == "w"
		assert sdr.read_key() == "s"


def test_read_key_drops_arrow_keys(keyboard):
	# Left arrow ends in D, which must not reach the Shift+D key.
	with sdr.terminal_mode(line_input=False):
		os.write(keyboard, b"\x1b[D")
		assert sdr.read_key() is None
		assert sdr.read_key() is None


def test_read_key_ignores_input_that_is_not_a_terminal(monkeypatch, tmp_path):
	piped = tmp_path / "piped"
	piped.write_text("w")
	with open(piped) as stdin:
		monkeypatch.setattr(sys, "stdin", stdin)
		with sdr.terminal_mode(line_input=False):
			assert sdr.read_key() is None


def test_terminal_mode_turns_echo_off_for_keys_and_on_for_prompts(keyboard):
	assert echo_is_on()
	with sdr.terminal_mode(line_input=False):
		assert not echo_is_on()
		with sdr.terminal_mode(line_input=True):
			assert echo_is_on()
		assert not echo_is_on()
	assert echo_is_on()


def test_set_title_sends_the_title_to_a_terminal(monkeypatch):
	master, slave = pty.openpty()
	with os.fdopen(slave, "w") as stdout:
		monkeypatch.setattr(sys, "stdout", stdout)
		sdr.set_title("93.3 MHz")
		assert os.read(master, 100) == b"\x1b]0;93.3 MHz\x07"
	os.close(master)


def test_set_title_writes_nothing_to_a_file(capsys):
	sdr.set_title("93.3 MHz")
	assert capsys.readouterr().out == ""


def test_get_title_is_empty_where_it_cannot_be_read():
	assert sdr.get_title() == ""
