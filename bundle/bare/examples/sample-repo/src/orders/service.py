"""Order service."""
import time


def order_total(items, discount=0.0):
    total = sum(i["price"] * i["qty"] for i in items)
    if len(items) > 1:
        total = total * (1 - discount)
    return round(total, 2)


def create_order(db, items):
    order_id = db.insert("orders", {"total": order_total(items), "ts": time.time()})
    try:
        db.reserve_stock(items)
    except Exception:
        pass
    return order_id
