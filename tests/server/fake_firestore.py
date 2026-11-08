"""An in-memory stand-in for the parts of the Firestore client that FirestoreStorage uses."""

import itertools

from nv_server.firestore_storage import FirestoreStorage

_auto = itertools.count()
_COMPARE = {"<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b}


class _Snapshot:
    def __init__(self, name, data):
        self.id, self._data = name, data
        self.exists = data is not None

    def get(self, field):
        return self._data[field]


class _Document:
    def __init__(self, store, path):
        self._store, self._path = store, path
        self.id = path.rsplit("/", 1)[-1]

    def collection(self, name):
        return _Collection(self._store, f"{self._path}/{name}")

    def get(self, transaction=None):
        return _Snapshot(self.id, self._store.get(self._path))

    def set(self, data):
        self._store[self._path] = dict(data)

    def update(self, data):
        self._store[self._path].update(data)


class _Collection:
    def __init__(self, store, path, filters=(), order=None, count=None):
        self._store, self._path, self._filters, self._order, self._count = store, path, filters, order, count

    def document(self, name=None):
        return _Document(self._store, f"{self._path}/{name if name is not None else 'auto' + str(next(_auto))}")

    def where(self, filter):
        return _Collection(self._store, self._path, (*self._filters, filter), self._order, self._count)

    def order_by(self, field, direction="ASCENDING"):
        return _Collection(self._store, self._path, self._filters, (field, direction), self._count)

    def limit(self, count):
        return _Collection(self._store, self._path, self._filters, self._order, count)

    def stream(self):
        prefix = f"{self._path}/"
        rows = [(k.rsplit("/", 1)[-1], v) for k, v in self._store.items() if k.startswith(prefix) and "/" not in k[len(prefix):]]
        for f in self._filters:
            rows = [r for r in rows if _COMPARE[f.op_string](r[1][f.field_path], f.value)]
        if self._order:
            rows.sort(key=lambda r: r[1][self._order[0]], reverse=self._order[1] == "DESCENDING")
        return iter([_Snapshot(name, data) for name, data in rows[: self._count]])


class _Transaction:
    def set(self, document, data):
        document.set(data)

    def update(self, document, data):
        document.update(data)


class FakeClient:
    def __init__(self):
        self.store = {}

    def collection(self, name):
        return _Collection(self.store, name)

    def close(self):
        pass


class FakeFirestoreStorage(FirestoreStorage):
    """The real storage code on the in-memory client; only the transaction wrapper is replaced."""

    def _atomic(self, work):
        return work(_Transaction())
