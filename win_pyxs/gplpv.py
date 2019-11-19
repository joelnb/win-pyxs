import os
import sys

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
import six
import wmi

from .exceptions import GPLPVDeviceOpenError

sys.coinit_flags = 0

_winDevicePath = None


class XenBusConnectionWinGPLPV(FileDescriptorConnection):
    def __init__(self):
        global _winDevicePath

        # Once the windows device path is learned once reuse it otherwise
        # ctypes.POINTER() for the same structure leaks memory. Although
        # this can be reclaimed with ctypes._reset_cache() this is poking
        # at the internals of ctypes which doesn't seem to be a good idea.
        if _winDevicePath:
            self.path = _winDevicePath
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
                raise WindowsDriverError(str(ctypes.WinError()))
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
                return "ClassGuid:%s DevInst:%s" % (self.ClassGuid, self.DevInst)

        PSP_DEVINFO_DATA = ctypes.POINTER(SP_DEVINFO_DATA)

        class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
            _fields_ = [
                ('cbSize', DWORD),
                ('InterfaceClassGuid', GUID),
                ('Flags', DWORD),
                ('Reserved', PULONG),
            ]

            def __str__(self):
                return "InterfaceClassGuid:%s Flags:%s" % (self.InterfaceClassGuid, self.Flags)

        PSP_DEVICE_INTERFACE_DATA = ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)
        PSP_DEVICE_INTERFACE_DETAIL_DATA = ctypes.c_void_p

        # Import the Windows APIs
        setupapi = ctypes.windll.LoadLibrary("setupapi")

        SetupDiGetClassDevs = setupapi.SetupDiGetClassDevsA
        SetupDiGetClassDevs.argtypes = [PGUID, PCTSTR, HWND, DWORD]
        SetupDiGetClassDevs.restype = HDEVINFO
        SetupDiGetClassDevs.errcheck = ValidHandle

        SetupDiEnumDeviceInterfaces = setupapi.SetupDiEnumDeviceInterfaces
        SetupDiEnumDeviceInterfaces.argtypes = [HDEVINFO, PSP_DEVINFO_DATA, PGUID, DWORD, PSP_DEVICE_INTERFACE_DATA]
        SetupDiEnumDeviceInterfaces.restype = BOOL

        SetupDiGetDeviceInterfaceDetail = setupapi.SetupDiGetDeviceInterfaceDetailA
        SetupDiGetDeviceInterfaceDetail.argtypes = [HDEVINFO, PSP_DEVICE_INTERFACE_DATA, PSP_DEVICE_INTERFACE_DETAIL_DATA, DWORD, PDWORD, PSP_DEVINFO_DATA]
        SetupDiGetDeviceInterfaceDetail.restype = BOOL

        SetupDiDestroyDeviceInfoList = setupapi.SetupDiDestroyDeviceInfoList
        SetupDiDestroyDeviceInfoList.argtypes = [HDEVINFO]
        SetupDiDestroyDeviceInfoList.restype = BOOL

        # Do stuff
        GUID_XENBUS_IFACE = GUID(0x14ce175aL, 0x3ee2, 0x4fae, (BYTE * 8)(0x92, 0x52, 0x0, 0xdb, 0xd8, 0x4f, 0x1, 0x8e))

        handle = SetupDiGetClassDevs(ctypes.byref(GUID_XENBUS_IFACE), NULL, NULL, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);

        sdid = SP_DEVICE_INTERFACE_DATA()
        sdid.cbSize = ctypes.sizeof(sdid)
        if not SetupDiEnumDeviceInterfaces(handle, NULL, ctypes.byref(GUID_XENBUS_IFACE), 0, ctypes.byref(sdid)):
            if ctypes.GetLastError() != ERROR_NO_MORE_ITEMS:
                    raise WindowsDriverError(str(ctypes.WinError()))

        buf_len = DWORD()
        if not SetupDiGetDeviceInterfaceDetail(handle, ctypes.byref(sdid), NULL, 0, ctypes.byref(buf_len), NULL):
            if ctypes.GetLastError() != ERROR_INSUFFICIENT_BUFFER:
                raise WindowsDriverError(str(ctypes.WinError()))

        # We didn't know how big to make the structure until buf_len is assigned...
        class SP_DEVICE_INTERFACE_DETAIL_DATA_A(ctypes.Structure):
            _fields_ = [
                ('cbSize', DWORD),
                ('DevicePath', CHAR*(buf_len.value - ctypes.sizeof(DWORD))),
            ]

            def __str__(self):
                return "DevicePath:%s" % (self.DevicePath,)

        sdidd = SP_DEVICE_INTERFACE_DETAIL_DATA_A()
        sdidd.cbSize = ctypes.sizeof(ctypes.POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA_A))
        if not SetupDiGetDeviceInterfaceDetail(handle, ctypes.byref(sdid), ctypes.byref(sdidd), buf_len, NULL, NULL):
            raise WindowsDriverError(str(ctypes.WinError()))
        self.path = ""+sdidd.DevicePath

        SetupDiDestroyDeviceInfoList(handle)

        _winDevicePath = self.path

    def __copy__(self):
        return self.__class__()

    def connect(self):
        if self.fd:
            return

        try:
            self.fd = osnmopen(self.path)
        except Exception as exc:
            six.raise_from(GPLPVDeviceOpenError("Error while opening {0!r}".format(self.path)), exc)

    @property
    def is_connected(self):
        return self.fd is not None

    def fileno(self):
        return self.fd

    def close(self, silent=True):
        osnmclose(self.fd)
        self.fd = None
