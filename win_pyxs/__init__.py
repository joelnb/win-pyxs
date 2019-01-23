"""
An implementation of pyxs.Connection for the Windows versions of the Xen PV
drivers.
"""

from __future__ import print_function

__all__ = []

import sys

import backports.socketpair
import pyxs
import pyxs.connection
import wmi

sys.coinit_flags = 0

_wmiSession = None


class XenBusConnectionWinWINPV(pyxs.connection.PacketConnection):
    session = None
    response_packet = None

    def __init__(self):
        pass

    def __copy__(self):
        return self.__class__(self.path)

    def connect(self, retry=0):
        global _wmiSession

        # Create a WMI Session
        try:
            if not _wmiSession or retry > 0:
                _wmiSession = wmi.WMI(
                    moniker="//./root/wmi", find_classes=False
                )
            xenStoreBase = _wmiSession.XenProjectXenStoreBase()[0]
        except Exception:  # WMI can raise all sorts of exceptions
            if retry < 20:
                sleep(5)
                self.connect(retry=(retry + 1))
                return
            else:
                raise pyxs.PyXSError, None, sys.exc_info()[2]

        try:
            sessions = _wmiSession.query((
                "select * from XenProjectXenStoreSession where InstanceName"
                " = 'Xen Interface\\Session_PyxsSession_0'"
            ))
        except Exception:
            sessions = []

        if len(sessions) <= 0:
            session_name = "PyxsSession"
            session_id = xenStoreBase.AddSession(Id=session_name)[0]

            wmi_query = (
                "select * from XenProjectXenStoreSession where SessionId"
                " = {id}"
            ).format(id=session_id)

            try:
                sessions = _wmiSession.query(wmi_query)
            except Exception:
                sleep(0.5)

                try:
                    sessions = _wmiSession.query(wmi_query)
                except Exception:
                    raise pyxs.PyXSError, None, sys.exc_info()[2]

        self.session = sessions.pop()

    # Emulate sending the packet directly to the XenStore interface
    # and store the result in response_packet
    def send(self, packet):
        global _wmiSession

        try:
            if not _wmiSession or not self.session:
                self.connect()
        except wmi.x_wmi:
            raise pyxs.PyXSError, None, sys.exc_info()[2]

        if packet.op == Op.READ:
            try:
                result = self.session.GetValue(packet.payload)[0]
            except wmi.x_wmi:
                raise pyxs.PyXSError, None, sys.exc_info()[2]
        elif packet.op == Op.WRITE:
            try:
                payload = packet.payload.split('\x00', 1)
                self.session.SetValue(payload[0], payload[1])
            except wmi.x_wmi:
                raise pyxs.PyXSError, None, sys.exc_info()[2]
            result = "OK"
        elif packet.op == Op.RM:
            try:
                self.session.RemoveValue(packet.payload)[0]
            except wmi.x_wmi:
                raise pyxs.PyXSError, None, sys.exc_info()[2]
            result = "OK"
        elif packet.op == Op.DIRECTORY:
            try:
                result = self.session.GetChildren(packet.payload)[0].childNodes
                result = "\x00".join(result)
            except wmi.x_wmi:
                raise pyxs.PyXSError, None, sys.exc_info()[2]
        else:
            raise Exception(
                "Unsupported XenStore Action ({x})".format(x=packet.op)
            )

        self.response_packet = Packet(
            packet.op, result, packet.rq_id, packet.tx_id
        )

    def recv(self):
        return self.response_packet

    def disconnect(self, silent=True):
        self.session = None


if __name__ == "__main__":
    con = XenBusConnectionWinWINPV()
    router = pyxs.Router(con)
    client = pyxs.Client(router=router)
