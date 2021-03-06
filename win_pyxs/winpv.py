"""
win_pyxs.winpv contains an implementation of a pyxs.connection.PacketConnection
which sends the packets over the WMI interface exposed by the WinPV drivers.
Not all xenstore functions are exposed using this WMI interface so this module
is only able to implement those which are available.
"""

from __future__ import print_function

__all__ = ['XenBusConnectionWinPV']

import logging
import socket
import sys
from time import sleep

try:
    from Queue import Queue
except ImportError:
    from queue import Queue

sys.coinit_flags = 0

import backports.socketpair  # pylint: disable=W0611
import pythoncom
import six
import wmi

import pyxs
import pyxs.connection
from pyxs._internal import Op, Packet, NUL

from .exceptions import UnknownSessionError

WMI_CONNECT_RETRY_DELAY = 2
WMI_QUERY_RETRY_DELAY = 0.5
WMI_QUERY_TEMPLATE = (
    "select * from XenProjectXenStoreSession where SessionId = {id}"
)


class XenBusConnectionWinPV(pyxs.connection.PacketConnection):
    """
    An implementation of a pyxs connection which uses the WMI interface
    provided by the WinPV drivers to communicate with the xenstore.
    """

    def __init__(self, xs_session_name="PyxsSession"):
        super(XenBusConnectionWinPV, self).__init__()

        self._logger = logging.getLogger(
            __name__ + '.' + self.__class__.__name__
        )

        self.session = None
        self.session_id = None
        self.session_name = xs_session_name

        self.response_packets = Queue()

        # A socket pair which can be used to mimic the default pyxs behaviour
        # of returning a fileno which can be slected on to check when data is
        # available
        self.r_terminator, self.w_terminator = socket.socketpair()

    def _get_xenstore_session(self, wmi_connect_retry=20):
        # Create a WMI Session
        try:
            wmi_session = wmi.WMI(moniker="//./root/wmi", find_classes=False)
            xenstore_base = wmi_session.XenProjectXenStoreBase()[0]
        except Exception as exc:  # WMI can raise all sorts of exceptions
            if wmi_connect_retry > 0:
                self._logger.error(
                    'Error connecting to WMI (will retry): %s', exc
                )

                sleep(WMI_CONNECT_RETRY_DELAY)
                return self._get_xenstore_session(
                    wmi_connect_retry=(wmi_connect_retry - 1)
                )

            self._logger.exception('Failed connecting to WMI:')
            six.raise_from(
                pyxs.PyXSError("Initialising WMI connection failed"), exc
            )

        if self.session_id is None:
            self._logger.debug('Adding a new XenProjectXenStoreSession')
            self.session_id = xenstore_base.AddSession(Id=self.session_name)[0]

        wmi_query = WMI_QUERY_TEMPLATE.format(id=self.session_id)

        try:
            sessions = wmi_session.query(wmi_query)
        except Exception:
            self._logger.warning((
                'Failed finding the XenProjectXenStoreSession with '
                'SessionId=%s (will retry)'
            ), self.session_id)
            sleep(WMI_QUERY_RETRY_DELAY)

            try:
                sessions = wmi_session.query(wmi_query)
            except Exception as exc:
                self._logger.exception((
                    'Failed finding the XenProjectXenStoreSession with '
                    'SessionId=%s:'
                ), self.session_id)

                six.raise_from(
                    pyxs.PyXSError("Unable to query for WMI session"), exc
                )

        try:
            return sessions[0]
        except IndexError:
            raise UnknownSessionError(
                "No session with SessionId={}".format(self.session_id)
            )

    def __copy__(self):
        return self.__class__()

    @property
    def is_connected(self):
        """
        Return whether this connection is currently active & connected to
        xenstore via the XenProjectXenStoreSession.
        """
        return self.session is not None

    def fileno(self):
        """
        Return the fileno from the reader half of the socket pair. This way
        when selecting on this object it will return when data becomes
        available.
        """
        return self.r_terminator.fileno()

    def connect(self, wmi_connect_retry=20):
        """
        Connect the WMI session ready for commands to be sent using this
        connection. Because there can be connection issues here this method
        will retry the connection by default. This can be disabled by passing
        wmi_connect_retry=0 and the number of retries is configurable through
        this parameter.
        """
        if self.is_connected:
            return

        if not self.response_packets:
            self.response_packets = Queue()

        if not self.r_terminator or not self.w_terminator:
            self.r_terminator, self.w_terminator = socket.socketpair()

        self.session = self._get_xenstore_session(
            wmi_connect_retry=wmi_connect_retry
        )

    def send(self, packet):
        """
        Emulates sending a packet to xenstore by calling the equivalent WMI
        method on the XenProjectXenStoreSession WMI object. Only a few
        operations (READ, WRITE, RM, DIRECTORY) because that is all that is
        available using the WMI interface. Because the result of the WMI call
        is the equivalent of the packet received from xenstore in the Linux
        device/socket code this method stores it in a FIFO queue for later
        to be returned by the recv() method.
        """
        try:
            if not self.session:
                self._logger.debug(
                    'Attempt to send without a connection - connecting now'
                )
                self.connect()
        except wmi.x_wmi as exc:
            six.raise_from(pyxs.PyXSError, exc)

        self._logger.debug('Sending packet to xenstore: %s', packet)

        if packet.op == Op.READ:
            try:
                result = self.session.GetValue(packet.payload)[0]
            except wmi.x_wmi as exc:
                six.raise_from(
                    pyxs.PyXSError("session.GetValue call failed"), exc
                )
        elif packet.op == Op.WRITE:
            payload = packet.payload.split('\x00', 1)

            try:
                self.session.SetValue(payload[0], payload[1])
            except wmi.x_wmi as exc:
                six.raise_from(
                    pyxs.PyXSError("session.SetValue call failed"), exc
                )

            result = "OK"
        elif packet.op == Op.RM:
            try:
                self.session.RemoveValue(packet.payload)[0]
            except wmi.x_wmi as exc:
                six.raise_from(
                    pyxs.PyXSError("session.RemoveValue call failed"), exc
                )

            result = "OK"
        elif packet.op == Op.DIRECTORY:
            try:
                result = self.session.GetChildren(packet.payload)[0].childNodes
            except wmi.x_wmi as exc:
                six.raise_from(
                    pyxs.PyXSError("session.GetChildren call failed"), exc
                )

            result = "\x00".join(result)
        else:
            raise NotImplementedError(
                "Unsupported XenStore Action ({x})".format(x=packet.op)
            )

        self.response_packets.put(
            Packet(packet.op, result, packet.rq_id, packet.tx_id)
        )

        # Notify that data is available
        self.w_terminator.sendall(NUL)

    def recv(self):
        """
        Receive a packet from xenstore. This method does very little because
        the send method is forced to receive the response (it is the result of
        the WMI call) so it is already written to a queue for this method to
        read.
        """
        self.r_terminator.recv(1)
        return self.response_packets.get(False)

    def close(self, silent=True):  # pylint disable=W0613
        """
        Close the sockets used to notify pyxs when data is ready & cleanup the
        WMI session used to query xenstore.
        """
        self._logger.debug('Closing XenProjectXenStoreSession using WMI')
        pythoncom.CoInitialize()
        session = self._get_xenstore_session()
        session.EndSession()
        self.session = None
        pythoncom.CoUninitialize()

        self._logger.debug(
            'Shutting down socket used to notify Router of readiness'
        )
        self.r_terminator.shutdown(socket.SHUT_RDWR)

        self.r_terminator.close()
        self.w_terminator.close()

        self.response_packets = None
        self.r_terminator = self.w_terminator = None
