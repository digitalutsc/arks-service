"""
Importing the legacy database.

Legacy stored everything as tab-separated keys in one table per collection:

    :/naa, :/naan, :/template, :/prefix ...   reserved configuration
    61220/utsc1<TAB>URL                       an element on the ARK itself
    61220/utsc1<TAB>/page1<TAB>URL            an element on a hierarchical part
    61220/utsc1<TAB>/page1<TAB>.png<TAB>URL   ... with a variant
    61220/utsc1<TAB>:/c                       circulation bookkeeping (dropped)

The importer must read those literally rather than re-deriving them, so
whatever is actually in production survives the move intact.
"""

import sqlite3

import pytest
from django.core.management import call_command

from core.legacy import parse_legacy_key
from core.models import Ark, Binding, Collection, Resolution

pytestmark = pytest.mark.django_db

TAB = "\t"


# --- key parsing ----------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (f"61220/utsc1{TAB}URL", ("61220/utsc1", "", "URL")),
        (f"61220/utsc1{TAB}/page1{TAB}URL", ("61220/utsc1", "/page1", "URL")),
        (
            f"61220/utsc1{TAB}/page1{TAB}.image.png{TAB}URL",
            ("61220/utsc1", "/page1.image.png", "URL"),
        ),
        (f"61220/utsc1{TAB}.image.png{TAB}URL", ("61220/utsc1", ".image.png", "URL")),
        (
            f"61220/utsc1{TAB}/vol1/page3{TAB}.jpg{TAB}WHO",
            ("61220/utsc1", "/vol1/page3.jpg", "WHO"),
        ),
    ],
)
def test_legacy_keys_split_into_ark_qualifier_and_element(key, expected):
    assert parse_legacy_key(key) == expected


def test_a_key_with_no_element_is_rejected():
    assert parse_legacy_key("61220/utsc1") is None


# --- the import itself ----------------------------------------------------


def build_legacy_db(path, rows=None, config=None):
    """Create a throwaway database shaped like the legacy one."""
    defaults = {
        ":/naa": "University of Toronto Scarborough",
        ":/naan": "61220",
        ":/subnaa": "DSU",
        ":/template": ".zd",
        ":/prefix": "utsc",
        ":/mask": "zd",
        ":/firstpart": "61220/utsc",
        ":/generator_type": "sequential",
        ":/total": "-1",
        ":/oacounter": "12",
        ":/longterm": "",
        ":/addcheckchar": "",
        ":/saclist": "0 1 2",
        ":/percounter": "0",
    }
    defaults.update(config or {})

    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE `system` (_key TEXT PRIMARY KEY, _value TEXT)")
    connection.execute("CREATE TABLE `user` (id INTEGER PRIMARY KEY, username TEXT)")
    connection.execute("CREATE TABLE `ARK_utsc` (_key TEXT PRIMARY KEY, _value TEXT)")
    connection.execute("INSERT INTO `system` VALUES ('Organization Name', 'UTSC DSU')")
    connection.execute(
        "INSERT INTO `system` VALUES ('Organization Website', 'https://dsu.example')"
    )

    payload = list(defaults.items()) + list(rows or [])
    connection.executemany("INSERT OR REPLACE INTO `ARK_utsc` VALUES (?, ?)", payload)
    connection.commit()
    connection.close()


@pytest.fixture
def legacy_db(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    build_legacy_db(
        path,
        rows=[
            (f"61220/utsc0{TAB}URL", "https://example.org/0"),
            (f"61220/utsc0{TAB}LOCAL_ID", "obj-0"),
            (f"61220/utsc1{TAB}URL", "https://example.org/1"),
            (f"61220/utsc1{TAB}PID", "islandora:1"),
            (f"61220/utsc1{TAB}REDIRECT", "37"),
            (f"61220/utsc1{TAB}/page1{TAB}URL", "https://example.org/1/p1"),
            (f"61220/utsc1{TAB}/page1{TAB}.image.png{TAB}URL", "https://example.org/1/p1.png"),
            (f"61220/utsc1{TAB}:/c", "circulation-junk"),
            (f"61220/utsc1{TAB}:/h", "hold-junk"),
            (f"61220/utsc12{TAB}URL", "https://example.org/12"),
        ],
    )
    return path


def run_import(path, **options):
    call_command("import_legacy", legacy_url=f"sqlite:///{path}", verbosity=0, **options)


def test_import_creates_the_collection_from_the_reserved_rows(legacy_db):
    run_import(legacy_db)
    collection = Collection.objects.get(prefix="utsc")
    assert collection.naan == "61220"
    assert collection.naa == "University of Toronto Scarborough"
    assert collection.template == ".zd"
    assert collection.name == "ARK_utsc"


def test_import_creates_every_ark(legacy_db):
    run_import(legacy_db)
    assert set(Ark.objects.values_list("identifier", flat=True)) == {"utsc0", "utsc1", "utsc12"}


def test_imported_arks_carry_a_decoded_sequence(legacy_db):
    run_import(legacy_db)
    assert Ark.objects.get(identifier="utsc12").sequence == 12
    assert Ark.objects.get(identifier="utsc0").sequence == 0


def test_minting_resumes_after_the_imported_identifiers(legacy_db):
    from minting.minter import mint

    run_import(legacy_db)
    (ark,) = mint(Collection.objects.get(prefix="utsc"))
    assert ark.name == "61220/utsc13"


def test_import_creates_bindings_with_their_qualifiers(legacy_db):
    run_import(legacy_db)
    ark = Ark.objects.get(identifier="utsc1")
    assert ark.bindings.get(qualifier="", name="URL").value == "https://example.org/1"
    assert ark.bindings.get(qualifier="/page1", name="URL").value == "https://example.org/1/p1"
    assert (
        ark.bindings.get(qualifier="/page1.image.png", name="URL").value
        == "https://example.org/1/p1.png"
    )


def test_import_turns_redirect_counters_into_resolutions(legacy_db):
    run_import(legacy_db)
    ark = Ark.objects.get(identifier="utsc1")
    assert Resolution.objects.get(ark=ark, qualifier="").count == 37
    assert not ark.bindings.filter(name="REDIRECT").exists()


def test_import_drops_circulation_and_hold_bookkeeping(legacy_db):
    run_import(legacy_db)
    names = set(Binding.objects.values_list("name", flat=True))
    assert ":/C" not in names
    assert ":/H" not in names
    assert not Binding.objects.filter(name__startswith=":").exists()


def test_import_does_not_create_arks_for_reserved_rows(legacy_db):
    run_import(legacy_db)
    assert not Ark.objects.filter(identifier__startswith=":").exists()


def test_import_records_the_organisation(legacy_db):
    from core.models import Organisation

    run_import(legacy_db)
    assert Organisation.load().name == "UTSC DSU"


def test_import_is_idempotent(legacy_db):
    run_import(legacy_db)
    run_import(legacy_db)
    assert Collection.objects.count() == 1
    assert Ark.objects.count() == 3
    assert Binding.objects.filter(ark__identifier="utsc1").count() == 4


def test_reimporting_updates_a_changed_value(legacy_db):
    run_import(legacy_db)
    connection = sqlite3.connect(legacy_db)
    connection.execute(
        "UPDATE `ARK_utsc` SET _value = ? WHERE _key = ?",
        ("https://example.org/1-moved", f"61220/utsc1{TAB}URL"),
    )
    connection.commit()
    connection.close()

    run_import(legacy_db)
    ark = Ark.objects.get(identifier="utsc1")
    assert ark.bindings.get(qualifier="", name="URL").value == "https://example.org/1-moved"


def test_dry_run_changes_nothing(legacy_db):
    run_import(legacy_db, dry_run=True)
    assert Collection.objects.count() == 0
    assert Ark.objects.count() == 0


def test_import_reports_what_it_did(legacy_db, capsys):
    call_command("import_legacy", legacy_url=f"sqlite:///{legacy_db}")
    output = capsys.readouterr().out
    assert "ARK_utsc" in output
    assert "3" in output  # three ARKs


def test_a_collection_whose_prefix_is_already_taken_is_reported(legacy_db):
    # Same NAAN, same prefix: a genuine clash.
    Collection.objects.create(name="Existing", prefix="utsc", naan="61220", template=".zd")
    with pytest.raises(Exception, match="(?i)prefix"):
        run_import(legacy_db)


def test_the_same_prefix_under_a_different_naan_is_not_a_clash(legacy_db):
    Collection.objects.create(name="Elsewhere", prefix="utsc", naan="99999", template=".zd")
    run_import(legacy_db)
    assert Collection.objects.filter(prefix="utsc").count() == 2


def test_import_survives_an_identifier_that_does_not_fit_the_template(tmp_path):
    # A hand-created ARK that the template could not have minted must still be
    # imported and resolvable; only its sequence is unknown.
    path = tmp_path / "odd.sqlite3"
    build_legacy_db(path, rows=[(f"61220/utscZZZ{TAB}URL", "https://example.org/odd")])
    run_import(path)
    ark = Ark.objects.get(identifier="utscZZZ")
    assert ark.sequence is None
    assert ark.bindings.get(name="URL").value == "https://example.org/odd"


# --- awkward legacy data --------------------------------------------------


def test_a_key_without_a_naan_is_imported_under_the_collection_naan(tmp_path):
    # Some legacy keys carry only the identifier. Dropping them would lose
    # bindings silently during a one-shot migration.
    path = tmp_path / "no-naan.sqlite3"
    build_legacy_db(path, rows=[(f"utsc7{TAB}URL", "https://example.org/7")])
    run_import(path)
    ark = Ark.objects.get(identifier="utsc7")
    assert ark.naan == "61220"
    assert ark.name == "61220/utsc7"
    assert ark.bindings.get(name="URL").value == "https://example.org/7"


def test_a_collection_without_a_naan_is_refused(tmp_path):
    path = tmp_path / "no-naan-cfg.sqlite3"
    build_legacy_db(
        path, config={":/naan": ""}, rows=[(f"61220/utsc0{TAB}URL", "https://example.org/0")]
    )
    with pytest.raises(Exception, match="(?i)naan"):
        run_import(path)


def test_nothing_is_written_when_a_collection_is_refused(tmp_path):
    path = tmp_path / "no-naan-cfg2.sqlite3"
    build_legacy_db(
        path, config={":/naan": ""}, rows=[(f"61220/utsc0{TAB}URL", "https://example.org/0")]
    )
    with pytest.raises(Exception, match="(?i)naan"):
        run_import(path)
    assert Collection.objects.count() == 0
    assert Ark.objects.count() == 0


def test_a_key_with_extra_tab_components_keeps_them_all_in_the_qualifier(tmp_path):
    path = tmp_path / "deep.sqlite3"
    build_legacy_db(
        path,
        rows=[(f"61220/utsc0{TAB}/vol1{TAB}/page2{TAB}.jpg{TAB}URL", "https://example.org/deep")],
    )
    run_import(path)
    binding = Binding.objects.get(name="URL")
    assert binding.qualifier == "/vol1/page2.jpg"


# --- the import must not hold the whole legacy table in memory ------------


def test_the_legacy_table_is_read_in_batches(tmp_path):
    # LegacyReader.rows() did fetchall() on the whole table, and the command
    # then built two more full copies: 4-5 GB at 1M ARKs, 40-50 GB at 10M, on a
    # VM that does not have it.
    from core.legacy import open_legacy

    path = tmp_path / "big.sqlite3"
    build_legacy_db(
        path,
        rows=[(f"61220/utsc{n}{TAB}URL", f"https://example.org/{n}") for n in range(500)],
    )

    with open_legacy(f"sqlite:///{path}") as reader:
        stream = reader.rows("ARK_utsc")
        assert not isinstance(stream, list), "rows() must stream, not materialise"
        first = next(iter(stream))
        assert len(first) == 2


def test_a_large_import_still_produces_the_right_data(tmp_path):
    path = tmp_path / "many.sqlite3"
    rows = []
    for n in range(400):
        rows.append((f"61220/utsc{n}{TAB}URL", f"https://example.org/{n}"))
        rows.append((f"61220/utsc{n}{TAB}PID", f"islandora:{n}"))
    build_legacy_db(path, rows=rows)

    run_import(path)

    assert Ark.objects.count() == 400
    assert Binding.objects.count() == 800
    assert Ark.objects.get(identifier="utsc399").bindings.count() == 2


def test_a_large_import_is_idempotent(tmp_path):
    path = tmp_path / "again.sqlite3"
    build_legacy_db(
        path,
        rows=[(f"61220/utsc{n}{TAB}URL", f"https://example.org/{n}") for n in range(300)],
    )
    run_import(path)
    run_import(path)
    assert Ark.objects.count() == 300
    assert Binding.objects.count() == 300
