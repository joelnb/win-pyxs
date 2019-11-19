"""
A sub-module to hold exceptions for win_pyxs. These exceptions all inherit from
pyxs.PyXSError so that they will be caught along with normal exceptions from
pyxs.
"""

from pyxs import PyXSError


class WinPyXSError(PyXSError):
    """
    Base class for all exceptions raised by this module. Derived from
    pyxs.PyXSError so that it is caught in the same way as the exceptions for
    the non-Windows classes.
    """


class UnknownSessionError(WinPyXSError):
    """
    Exception raised when the xenstore session cannot be found. This can happen
    if something removes the session (via the WMI interface) while your program
    is running.
    """
