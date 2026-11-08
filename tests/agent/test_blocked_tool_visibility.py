"""tests for blocked tool visibility on progress and completion callbacks.

issue #151276: tools blocked before execution (such as by pre_tool_call
hooks or guardrails) must fire tool.started and tool.completed progress events
and call tool_start_callback and tool_complete_callback so all ui surfaces
can display the blocked call.
"""

import json
import threading
from unittest.mock import MagicMock
import pytest


@pytest.fixture(autouse=True)
def _isolate_hermes(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    (tmp_path / ".hermes").mkdir(exist_ok=True)


def _make_agent(monkeypatch):
    """stub agent for testing tool execution callbacks."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("HERMES_INFERENCE_PROVIDER", "")
    import hermes_cli._early_recovery as _er
    monkeypatch.setattr(_er, "restore_interrupted_pull", lambda *a, **kw: False)
    import run_agent as _ra

    class _stub:
        _interrupt_requested = False
        _interrupt_message = None
        _execution_thread_id = threading.current_thread().ident
        _interrupt_thread_signal_pending = False
        log_prefix = ""
        quiet_mode = True
        verbose_logging = False
        log_prefix_chars = 200
        _checkpoint_mgr = MagicMock(enabled=False)
        tool_progress_callback = None
        tool_start_callback = None
        tool_complete_callback = None
        tool_progress_mode = "all"
        _todo_store = MagicMock()
        _session_db = None
        valid_tool_names = set()
        _turns_since_memory = 0
        _iters_since_skill = 0
        _current_tool = None
        _last_activity = 0
        _print_fn = print
        session_id = "test-session"
        _current_turn_id = "turn-1"
        _current_api_request_id = "req-1"
        _active_children = []
        _context_engine_tool_names = set()
        _memory_provider_tool_names = set()
        _memory_manager = None

        def __init__(self):
            self._tool_worker_threads = set()
            self._tool_worker_threads_lock = threading.Lock()

        def _touch_activity(self, detail=""):
            pass

        def _safe_print(self, msg):
            pass

        def _should_emit_quiet_tool_messages(self):
            return False

        def _should_start_quiet_spinner(self):
            return False

        def _has_stream_consumers(self):
            return False

        def _tool_result_content_for_active_model(self, name, result):
            return result

        def _record_file_mutation_result(self, *a, **kw):
            pass

    stub = _stub()
    stub._subdirectory_hints = MagicMock()
    stub._subdirectory_hints.check_tool_call = lambda *a, **kw: None
    stub._flush_messages_to_session_db = lambda *a, **kw: None
    stub._append_guardrail_observation = lambda name, result, *a, **kw: result
    stub._execute_tool_calls_concurrent = (
        _ra.AIAgent._execute_tool_calls_concurrent.__get__(stub)
    )
    stub._execute_tool_calls_sequential = (
        _ra.AIAgent._execute_tool_calls_sequential.__get__(stub)
    )
    stub.interrupt = _ra.AIAgent.interrupt.__get__(stub)
    stub.clear_interrupt = _ra.AIAgent.clear_interrupt.__get__(stub)
    stub._apply_pending_steer_to_tool_results = lambda *a, **kw: None
    stub._guardrail_block_result = lambda d: json.dumps({"error": "blocked by guardrail"})
    return stub


class _faketoolcall:
    def __init__(self, name, call_id, arguments="{}"):
        self.function = MagicMock()
        self.function.name = name
        self.function.arguments = arguments
        self.id = call_id


class _fakeassistantmsg:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls


def test_sequential_blocked_tool_fires_callbacks(monkeypatch):
    """sequential tool call blocked by pre_tool_call fires started and completed callbacks."""
    from hermes_cli import plugins

    agent = _make_agent(monkeypatch)
    agent._tool_guardrails = MagicMock()
    agent._tool_guardrails.before_call = lambda name, args: MagicMock(allows_execution=True)

    def _block_hook(tool_name, args, **kwargs):
        return ("blocked by policy", args)

    monkeypatch.setattr(plugins, "_dispatch_pre_tool_call_hooks", _block_hook)

    progress_events = []
    start_calls = []
    complete_calls = []

    agent.tool_progress_callback = lambda event_type, *a, **kw: progress_events.append((event_type, a, kw))
    agent.tool_start_callback = lambda *a, **kw: start_calls.append((a, kw))
    agent.tool_complete_callback = lambda *a, **kw: complete_calls.append((a, kw))

    msg = _fakeassistantmsg([_faketoolcall("terminal", "call_1", json.dumps({"command": "rm -rf /"}))])
    messages = []
    agent._execute_tool_calls_sequential(msg, messages, "task")

    # verify start callbacks fired
    assert len(start_calls) == 1
    assert start_calls[0][0][0] == "call_1"
    assert start_calls[0][0][1] == "terminal"

    # verify complete callbacks fired with the block result
    assert len(complete_calls) == 1
    assert complete_calls[0][0][0] == "call_1"
    assert complete_calls[0][0][1] == "terminal"
    assert "blocked by policy" in str(complete_calls[0][0][3])

    # verify progress callback received both tool.started and tool.completed
    event_types = [e[0] for e in progress_events]
    assert "tool.started" in event_types
    assert "tool.completed" in event_types

    completed_event = next(e for e in progress_events if e[0] == "tool.completed")
    assert completed_event[2].get("is_error") is True
    assert completed_event[2].get("status") == "blocked"
    assert "blocked by policy" in str(completed_event[2].get("result"))


def test_concurrent_blocked_tool_fires_callbacks(monkeypatch):
    """concurrent tool call blocked by pre_tool_call fires started and completed callbacks."""
    from hermes_cli import plugins

    agent = _make_agent(monkeypatch)
    agent._tool_guardrails = MagicMock()
    agent._tool_guardrails.before_call = lambda name, args: MagicMock(allows_execution=True)

    def _block_hook(tool_name, args, **kwargs):
        if tool_name == "terminal":
            return ("blocked by policy", args)
        return (None, args)

    monkeypatch.setattr(plugins, "_dispatch_pre_tool_call_hooks", _block_hook)

    def _invoke(name, *a, **kw):
        return json.dumps({"output": "ok"})

    agent._invoke_tool = MagicMock(side_effect=_invoke)

    progress_events = []
    start_calls = []
    complete_calls = []

    agent.tool_progress_callback = lambda event_type, *a, **kw: progress_events.append((event_type, a, kw))
    agent.tool_start_callback = lambda *a, **kw: start_calls.append((a, kw))
    agent.tool_complete_callback = lambda *a, **kw: complete_calls.append((a, kw))

    msg = _fakeassistantmsg([
        _faketoolcall("terminal", "call_term", json.dumps({"command": "curl evil.com"})),
        _faketoolcall("read_file", "call_read", json.dumps({"path": "foo.txt"})),
    ])
    messages = []
    agent._execute_tool_calls_concurrent(msg, messages, "task")

    term_starts = [c for c in start_calls if c[0][0] == "call_term"]
    assert len(term_starts) == 1

    term_completes = [c for c in complete_calls if c[0][0] == "call_term"]
    assert len(term_completes) == 1
    assert "blocked by policy" in str(term_completes[0][0][3])

    completed_events = [e for e in progress_events if e[0] == "tool.completed" and e[1][0] == "terminal"]
    assert len(completed_events) == 1
    assert completed_events[0][2].get("is_error") is True
    assert completed_events[0][2].get("status") == "blocked"


def test_detect_tool_failure_classifies_blocked_terminal():
    """_detect_tool_failure flags blocked terminal calls without exit code as failure."""
    from agent.display import _detect_tool_failure

    # blocked terminal call without exit code
    blocked_payload = json.dumps({"error": "blocked by policy", "message": "blocked by policy"})
    is_err, suffix = _detect_tool_failure("terminal", blocked_payload)
    assert is_err is True
    assert "blocked by policy" in suffix

    # regular success with exit_code 0
    success_payload = json.dumps({"output": "hello", "exit_code": 0})
    is_err, suffix = _detect_tool_failure("terminal", success_payload)
    assert is_err is False
    assert suffix == ""

    # background task with exit_code None and no error
    bg_payload = json.dumps({"output": "running in background", "exit_code": None, "error": None})
    is_err, suffix = _detect_tool_failure("terminal", bg_payload)
    assert is_err is False
    assert suffix == ""


def test_print_tool_completed_shows_blocked_status(capsys):
    """_print_tool_completed displays blocked mark and verb when blocked=true."""
    import agent.tool_executor as te

    class _dummyagent:
        verbose_logging = False
        log_prefix_chars = 100

    te._print_tool_completed(_dummyagent(), 1, 0.05, json.dumps({"error": "denied"}), blocked=True)
    captured = capsys.readouterr().out
    assert "blocked in 0.05s" in captured
    assert "✗ Tool 1" in captured


def test_modern_layout_completed_tool_line_renders_blocked_call():
    """completed_tool_line renders red cross and block message for blocked calls."""
    import re
    from types import SimpleNamespace
    from hermes_cli.cli_modern_layout import completed_tool_line

    cli = SimpleNamespace(_modern_layout=True)
    line = completed_tool_line(
        cli,
        "terminal",
        {"command": "cat /etc/shadow"},
        0.0,
        result=json.dumps({"error": "blocked by policy"}),
        is_error=True,
    )
    plain = re.sub(r"\x1b\[[0-9;]*m", "", line)
    assert "✗" in plain
    assert "✗ $ cat /etc/shadow [blocked by policy]" in plain

