"""
Performs a simple access to xenstore and prints some details about the
current VM.
"""

from __future__ import print_function

from pprint import pprint

import pyxs

from win_pyxs import XenBusConnectionWinPV
from win_pyxs.gplpv import XenBusConnectionWinGPLPV


def _main():
    con = XenBusConnectionWinGPLPV()
    router = pyxs.Router(con)
    with pyxs.Client(router=router) as client:
        my_uuid = client.read("vm")
        print('My UUID: ', my_uuid)
        my_domid = client.read("domid")
        print('My DomID:', my_domid)
        my_mac = client.read("device/vif/0/mac")
        print('My MAC:  ', my_mac)
        first = True
        for driver in client.list("drivers"):
            caption = '         '
            if first:
                caption = 'Drivers: '
                first = False
            print(caption, client.read(driver))
        print('My Home:')
        pprint(client.list("/local/domain/{}".format(my_domid)))


if __name__ == "__main__":
    _main()
