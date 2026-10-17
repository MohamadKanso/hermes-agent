"""regression tests for issue #140704.

ensures command floors (hardline, approvals.deny, dangerous patterns)
properly handle heredoc bodies so that quotes in bodies do not hide
subsequent commands or cause unclosed quote states.
"""

import pytest
from tools import approval, approval_context
from tools.approval_detection import detect_dangerous_command, detect_hardline_command
from tools.shell_heredoc import mask_heredoc_bodies_for_detection


@pytest.fixture(autouse=True)
def _setup_approval_context(monkeypatch):
    """configure off mode and sample deny rules."""
    monkeypatch.setattr(approval_context, "_get_approval_mode", lambda: "off")
    monkeypatch.setattr(
        approval_context,
        "_get_approval_config",
        lambda: {"mode": "off", "deny": ["rm", "rm *", "git push*"]},
    )


def test_hardline_catches_root_delete_after_heredoc_with_apostrophe():
    cmd = "cat > notes.txt <<'EOF'\nit's done\nEOF\nrm -rf /"
    is_hardline, desc = detect_hardline_command(cmd)
    assert is_hardline is True
    assert "root filesystem" in desc


def test_hardline_catches_root_delete_after_heredoc_with_double_quote():
    cmd = 'cat > notes.txt <<"EOF"\nsay "hello\nEOF\nrm -rf /'
    is_hardline, desc = detect_hardline_command(cmd)
    assert is_hardline is True
    assert "root filesystem" in desc


def test_user_deny_blocks_rm_after_heredoc_with_apostrophe():
    cmd = "cat > notes.txt <<'EOF'\nit's done\nEOF\nrm notes.txt"
    res = approval.check_all_command_guards(cmd, "local")
    assert res.get("approved") is False
    assert res.get("user_deny") is True


def test_user_deny_blocks_git_push_force_after_heredoc_with_apostrophe():
    cmd = "cat > notes.txt <<'EOF'\nit's done\nEOF\ngit push --force"
    res = approval.check_all_command_guards(cmd, "local")
    assert res.get("approved") is False
    assert res.get("user_deny") is True


def test_tab_indented_heredoc_with_apostrophe():
    cmd = "cat > n.txt <<-'EOF'\n\tit's\n\tEOF\nrm n.txt"
    res = approval.check_all_command_guards(cmd, "local")
    assert res.get("approved") is False
    assert res.get("user_deny") is True


def test_two_heredocs_on_one_line():
    cmd = "cat <<'A' > a.txt; cat <<'B' > b.txt\nit's\nA\nok\nB\nrm a.txt"
    res = approval.check_all_command_guards(cmd, "local")
    assert res.get("approved") is False
    assert res.get("user_deny") is True


def test_heredoc_inside_command_substitution():
    cmd = "x=$(cat <<'EOF'\nit's\nEOF\n); rm x.txt"
    res = approval.check_all_command_guards(cmd, "local")
    assert res.get("approved") is False
    assert res.get("user_deny") is True


def test_python_heredoc_with_apostrophe_then_rm():
    cmd = 'python3 - <<\'EOF\'\nprint("it\'s")\nEOF\nrm -f x.txt'
    res = approval.check_all_command_guards(cmd, "local")
    assert res.get("approved") is False
    assert res.get("user_deny") is True


def test_unquoted_heredoc_substitution_is_scanned():
    cmd = "cat > n.txt <<EOF\n$(rm x)\nEOF"
    res = approval.check_all_command_guards(cmd, "local")
    assert res.get("approved") is False
    assert res.get("user_deny") is True


def test_quoted_heredoc_prose_does_not_trip_false_positive():
    cmd = "cat > notes.txt <<'EOF'\nrm is not allowed here\nEOF\nwc -l notes.txt"
    res = approval.check_all_command_guards(cmd, "local")
    assert res.get("approved") is True


def test_quoted_heredoc_backticks_do_not_trip_false_positive():
    cmd = "cat > notes.txt <<'EOF'\nUse trash, never `rm -rf`.\nEOF\nwc -l notes.txt"
    res = approval.check_all_command_guards(cmd, "local")
    assert res.get("approved") is True


def test_quoted_heredoc_prose_hardline_mention_is_safe():
    cmd = "cat > notes.txt <<'EOF'\nNever run rm -rf on the build dir.\nEOF\nwc -l notes.txt"
    is_hardline, _ = detect_hardline_command(cmd)
    assert is_hardline is False


def test_here_string_is_not_treated_as_heredoc():
    cmd = 'cat <<< "hello world"\nrm -rf /'
    is_hardline, _ = detect_hardline_command(cmd)
    assert is_hardline is True


def test_arithmetic_shift_is_not_treated_as_heredoc():
    cmd = "val=$(( 1 << 4 ))\nrm -rf /"
    is_hardline, _ = detect_hardline_command(cmd)
    assert is_hardline is True


def test_bash_c_wrapped_heredoc():
    cmd = "bash -c \"cat <<'EOF'\nit's done\nEOF\nrm -rf /\""
    is_hardline, _ = detect_hardline_command(cmd)
    assert is_hardline is True


def test_sudo_tee_heredoc():
    cmd = "sudo tee /etc/hosts <<'EOF'\nit's a test\nEOF\nrm -rf /"
    is_hardline, _ = detect_hardline_command(cmd)
    assert is_hardline is True


def test_unterminated_heredoc_fails_closed_and_leaves_subsequent_commands_visible():
    cmd = "cat <<'EOF'\nrm -rf /"
    is_hardline, _ = detect_hardline_command(cmd)
    assert is_hardline is True


def test_compound_arithmetic_shift_is_not_treated_as_heredoc():
    cmd = "(( x = 1 << 2 ))\nrm -rf /"
    is_hardline, _ = detect_hardline_command(cmd)
    assert is_hardline is True


def test_delimiter_matching_deny_rule_is_not_flagged_as_command():
    cmd = "cat <<'rm'\nhello world\nrm\necho ok"
    # terminator 'rm' is on its own line ending heredoc, should not trigger deny: ['rm']
    matched = approval._match_user_deny_rule(cmd)
    assert matched is None

    # subsequent rm command after terminator should still match deny
    cmd_with_rm = "cat <<'rm'\nhello world\nrm\nrm foo"
    matched_rm = approval._match_user_deny_rule(cmd_with_rm)
    assert matched_rm is not None


