import subprocess
import sys

import pytest

import airwaves
from airwaves import sdr


def test_receiver_api_is_on_the_package():
	assert airwaves.Receiver is sdr.Receiver
	assert airwaves.list_devices is sdr.list_devices
	assert airwaves.FM is sdr.FM


def test_unknown_name_raises_attribute_error():
	with pytest.raises(AttributeError):
		airwaves.no_such_name


def test_directory_tools_do_not_load_the_receiver():
	code = "import sys, airwaves.tunein; print('airwaves.sdr' in sys.modules)"
	result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
	assert result.stdout.strip() == "False"
