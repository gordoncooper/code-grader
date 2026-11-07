from src.orders.service import order_total


def test_total_multiple_items():
    items = [{"price": 10, "qty": 1}, {"price": 5, "qty": 2}]
    assert order_total(items, discount=0.1) == 18.0
