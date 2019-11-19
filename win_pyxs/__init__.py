"""
An implementation of pyxs.Connection for the Windows versions of the Xen PV
drivers.
"""

from __future__ import print_function

__all__ = []

import socket
import sys
from time import sleep

try:
    from Queue import Queue
except ImportError:
    from queue import Queue

import backports.socketpair
import pyxs
import pyxs.connection
from pyxs._internal import Op, Packet, NUL
import wmi

sys.coinit_flags = 0

_WMI_SESSION = None


class XenBusConnectionWinPV(pyxs.connection.PacketConnection):
    def __init__(self):
        self.session = None
        self.response_packets = Queue()

        # A socket pair which can be used to mimic the default pyxs behaviour
        # of returning a fileno which can be slected on to check when data is
        # available
        self.r_terminator, self.w_terminator = socket.socketpair()

    def __copy__(self):
        return self.__class__(self.path)

    @property
    def is_connected(self):
        return self.session is not None

    def fileno(self):
        return self.r_terminator.fileno()

    def connect(self, retry=0):
        global _WMI_SESSION

        # Create a WMI Session
        try:
            if not _WMI_SESSION or retry > 0:
                _WMI_SESSION = wmi.WMI(
                    moniker="//./root/wmi", find_classes=False
                )
            xenstore_base = _WMI_SESSION.XenProjectXenStoreBase()[0]
        except Exception:  # WMI can raise all sorts of exceptions
            if retry < 20:
                sleep(5)
                self.connect(retry=(retry + 1))
                return
            else:
                raise pyxs.PyXSError, None, sys.exc_info()[2]

        try:
            sessions = _WMI_SESSION.query((
                "select * from XenProjectXenStoreSession where InstanceName"
                " = 'Xen Interface\\Session_PyxsSession_0'"
            ))
        except Exception:
            sessions = []

        if len(sessions) <= 0:
            session_name = "PyxsSession"
            session_id = xenstore_base.AddSession(Id=session_name)[0]

            wmi_query = (
                "select * from XenProjectXenStoreSession where SessionId"
                " = {id}"
            ).format(id=session_id)

            try:
                sessions = _WMI_SESSION.query(wmi_query)
            except Exception:
                sleep(0.5)

                try:
                    sessions = _WMI_SESSION.query(wmi_query)
                except Exception:
                    raise pyxs.PyXSError, None, sys.exc_info()[2]

        self.session = sessions.pop()

    # Emulate sending the packet directly to the XenStore interface
    # and store the result in response_packet
    def send(self, packet):
        global _WMI_SESSION

        try:
            if not _WMI_SESSION or not self.session:
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

        self.response_packets.put(Packet(
            packet.op, result, packet.rq_id, packet.tx_id
        ))

        # Notify that data is available
        self.w_terminator.sendall(NUL)

    def recv(self):
        self.r_terminator.recv(1)
        return self.response_packets.get(False)

    def close(self, silent=True):
        self.w_terminator.sendall(NUL)

    def __del__(self):
        if self.session:
            print('Ending session')
            self.session.EndSession()

        self.session = None

        self.r_terminator.close()
        self.w_terminator.close()


if __name__ == "__main__":
    con = XenBusConnectionWinPV()
    router = pyxs.Router(con)
    with pyxs.Client(router=router) as client:
        my_uuid = client.read("vm")
        print('My UUID:', my_uuid)
        my_domid = client.read("domid")
        print('My DomID:', my_domid)
        print(client.list("/local/domain/{}".format(my_domid)))
