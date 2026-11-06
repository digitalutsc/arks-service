"""
A variant of the object itself: ``ark:/61220/utsc1.image.png``.

The ARK spec defines variants of the whole object as well as of its parts
(§2.5). This system stores one as ARK ``utsc1`` with the qualifier
``.image.png``, and the ARK page, export and template all write it back as
``61220/utsc1.image.png``. But the parser, like legacy's, keeps a dot in the
identifier component, so that spelling was looked up as an ARK called
``utsc1.image.png`` and never resolved.

It is now read as a variant only after the request as written has missed, so an
identifier that really contains a dot keeps exact matching. The staff side
reads it the same way. See INTENTS_object_variants.md.
"""

import csv
import io

import pytest
from django.core.management import CommandError, call_command

from core.arkpath import parse_ark_path
from core.counters import flush_counters
from core.models import Ark, Binding, Collection, Resolution
from core.search import export_rows
from jobs.bulkbind import apply_csv

pytestmark = pytest.mark.django_db


@pytest.fixture
def collection():
    return Collection.objects.create(
        name="UTSC", prefix="utsc", naan="61220", naa="UTSC Library", template=".zd"
    )


@pytest.fixture
def ark(collection):
    ark = Ark.objects.create(collection=collection, identifier="utsc1", sequence=1)
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/1")
    Binding.objects.create(ark=ark, qualifier=".image.png", name="URL", value="https://x.org/1.png")
    Binding.objects.create(ark=ark, qualifier=".image.png", name="WHAT?", value="The image")
    return ark


def get(client, path):
    """Issue a request, preserving the raw URI so a trailing '?' survives."""
    return client.get(path, RAW_URI=path)


# --- the reading ----------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "identifier", "qualifier"),
    [
        ("ark:/61220/utsc1.image.png", "utsc1", ".image.png"),
        ("ark:/61220/utsc1.pdf", "utsc1", ".pdf"),
        ("ark:61220/utsc1.tar.gz", "utsc1", ".tar.gz"),
        # A qualifier after it stays behind the variant, so a service suffix
        # applies to the variant: the manifest of utsc1's .image.png.
        ("ark:/61220/utsc1.image.png/manifest", "utsc1", ".image.png/manifest"),
    ],
)
def test_a_dotted_identifier_reads_as_a_variant_of_the_object(path, identifier, qualifier):
    variant = parse_ark_path(path).object_variant()
    assert (variant.identifier, variant.qualifier) == (identifier, qualifier)


@pytest.mark.parametrize(
    "path",
    [
        "ark:/61220/utsc1",  # no dot
        "ark:/61220/utsc1/page2.image.png",  # a variant of a part: already a qualifier
        "ark:/61220/.png",  # nothing before the dot
        "ark:/61220/utsc1.",  # nothing after it: a trailing full stop, not a variant
    ],
)
def test_there_is_no_object_variant_reading(path):
    assert parse_ark_path(path).object_variant() is None


def test_the_parser_itself_still_keeps_the_dot_in_the_identifier():
    # The legacy parse, unchanged: the variant reading is a fallback, not the parse.
    assert parse_ark_path("ark:/61220/utsc1.image.png").identifier == "utsc1.image.png"


def test_alternatives_are_tried_in_order():
    forms = [
        (form.identifier, form.qualifier)
        for form in parse_ark_path("ark:/61220/utsc-1.image.png").alternatives()
    ]
    assert forms == [
        ("utsc-1", ".image.png"),  # as written, read as a variant
        ("utsc1.image.png", ""),  # normalised
        ("utsc1", ".image.png"),  # normalised, read as a variant
    ]


def test_alternatives_are_not_repeated():
    forms = list(parse_ark_path("ark:/61220/utsc1.image.png").alternatives())
    assert [(f.identifier, f.qualifier) for f in forms] == [("utsc1", ".image.png")]


# --- resolving ------------------------------------------------------------


def test_a_variant_of_the_object_resolves(client, ark):
    response = get(client, "/ark:/61220/utsc1.image.png")
    assert response.status_code == 302
    assert response["Location"] == "https://x.org/1.png"


@pytest.mark.parametrize(
    "path",
    [
        "/ark:61220/utsc1.image.png",
        "/ARK:/61220/utsc1.image.png",
        "/ark:/61220/utsc-1.image.png",
        "/ark:/61220/utsc1.image.png.",
    ],
)
def test_it_resolves_with_the_other_tolerated_spellings(client, ark, path):
    assert get(client, path)["Location"] == "https://x.org/1.png"


def test_the_object_itself_still_resolves(client, ark):
    assert get(client, "/ark:/61220/utsc1")["Location"] == "https://example.org/1"


def test_an_unbound_variant_of_the_object_is_not_found(client, ark):
    # No fallback to the object: exact qualifier matching, as for any variant.
    assert get(client, "/ark:/61220/utsc1.image.jpg").status_code == 404


def test_an_identifier_that_really_contains_a_dot_wins(client, collection, ark):
    dotted = Ark.objects.create(collection=collection, identifier="utsc1.image.png", sequence=0)
    Binding.objects.create(ark=dotted, name="URL", value="https://example.org/dotted")
    assert get(client, "/ark:/61220/utsc1.image.png")["Location"] == "https://example.org/dotted"


def test_the_hit_is_counted_against_the_variant(client, ark):
    get(client, "/ark:/61220/utsc1.image.png")
    flush_counters()
    assert Resolution.objects.get(ark=ark, qualifier=".image.png").count == 1
    assert not Resolution.objects.filter(qualifier="").exists()


def test_an_inflection_on_a_variant_of_the_object_shows_its_elements(client, ark):
    response = get(client, "/ark:/61220/utsc1.image.png??")
    assert response.status_code == 200
    body = response.content.decode()
    assert "What: The image" in body
    assert "Url: https://x.org/1.png" in body


def test_manifest_on_a_variant_of_the_object(client, ark, monkeypatch):
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        return b"{}"

    monkeypatch.setattr("resolver.views.fetch_json", fake_fetch)
    assert get(client, "/ark:/61220/utsc1.image.png/manifest").status_code == 200
    assert fetched == ["https://x.org/1.png"]


def test_an_exact_redirect_still_costs_two_reads(client, ark):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as captured:
        get(client, "/ark:/61220/utsc1")
    selects = [q for q in captured.captured_queries if q["sql"].lower().startswith("select")]
    assert len(selects) <= 2


# --- the staff side reads it the same way ---------------------------------


def run(*args):
    out = io.StringIO()
    call_command(*args, stdout=out, stderr=out)
    return out.getvalue()


def test_bind_accepts_a_variant_of_the_object(ark):
    run("bind", "61220/utsc1.pdf", "URL", "https://x.org/1.pdf")
    assert Binding.objects.get(ark=ark, qualifier=".pdf", name="URL").value == "https://x.org/1.pdf"


def test_unbind_accepts_a_variant_of_the_object(ark):
    run("unbind", "61220/utsc1.image.png", "--all")
    assert not Binding.objects.filter(ark=ark, qualifier=".image.png").exists()
    assert Binding.objects.filter(ark=ark, qualifier="").exists()


def test_bind_still_reports_an_unknown_ark(ark):
    with pytest.raises(CommandError, match="(?i)no such ark"):
        run("bind", "61220/utsc9.pdf", "URL", "https://x.org/9.pdf")


def test_bind_refuses_a_hyphen_in_a_variant_of_the_object(ark):
    with pytest.raises(CommandError, match="(?i)hyphen"):
        run("bind", "61220/utsc1.image-x.png", "URL", "https://x.org/x.png")


def test_bulk_bind_accepts_a_variant_of_the_object(collection, ark):
    result = apply_csv(collection, io.StringIO("Ark_ID,URL\n61220/utsc1.pdf,https://x.org/1.pdf\n"))
    assert result.ok
    assert Binding.objects.get(ark=ark, qualifier=".pdf").value == "https://x.org/1.pdf"


def test_bulk_bind_refuses_a_hyphen_in_a_variant_of_the_object(collection, ark):
    result = apply_csv(collection, io.StringIO("Ark_ID,URL\n61220/utsc1.a-b,https://x.org/\n"))
    assert result.failed == 1
    assert "hyphen" in result.errors[0].message.lower()


def test_bulk_bind_still_fails_an_unknown_ark(collection, ark):
    result = apply_csv(collection, io.StringIO("Ark_ID,URL\n61220/utsc9.pdf,https://x.org/\n"))
    assert result.failed == 1
    assert "not an ARK in this collection" in result.errors[0].message


def test_an_export_round_trips_through_bulk_bind(collection, ark):
    exported = io.StringIO()
    writer = csv.writer(exported)
    for row in export_rows(Ark.objects.filter(pk=ark.pk)):
        writer.writerow(row)
    assert "61220/utsc1.image.png" in exported.getvalue()

    edited = exported.getvalue().replace("https://x.org/1.png", "https://x.org/new.png")
    result = apply_csv(collection, io.StringIO(edited))
    assert result.ok, [row.message for row in result.errors]
    assert Binding.objects.get(ark=ark, qualifier=".image.png", name="URL").value == (
        "https://x.org/new.png"
    )
