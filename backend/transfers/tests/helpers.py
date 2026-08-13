"""Shared helpers for the API tests: URL builders and well-formed unknown identifiers.

URLs go through reverse() so routing knowledge lives only in config/urls.py; a renamed
route fails here with a NoReverseMatch naming the missing route, not as an opaque 404
assertion somewhere downstream.
"""

from django.urls import reverse

# Syntactically valid per REFERENCE_PATTERN, guaranteed never minted (ids are random hex).
UNKNOWN_REFERENCE = "TRF-" + "0" * 16


def create_url() -> str:
    return reverse("transfer-list")


def detail_url(reference: str) -> str:
    return reverse("transfer-detail", args=[reference])


def submit_url(reference: str) -> str:
    return reverse("transfer-submit", args=[reference])


def cancel_url(reference: str) -> str:
    return reverse("transfer-cancel", args=[reference])
