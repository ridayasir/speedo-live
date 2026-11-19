"""Cloud Firestore persistence.

Every record is a Firestore document (collection = model, document id = the record's id). Reference data
that the API reads on almost every request (routes, stops, buses, drivers, users, schedules, alerts,
favourites, watches, device tokens and *active* trips) is mirrored in memory after start-up, so ETA, planner
and live-tracking code reads it without a network round trip. History that only grows (finished trips, GPS
fixes, notifications, journeys, audit log) is queried from Firestore when needed.

Writes go through a unit of work: `db.add()` / `db.delete()` / attribute changes are collected and written in
one Firestore batch on `db.commit()`; `db.rollback()` restores the last committed state. Queries only ever ask
Firestore for single-field filters, so the app needs no composite indexes.

Run ONE API instance per Firebase project: the in-memory mirror is not shared between processes.
"""
from __future__ import annotations

import enum
import logging
import threading
import time as _time
from collections.abc import Iterable
from datetime import datetime, time, timezone
from typing import Any, TypeVar

log = logging.getLogger("speedo.store")
T = TypeVar("T", bound="Doc")
_MISSING = object()
ID_BLOCK = 10  # ids are reserved from the Firestore counter in blocks to save round trips


class IntegrityError(Exception):
    """A unique field (code, number, email, ...) clashes with an existing record."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ----------------------------------------------------------------------------- filters
Filter = tuple[str, str, Any]  # (field, op, value); op in == != < <= > >= in


def _match(obj: Doc, filters: Iterable[Filter]) -> bool:
    for field, op, value in filters:
        v = getattr(obj, field)
        if isinstance(v, enum.Enum):
            v = v.value
        if isinstance(value, enum.Enum):
            value = value.value
        if op == "==":
            ok = v == value
        elif op == "!=":
            ok = v != value
        elif op == "in":
            ok = v in [x.value if isinstance(x, enum.Enum) else x for x in value]
        else:
            if v is None or value is None:
                return False
            ok = {"<": v < value, "<=": v <= value, ">": v > value, ">=": v >= value}[op]
        if not ok:
            return False
    return True


# ----------------------------------------------------------------------------- models
class Doc:
    """Base for Firestore-backed records. Subclasses declare FIELDS = {name: default or factory}."""

    __collection__: str = ""
    FIELDS: dict[str, Any] = {}
    ENUMS: dict[str, type[enum.Enum]] = {}
    TIMES: tuple[str, ...] = ()
    UNIQUE: tuple[tuple[str, ...], ...] = ()
    CACHED = True  # mirrored in memory
    TIMESTAMPS = True  # maintain created_at / updated_at
    STR_ID = False  # id is a string chosen by the model instead of a counter
    # Fields that change every few seconds (live GPS). When ONLY these changed, the record is written to
    # Firestore at most every WRITE_EVERY seconds; the in-memory copy (what the API serves) is always current.
    # This keeps live tracking inside Firestore's free daily write quota.
    VOLATILE: frozenset[str] = frozenset()
    WRITE_EVERY = 0

    REGISTRY: list[type[Doc]] = []

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        if cls.__collection__:
            Doc.REGISTRY.append(cls)

    def __init__(self, **kw):
        object.__setattr__(self, "id", kw.pop("id", None))
        object.__setattr__(self, "_persisted", None)
        for k, d in self.FIELDS.items():
            object.__setattr__(self, k, d() if callable(d) and not isinstance(d, enum.Enum) else d)
        for k, v in kw.items():
            if k not in self.FIELDS:
                raise TypeError(f"{type(self).__name__} has no field {k!r}")
            object.__setattr__(self, k, self._coerce(k, v))

    @classmethod
    def _coerce(cls, k, v):
        """Enum fields accept their plain values ("info" -> AlertSeverity.info), as the SQL layer did."""
        if v is not None and k in cls.ENUMS and not isinstance(v, cls.ENUMS[k]):
            return cls.ENUMS[k](v)
        return v

    def __setattr__(self, k, v):
        object.__setattr__(self, k, self._coerce(k, v))
        if k in self.FIELDS and self._persisted is not None:
            store.mark(self)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.id}>"

    # --- (de)serialisation
    @staticmethod
    def _out(v):
        if isinstance(v, enum.Enum):
            return v.value
        if isinstance(v, time):
            return v.strftime("%H:%M:%S")
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    def to_dict(self) -> dict:
        return {k: self._out(getattr(self, k)) for k in self.FIELDS}

    @classmethod
    def _in(cls, k, v):
        if v is None:
            return None
        if k in cls.ENUMS:
            return cls.ENUMS[k](v)
        if k in cls.TIMES and isinstance(v, str):
            return time.fromisoformat(v)
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return v

    @classmethod
    def from_dict(cls: type[T], doc_id, data: dict) -> T:
        obj = cls.__new__(cls)
        object.__setattr__(obj, "id", doc_id if cls.STR_ID else int(doc_id))
        object.__setattr__(obj, "_persisted", None)
        for k, d in cls.FIELDS.items():
            v = data.get(k, _MISSING)
            if v is _MISSING:
                v = d() if callable(d) and not isinstance(d, enum.Enum) else d
            object.__setattr__(obj, k, cls._in(k, v))
        obj._load_extra(data)
        object.__setattr__(obj, "_persisted", obj.to_dict())
        return obj

    def _load_extra(self, data: dict) -> None:
        """Hook for embedded data (route stops)."""

    def _restore_extra(self, fresh: Doc) -> None:
        """Hook for rollback of embedded data."""

    def new_id(self):
        """String id for STR_ID models."""
        raise NotImplementedError

    # --- lifecycle hooks
    def on_delete(self, db: Session) -> None:
        """Cascade to dependent records (mirrors the old foreign-key rules)."""

    @classmethod
    def keep_cached(cls, obj) -> bool:
        return True

    CACHE_FILTERS: tuple[Filter, ...] = ()


class TrackedList(list):
    """A list attribute stored inside its owner's document; changes mark the owner as modified."""

    def __init__(self, owner: Doc, items=()):
        super().__init__(items)
        self._owner = owner

    def _touch(self):
        if self._owner._persisted is not None:
            store.mark(self._owner)

    def append(self, x):
        super().append(x)
        self._touch()

    def extend(self, xs):
        super().extend(xs)
        self._touch()

    def remove(self, x):
        super().remove(x)
        self._touch()

    def clear(self):
        super().clear()
        self._touch()

    def pop(self, *a):
        v = super().pop(*a)
        self._touch()
        return v

    def sort(self, *a, **kw):
        super().sort(*a, **kw)
        self._touch()

    def __setitem__(self, i, v):
        super().__setitem__(i, v)
        self._touch()

    def __delitem__(self, i):
        super().__delitem__(i)
        self._touch()


# ----------------------------------------------------------------------------- store
class Store:
    def __init__(self) -> None:
        self.backend = None
        self.cache: dict[type[Doc], dict] = {}
        self.dirty: set[Doc] = set()
        self.new: list[Doc] = []
        self.deleted: list[Doc] = []
        self.lock = threading.RLock()
        self._ids: dict[str, list[int]] = {}
        self._last_write: dict[tuple[str, object], float] = {}

    @staticmethod
    def _volatile_only(obj: Doc) -> bool:
        if not obj.VOLATILE or obj._persisted is None:
            return False
        now, old = obj.to_dict(), obj._persisted
        changed = {k for k in now if now[k] != old.get(k)} - {"updated_at"}
        return bool(changed) and changed <= obj.VOLATILE

    # --- setup
    def connect(self, backend) -> None:
        self.backend = backend
        self.reload()

    def reload(self) -> None:
        from . import models  # noqa: F401  (registers every collection)

        with self.lock:
            self.cache = {}
            self.dirty, self.new, self.deleted = set(), [], []
            self._ids = {}
            for model in Doc.REGISTRY:
                if not model.CACHED:
                    continue
                rows = self.backend.stream(model.__collection__, list(model.CACHE_FILTERS))
                self.cache[model] = {}
                for doc_id, data in rows:
                    obj = model.from_dict(doc_id, data)
                    self.cache[model][obj.id] = obj
            log.info("Loaded from Firestore: %s",
                     ", ".join(f"{m.__collection__}={len(v)}" for m, v in self.cache.items()))

    @property
    def ready(self) -> bool:
        return self.backend is not None

    def _need(self):
        if self.backend is None:
            raise RuntimeError("Firestore is not connected (see app/firebase.py: firebase.init())")

    # --- ids
    def _allocate(self, model: type[Doc]) -> int:
        pool = self._ids.setdefault(model.__collection__, [])
        if not pool:
            high = self.backend.allocate(model.__collection__, ID_BLOCK)
            pool.extend(range(high - ID_BLOCK + 1, high + 1))
        return pool.pop(0)

    # --- unit of work
    def mark(self, obj: Doc) -> None:
        self.dirty.add(obj)

    def add(self, obj: Doc) -> None:
        self._need()
        with self.lock:
            if obj._persisted is not None or obj in self.new:
                return
            if obj.id is None:
                object.__setattr__(obj, "id", obj.new_id() if obj.STR_ID else self._allocate(type(obj)))
            if obj.TIMESTAMPS or "created_at" in obj.FIELDS:
                if "created_at" in obj.FIELDS and obj.created_at is None:
                    object.__setattr__(obj, "created_at", utcnow())
                if "updated_at" in obj.FIELDS and obj.updated_at is None:
                    object.__setattr__(obj, "updated_at", obj.created_at)
            self.new.append(obj)
            if type(obj).CACHED:
                self.cache[type(obj)][obj.id] = obj

    def delete(self, obj: Doc, db: Session | None = None) -> None:
        with self.lock:
            if obj in self.deleted:
                return
            self.deleted.append(obj)
            obj.on_delete(db or Session())

    def _check_unique(self) -> None:
        dead = set(map(id, self.deleted))
        touched = [o for o in list(self.new) + list(self.dirty) if id(o) not in dead and type(o).UNIQUE]
        for obj in touched:
            model = type(obj)
            others = [o for o in self.cache.get(model, {}).values() if o is not obj and id(o) not in dead]
            for key in model.UNIQUE:
                val = tuple(getattr(obj, k) for k in key)
                if any(v is None for v in val):
                    continue
                if any(tuple(getattr(o, k) for k in key) == val for o in others):
                    raise IntegrityError(f"{model.__collection__}: duplicate {'/'.join(key)} {val}")

    def commit(self, force: bool = False) -> None:
        """Write pending changes. force=True also writes throttled live-GPS updates (used at shutdown)."""
        with self.lock:
            if not (self.new or self.dirty or self.deleted):
                return
            self._need()
            self._check_unique()
            now = utcnow()
            dead = set(map(id, self.deleted))
            writes: list[Doc] = []
            for obj in self.new:
                if id(obj) not in dead:
                    writes.append(obj)
            new_ids = set(map(id, self.new))
            held: set[Doc] = set()
            mono = _time.monotonic()
            for obj in self.dirty:
                if id(obj) in dead or id(obj) in new_ids or obj._persisted is None:
                    continue
                key = (type(obj).__collection__, obj.id)
                if (not force and self._volatile_only(obj)
                        and mono - self._last_write.get(key, -1e9) < obj.WRITE_EVERY):
                    held.add(obj)  # live position only; written on a later commit
                    continue
                if obj.to_dict() != obj._persisted:
                    if "updated_at" in obj.FIELDS:
                        object.__setattr__(obj, "updated_at", now)
                    writes.append(obj)
            deletes = [o for o in self.deleted if o._persisted is not None]
            try:
                self.backend.write(
                    [(type(o).__collection__, str(o.id), o.to_dict()) for o in writes],
                    [(type(o).__collection__, str(o.id)) for o in deletes],
                )
            except Exception:
                log.exception("Firestore write failed; changes rolled back")
                self.rollback()
                raise
            for obj in writes:
                object.__setattr__(obj, "_persisted", obj.to_dict())
                if obj.VOLATILE:
                    self._last_write[(type(obj).__collection__, obj.id)] = mono
                model = type(obj)
                if model.CACHED:
                    if model.keep_cached(obj):
                        self.cache[model][obj.id] = obj
                    else:
                        self.cache[model].pop(obj.id, None)
            for obj in self.deleted:
                if type(obj).CACHED:
                    self.cache[type(obj)].pop(obj.id, None)
                object.__setattr__(obj, "_persisted", None)
            self.dirty, self.new, self.deleted = held, [], []

    def rollback(self) -> None:
        with self.lock:
            for obj in self.new:
                if type(obj).CACHED:
                    self.cache[type(obj)].pop(obj.id, None)
            held = {o for o in self.dirty if o not in self.deleted and self._volatile_only(o)}
            for obj in list(self.dirty) + list(self.deleted):
                if obj._persisted is None or obj in held:
                    continue  # throttled live-GPS updates are not undone by an unrelated failure
                fresh = type(obj).from_dict(obj.id, obj._persisted)
                for k in obj.FIELDS:
                    object.__setattr__(obj, k, getattr(fresh, k))
                obj._restore_extra(fresh)
                if type(obj).CACHED and type(obj).keep_cached(obj):
                    self.cache[type(obj)][obj.id] = obj
            self.dirty, self.new, self.deleted = held, [], []

    # --- reads
    def _materialize(self, model: type[T], doc_id, data: dict) -> T:
        key = doc_id if model.STR_ID else int(doc_id)
        if model.CACHED and key in self.cache[model]:
            return self.cache[model][key]
        return model.from_dict(doc_id, data)

    def get(self, model: type[T], obj_id) -> T | None:
        if obj_id is None:
            return None
        self._need()
        key = obj_id if model.STR_ID else int(obj_id)
        if model.CACHED and key in self.cache[model]:
            obj = self.cache[model][key]
            return None if obj in self.deleted else obj
        if model.CACHED and not model.CACHE_FILTERS:
            return None  # fully mirrored: not in memory means it does not exist
        for obj in self.new:
            if type(obj) is model and obj.id == key:
                return obj
        data = self.backend.get(model.__collection__, str(key))
        return None if data is None else self._materialize(model, key, data)

    def adopt(self, model: type[T], filters: list) -> T | None:
        """Load one record written by another process straight from Firestore into the mirror."""
        self._need()
        rows = self.backend.stream(model.__collection__, filters)
        if not rows:
            return None
        with self.lock:
            obj = self._materialize(model, *rows[0])
            if model.CACHED and model.keep_cached(obj):
                self.cache[model][obj.id] = obj
        return obj

    def cached(self, model: type[T]) -> list[T]:
        dead = set(map(id, self.deleted))
        return [o for o in list(self.cache[model].values()) if id(o) not in dead]

    def query(self, model: type[T], filters: Iterable[Filter] = (), order_by: str | None = None,
              desc: bool = False, limit: int | None = None, cache_only: bool = False) -> list[T]:
        filters = list(filters)
        if model.CACHED and (cache_only or not model.CACHE_FILTERS
                             or all(f in filters for f in model.CACHE_FILTERS)):
            rows = [o for o in self.cached(model) if _match(o, filters)]
        else:
            self._need()
            dead = set(map(id, self.deleted))
            raw = self.backend.stream(model.__collection__, [(f, op, v.value if isinstance(v, enum.Enum) else v)
                                                             for f, op, v in filters],
                                      order_by=order_by, desc=desc, limit=limit)
            seen = set()
            rows = []
            for doc_id, data in raw:
                o = self._materialize(model, doc_id, data)
                if id(o) in dead or not _match(o, filters):
                    continue  # the in-memory copy may have changed since it was written
                rows.append(o)
                seen.add(o.id)
            rows += [o for o in self.new if type(o) is model and o.id not in seen and _match(o, filters)]
            if model.CACHED:  # active records changed in memory but not yet committed
                rows += [o for o in self.cached(model) if o.id not in seen and o not in rows and _match(o, filters)]
        if order_by:
            rows.sort(key=lambda o: (getattr(o, order_by) is None, getattr(o, order_by) or 0), reverse=desc)
            if desc:  # keep None values last
                rows = [o for o in rows if getattr(o, order_by) is not None] + \
                       [o for o in rows if getattr(o, order_by) is None]
        return rows[:limit] if limit else rows


store = Store()


class Session:
    """The `db` object handed to request handlers and services (same calls as the old SQLAlchemy session)."""

    def get(self, model: type[T], obj_id) -> T | None:
        return store.get(model, obj_id)

    def add(self, obj: Doc) -> None:
        store.add(obj)

    def delete(self, obj: Doc) -> None:
        store.delete(obj, self)

    def commit(self) -> None:
        store.commit()

    def rollback(self) -> None:
        store.rollback()

    def flush(self) -> None:
        """Ids are assigned on add(), so there is nothing to flush."""

    def refresh(self, obj: Doc) -> None:
        """Objects are shared and always current."""

    def expire_all(self) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    # --- queries
    def all(self, model: type[T]) -> list[T]:
        return store.query(model, cache_only=True) if model.CACHED else store.query(model)

    def where(self, model: type[T], *filters: Filter, order_by: str | None = None, desc: bool = False,
              limit: int | None = None, **eq) -> list[T]:
        fl = list(filters) + [(k, "==", v) for k, v in eq.items()]
        return store.query(model, fl, order_by=order_by, desc=desc, limit=limit)

    def first(self, model: type[T], *filters: Filter, **eq) -> T | None:
        rows = self.where(model, *filters, **eq)
        return rows[0] if rows else None

    def count(self, model: type[T], *filters: Filter, **eq) -> int:
        return len(self.where(model, *filters, **eq))
