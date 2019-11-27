import tempfile
import unittest

import mock
from win32file import CreateFile

from win_pyxs import XenBusConnectionGPLPV

EXAMPLE_DEVICE_PATH = (
    r'\\?\pci#ven_5853&dev_0001&subsys_00015853&rev_01#3&267a616a&1&10#'
    r'{14ce175a-3ee2-4fae-9252-00dbd84f018e}\xenbus'
)


class GPLPVTester(unittest.TestCase):

    def setUp(self):
        self.connection = XenBusConnectionGPLPV()

    def test_connect(self):
        with mock.patch('win_pyxs.gplpv.XenBusTransportGPLPV') as transport_m:
            with tempfile.TemporaryFile() as temp_file:
                transport_m.return_value._get_device_path.return_value = temp_file

            self.connection.connect()
            self.connection.close()
