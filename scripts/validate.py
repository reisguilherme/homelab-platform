"""Validate committed contract schemas without network access or runtime changes."""

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry

ROOT = Path(__file__).resolve().parents[1]


def unique_object(pairs):
    """Reject duplicate JSON keys instead of silently choosing the last value."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def reject_constant(_value):
    raise ValueError("non-finite JSON number")


def read_json(path):
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )


def validate(kind, document):
    """Return a value-free error category, or None for a valid declaration."""
    schema = read_json(ROOT / "contracts" / "v1" / f"{kind}.schema.json")
    Draft202012Validator.check_schema(schema)
    # An empty registry has no retrieval callback: even an external $ref cannot fetch a URL.
    validator = Draft202012Validator(schema, registry=Registry())
    if next(validator.iter_errors(document), None) is not None:
        return "schema constraint failed"
    entries = document["services"] if kind == "catalog" else document["storage"]
    identifiers = [entry["id"] for entry in entries]
    if len(identifiers) != len(set(identifiers)):
        return "duplicate identifier"
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("service", "catalog"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        document = read_json(args.path)
        error = validate(args.kind, document)
    except (OSError, ValueError, RecursionError):
        error = "unreadable or malformed JSON"
    if error:
        # Never interpolate input, filenames, exception messages or JSON Schema error messages.
        print(f"invalid {args.kind}: {error}", file=sys.stderr)
        return 1
    print(f"valid {args.kind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
