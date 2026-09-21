# /// script
# dependencies = ["datamodel-code-generator", "pyyaml"]
# ///
"""Generate M1-07 user schemas: uv run scripts/generate_user_schemas.py.

Pull the tracked API contract first. Semantic checks stay in endpoint models --
`backend/app/user_schemas.py` layers them on top of the output of this script.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from datamodel_code_generator import DataModelType, InputFileType, generate

root = Path(__file__).resolve().parents[1]
schemas = yaml.safe_load((root / "docs/api/openapi.yaml").read_text(encoding="utf-8"))["components"]["schemas"]
selected = {}


def include(name):
    if name in selected:
        return
    selected[name] = schemas[name]

    def visit(value):
        if isinstance(value, dict):
            if "$ref" in value:
                include(value["$ref"].rsplit("/", 1)[1])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schemas[name])


for name in (
    "UserCreateRequest",
    "UserUpdateRequest",
    "UserResponse",
    "UserListResponse",
    "RoleListResponse",
):
    include(name)

with TemporaryDirectory() as temporary:
    source = Path(temporary) / "user-contract.json"
    source.write_text(json.dumps({"$defs": selected}).replace("#/components/schemas/", "#/$defs/"))
    generate(
        input_=source,
        input_file_type=InputFileType.JsonSchema,
        output=root / "backend/app/user_contract.py",
        output_model_type=DataModelType.PydanticV2BaseModel,
        disable_timestamp=True,
    )
