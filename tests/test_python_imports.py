"""Reviewed Python distribution-to-import mapping tests."""

import pytest

from dependabot_validator_grunt.python_imports import (
    PYTHON_IMPORT_MAPPING_VERSION,
    python_import_targets,
)


@pytest.mark.parametrize(
    ("distribution", "targets", "authoritative"),
    [
        ("pillow", ("PIL",), False),
        ("pyyaml", ("yaml",), True),
        ("scikit-learn", ("sklearn",), True),
        ("beautifulsoup4", ("bs4",), True),
        ("opencv-python", ("cv2",), False),
        ("python-dateutil", ("dateutil",), False),
        ("python-dotenv", ("dotenv",), False),
        ("typing-extensions", ("typing_extensions",), True),
        ("django-cors-headers", ("corsheaders",), True),
        ("djangorestframework", ("rest_framework",), True),
        ("psycopg2-binary", ("psycopg2",), False),
        ("pyjwt", ("jwt",), False),
        ("python-jose", ("jose",), False),
        ("python-multipart", ("multipart",), False),
        ("email-validator", ("email_validator",), True),
        ("grpcio", ("grpc",), True),
        ("apache-airflow", ("airflow",), True),
        ("ansible-core", ("ansible",), True),
        ("ipython", ("IPython",), True),
        ("pycryptodome", ("Crypto",), False),
    ],
)
def test_curated_python_import_targets(
    distribution: str,
    targets: tuple[str, ...],
    authoritative: bool,
) -> None:
    result = python_import_targets(distribution)

    assert PYTHON_IMPORT_MAPPING_VERSION == "1.0"
    assert tuple(target.value for target in result) == targets
    assert all(target.provenance == "curated_mapping" for target in result)
    assert all(target.authoritative is authoritative for target in result)


def test_same_name_python_import_target_remains_authoritative() -> None:
    result = python_import_targets("requests")

    assert tuple(target.value for target in result) == ("requests",)
    assert result[0].provenance == "canonical_distribution"
    assert result[0].authoritative is True


@pytest.mark.parametrize("distribution", ["jwt", "multipart", "psycopg2", "msgpack"])
def test_known_colliding_same_name_target_is_advisory(distribution: str) -> None:
    result = python_import_targets(distribution)

    assert tuple(target.value for target in result) == (distribution,)
    assert result[0].provenance == "canonical_distribution"
    assert result[0].authoritative is False


@pytest.mark.parametrize("distribution", ["google-auth", "azure-core", "zope-interface"])
def test_shared_namespace_distributions_are_not_guessed(distribution: str) -> None:
    assert python_import_targets(distribution) == ()
