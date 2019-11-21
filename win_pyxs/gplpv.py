"""
win_pyxs.gplpv contains an implementation of a pyxs.connection.PacketConnection
which sends the packets over the PCI device exposed by the GPLPV drivers for
Windows.
"""

from __future__ import print_function

__all__ = ['XenBusConnectionGPLPV']

import ctypes
from ctypes.wintypes import HANDLE
from ctypes.wintypes import BOOL
from ctypes.wintypes import HWND
from ctypes.wintypes import DWORD
from ctypes.wintypes import WORD
from ctypes.wintypes import LONG
from ctypes.wintypes import ULONG
from ctypes.wintypes import LPCSTR
from ctypes.wintypes import HKEY
from ctypes.wintypes import BYTE
import logging
import socket

import backports.socketpair
import six
from win32file import CreateFile, CloseHandle, ReadFile, WriteFile
from win32file import (
    FILE_GENERIC_READ, FILE_GENERIC_WRITE, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL
)

import pyxs.connection
from pyxs._internal import NUL

from .exceptions import GPLPVDeviceOpenError, GPLPVDriverError

_winDevicePath = None


class XenBusConnectionGPLPV(pyxs.connection.PacketConnection):
    """
    A pyxs.PacketConnection which communicates with xenstore over the PCI
    device exposed by the GPLPV drivers on Windows. The interface of this
    driver is very similar to the ones on Linux (direct reads/writes to a
    file-like object) so we reuse most of the PacketConnection class and leave
    the implementation detail to the XenBusTransportGPLPV.
    """

    def create_transport(self):
        """
        Initialises a new instance of XenBusTransportGPLPV to communicate with
        xenstore using the GPLPV drivers on Windows.
        """
        return XenBusTransportGPLPV()

    def recv(self):
        """
        This version of recv simply wraps the version from the superclass to
        ensure that a second recv on the XenBusTransportGPLPV is performed
        even for packets where no data actually needed to be read from
        xenstore. Because the read is of 0 length no actual access to the
        device will be performed but the sends and recvs will tally up
        correctly which is important to ensure we do not cause a deadlock when
        reading the file.
        """
        packet = super(XenBusConnectionGPLPV, self).recv()
        if not packet.payload:
            self.transport.recv(0)
        return packet


class XenBusTransportGPLPV(object):
    """
    A transport for pyxs which communicates with xenstore using the PCI device
    exposed by the GPLPV drivers for Windows. The PCI device is a file-like
    object which can only be written to/read from using Windows APIs. Despite
    the alternate APIs the goal is to keep things as similar as possible to the
    equivalent transports in pyxs. The major limitation preventing this is that
    it is not possible to use select on the file-like objects used here (as
    select on Windows can only be used on sockets) so a less-optimal way
    involving a socketpair has been used instead.
    """

    def __init__(self):
        global _winDevicePath

        self._logger = logging.getLogger(
            __name__ + '.' + self.__class__.__name__
        )

        self.fd = None
        self.notify = False

        # A socket pair which can be used to mimic the default pyxs behaviour
        # of returning a fileno which can be slected on to check when data is
        # available
        self.r_terminator, self.w_terminator = socket.socketpair()

        # Once the windows device path is learned once reuse it otherwise
        # ctypes.POINTER() for the same structure leaks memory. Although
        # this can be reclaimed with ctypes._reset_cache() this is poking
        # at the internals of ctypes which doesn't seem to be a good idea.
        if _winDevicePath:
            self.path = _winDevicePath
            self._open_device()
            return

        # Determine self.path using some magic Windows code which is derived
        # from:
        #   http://pydoc.net/Python/pyserial/2.6/serial.tools.list_ports_windows/.
        # The equivalent C from The GPLPV driver source can be found in
        # get_xen_interface_path() of shutdownmon:
        #   http://xenbits.xensource.com/ext/win-pvdrivers/file/896402519f15/shutdownmon/shutdownmon.c

        DIGCF_PRESENT = 2
        DIGCF_DEVICEINTERFACE = 16
        NULL = None
        ERROR_SUCCESS = 0
        ERROR_INSUFFICIENT_BUFFER = 122
        ERROR_NO_MORE_ITEMS = 259

        HDEVINFO = ctypes.c_void_p
        PCTSTR = ctypes.c_char_p
        CHAR = ctypes.c_char
        PDWORD = ctypes.POINTER(DWORD)
        LPDWORD = ctypes.POINTER(DWORD)
        PULONG = ctypes.POINTER(ULONG)

        # Return code checkers
        def ValidHandle(value, func, arguments):
            if value == 0:
                raise GPLPVDriverError(str(ctypes.WinError()))
            return value

        # Some structures used by the Windows API
        class GUID(ctypes.Structure):
            _fields_ = [
                ('Data1', DWORD),
                ('Data2', WORD),
                ('Data3', WORD),
                ('Data4', BYTE * 8),
            ]

            def __str__(self):
                return "{%08x-%04x-%04x-%s-%s}" % (
                    self.Data1,
                    self.Data2,
                    self.Data3,
                    ''.join(["%02x" % d for d in self.Data4[:2]]),
                    ''.join(["%02x" % d for d in self.Data4[2:]]),
                )

        PGUID = ctypes.POINTER(GUID)

        class SP_DEVINFO_DATA(ctypes.Structure):
            _fields_ = [
                ('cbSize', DWORD),
                ('ClassGuid', GUID),
                ('DevInst', DWORD),
                ('Reserved', PULONG),
            ]

            def __str__(self):
                return "ClassGuid:%s DevInst:%s" % (
                    self.ClassGuid, self.DevInst
                )

        PSP_DEVINFO_DATA = ctypes.POINTER(SP_DEVINFO_DATA)

        class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
            _fields_ = [
                ('cbSize', DWORD),
                ('InterfaceClassGuid', GUID),
                ('Flags', DWORD),
                ('Reserved', PULONG),
            ]

            def __str__(self):
                return "InterfaceClassGuid:%s Flags:%s" % (
                    self.InterfaceClassGuid, self.Flags
                )

        PSP_DEVICE_INTERFACE_DATA = ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)
        PSP_DEVICE_INTERFACE_DETAIL_DATA = ctypes.c_void_p

        # Import the Windows APIs
        setupapi = ctypes.windll.LoadLibrary("setupapi")

        SetupDiGetClassDevs = setupapi.SetupDiGetClassDevsA
        SetupDiGetClassDevs.argtypes = [PGUID, PCTSTR, HWND, DWORD]
        SetupDiGetClassDevs.restype = HDEVINFO
        SetupDiGetClassDevs.errcheck = ValidHandle

        SetupDiEnumDeviceInterfaces = setupapi.SetupDiEnumDeviceInterfaces
        SetupDiEnumDeviceInterfaces.argtypes = [
            HDEVINFO, PSP_DEVINFO_DATA, PGUID, DWORD, PSP_DEVICE_INTERFACE_DATA
        ]
        SetupDiEnumDeviceInterfaces.restype = BOOL

        SetupDiGetDeviceInterfaceDetail = \
            setupapi.SetupDiGetDeviceInterfaceDetailA
        SetupDiGetDeviceInterfaceDetail.argtypes = [
            HDEVINFO, PSP_DEVICE_INTERFACE_DATA,
            PSP_DEVICE_INTERFACE_DETAIL_DATA, DWORD, PDWORD, PSP_DEVINFO_DATA
        ]
        SetupDiGetDeviceInterfaceDetail.restype = BOOL

        SetupDiDestroyDeviceInfoList = setupapi.SetupDiDestroyDeviceInfoList
        SetupDiDestroyDeviceInfoList.argtypes = [HDEVINFO]
        SetupDiDestroyDeviceInfoList.restype = BOOL

        # Do stuff
        GUID_XENBUS_IFACE = GUID(
            0x14ce175a, 0x3ee2, 0x4fae,
            (BYTE * 8)(0x92, 0x52, 0x0, 0xdb, 0xd8, 0x4f, 0x1, 0x8e)
        )

        handle = SetupDiGetClassDevs(
            ctypes.byref(GUID_XENBUS_IFACE), NULL, NULL,
            DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
        )

        sdid = SP_DEVICE_INTERFACE_DATA()
        sdid.cbSize = ctypes.sizeof(sdid)
        if not SetupDiEnumDeviceInterfaces(
            handle, NULL, ctypes.byref(GUID_XENBUS_IFACE), 0,
            ctypes.byref(sdid)
        ):
            if ctypes.GetLastError() != ERROR_NO_MORE_ITEMS:
                raise GPLPVDriverError(str(ctypes.WinError()))

        buf_len = DWORD()
        if not SetupDiGetDeviceInterfaceDetail(
            handle, ctypes.byref(sdid), NULL, 0, ctypes.byref(buf_len), NULL
        ):
            if ctypes.GetLastError() != ERROR_INSUFFICIENT_BUFFER:
                raise GPLPVDriverError(str(ctypes.WinError()))

        # We didn't know how big to make the structure until buf_len is
        # assigned...
        class SP_DEVICE_INTERFACE_DETAIL_DATA_A(ctypes.Structure):
            _fields_ = [
                ('cbSize', DWORD),
                ('DevicePath', CHAR * (buf_len.value - ctypes.sizeof(DWORD))),
            ]

            def __str__(self):
                return "DevicePath:%s" % (self.DevicePath, )

        sdidd = SP_DEVICE_INTERFACE_DETAIL_DATA_A()
        sdidd.cbSize = ctypes.sizeof(
            ctypes.POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA_A)
        )
        if not SetupDiGetDeviceInterfaceDetail(
            handle, ctypes.byref(sdid), ctypes.byref(sdidd), buf_len, NULL,
            NULL
        ):
            raise GPLPVDriverError(str(ctypes.WinError()))

        self.path = "" + sdidd.DevicePath

        SetupDiDestroyDeviceInfoList(handle)

        _winDevicePath = self.path

        self._open_device()

    def _open_device(self):
        try:
            self.fd = CreateFile(
                self.path, FILE_GENERIC_READ | FILE_GENERIC_WRITE, 0, None,
                OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None
            )
        except Exception as exc:
            self._logger.exception('Exception opening GPLPV device:')
            six.raise_from(
                GPLPVDeviceOpenError(
                    "Error while opening {0!r}".format(self.path)
                ), exc
            )

    def fileno(self):
        return self.r_terminator.fileno()

    def close(self, silent=True):
        CloseHandle(self.fd)
        self.fd = None

        self.r_terminator.shutdown(socket.SHUT_RDWR)

        self.r_terminator.close()
        self.w_terminator.close()

    def recv(self, size):
        self._logger.debug('recv: %d', size)

        chunks = []
        while size:
            (err, read) = ReadFile(self.fd, size, None)
            if err:
                raise OSError(err)

            chunks.append(read)
            size -= len(read)

        received = 0
        while received < 1:
            data = self.r_terminator.recv(1)
            received += len(data)
        self._logger.debug('recv: read 1 byte from socket, returning data')

        return b"".join(chunks)

    def send(self, data):
        self._logger.debug('send: %d', len(data))

        size = len(data)
        while size:
            err, lwrite = WriteFile(self.fd, data[-size:], None)
            if err:
                raise OSError(err)

            size -= lwrite

        if self.notify:
            self._logger.debug('send: notifying router')
            self.w_terminator.sendall(NUL + NUL)

        self.notify = not self.notify
