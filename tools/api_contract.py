"""Generate the contest API client routes and check that callers use the adapter."""

import argparse
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SPEC = Path("api/openapi.json")
GENERATED = Path("public/contest-api-routes.js")
ADAPTER = Path("public/contest-api.js")
DIRECT_FETCH = re.compile(r"\bfetch\s*\(")
NETWORK_ROUTE = re.compile(r"/api/[a-z0-9-]+")
OPERATION_ID = re.compile(r"[A-Za-z][A-Za-z0-9]*")
SCHEMA_PREFIX = "#/components/schemas/"


def operations(root=ROOT):
    spec = json.loads((root / SPEC).read_text(encoding="utf-8"))
    if not str(spec["openapi"]).startswith("3.1."):
        raise ValueError("Expected the board's OpenAPI 3.1 document")
    schemas = spec["components"]["schemas"]
    entries = {}
    for route, methods in spec["paths"].items():
        if not NETWORK_ROUTE.fullmatch(route):
            raise ValueError(f"Unsupported board API path: {route}")
        for method, details in methods.items():
            name = details["operationId"]
            if method not in {"get", "post"} or not OPERATION_ID.fullmatch(name) or name in entries:
                raise ValueError(f"Invalid or duplicate operation: {name}")
            responses = details["responses"]
            success = [value for code, value in responses.items() if re.fullmatch(r"2\d\d", code)]
            if len(success) != 1:
                raise ValueError(f"{name} needs one JSON success response")
            ref = success[0]["content"]["application/json"]["schema"]["$ref"]
            if not ref.startswith(SCHEMA_PREFIX):
                raise ValueError(f"{name} must reference a local response schema")
            schema = schemas[ref.removeprefix(SCHEMA_PREFIX)]
            if not set(schema["required"]).issubset(schema["properties"]):
                raise ValueError(f"Required fields are missing from {name}'s schema")
            request = details.get("requestBody")
            options = {
                "path": route,
                "method": method.upper(),
                "responseFields": schema["required"],
                **({"body": request["content"]["application/json"]["example"]} if request else {}),
            }
            for source in details["x-code"].values():
                relative = Path(source.split(":", 1)[0])
                if relative.is_absolute() or ".." in relative.parts or not (root / relative).is_file():
                    raise ValueError(f"Cannot locate the source for {name}: {source}")
            entries[name] = (options, details["x-code"], list(responses), ref.removeprefix(SCHEMA_PREFIX), schema)
    if not entries:
        raise ValueError("The OpenAPI document has no board operations")
    return entries


def js_type(schema):
    return {
        "array": "Array<object>", "boolean": "boolean", "string": "string",
        "integer": "number", "number": "number", "object": "object",
    }[schema["type"]]


def generated_routes(entries):
    routes = {name: {key: value for key, value in options.items() if key != "responseFields"}
              for name, (options, _, _, _, _) in entries.items()}
    typedefs = []
    for type_name, schema in {name: schema for _, _, _, name, schema in entries.values()}.items():
        typedefs.extend(["/**", f" * @typedef {{Object}} {type_name}"])
        for field in schema["required"]:
            typedefs.append(f" * @property {{{js_type(schema['properties'][field])}}} {field}")
        typedefs.append(" */")
    return (
        "// Generated from api/openapi.json by tools/api_contract.py. Do not edit.\n"
        '"use strict";\n\n' + "\n".join(typedefs) + "\n"
        "window.contestApiRoutes = " + json.dumps(routes, ensure_ascii=False, indent=2) + ";\n"
    )


def direct_fetch_violations(root=ROOT):
    for file in sorted((root / "public").glob("*.js")):
        if file.relative_to(root) == ADAPTER:
            continue
        for line_number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            for _match in DIRECT_FETCH.finditer(line):
                yield f"{file.relative_to(root).as_posix()}:{line_number}: use the contest API adapter"


def check(root=ROOT):
    expected = generated_routes(operations(root))
    file = root / GENERATED
    problems = []
    if not file.is_file() or file.read_text(encoding="utf-8") != expected:
        problems.append(f"{GENERATED}: regenerate with python tools/api_contract.py generate")
    problems.extend(direct_fetch_violations(root))
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("generate")
    commands.add_parser("check")
    describe = commands.add_parser("describe")
    describe.add_argument("method", choices=["GET", "POST"])
    describe.add_argument("path")
    args = parser.parse_args()
    try:
        if args.command == "generate":
            (ROOT / GENERATED).write_text(generated_routes(operations()), encoding="utf-8")
        elif args.command == "check":
            if problems := check():
                parser.exit(1, "\n".join(problems) + "\n")
            print("Contest API contract, generated routes and adapter rule passed.")
        else:
            for name, (options, code, statuses, _, _) in operations().items():
                if (options["method"], options["path"]) == (args.method, args.path):
                    print(json.dumps({"operationId": name, **options, **code, "responses": statuses}, indent=2))
                    return
            parser.exit(1, "No matching operation.\n")
    except (KeyError, OSError, TypeError, ValueError) as error:
        parser.exit(1, f"Invalid contest API contract: {error}\n")


if __name__ == "__main__":
    main()
