"""
An implementation of pyxs.connection.PacketConnection for the Windows
versions of the Xen PV drivers. There are two possible connections:
XenBusConnectionWinPV which can be used with the WinPV drivers available for
modern versions of Windows & XenBusConnectionGPLPV which works with the GPLPV
drivers which were available for older versions of Windows.
"""

__all__ = ['XenBusConnectionWinPV', 'XenBusConnectionGPLPV']

from .gplpv import XenBusConnectionGPLPV
from .winpv import XenBusConnectionWinPV
