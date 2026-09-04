from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, validators
from referencing import Registry, Resource

from .errors import SchemaValidationError


SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"


def _is_exact_integer(_checker: Any, instance: Any) -> bool:
    return isinstance(instance, int) and not isinstance(instance, bool)


_exact_type_checker = Draft202012Validator.TYPE_CHECKER.redefine("integer", _is_exact_integer)
ExactDraft202012Validator = validators.extend(
    Draft202012Validator, type_checker=_exact_type_checker
)


@lru_cache(maxsize=1)
def _schemas() -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for path in sorted(SCHEMA_ROOT.glob("*.schema.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SchemaValidationError(f"cannot load schema {path.name}: {exc}") from exc
        Draft202012Validator.check_schema(document)
        documents[path.name] = document
    if not documents:
        raise SchemaValidationError(f"no schemas found under {SCHEMA_ROOT}")
    return documents


@lru_cache(maxsize=1)
def _registry() -> Registry:
    resources = []
    for name, document in _schemas().items():
        uri = document.get("$id")
        if not isinstance(uri, str):
            raise SchemaValidationError(f"schema {name} is missing a string $id")
        resources.append((uri, Resource.from_contents(document)))
    return Registry().with_resources(resources)


def validate_schema(document: Any, schema_name: str) -> None:
    """Validate a document with the named Draft 2020-12 schema."""
    name = schema_name if schema_name.endswith(".schema.json") else f"{schema_name}.schema.json"
    try:
        schema = _schemas()[name]
    except KeyError as exc:
        raise SchemaValidationError(f"unknown schema {name!r}") from exc

    validator = ExactDraft202012Validator(schema, registry=_registry())
    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: tuple(
            (type(part).__name__, str(part)) for part in error.absolute_path
        ),
    )
    if not errors:
        return
    first = errors[0]
    path = "$" + "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}" for part in first.absolute_path
    )
    raise SchemaValidationError(f"{name} validation failed at {path}: {first.message}")
