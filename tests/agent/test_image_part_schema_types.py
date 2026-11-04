"""tests for image part detection with json schemas containing type properties."""

import pytest

from agent.client_lifecycle import ClientLifecycleMixin


def _make_payload(content, field="messages"):
    return {field: [{"role": "user", "content": content}]}


@pytest.mark.parametrize(
    "schema",
    [
        pytest.param(
            {"type": "object", "properties": {"type": {"type": "string"}}},
            id="property-named-type",
        ),
        pytest.param(
            {"type": "object", "properties": {"type": {"type": "string"}, "status": {"type": "string"}}},
            id="delegate-task-output-schema",
        ),
        pytest.param(
            {"type": ["string", "null"]},
            id="schema-union-list",
        ),
        pytest.param(
            {"type": None},
            id="type-none",
        ),
        pytest.param(
            {"type": 123},
            id="type-number",
        ),
        pytest.param(
            {"type": []},
            id="type-empty-list",
        ),
        pytest.param(
            {"type": {}},
            id="type-empty-dict",
        ),
    ],
)
def test_schema_with_non_string_type_does_not_crash(schema):
    """schemas with non-string type values do not raise typeerror and return false."""
    payload = _make_payload([{"type": "tool_result", "content": schema}])
    assert ClientLifecycleMixin._api_kwargs_have_image_parts(payload) is False


def test_schema_with_nested_image_part_is_found():
    """recursing into properties still detects real image parts inside schemas."""
    schema = {
        "type": "object",
        "properties": {
            "type": {"type": "string"},
            "avatar": {"type": "image_url", "image_url": "https://example.com/pic.png"},
        },
    }
    payload = _make_payload([{"type": "tool_result", "content": schema}])
    assert ClientLifecycleMixin._api_kwargs_have_image_parts(payload) is True


@pytest.mark.parametrize("field", ["messages", "input"])
@pytest.mark.parametrize("image_type", ["image_url", "input_image"])
def test_valid_image_parts_are_detected(field, image_type):
    """real image parts on messages and input fields are detected."""
    payload = _make_payload([{"type": image_type}], field=field)
    assert ClientLifecycleMixin._api_kwargs_have_image_parts(payload) is True


def test_invalid_api_kwargs_returns_false():
    """non-dict or empty inputs safely return false."""
    assert ClientLifecycleMixin._api_kwargs_have_image_parts(None) is False
    assert ClientLifecycleMixin._api_kwargs_have_image_parts([]) is False
    assert ClientLifecycleMixin._api_kwargs_have_image_parts({}) is False
