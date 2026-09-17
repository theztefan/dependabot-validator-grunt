"""Reviewed Python distribution-to-import target mapping."""

from __future__ import annotations

import keyword

from dependabot_validator_grunt.models import ImportTarget

PYTHON_IMPORT_MAPPING_VERSION = "1.0"

_CURATED_IMPORT_TARGETS: dict[str, tuple[str, ...]] = {
    "ansible-core": ("ansible",),
    "apache-airflow": ("airflow",),
    "beautifulsoup4": ("bs4",),
    "django-cors-headers": ("corsheaders",),
    "djangorestframework": ("rest_framework",),
    "email-validator": ("email_validator",),
    "grpcio": ("grpc",),
    "importlib-metadata": ("importlib_metadata",),
    "ipython": ("IPython",),
    "jupyter-client": ("jupyter_client",),
    "jupyter-core": ("jupyter_core",),
    "msgpack-python": ("msgpack",),
    "opencv-contrib-python": ("cv2",),
    "opencv-contrib-python-headless": ("cv2",),
    "opencv-python": ("cv2",),
    "opencv-python-headless": ("cv2",),
    "pillow": ("PIL",),
    "psycopg2-binary": ("psycopg2",),
    "pycryptodome": ("Crypto",),
    "pycryptodomex": ("Cryptodome",),
    "pyjwt": ("jwt",),
    "python-dateutil": ("dateutil",),
    "python-dotenv": ("dotenv",),
    "python-jose": ("jose",),
    "python-multipart": ("multipart",),
    "pyyaml": ("yaml",),
    "scikit-learn": ("sklearn",),
    "typing-extensions": ("typing_extensions",),
}

_AMBIGUOUS_DISTRIBUTIONS = frozenset(
    {
        "cv2",
        "dateutil",
        "dotenv",
        "grpc",
        "jose",
        "jwt",
        "msgpack",
        "msgpack-python",
        "multipart",
        "opencv-contrib-python",
        "opencv-contrib-python-headless",
        "opencv-python",
        "opencv-python-headless",
        "pil",
        "pillow",
        "psycopg2",
        "psycopg2-binary",
        "pycrypto",
        "pycryptodome",
        "pyjwt",
        "python-dateutil",
        "python-dotenv",
        "python-jose",
        "python-multipart",
    }
)


def python_import_targets(package_identity: str) -> tuple[ImportTarget, ...]:
    """Return complete application-owned import targets for one distribution."""
    authoritative = package_identity not in _AMBIGUOUS_DISTRIBUTIONS
    curated = _CURATED_IMPORT_TARGETS.get(package_identity)
    if curated is not None:
        return tuple(
            ImportTarget(
                value=value,
                provenance="curated_mapping",
                authoritative=authoritative,
            )
            for value in curated
        )
    if package_identity.isidentifier() and not keyword.iskeyword(package_identity):
        return (
            ImportTarget(
                value=package_identity,
                provenance="canonical_distribution",
                authoritative=authoritative,
            ),
        )
    return ()
