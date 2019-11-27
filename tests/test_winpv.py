import unittest

import mock

from win_pyxs import XenBusConnectionWinPV


class WinPVTester(unittest.TestCase):

    @mock.patch('wmi.WMI')
    def test_connect(self, wmi_mock):
        base_mock = mock.MagicMock(name='wmi.WMI.XenProjectXenStoreBase')
        base_mock.AddSession.return_value = [3]

        session_mock = mock.MagicMock(
            name='wmi.WMI.XenProjectXenStoreBase.AddSession'
        )

        wmi_mock.return_value.XenProjectXenStoreBase.return_value = [base_mock]
        wmi_mock.return_value.query.return_value = [session_mock]

        connection = XenBusConnectionWinPV()
        connection.connect()

        wmi_mock.assert_called_with(moniker="//./root/wmi", find_classes=False)
        base_mock.AddSession.assert_called_with(Id="PyxsSession")

        self.assertEqual(connection.session, session_mock)
