"""
Performs a simple access to xenstore and prints some details about the
current VM.
"""

from __future__ import print_function

import pyxs

from win_pyxs import XenBusConnectionWinPV


def _main():
    con = XenBusConnectionWinPV()
    router = pyxs.Router(con)
    with pyxs.Client(router=router) as client:
        my_uuid = client.read("vm")
        print('My UUID:', my_uuid)
        my_domid = client.read("domid")
        print('My DomID:', my_domid)
        print(client.list("/local/domain/{}".format(my_domid)))


if __name__ == "__main__":
    _main()
