import yaml


def validate_flow_yaml(yaml_content: str) -> list[str]:
    errors = []
    try:
        parsed = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        return [f"yaml: {e}"]

    if not isinstance(parsed, dict):
        return ["root must be a mapping"]

    states = parsed.get("states")
    if not isinstance(states, dict):
        errors.append("states: missing or not a mapping")
        states = {}

    initial_state = parsed.get("initial_state")
    if not isinstance(initial_state, str):
        errors.append("initial_state: missing or not a string")
        initial_state = None

    if initial_state is not None and states and initial_state not in states:
        errors.append(f"initial_state '{initial_state}' not found in states")

    for state_name, state_body in states.items():
        if not isinstance(state_body, dict):
            continue
        for transition in state_body.get("transitions", []):
            if not isinstance(transition, dict):
                continue
            target = transition.get("target")
            if target and target not in states:
                errors.append(
                    f"state '{state_name}' transition target '{target}' not found in states"
                )

    for transition in parsed.get("global_transitions", []):
        if not isinstance(transition, dict):
            continue
        target = transition.get("target")
        if target and target not in states:
            errors.append(f"global_transitions target '{target}' not found in states")

    return errors
