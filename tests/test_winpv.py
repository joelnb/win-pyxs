import unittest

import mock

from win_pyxs import XenBusConnectionWinPV


class WinPVTester(unittest.TestCase):

    def setUp(self):
        self.base_mock = mock.MagicMock(name='wmi.WMI.XenProjectXenStoreBase')
        self.base_mock.AddSession.return_value = [3]

        self.session_mock = mock.MagicMock(
            name='wmi.WMI.XenProjectXenStoreBase.AddSession'
        )

        self.connection_params = [{}, {'xs_session_name': 'CUSTOM_session'}]
        self.connections = []
        for kwargs in self.connection_params:
            self.connections.append(XenBusConnectionWinPV(**kwargs))

        self.wmi_mock = mock.MagicMock(name='wmi.WMI')
        self.wmi_mock.return_value.XenProjectXenStoreBase.return_value = [
            self.base_mock
        ]
        self.wmi_mock.return_value.query.return_value = [self.session_mock]

    def test_connect(self):
        with mock.patch('wmi.WMI', new=self.wmi_mock) as wmi_mock:
            for idx, connection in enumerate(self.connections):
                connection.connect()

                wmi_mock.assert_called_with(
                    moniker="//./root/wmi", find_classes=False
                )
                self.base_mock.AddSession.assert_called_with(
                    Id=self.connection_params[idx].
                    get('xs_session_name', 'PyxsSession')
                )
                self.assertEqual(connection.session, self.session_mock)

                connection.close()

                self.session_mock.EndSession.assert_called_with()
                self.assertEqual(connection.session, None)
