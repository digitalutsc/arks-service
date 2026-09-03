"""
Importing the legacy database.

Legacy stored everything as tab-separated keys in one table per collection:

    :/naa, :/naan, :/template, :/prefix ...   reserved configuration
    61220/utsc1<TAB>URL                       an element on the ARK itself
    61220/utsc1<TAB>/page1<TAB>URL            an element on a hierarchical part
    61220/utsc1<TAB>/page1<TAB>.png<TAB>URL   ... with a variant
    61220/utsc1<TAB>:/c                       circulation record (when it was minted)
    61220/utsc1<TAB>:/h                       hold marker (dropped)

The importer must read those literally rather than re-deriving them, so
whatever is actually in production survives the move intact. The same data
arrives two ways — a live database, or the export file a handover actually
consists of — and both must produce the same result.
"""

import csv
import os
import shutil
import sqlite3
import subprocess

import pytest
from django.core.management import call_command
from django.db import connection as django_connection

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


LEGACY_CONFIG = {
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


def build_legacy_db(path, rows=None, config=None):
    """Create a throwaway database shaped like the legacy one."""
    defaults = dict(LEGACY_CONFIG)
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


def _sql_quote(text):
    escaped = (
        str(text)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )
    return f"'{escaped}'"


def write_legacy_dump(path, rows=None, config=None, table="ARK_utsc"):
    """Write the same content as build_legacy_db, as a phpMyAdmin export."""
    defaults = dict(LEGACY_CONFIG)
    defaults.update(config or {})
    payload = list(defaults.items()) + list(rows or [])

    lines = [
        "-- phpMyAdmin SQL Dump",
        "/*!40101 SET NAMES utf8mb4 */;",
        "START TRANSACTION;",
        "",
        f"CREATE TABLE `{table}` (",
        "  `_key` varchar(512) COLLATE utf8mb4_general_ci NOT NULL,",
        "  `_value` varchar(4096) COLLATE utf8mb4_general_ci DEFAULT NULL",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;",
        "",
        f"INSERT INTO `{table}` (`_key`, `_value`) VALUES",
    ]
    body = [f"({_sql_quote(key)}, {_sql_quote(value)})" for key, value in payload]
    lines.append(",\n".join(body) + ";")
    lines += [
        "",
        "INSERT INTO `system` (`_key`, `_value`) VALUES",
        "('Organization Name', 'UTSC DSU'),",
        "('Organization Website', 'https://dsu.example');",
        "COMMIT;",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def read_report(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


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


# --- the export file ------------------------------------------------------


def run_import_dump(path, **options):
    call_command("import_legacy", legacy_dump=str(path), verbosity=0, **options)


CIRCULATION = "i|20201022094659|1603374419|1"

RICH_ROWS = [
    (f"61220/utsc0{TAB}URL", "https://example.org/0?a=1&amp;b=2"),
    (f"61220/utsc0{TAB}WHAT?", "Fish &amp; Chips"),
    (f"61220/utsc0{TAB}:/c", CIRCULATION),
    (f"61220/utsc0{TAB}:/h", "1"),
    (f"61220/utsc1{TAB}/page1{TAB}.image.png{TAB}URL", "https://example.org/1.png"),
    (f"61220/utsc1{TAB}REDIRECT", "37"),
    (f"61220/utsc1{TAB}:/c", "i|20210101120000|1609513200|2"),
    (f"61220/utsc2{TAB}:/c", "i|20220101120000|1641056400|3"),
]


def snapshot():
    return {
        "arks": sorted(Ark.objects.values_list("naan", "identifier", "sequence")),
        "bindings": sorted(
            Binding.objects.values_list("ark__identifier", "qualifier", "name", "value")
        ),
        "resolutions": sorted(
            Resolution.objects.values_list("ark__identifier", "qualifier", "count")
        ),
        "minted": sorted(Ark.objects.values_list("identifier", "minted_at")),
    }


def test_an_export_file_imports_exactly_like_the_database(tmp_path):
    build_legacy_db(tmp_path / "same.sqlite3", rows=RICH_ROWS)
    write_legacy_dump(tmp_path / "same.sql", rows=RICH_ROWS)

    run_import(tmp_path / "same.sqlite3")
    from_database = snapshot()

    Collection.objects.all().delete()
    run_import_dump(tmp_path / "same.sql")

    assert snapshot() == from_database
    assert from_database["arks"]  # and it was not simply empty both times


def test_exactly_one_source_must_be_given(legacy_db):
    with pytest.raises(Exception, match="(?i)exactly one"):
        call_command("import_legacy", verbosity=0)
    with pytest.raises(Exception, match="(?i)exactly one"):
        call_command(
            "import_legacy",
            legacy_url=f"sqlite:///{legacy_db}",
            legacy_dump=str(legacy_db),
            verbosity=0,
        )


def test_a_missing_export_file_is_reported(tmp_path):
    with pytest.raises(Exception, match="(?i)no such file"):
        run_import_dump(tmp_path / "absent.sql")


# --- identifiers that legacy minted but never bound -----------------------


def test_an_ark_that_was_minted_but_never_bound_is_imported(tmp_path):
    # A fifth of production is like this: minted, held, never given a URL.
    # Dropping them would lose the identifiers and let minting reissue them.
    path = tmp_path / "unbound.sqlite3"
    build_legacy_db(
        path,
        rows=[
            (f"61220/utsc5{TAB}:/c", CIRCULATION),
            (f"61220/utsc5{TAB}:/h", "1"),
        ],
    )
    run_import(path)
    ark = Ark.objects.get(identifier="utsc5")
    assert ark.bindings.count() == 0
    assert ark.sequence == 5


def test_minting_does_not_reissue_an_imported_unbound_identifier(tmp_path):
    from minting.minter import mint

    path = tmp_path / "unbound2.sqlite3"
    build_legacy_db(path, rows=[(f"61220/utsc20{TAB}:/c", CIRCULATION)])
    run_import(path)
    minted = mint(Collection.objects.get(name="ARK_utsc"), 1)
    assert minted[0].identifier == "utsc21"


def test_minted_at_comes_from_the_circulation_record(tmp_path):
    path = tmp_path / "minted.sqlite3"
    build_legacy_db(path, rows=[(f"61220/utsc5{TAB}:/c", CIRCULATION)])
    run_import(path)
    assert Ark.objects.get(identifier="utsc5").minted_at.timestamp() == 1603374419


def test_an_unreadable_circulation_record_leaves_the_default(tmp_path):
    path = tmp_path / "junkcirc.sqlite3"
    build_legacy_db(
        path,
        rows=[
            (f"61220/utsc5{TAB}URL", "https://example.org/5"),
            (f"61220/utsc5{TAB}:/c", "uncirculated"),
        ],
    )
    run_import(path)
    assert Ark.objects.get(identifier="utsc5").minted_at is not None


# --- rows that cannot be carried over verbatim ----------------------------


def test_a_redirect_only_identifier_is_skipped_and_reported(tmp_path):
    # The legacy resolver wrote a REDIRECT row for anything anyone requested,
    # including crawler URLs that were never ARKs at all.
    path = tmp_path / "junk.sql"
    write_legacy_dump(
        path,
        rows=[
            (f"61220/utsc0{TAB}URL", "https://example.org/0"),
            (f"61220/utsc0{TAB}:/c", CIRCULATION),
            (f"61220/utsc35657biblio{TAB}REDIRECT", "8"),
        ],
    )
    report = tmp_path / "report.csv"
    run_import_dump(path, report=str(report))

    assert not Ark.objects.filter(identifier="utsc35657biblio").exists()
    assert Ark.objects.count() == 1
    rows = read_report(report)
    assert [row["reason"] for row in rows] == ["redirect-for-unknown-ark"]
    assert "utsc35657biblio" in rows[0]["ark_path"]


def test_a_redirect_that_precedes_its_arks_other_rows_still_counts(tmp_path):
    path = tmp_path / "order.sql"
    write_legacy_dump(
        path,
        rows=[
            (f"61220/utsc5{TAB}/page1{TAB}REDIRECT", "9"),
            (f"61220/utsc5{TAB}:/c", CIRCULATION),
        ],
    )
    run_import_dump(path)
    resolution = Resolution.objects.get(ark__identifier="utsc5", qualifier="/page1")
    assert resolution.count == 9


def test_a_carriage_return_twin_loses_to_the_clean_element_and_is_reported(tmp_path):
    path = tmp_path / "crlf.sql"
    write_legacy_dump(
        path,
        rows=[
            (f"61220/utsc0{TAB}COLLECTION", "Clean Collection"),
            (f"61220/utsc0{TAB}COLLECTION\r", "CRLF Collection"),
        ],
    )
    report = tmp_path / "report.csv"
    run_import_dump(path, report=str(report))

    assert Binding.objects.get(name="COLLECTION").value == "Clean Collection"
    rows = read_report(report)
    assert [row["reason"] for row in rows] == ["duplicate-element"]
    assert rows[0]["value"] == "CRLF Collection"
    assert rows[0]["element"] == "COLLECTION"


def test_the_clean_element_wins_whichever_order_the_rows_arrive_in(tmp_path):
    path = tmp_path / "crlf2.sql"
    write_legacy_dump(
        path,
        rows=[
            (f"61220/utsc0{TAB}COLLECTION\r", "CRLF Collection"),
            (f"61220/utsc0{TAB}COLLECTION", "Clean Collection"),
        ],
    )
    run_import_dump(path)
    assert Binding.objects.get(name="COLLECTION").value == "Clean Collection"


def test_a_lone_carriage_return_element_is_kept_under_its_clean_name(tmp_path):
    path = tmp_path / "crlf3.sql"
    write_legacy_dump(path, rows=[(f"61220/utsc0{TAB}TITLE\r", "Only spelling\r")])
    run_import_dump(path)
    binding = Binding.objects.get(ark__identifier="utsc0")
    assert binding.name == "TITLE"
    assert binding.value == "Only spelling"


def test_entity_encoded_values_are_stored_decoded(tmp_path):
    path = tmp_path / "entities.sqlite3"
    build_legacy_db(
        path,
        rows=[
            (f"61220/utsc0{TAB}URL", "https://example.org/search?a=1&amp;b=2"),
            (f"61220/utsc0{TAB}WHAT?", "&quot;Quoted&quot; &#039;title&#039;"),
        ],
    )
    run_import(path)
    ark = Ark.objects.get(identifier="utsc0")
    assert ark.bindings.get(name="URL").value == "https://example.org/search?a=1&b=2"
    assert ark.bindings.get(name="WHAT?").value == "\"Quoted\" 'title'"


def test_dry_run_still_writes_the_report(tmp_path):
    path = tmp_path / "dry.sql"
    write_legacy_dump(path, rows=[(f"61220/utsc35657biblio{TAB}REDIRECT", "8")])
    report = tmp_path / "report.csv"
    run_import_dump(path, report=str(report), dry_run=True)
    assert Ark.objects.count() == 0
    assert read_report(report)[0]["reason"] == "redirect-for-unknown-ark"


def test_nothing_is_reported_when_everything_carries_over(tmp_path):
    path = tmp_path / "clean.sql"
    write_legacy_dump(path, rows=[(f"61220/utsc0{TAB}URL", "https://example.org/0")])
    report = tmp_path / "report.csv"
    run_import_dump(path, report=str(report))
    assert read_report(report) == []


# --- naming ---------------------------------------------------------------


def test_collection_name_targets_a_renamed_collection(legacy_db):
    run_import(legacy_db, collection_name="UTSC Digital Collections")
    collection = Collection.objects.get()
    assert collection.name == "UTSC Digital Collections"
    assert collection.prefix == "utsc"

    # And re-importing under that name updates it rather than making a second.
    run_import(legacy_db, collection_name="UTSC Digital Collections")
    assert Collection.objects.count() == 1


def test_collection_name_is_refused_when_the_source_has_several_collections(tmp_path):
    path = tmp_path / "two.sql"
    write_legacy_dump(path, rows=[(f"61220/utsc0{TAB}URL", "https://example.org/0")])
    with open(path, "a") as handle:
        handle.write(
            "\nINSERT INTO `ARK_other` (`_key`, `_value`) VALUES\n"
            "(':/naan', '61220'),\n(':/prefix', 'other');\n"
        )
    with pytest.raises(Exception, match="(?i)--collection-name"):
        run_import_dump(path, collection_name="Only One")


# --- the real exporter ----------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_real_mysqldump_of_a_legacy_shaped_table_imports(tmp_path):
    """The format tests are hand-written; this one is written by mysqldump."""
    if django_connection.vendor != "mysql":
        pytest.skip("needs the MySQL engine")
    if not shutil.which("mysqldump"):
        pytest.skip("needs the mysqldump client")

    table = "legacy_export_check"
    payload = list(LEGACY_CONFIG.items()) + [
        (f"61220/utsc0{TAB}URL", "https://example.org/0?a=1&amp;b=2"),
        (f"61220/utsc0{TAB}/page1{TAB}.image.png{TAB}URL", "https://example.org/0.png"),
        (f"61220/utsc0{TAB}COLLECTION\r", "CRLF Collection"),
        (f"61220/utsc0{TAB}:/c", CIRCULATION),
        (f"61220/utsc1{TAB}WHAT?", 'quote\'s and "quotes" and \\ backslash'),
        (f"61220/utsc1{TAB}:/c", CIRCULATION),
    ]
    settings_dict = django_connection.settings_dict
    try:
        with django_connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS `{table}`")
            cursor.execute(
                f"CREATE TABLE `{table}` ("
                "`_key` VARCHAR(512) NOT NULL, `_value` VARCHAR(4096) DEFAULT NULL, "
                "PRIMARY KEY (`_key`)) DEFAULT CHARSET=utf8mb4"
            )
            cursor.executemany(f"INSERT INTO `{table}` VALUES (%s, %s)", payload)

        dump = tmp_path / "real.sql"
        result = subprocess.run(
            [
                "mysqldump",
                "--no-create-info",
                "--default-character-set=utf8mb4",
                f"--host={settings_dict['HOST'] or '127.0.0.1'}",
                f"--port={settings_dict['PORT'] or 3306}",
                f"--user={settings_dict['USER']}",
                settings_dict["NAME"],
                table,
            ],
            env=dict(os.environ, MYSQL_PWD=settings_dict["PASSWORD"] or ""),
            check=True,
            capture_output=True,
        )
        dump.write_bytes(result.stdout)

        run_import_dump(dump)

        ark = Ark.objects.get(identifier="utsc0")
        assert ark.bindings.get(qualifier="", name="URL").value == ("https://example.org/0?a=1&b=2")
        assert ark.bindings.get(qualifier="/page1.image.png", name="URL").value == (
            "https://example.org/0.png"
        )
        assert ark.bindings.get(name="COLLECTION").value == "CRLF Collection"
        assert ark.minted_at.timestamp() == 1603374419
        assert Ark.objects.get(identifier="utsc1").bindings.get(name="WHAT?").value == (
            'quote\'s and "quotes" and \\ backslash'
        )
    finally:
        with django_connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS `{table}`")
