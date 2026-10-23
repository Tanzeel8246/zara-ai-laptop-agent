"""(a) The tool registry must load exactly the original 38 tools."""

from agent.tools import load_all

EXPECTED_COUNT = 38


def test_exactly_38_tools():
    schemas, handlers = load_all()
    assert len(schemas) == EXPECTED_COUNT
    assert len(handlers) == EXPECTED_COUNT


def test_tool_names_unique_and_matched():
    schemas, handlers = load_all()
    names = [s["name"] for s in schemas]
    assert len(set(names)) == EXPECTED_COUNT
    assert set(names) == set(handlers.keys())


def test_schemas_well_formed():
    schemas, _ = load_all()
    for schema in schemas:
        assert schema["name"]
        assert schema["description"]
        assert schema["input_schema"]["type"] == "object"
        assert "properties" in schema["input_schema"]


def test_key_tools_present():
    _, handlers = load_all()
    for name in ("screenshot", "run_powershell", "speak", "system_status", "whatsapp_send"):
        assert name in handlers
