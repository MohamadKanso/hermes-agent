"""Process-identity contract: the two kill/relaunch predicates and the profile liveness probe
defer to the canonical matchers instead of argv substrings (root AGENTS.md process-identity rule).
"""

from __future__ import annotations

import os

import pytest

from hermes_cli.dashboard_procs import _is_desktop_local_serve_cmdline
from hermes_cli.update_cmd_windows import _hermes_holder_subcommand, _is_backend_argv

LOOPBACK = "--host 127.0.0.1 --port 0"

# (cmdline, holder subcommand, desktop-local reap?, Windows updater "Desktop backend"?). Substring
# scanners get every "trap" row wrong: "serve" appears inside --preserve-cache / observer.py / a flag
# value. The updater's kill set additionally requires the Desktop's `-m hermes_cli.main` spawn shape —
# a user-launched `hermes serve` / `hermes dashboard` is refused on, never tree-killed.
CMDLINES = [
    ("python -m hermes_cli.main serve " + LOOPBACK, "serve", True, True),
    ("python -m hermes_cli.main dashboard", "dashboard", False, True),
    ("python /venv/bin/hermes serve " + LOOPBACK, "serve", True, False),
    ("python3.13 /venv/bin/hermes serve " + LOOPBACK, "serve", True, False),
    ("python -X utf8 /venv/bin/hermes serve " + LOOPBACK, "serve", True, False),
    ("python -W default -m hermes_cli.main serve " + LOOPBACK, "serve", True, True),
    ("python -x /venv/bin/hermes serve " + LOOPBACK, "serve", True, False),
    (r"C:\Python\python.exe C:\Hermes\.venv\Scripts\hermes.exe dashboard", "dashboard", False, False),
    ("python hermes_cli/main.py serve " + LOOPBACK, "serve", True, False),
    ("python /tmp/hermes-script.py dashboard", None, False, False),
    ("python /opt/not-hermes_cli/main.py serve " + LOOPBACK, None, False, False),
    ("/venv/bin/hermes serve --isolated --host=127.0.0.1 --port=0 --ssh-owner-nonce abc", "serve", True, False),
    (r"C:\hermes\.venv\Scripts\hermes.exe serve --host 100.106.105.2 --port 9119", "serve", False, False),
    ("hermes.exe dashboard", "dashboard", False, False),
    ("hermes --profile ops serve " + LOOPBACK, "serve", True, False),
    ("hermes -m serve kanban --preserve-cache " + LOOPBACK, "kanban", False, False),
    ("python -m hermes_cli.main kanban --preserve-cache " + LOOPBACK, "kanban", False, False),
    ("hermes --reasoning high dashboard " + LOOPBACK, "dashboard", False, False),
    ("hermes gateway run --replace", "gateway", False, False),
    ("hermes chat --model serve", "chat", False, False),
    ("python worker.py hermes serve " + LOOPBACK, None, False, False),
    ("python worker.py /venv/bin/hermes serve " + LOOPBACK, None, False, False),
    ("python worker.py -m hermes_cli.main serve " + LOOPBACK, None, False, False),
    ("python -X utf8 worker.py hermes serve " + LOOPBACK, None, False, False),
    ("python -W default worker.py -m hermes_cli.main serve " + LOOPBACK, None, False, False),
    ("python observer.py serve " + LOOPBACK, None, False, False),
    # #121156: `hermes serve` is a PREFIX of other words, and `hermes` is a common session/host name.
    ("herdr --session hermes server", None, False, False),
    ("hermes serverless --port 9119", "serverless", False, False),
    ("hermes service status", "service", False, False),
    # A shebang-launched checkout entry point: argv[0] is the script, with no interpreter token.
    ("/opt/hermes/hermes_cli/main.py serve " + LOOPBACK, "serve", True, False),
]


@pytest.mark.parametrize("cmdline,subcommand,reapable,desktop_backend", CMDLINES)
def test_kill_and_relaunch_predicates_agree_with_the_canonical_holder_matcher(
        cmdline, subcommand, reapable, desktop_backend):
    assert _hermes_holder_subcommand(cmdline) == subcommand
    # Desktop-local reap (a KILL path): serve + loopback + ephemeral port, decided by tokens.
    assert _is_desktop_local_serve_cmdline(cmdline) is reapable
    # Windows updater backend classifier (taskkill /T on orphans): canonical subcommand AND Desktop spawn shape.
    assert _is_backend_argv(cmdline) is desktop_backend


@pytest.mark.parametrize("cmdline,subcommand,reapable,desktop_backend", CMDLINES)
def test_dashboard_runtime_parse_agrees_with_the_canonical_holder_matcher(
        cmdline, subcommand, reapable, desktop_backend):
    """``_parse_dashboard_runtime`` gates the launchd backend inventory (a kill + kickstart path)
    and ``--status``: it must claim a cmdline as a backend on exactly the canonical subcommands."""
    from hermes_cli.main_dashboard import _parse_dashboard_runtime

    runtime = _parse_dashboard_runtime(cmdline)
    assert (runtime is not None) is (subcommand in ("dashboard", "serve"))
    if runtime is not None:
        assert runtime[0] == subcommand


@pytest.mark.skipif(os.name == "nt", reason="Python module names resolve case-insensitively on Windows")
def test_module_entrypoint_is_case_sensitive_on_posix():
    assert _hermes_holder_subcommand("python -m HERMES_CLI.MAIN serve") is None


@pytest.mark.skipif(os.name == "nt", reason="Python module names resolve case-insensitively on Windows")
def test_live_argv_is_not_case_folded_before_the_canonical_matcher():
    """The reap paths classify the LIVE argv; case-folding it there would re-open the bug class.

    ``_orphaned_desktop_backend_pids`` / ``_handoff_reapable_backend_pids`` read the running
    process's argv through ``_live_argv`` and hand it to ``_is_backend_argv`` (which feeds
    ``taskkill /T``). ``_hermes_holder_subcommand`` matches ``-m hermes_cli.main`` case-sensitively,
    so a lower-casing ``_live_argv`` would make a non-Hermes ``-m HERMES_CLI.MAIN`` argv reapable —
    exactly the false-positive identity the canonical matcher exists to prevent (#121156).
    """
    from hermes_cli.update_cmd_windows import _live_argv

    class _FakePsutil:
        class NoSuchProcess(Exception):
            pass

        @staticmethod
        def Process(_pid):
            class _P:
                @staticmethod
                def cmdline():
                    return ["python", "-m", "HERMES_CLI.MAIN", "serve"]
            return _P()

    argv = _live_argv(_FakePsutil, 4242, "python -m HERMES_CLI.MAIN serve")
    assert argv == "python -m HERMES_CLI.MAIN serve"
    assert _is_backend_argv(argv) is False


def test_desktop_local_serve_spares_fixed_port_and_remote_hosts():
    assert not _is_desktop_local_serve_cmdline("hermes serve --host 100.106.105.2 --port 9119 --skip-build")
    assert not _is_desktop_local_serve_cmdline("hermes serve --host 127.0.0.1 --port 9119")
    assert _is_desktop_local_serve_cmdline("hermes serve --host localhost --port 0")


def test_profile_liveness_is_the_shared_ladder(tmp_path, monkeypatch):
    """``_check_gateway_running`` is ``resolve_gateway_liveness`` scoped to the profile dir, with the
    PID rung reading (never cleaning) THAT profile's ``gateway.pid``."""
    import gateway.status as gw_status
    from hermes_cli.profiles import _check_gateway_running

    seen: dict = {}

    def fake_resolve(**kwargs):
        seen.update(kwargs)
        return gw_status.GatewayLiveness(running=True, pid=1, source="pid")

    monkeypatch.setattr(gw_status, "resolve_gateway_liveness", fake_resolve)
    calls: list = []
    monkeypatch.setattr(gw_status, "get_running_pid",
                        lambda path, cleanup_stale=True: calls.append((path, cleanup_stale)))
    assert _check_gateway_running(tmp_path) is True
    assert seen["profile_dir"] == tmp_path
    seen["pid_probe"](tmp_path / "gateway.pid")
    assert calls == [(tmp_path / "gateway.pid", False)]
