"""Migrated from legacy/inventory/inventory.cbl."""

from decimal import Decimal

from generated.inventory_records import InRecord, OutRecord
from seance.cobol_num import store

D = Decimal


def transform(rec: InRecord) -> OutRecord:
    net = store(rec.on_hand + rec.received - rec.shipped, 6, 0)
    if net < 0:
        backorder = store(-net, 5, 0, signed=False)
        new_on_hand = D(0)
    else:
        backorder = D(0)
        new_on_hand = store(net, 5, 0, signed=False)
    flag = "R" if new_on_hand <= rec.reorder else " "
    return OutRecord(sku=rec.sku, new_on_hand=new_on_hand, backorder=backorder, flag=flag)
