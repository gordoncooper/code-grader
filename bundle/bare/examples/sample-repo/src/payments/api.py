def charge(request, gateway, store):
    key = request.headers["Idempotency-Key"]
    if store.seen(key):
        return store.result(key)
    result = gateway.charge(request.json["amount"])
    store.save(key, result)
    return result
