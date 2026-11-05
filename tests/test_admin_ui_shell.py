"""
The dashboard shell: environment-aware ARK URLs, and staying inside the CSP.

Staff need the public URL of an ARK to hand to someone, and it has to be the
URL for the environment they are actually looking at — copying a localhost URL
into a catalogue record is a silent mistake. The CSP test is the guard rail:
``script-src 'self'; style-src 'self'`` means an inline ``style=`` or
``onclick=`` is dropped by the browser without any error, so a template that
grows one looks fine locally and quietly stops working.
"""

import re

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from admin_ui.roles import ADMIN, ensure_groups, set_role
from core.models import Ark, Binding, Collection
from jobs.models import BulkBindJob

pytestmark = pytest.mark.django_db

PROD_HOST = "ark.digital.utsc.utoronto.ca"


@pytest.fixture
def admin_client(django_user_model, client):
    ensure_groups()
    user = django_user_model.objects.create_user("boss", password="pw")
    set_role(user, ADMIN)
    client.force_login(user)
    return client


@pytest.fixture
def collection():
    return Collection.objects.create(
        name="UTSC", prefix="utsc", naan="61220", naa="UTSC Library", template=".zd"
    )


@pytest.fixture
def ark(collection):
    return Ark.objects.create(collection=collection, identifier="utsc1", sequence=1)


# --- the ARK's own public path ---------------------------------------------


def test_an_ark_knows_its_resolver_path(ark):
    assert ark.path == "ark:61220/utsc1"


# --- environment detection -------------------------------------------------


def test_a_local_host_gives_a_localhost_base_url_and_says_so(admin_client):
    response = admin_client.get(reverse("admin_ui:collection_list"), HTTP_HOST="localhost:8000")
    assert response.context["ark_base_url"] == "http://localhost:8000/"
    assert response.context["environment_label"] == "Local"
    assert response.context["environment_is_local"] is True


def test_a_proxied_production_host_gives_an_https_base_url(admin_client, settings):
    settings.ALLOWED_HOSTS = [PROD_HOST]
    response = admin_client.get(
        reverse("admin_ui:collection_list"),
        HTTP_HOST=PROD_HOST,
        HTTP_X_FORWARDED_PROTO="https",
    )
    assert response.context["ark_base_url"] == f"https://{PROD_HOST}/"
    assert response.context["environment_label"] == PROD_HOST
    assert response.context["environment_is_local"] is False


def test_an_explicit_public_base_url_wins_over_the_request_host(admin_client, settings):
    # Staff may reach the admin on a different hostname than the resolver.
    settings.ARK_PUBLIC_BASE_URL = f"https://{PROD_HOST}"
    response = admin_client.get(reverse("admin_ui:collection_list"), HTTP_HOST="localhost:8000")
    assert response.context["ark_base_url"] == f"https://{PROD_HOST}/"
    assert response.context["environment_label"] == PROD_HOST
    assert response.context["environment_is_local"] is False


def test_a_configured_base_url_keeps_exactly_one_trailing_slash(admin_client, settings):
    settings.ARK_PUBLIC_BASE_URL = f"https://{PROD_HOST}///"
    response = admin_client.get(reverse("admin_ui:collection_list"))
    assert response.context["ark_base_url"] == f"https://{PROD_HOST}/"


# --- the URL column --------------------------------------------------------


def test_browsing_arks_shows_the_full_public_url_for_this_environment(admin_client, ark):
    body = admin_client.get(
        reverse("admin_ui:ark_list"), {"collection": ark.collection_id}, HTTP_HOST="localhost:8000"
    ).content.decode()
    assert 'href="http://localhost:8000/ark:61220/utsc1"' in body
    assert 'data-copy="http://localhost:8000/ark:61220/utsc1"' in body


def test_the_url_column_follows_the_environment(admin_client, ark, settings):
    settings.ALLOWED_HOSTS = [PROD_HOST]
    body = admin_client.get(
        reverse("admin_ui:ark_list"),
        {"collection": ark.collection_id},
        HTTP_HOST=PROD_HOST,
        HTTP_X_FORWARDED_PROTO="https",
    ).content.decode()
    assert f'href="https://{PROD_HOST}/ark:61220/utsc1"' in body
    assert "localhost" not in body


def test_an_ark_page_shows_its_public_url(admin_client, ark):
    body = admin_client.get(reverse("admin_ui:ark_detail", args=[ark.pk])).content.decode()
    assert 'href="http://testserver/ark:61220/utsc1"' in body


def test_freshly_minted_arks_show_their_public_urls(admin_client, collection):
    body = admin_client.post(
        reverse("admin_ui:mint", args=[collection.pk]), {"count": "2"}
    ).content.decode()
    # A fresh .zd minter counts from zero.
    assert 'href="http://testserver/ark:61220/utsc0"' in body
    assert 'href="http://testserver/ark:61220/utsc1"' in body


# --- the dashboard ---------------------------------------------------------


def test_the_dashboard_counts_collections_and_arks(admin_client, collection):
    Ark.objects.create(collection=collection, identifier="utsc1", sequence=1)
    Ark.objects.create(collection=collection, identifier="utsc2", sequence=2)
    response = admin_client.get(reverse("admin_ui:collection_list"))
    assert response.context["collection_count"] == 1
    assert response.context["ark_total"] == 2
    assert response.context["running_jobs"] == 0


def test_the_dashboard_counts_jobs_that_are_still_running(admin_client, collection):
    BulkBindJob.objects.create(collection=collection, status=BulkBindJob.Status.RUNNING)
    BulkBindJob.objects.create(collection=collection, status=BulkBindJob.Status.FINISHED)
    response = admin_client.get(reverse("admin_ui:collection_list"))
    assert response.context["running_jobs"] == 1


# --- the CSP guard ---------------------------------------------------------

#: Anything the browser would refuse to run under ``script-src 'self'`` and
#: ``style-src 'self'`` (see arkservice.middleware.DEFAULT_CSP).
INLINE_STYLE = re.compile(r"\sstyle\s*=")
INLINE_HANDLER = re.compile(r"\son(?:click|change|submit|input|load|focus|blur|keyup)\s*=")


def admin_pages(collection, ark, job):
    return [
        reverse("admin_ui:collection_list"),
        reverse("admin_ui:collection_create"),
        reverse("admin_ui:collection_detail", args=[collection.pk]),
        reverse("admin_ui:mint", args=[collection.pk]),
        reverse("admin_ui:bulk_bind", args=[collection.pk]),
        reverse("admin_ui:ark_list") + f"?collection={collection.pk}",
        reverse("admin_ui:ark_detail", args=[ark.pk]),
        reverse("admin_ui:job_detail", args=[job.pk]),
        reverse("admin_ui:user_list"),
    ]


def test_no_admin_page_relies_on_inline_styles_or_handlers(
    admin_client, collection, ark, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    Binding.objects.create(ark=ark, name="URL", value="https://example.org/1")
    # And a variant, so the ARK page draws a qualified section as well.
    Binding.objects.create(ark=ark, qualifier="/p1", name="URL", value="https://example.org/1/p1")
    job = BulkBindJob.objects.create(collection=collection, status=BulkBindJob.Status.FINISHED)
    # With a results file, so the job page draws its table, filters and pager.
    job.results.save(
        "results.csv", ContentFile(b"row,ark_id,status,message\n2,61220/utsc1,ok,\n"), save=True
    )
    for url in admin_pages(collection, ark, job):
        body = admin_client.get(url).content.decode()
        if url == reverse("admin_ui:job_detail", args=[job.pk]):
            assert "<table" in body, "the job page did not draw its results table"
        assert not INLINE_STYLE.search(body), f"inline style= on {url}"
        assert not INLINE_HANDLER.search(body), f"inline event handler on {url}"


def test_the_sign_in_page_relies_on_neither_either(client):
    body = client.get(reverse("admin_ui:login")).content.decode()
    assert not INLINE_STYLE.search(body)
    assert not INLINE_HANDLER.search(body)


def test_every_admin_page_loads_the_stylesheet_and_the_shell_script(admin_client, collection, ark):
    job = BulkBindJob.objects.create(collection=collection, status=BulkBindJob.Status.FINISHED)
    for url in admin_pages(collection, ark, job):
        body = admin_client.get(url).content.decode()
        assert "css/app" in body, f"no stylesheet on {url}"
        assert "js/app" in body, f"no shell script on {url}"


# --- readability of large counts ------------------------------------------


def test_large_counts_are_written_with_thousands_separators(admin_client, collection):
    # Production holds ~100k ARKs in one collection; "101204" is unreadable.
    Ark.objects.bulk_create(
        Ark(collection=collection, naan=collection.naan, identifier=f"utsc{n}") for n in range(1000)
    )
    body = admin_client.get(reverse("admin_ui:collection_list")).content.decode()
    assert "1,000" in body
    assert ">1000<" not in body
