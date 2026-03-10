from gatewaychef_v2.errors import StateTransitionError

STATE_DRAFT = "DRAFT"
STATE_PRECHECK_PASSED = "PRECHECK_PASSED"
STATE_CONFIG_PENDING = "CONFIG_PENDING"
STATE_CONFIG_APPLIED = "CONFIG_APPLIED"
STATE_CLOUD_SYNCED = "CLOUD_SYNCED"
STATE_VERIFIED = "VERIFIED"
STATE_DONE = "DONE"
STATE_FAILED = "FAILED"

TERMINAL_STATES = {STATE_DONE}

ALLOWED_TRANSITIONS = {
    STATE_DRAFT: {STATE_PRECHECK_PASSED, STATE_FAILED},
    STATE_PRECHECK_PASSED: {STATE_CONFIG_PENDING, STATE_FAILED},
    STATE_CONFIG_PENDING: {STATE_CONFIG_APPLIED, STATE_FAILED},
    STATE_CONFIG_APPLIED: {STATE_CLOUD_SYNCED, STATE_FAILED},
    STATE_CLOUD_SYNCED: {STATE_VERIFIED, STATE_FAILED},
    STATE_VERIFIED: {STATE_DONE, STATE_FAILED},
    STATE_FAILED: {
        STATE_PRECHECK_PASSED,
        STATE_CONFIG_PENDING,
        STATE_CONFIG_APPLIED,
        STATE_CLOUD_SYNCED,
        STATE_VERIFIED,
    },
    STATE_DONE: set(),
}


def ensure_transition(current_state, next_state):
    allowed = ALLOWED_TRANSITIONS.get(current_state, set())
    if next_state == current_state:
        return
    if next_state not in allowed:
        raise StateTransitionError(
            f"Ungueltiger Zustandswechsel: {current_state} -> {next_state}.",
            details={"current_state": current_state, "next_state": next_state},
        )
