"""
This module contains utility code used by win_pyxs which should not be
needed by any client code & is only intended for internal use.
"""


class LazyVar(object):
    """
    Wrap a function in a LazyVar to create a callable whose return value is
    calculated no moe than once & then stored and returned for future callers.
    This can be useful to reduce the time taken to initialise expensive
    values without having to use a global varaible within a module.
    """

    def __init__(self, func):
        self.func = func

    def __call__(self):
        try:
            return self.value
        except AttributeError:
            self.value = self.func()
            return self.value
