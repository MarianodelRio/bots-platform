"""Tests for the flow YAML validator."""

from control_plane.services.flow_validator import validate_flow_yaml


def test_valid_minimal_yaml():
    yaml_content = """
initial_state: START
states:
  START:
    transitions: []
"""
    errors = validate_flow_yaml(yaml_content)
    assert errors == []


def test_non_parseable_yaml():
    yaml_content = "key: [\n  unclosed"
    errors = validate_flow_yaml(yaml_content)
    assert len(errors) >= 1
    assert "yaml" in errors[0]


def test_dict_without_states():
    yaml_content = """
initial_state: START
"""
    errors = validate_flow_yaml(yaml_content)
    assert any("states" in e for e in errors)


def test_dict_without_initial_state():
    yaml_content = """
states:
  START:
    transitions: []
"""
    errors = validate_flow_yaml(yaml_content)
    assert any("initial_state" in e for e in errors)


def test_initial_state_nonexistent():
    yaml_content = """
initial_state: NONEXISTENT
states:
  START:
    transitions: []
"""
    errors = validate_flow_yaml(yaml_content)
    assert any("NONEXISTENT" in e for e in errors)


def test_transition_target_not_in_states():
    yaml_content = """
initial_state: START
states:
  START:
    transitions:
      - on_payload: "go"
        target: MISSING_STATE
"""
    errors = validate_flow_yaml(yaml_content)
    assert any("MISSING_STATE" in e or "target" in e for e in errors)


def test_global_transition_target_not_in_states():
    yaml_content = """
initial_state: START
states:
  START:
    transitions: []
global_transitions:
  - on_payload: "reset"
    target: GHOST_STATE
"""
    errors = validate_flow_yaml(yaml_content)
    assert any("GHOST_STATE" in e for e in errors)


def test_root_is_not_a_dict():
    yaml_content = "- item1\n- item2"
    errors = validate_flow_yaml(yaml_content)
    assert "root must be a mapping" in errors
