from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from rawstore import AuthorizedReader, Provenance, RawStore


BASE_T = datetime(2026, 4, 22, 0, 0, 0, tzinfo=timezone.utc)


class _StorageReader(AuthorizedReader):
    """Bare reader for low-level storage tests. Not a production path."""
    pass


READER = _StorageReader()


def _prov(
    source: str = "vendor-A",
    fetch: datetime = BASE_T,
    vendor: datetime = BASE_T,
) -> Provenance:
    return Provenance(source, fetch, vendor)


def _files_under(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


@pytest.fixture
def store(tmp_path: Path):
    s = RawStore(tmp_path / "rs")
    try:
        yield s
    finally:
        s.close()


def test_put_get_roundtrip(store: RawStore) -> None:
    data = b"hello world"
    h = store.put(data, _prov())
    assert h == hashlib.sha256(data).hexdigest()
    assert store.get(h, reader=READER) == data


def test_get_unknown_hash_raises(store: RawStore) -> None:
    with pytest.raises(KeyError):
        store.get("0" * 64, reader=READER)


def test_read_without_reader_rejected(store: RawStore) -> None:
    h = store.put(b"guarded", _prov())
    with pytest.raises(PermissionError):
        store.get(h, reader=object())  # type: ignore[arg-type]
    with pytest.raises(PermissionError):
        store.provenance(h, reader=object())  # type: ignore[arg-type]
    with pytest.raises(PermissionError):
        store.corrections(h, reader=object())  # type: ignore[arg-type]
    with pytest.raises(PermissionError):
        store.has(h, reader=object())  # type: ignore[arg-type]


def test_naive_datetime_rejected(store: RawStore) -> None:
    naive = datetime(2026, 4, 22, 0, 0, 0)  # no tzinfo
    with pytest.raises(ValueError):
        store.put(b"x", Provenance("vendor-A", naive, BASE_T))
    with pytest.raises(ValueError):
        store.put(b"x", Provenance("vendor-A", BASE_T, naive))


def test_empty_source_id_rejected(store: RawStore) -> None:
    with pytest.raises(ValueError):
        store.put(b"x", Provenance("", BASE_T, BASE_T))


def test_corrects_must_be_sha256_hex(store: RawStore) -> None:
    with pytest.raises(ValueError):
        store.put(b"x", _prov(), corrects="not-a-hash")


def test_corrections_link_and_no_mutation(store: RawStore) -> None:
    h_orig = store.put(b"original", _prov(source="vendor-A"))
    h_corr = store.put(
        b"corrected",
        _prov(source="vendor-A", fetch=BASE_T + timedelta(hours=1)),
        corrects=h_orig,
    )
    assert h_orig != h_corr
    assert store.corrections(h_orig, reader=READER) == [h_corr]
    # Reverse direction does not exist.
    assert store.corrections(h_corr, reader=READER) == []
    # Original bytes survive unchanged.
    assert store.get(h_orig, reader=READER) == b"original"
    assert store.get(h_corr, reader=READER) == b"corrected"


def test_multiple_corrections_to_same_original(store: RawStore) -> None:
    h_orig = store.put(b"v0", _prov())
    h_c1 = store.put(b"v1", _prov(fetch=BASE_T + timedelta(hours=1)), corrects=h_orig)
    h_c2 = store.put(b"v2", _prov(fetch=BASE_T + timedelta(hours=2)), corrects=h_orig)
    assert sorted(store.corrections(h_orig, reader=READER)) == sorted([h_c1, h_c2])


def test_no_byte_file_rewrite_on_repeat_put(store: RawStore, tmp_path: Path) -> None:
    h = store.put(b"immutable", _prov())
    files = _files_under(store._bytes_root)
    assert len(files) == 1
    mtime_before = files[0].stat().st_mtime_ns
    # Second put with a *different* provenance must not touch the byte file.
    store.put(b"immutable", _prov(source="vendor-B"))
    mtime_after = files[0].stat().st_mtime_ns
    assert mtime_before == mtime_after


@given(
    data=st.binary(max_size=256),
    repeats=st.integers(min_value=1, max_value=6),
)
@settings(max_examples=40, deadline=None)
def test_put_idempotent_on_repeat_hash(
    tmp_path_factory: pytest.TempPathFactory,
    data: bytes,
    repeats: int,
) -> None:
    """put(same bytes, same provenance) n times: stable hash, one file, one row."""
    root = tmp_path_factory.mktemp("rs_idem")
    s = RawStore(root)
    try:
        hashes = {s.put(data, _prov()) for _ in range(repeats)}
        assert len(hashes) == 1
        h = next(iter(hashes))
        assert s.get(h, reader=READER) == data
        assert len(_files_under(s._bytes_root)) == 1
        assert len(s.provenance(h, reader=READER)) == 1
    finally:
        s.close()


@given(
    data=st.binary(min_size=1, max_size=256),
    sources=st.lists(
        st.text(
            alphabet=st.characters(min_codepoint=48, max_codepoint=122),
            min_size=1,
            max_size=16,
        ),
        min_size=1,
        max_size=5,
        unique=True,
    ),
)
@settings(max_examples=30, deadline=None)
def test_provenance_multiplicity(
    tmp_path_factory: pytest.TempPathFactory,
    data: bytes,
    sources: list[str],
) -> None:
    """Same bytes from N distinct vendors: single byte-file, N provenance rows."""
    root = tmp_path_factory.mktemp("rs_mult")
    s = RawStore(root)
    try:
        h: str | None = None
        for i, src in enumerate(sources):
            returned = s.put(
                data,
                Provenance(
                    src,
                    BASE_T + timedelta(seconds=i),
                    BASE_T + timedelta(seconds=i),
                ),
            )
            h = returned if h is None else h
            assert returned == h  # hash stable across vendors
        assert h is not None
        assert len(_files_under(s._bytes_root)) == 1
        triples = s.provenance(h, reader=READER)
        assert len(triples) == len(sources)
        assert {t.source_id for t in triples} == set(sources)
    finally:
        s.close()


@given(data=st.binary(max_size=128))
@settings(max_examples=20, deadline=None)
def test_exact_duplicate_provenance_dedup(
    tmp_path_factory: pytest.TempPathFactory,
    data: bytes,
) -> None:
    """Repeated put with identical provenance must not multiply provenance rows."""
    root = tmp_path_factory.mktemp("rs_dedup")
    s = RawStore(root)
    try:
        p = _prov()
        h1 = s.put(data, p)
        h2 = s.put(data, p)
        h3 = s.put(data, p)
        assert h1 == h2 == h3
        assert len(s.provenance(h1, reader=READER)) == 1
    finally:
        s.close()


def test_bytes_path_lives_under_bytes_root(store: RawStore) -> None:
    h = store.put(b"layout-check", _prov())
    files = _files_under(store._bytes_root)
    assert len(files) == 1
    path = files[0]
    # <root>/bytes/<YYYY-MM-DD>/<prefix>/<hash>
    assert path.name == h
    assert path.parent.name == h[:2]
    # parent-of-parent must be an ISO date dir
    datetime.strptime(path.parent.parent.name, "%Y-%m-%d")


def test_persists_across_reopen(tmp_path: Path) -> None:
    root = tmp_path / "rs_persist"
    s1 = RawStore(root)
    h = s1.put(b"persist-me", _prov(source="vendor-A"))
    s1.put(b"persist-me", _prov(source="vendor-B"))
    s1.close()

    s2 = RawStore(root)
    try:
        assert s2.get(h, reader=READER) == b"persist-me"
        assert {p.source_id for p in s2.provenance(h, reader=READER)} == {"vendor-A", "vendor-B"}
    finally:
        s2.close()
