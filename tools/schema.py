"""Small schema builders and fail-closed validation; server remains authoritative."""
import json
from uuid import UUID
from .client import CommonsError

KINDS = ["task", "note", "entity", "source", "theme", "event", "thread"]
WRITABLE_KINDS = KINDS[:-1]
UUID_SCHEMA = {"type": "string", "format": "uuid"}
REVISION = {"type": "integer", "minimum": 1}


def obj(properties, required=(), **extra):
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False, **extra}


def string(description="", **extra):
    return {"type": "string", **({"description": description} if description else {}), **extra}


def integer(minimum, maximum, default=None):
    return {"type": "integer", "minimum": minimum, "maximum": maximum,
            **({"default": default} if default is not None else {})}


def validate(value, schema, path="arguments"):
    """Validate the published JSON-schema subset without a transport dependency."""
    def fail(detail):
        raise CommonsError("invalid_arguments", f"{path}: {detail}", saved=False)
    for rule in schema.get("allOf", []):
        validate(value, rule, path)
    if "if" in schema:
        try:
            validate(value, schema["if"], path)
        except CommonsError:
            branch = schema.get("else", {})
        else:
            branch = schema.get("then", {})
        validate(value, branch, path)
    for choice in ("oneOf", "anyOf"):
        if choice in schema:
            count = 0
            for variant in schema[choice]:
                try:
                    validate(value, variant, path)
                    count += 1
                except CommonsError:
                    pass
            if count == 0 or choice == "oneOf" and count != 1:
                fail(f"must match {choice} supported shape")
    if "const" in schema and value != schema["const"]:
        fail("unexpected value")
    if "enum" in schema and value not in schema["enum"]:
        fail("unsupported value; accepted: " + ", ".join(json.dumps(v, ensure_ascii=False) for v in schema["enum"]))
    typ = schema.get("type")
    types = typ if isinstance(typ, list) else [typ]
    checks = {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list),
              "string": lambda: isinstance(value, str), "integer": lambda: type(value) is int,
              "boolean": lambda: type(value) is bool, "null": lambda: value is None}
    if typ and not any(checks[t]() for t in types):
        fail(f"expected {typ}")
    if value is None:
        return
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                fail(f"missing {key}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                fail(f"unknown field {key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            fail("array length outside limits")
        for i, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{path}[{i}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", float("inf")):
            fail("string length outside limits")
        if schema.get("format") == "uuid":
            try:
                UUID(value)
            except (ValueError, AttributeError):
                fail("expected UUID from this installation")
    if type(value) is int and (value < schema.get("minimum", value) or value > schema.get("maximum", value)):
        fail(f"number outside limits; minimum={schema.get('minimum', 'unbounded')}, maximum={schema.get('maximum', 'unbounded')}")
