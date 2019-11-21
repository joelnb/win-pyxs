"""
Performs a simple access to xenstore and prints some details about the
current VM.
"""

from __future__ import print_function

import logging
from pprint import pprint

import six

import pyxs

from win_pyxs import XenBusConnectionWinPV, XenBusConnectionGPLPV
from win_pyxs.exceptions import GPLPVDeviceOpenError, GPLPVDriverError


def _basic_logger_init(logger, verbose=False):
    """
    Setup a logger to output to the stderr stream.

    :param logger: The logger to setup.
    :param verbose: If True the logger & formatter will be set to DEBUG level.
    """
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(name)s: %(message)s')
    handler.setFormatter(formatter)

    log_level = logging.INFO
    if verbose:
        log_level = logging.DEBUG

    logger.setLevel(log_level)
    handler.setLevel(log_level)

    logger.addHandler(handler)


def _main():
    logger = logging.getLogger('win_pyxs')
    _basic_logger_init(logger, verbose=True)

    try:
        con = XenBusConnectionGPLPV()
        logger.info('Using XenBusConnectionGPLPV')
    except (GPLPVDeviceOpenError, GPLPVDriverError) as gplpv_exc:
        try:
            con = XenBusConnectionWinPV()
            logger.info('Using XenBusConnectionWinPV')
        except Exception as winpv_exc:
            six.raise_from(winpv_exc, gplpv_exc)

    router = pyxs.Router(con)
    with pyxs.Client(router=router) as client:
        my_uuid = client.read("vm")
        print('My UUID: ', my_uuid)
        my_domid = client.read("domid")
        print('My DomID:', my_domid)
        my_mac = client.read("device/vif/0/mac")
        print('My MAC:  ', my_mac)
        caption, first = 'Drivers: ', True
        for driver in client.list("drivers"):
            if first:
                first = False
            print(caption, client.read(driver))
            caption = '         '
        if first:
            print(caption, 'GPLPV (None in xenstore)')
        print('My Home:')
        pprint(client.list("/local/domain/{}".format(my_domid)))


if __name__ == "__main__":
    _main()
