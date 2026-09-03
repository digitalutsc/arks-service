"""
Reading a mysqldump or phpMyAdmin export of the legacy database.

Production is handed over as a ``.sql`` file, not a live database, so the
importer reads the export directly rather than needing it restored into a
scratch MySQL server first. Both exporters are supported: phpMyAdmin writes one
row per line, mysqldump packs a whole table into one extended INSERT.
"""

import gzip

import pytest

from core.legacy import (
    DumpFormatError,
    decode_legacy_text,
    open_legacy_dump,
    parse_circulation,
)

TAB = "\t"

PHPMYADMIN = "\n".join(
    [
        "-- phpMyAdmin SQL Dump",
        "-- Host: dsu-sql:3306",
        "",
        "/*!40101 SET NAMES utf8mb4 */;",
        "START TRANSACTION;",
        "",
        "CREATE TABLE `dsu_ark` (",
        "  `_key` varchar(512) COLLATE utf8mb4_general_ci NOT NULL,",
        "  `_value` varchar(4096) COLLATE utf8mb4_general_ci DEFAULT NULL",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;",
        "",
        "INSERT INTO `dsu_ark` (`_key`, `_value`) VALUES",
        "(':/naan', '61220'),",
        f"('61220/utsc0{TAB}URL', 'https://example.org/0'),",
        f"('61220/utsc0{TAB}/page1{TAB}.png{TAB}URL', 'https://example.org/0.png');",
        "",
        "INSERT INTO `system` (`_key`, `_value`) VALUES",
        "('Organization Name', 'Ark Ids Services'),",
        "('Organization Website', 'https://ark.example.org/');",
        "",
        "ALTER TABLE `dsu_ark`",
        "  ADD PRIMARY KEY (`_key`);",
        "COMMIT;",
    ]
)


def write(tmp_path, text, name="dump.sql", encoding="utf-8"):
    path = tmp_path / name
    path.write_text(text, encoding=encoding)
    return path


# --- the two export shapes ------------------------------------------------


def test_a_phpmyadmin_export_is_read_row_by_row(tmp_path):
    with open_legacy_dump(write(tmp_path, PHPMYADMIN)) as reader:
        assert reader.collection_tables() == ["dsu_ark"]
        assert list(reader.rows("dsu_ark")) == [
            (":/naan", "61220"),
            (f"61220/utsc0{TAB}URL", "https://example.org/0"),
            (f"61220/utsc0{TAB}/page1{TAB}.png{TAB}URL", "https://example.org/0.png"),
        ]


def test_a_mysqldump_extended_insert_on_one_line_is_read(tmp_path):
    dump = "\n".join(
        [
            "/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;",
            "DROP TABLE IF EXISTS `dsu_ark`;",
            "CREATE TABLE `dsu_ark` (",
            "  `_key` varchar(512) NOT NULL,",
            "  `_value` varchar(4096) DEFAULT NULL,",
            "  PRIMARY KEY (`_key`)",
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;",
            "LOCK TABLES `dsu_ark` WRITE;",
            "/*!40000 ALTER TABLE `dsu_ark` DISABLE KEYS */;",
            f"INSERT INTO `dsu_ark` VALUES (':/naan','61220'),"
            f"('61220/utsc0{TAB}URL','https://example.org/0'),"
            f"('61220/utsc1{TAB}URL','https://example.org/1');",
            "/*!40000 ALTER TABLE `dsu_ark` ENABLE KEYS */;",
            "UNLOCK TABLES;",
        ]
    )
    with open_legacy_dump(write(tmp_path, dump)) as reader:
        assert reader.collection_tables() == ["dsu_ark"]
        assert list(reader.rows("dsu_ark")) == [
            (":/naan", "61220"),
            (f"61220/utsc0{TAB}URL", "https://example.org/0"),
            (f"61220/utsc1{TAB}URL", "https://example.org/1"),
        ]


def test_several_statements_for_one_table_are_all_read(tmp_path):
    dump = "\n".join(
        [
            "INSERT INTO `dsu_ark` (`_key`, `_value`) VALUES",
            "('a', '1');",
            "INSERT INTO `dsu_ark` (`_key`, `_value`) VALUES",
            "('b', '2');",
        ]
    )
    with open_legacy_dump(write(tmp_path, dump)) as reader:
        assert list(reader.rows("dsu_ark")) == [("a", "1"), ("b", "2")]


# --- values ---------------------------------------------------------------


def test_mysql_escapes_and_doubled_quotes_are_unescaped(tmp_path):
    dump = "\n".join(
        [
            "INSERT INTO `dsu_ark` (`_key`, `_value`) VALUES",
            r"('a\tb', 'line\none\r\ntwo'),",
            r"('quote''s', 'back\\slash'),",
            r"('apostrophe\'s', 'a, b) c');",
        ]
    )
    with open_legacy_dump(write(tmp_path, dump)) as reader:
        assert list(reader.rows("dsu_ark")) == [
            ("a\tb", "line\none\r\ntwo"),
            ("quote's", "back\\slash"),
            ("apostrophe's", "a, b) c"),
        ]


def test_a_null_value_is_read_as_empty(tmp_path):
    dump = "INSERT INTO `dsu_ark` (`_key`, `_value`) VALUES\n('a', NULL);"
    with open_legacy_dump(write(tmp_path, dump)) as reader:
        assert list(reader.rows("dsu_ark")) == [("a", "")]


def test_a_value_that_spans_lines_is_joined(tmp_path):
    dump = "\n".join(
        [
            "INSERT INTO `dsu_ark` (`_key`, `_value`) VALUES",
            "(':/erc', 'erc:",
            "who: utsc');",
        ]
    )
    with open_legacy_dump(write(tmp_path, dump)) as reader:
        assert list(reader.rows("dsu_ark")) == [(":/erc", "erc:\nwho: utsc")]


def test_columns_are_matched_by_name_not_position(tmp_path):
    dump = "\n".join(
        [
            "INSERT INTO `dsu_ark` (`_value`, `_key`) VALUES",
            "('https://example.org/0', '61220/utsc0');",
        ]
    )
    with open_legacy_dump(write(tmp_path, dump)) as reader:
        assert list(reader.rows("dsu_ark")) == [("61220/utsc0", "https://example.org/0")]


# --- what is and is not a collection --------------------------------------


def test_system_and_user_are_not_collection_tables(tmp_path):
    dump = "\n".join(
        [
            PHPMYADMIN,
            "CREATE TABLE `user` (",
            "  `id` int UNSIGNED NOT NULL,",
            "  `username` varchar(50) NOT NULL",
            ") ENGINE=InnoDB;",
            "INSERT INTO `user` VALUES (1, 'dsuadmin');",
        ]
    )
    with open_legacy_dump(write(tmp_path, dump)) as reader:
        assert reader.collection_tables() == ["dsu_ark"]


def test_a_table_without_key_and_value_columns_is_not_a_collection(tmp_path):
    dump = "\n".join(
        [
            "CREATE TABLE `visits` (",
            "  `id` int NOT NULL,",
            "  `seen` datetime DEFAULT NULL",
            ") ENGINE=InnoDB;",
            "INSERT INTO `visits` VALUES (1, '2026-01-01 00:00:00');",
            "INSERT INTO `dsu_ark` (`_key`, `_value`) VALUES ('a', '1');",
        ]
    )
    with open_legacy_dump(write(tmp_path, dump)) as reader:
        assert reader.collection_tables() == ["dsu_ark"]


def test_the_system_table_is_read_without_decoding(tmp_path):
    dump = "\n".join(
        [
            "INSERT INTO `system` (`_key`, `_value`) VALUES",
            "('Organization Name', 'Books &amp; Records');",
        ]
    )
    with open_legacy_dump(write(tmp_path, dump)) as reader:
        assert reader.system_settings() == {"Organization Name": "Books &amp; Records"}


# --- entity decoding ------------------------------------------------------


def test_the_five_entities_legacy_wrote_are_decoded():
    assert decode_legacy_text("Fish &amp; Chips") == "Fish & Chips"
    assert decode_legacy_text("&lt;i&gt;Title&lt;/i&gt;") == "<i>Title</i>"
    assert decode_legacy_text("say &quot;hello&quot;") == 'say "hello"'
    assert decode_legacy_text("it&#039;s") == "it's"


def test_entities_are_decoded_exactly_once():
    # Legacy encoded what the curator typed. Someone who typed "&lt;" has it
    # stored as "&amp;lt;", and must get "&lt;" back, not "<".
    assert decode_legacy_text("&amp;lt;") == "&lt;"
    assert decode_legacy_text("&amp;amp;") == "&amp;"


def test_values_are_decoded_when_read(tmp_path):
    dump = "\n".join(
        [
            "INSERT INTO `dsu_ark` (`_key`, `_value`) VALUES",
            "('61220/utsc0\tWHAT?', 'Fish &amp; Chips');",
        ]
    )
    with open_legacy_dump(write(tmp_path, dump)) as reader:
        assert list(reader.rows("dsu_ark")) == [("61220/utsc0\tWHAT?", "Fish & Chips")]


def test_a_trailing_carriage_return_is_stripped_from_the_value(tmp_path):
    dump = "\n".join(
        [
            "INSERT INTO `dsu_ark` (`_key`, `_value`) VALUES",
            r"('61220/utsc0" + TAB + r"TITLE\r', 'Digital File Name: _A1\r');",
        ]
    )
    with open_legacy_dump(write(tmp_path, dump)) as reader:
        # The name keeps its carriage return - the importer needs to see which
        # spelling a row used - but the value is cleaned up.
        assert list(reader.rows("dsu_ark")) == [
            (f"61220/utsc0{TAB}TITLE\r", "Digital File Name: _A1")
        ]


# --- files ----------------------------------------------------------------


def test_a_gzipped_dump_is_read(tmp_path):
    path = tmp_path / "dump.sql.gz"
    path.write_bytes(gzip.compress(PHPMYADMIN.encode("utf-8")))
    with open_legacy_dump(path) as reader:
        assert reader.collection_tables() == ["dsu_ark"]
        assert len(list(reader.rows("dsu_ark"))) == 3


def test_a_missing_file_is_reported(tmp_path):
    with (
        pytest.raises(DumpFormatError, match="No such file|not readable"),
        open_legacy_dump(tmp_path / "nope.sql"),
    ):
        pass


def test_a_dump_in_another_encoding_can_be_read(tmp_path):
    dump = "INSERT INTO `dsu_ark` (`_key`, `_value`) VALUES\n('a', 'café');"
    path = write(tmp_path, dump, encoding="latin-1")
    with open_legacy_dump(path, encoding="latin-1") as reader:
        assert list(reader.rows("dsu_ark")) == [("a", "café")]


def test_a_dump_in_the_wrong_encoding_says_how_to_fix_it(tmp_path):
    dump = "INSERT INTO `dsu_ark` (`_key`, `_value`) VALUES\n('a', 'café');"
    path = write(tmp_path, dump, encoding="latin-1")
    with pytest.raises(DumpFormatError, match="encoding"), open_legacy_dump(path) as reader:
        list(reader.rows("dsu_ark"))


# --- malformed input ------------------------------------------------------


def test_an_unterminated_string_reports_the_line_number(tmp_path):
    dump = "\n".join(
        [
            "INSERT INTO `dsu_ark` (`_key`, `_value`) VALUES",
            "('a', 'ok'),",
            "('b', 'oops),",
        ]
    )
    with (
        pytest.raises(DumpFormatError, match="line 3"),
        open_legacy_dump(write(tmp_path, dump)) as reader,
    ):
        list(reader.rows("dsu_ark"))


def test_unreadable_content_inside_a_statement_reports_the_line_number(tmp_path):
    dump = "\n".join(
        [
            "INSERT INTO `dsu_ark` (`_key`, `_value`) VALUES",
            "('a', 'ok'),",
            "nonsense here,",
            "('b', '2');",
        ]
    )
    with (
        pytest.raises(DumpFormatError, match="line 3"),
        open_legacy_dump(write(tmp_path, dump)) as reader,
    ):
        list(reader.rows("dsu_ark"))


def test_a_file_that_is_not_a_dump_has_no_collections(tmp_path):
    with open_legacy_dump(write(tmp_path, "hello, world\n")) as reader:
        assert reader.collection_tables() == []


# --- circulation records --------------------------------------------------


def test_parse_circulation_prefers_the_epoch(settings):
    settings.TIME_ZONE = "America/Toronto"
    minted = parse_circulation("i|20201022094659|1603374419|1")
    assert minted is not None
    assert minted.isoformat().startswith("2020-10-22")
    assert minted.timestamp() == 1603374419


def test_parse_circulation_falls_back_to_the_local_timestamp(settings):
    settings.TIME_ZONE = "America/Toronto"
    minted = parse_circulation("i|20201022094659||1")
    assert minted is not None
    # Read in the service's own time zone, which is where legacy ran - which is
    # why it agrees with the epoch legacy stored beside it.
    assert minted.timestamp() == 1603374419


@pytest.mark.parametrize(
    "value",
    ["", "uncirculated", "i", "i|not-a-date|not-an-epoch|1", "|||"],
)
def test_parse_circulation_gives_up_quietly_on_junk(value):
    assert parse_circulation(value) is None
