"""Conservative heredoc masking for shell-command scanners ('&' guard, blocked-command checks,
cron lifecycle_guard) that false-positive on heredoc *bodies*. Stripping every body is unsafe the
other way (a fake ``<<`` in quotes can swallow an operator; unquoted bodies expand; ``bash <<'EOF'``
executes), so a body is masked ONLY when every delimiter is quoted, every heredoc has an exact
terminator line, the owning simple command is an allowlisted non-shell interpreter, and no list
operator follows the heredoc. Otherwise the command is returned untouched: a false positive is
acceptable, hiding shell syntax from a guard is not.
Masked bodies keep their newline count (re.MULTILINE)."""

from __future__ import annotations

import re

# Non-shell interpreters whose quoted heredoc bodies are data for THAT interpreter; optional
# VAR=... assignments, ``env`` and a path prefix allowed. Narrow on purpose: unmatched = visible.
_INERT_HEREDOC_CONSUMER_RE = re.compile(
    r"^\s*(?:[A-Z_][A-Z0-9_]*=\S+\s+)*(?:env\s+)?(?:[A-Za-z0-9_./-]+/)?"
    r"(?:python(?:3(?:\.\d+)*)?|osascript|cat)(?=\s|$)",
    re.IGNORECASE)


def _span_end(command: str, cursor: int, closer: str) -> int:
    """Index just past the backslash-aware span opened at ``cursor``."""
    end = cursor + 1
    while end < len(command):
        if command[end] == closer:
            return end + 1
        end += 2 if command[end] == "\\" and end + 1 < len(command) else 1
    return end


def _mask_simple_quotes(command: str) -> str:
    """Blank inert quoted spans; keep ``$(``/backtick-bearing ones visible."""
    result = []
    cursor = 0
    while cursor < len(command):
        char = command[cursor]
        if char in "'\"":  # single quotes have no escapes; double quotes are backslash-aware
            end = (command.find("'", cursor + 1) + 1 if char == "'"
                   else _span_end(command, cursor, '"'))
            segment = command[cursor:end]
            if not segment.endswith(char):
                result.append(command[cursor:])
                break
            keep = char == '"' and ("$(" in segment or "`" in segment)
            result.append(segment if keep else char * 2)
            cursor = end
        elif char == "`":
            end = _span_end(command, cursor, "`")
            result.append(command[cursor:end])
            cursor = end
        else:
            result.append(char)
            cursor += 1
    return "".join(result)


def _parse_heredoc_operator(command: str, index: int):
    """Parse one ``<<`` opener -> ``(end_index, delimiter, strip_tabs, quoted)`` or None."""
    if not command.startswith("<<", index) or command.startswith("<<<", index):
        return None
    strip_tabs = command.startswith("-", index + 2)
    cursor = index + 3 if strip_tabs else index + 2
    while cursor < len(command) and command[cursor] in " \t":
        cursor += 1
    if cursor >= len(command) or command[cursor] in "\r\n":
        return None
    delimiter: list[str] = []
    quoted = False
    while cursor < len(command) and not (command[cursor].isspace() or command[cursor] in ";&|<>()"):
        char = command[cursor]
        if char == "\\":  # backslash-escaped char: quoted, literal
            if cursor + 1 >= len(command) or command[cursor + 1] in "\r\n":
                return None
            quoted = True
            delimiter.append(command[cursor + 1])
            cursor += 2
        elif char in "'\"":
            quoted = True
            cursor += 1
            while cursor < len(command) and command[cursor] != char:
                current = command[cursor]
                if current in "\r\n":
                    return None
                if char == '"' and current == "\\":
                    if cursor + 1 >= len(command):
                        return None
                    if command[cursor + 1] in '$`"\\\n':  # else backslash is literal in dquotes
                        cursor += 1
                        current = command[cursor]
                delimiter.append(current)
                cursor += 1
            if cursor >= len(command):  # unterminated quote
                return None
            cursor += 1
        else:
            delimiter.append(char)
            cursor += 1
    if not delimiter and not quoted:
        return None
    return cursor, "".join(delimiter), strip_tabs, quoted


def _is_fd_redirect_ampersand(command: str, index: int) -> bool:
    """Return whether ``&`` at ``index`` belongs to ``>&``/``<&``/``&>`` redirection."""
    before = command[index - 1] if index else ""
    after = command[index + 1] if index + 1 < len(command) else ""
    return before in "<>" or after == ">"


def _scan_heredoc_command_unit(command: str, start: int):
    """Scan one logical command.

    Return ``(end, specs, unknown_operator, post_heredoc_list_operator, owner_start)``.
    List operators before the first heredoc select the simple command that owns it. A list
    operator after a heredoc keeps the body visible because another command may consume it.
    """
    cursor = start
    quote = None
    comment = False
    specs = []
    unknown_operator = False
    post_heredoc_list_operator = False
    owner_start = start
    while cursor < len(command):
        char = command[cursor]
        if char == "\n" and (comment or quote is None):
            break
        # Backslash escapes (incl. line continuations) outside single quotes skip the next char.
        escaped = char == "\\" and quote != "'" and not comment and cursor + 1 < len(command)
        if comment or quote is not None or escaped:
            if char == quote:
                quote = None
            cursor += 2 if escaped else 1
        elif char in "'\"`":
            quote = char
            cursor += 1
        elif char == "#" and (cursor == start or command[cursor - 1].isspace()
                              or command[cursor - 1] in ";&|()"):
            comment = True
            cursor += 1
        elif command.startswith("<<<", cursor):
            cursor += 3
        elif command.startswith("<<", cursor):
            parsed = _parse_heredoc_operator(command, cursor)
            if parsed is None:
                unknown_operator = True
                cursor += 2
            else:
                cursor, delimiter, strip_tabs, quoted = parsed
                specs.append((delimiter, strip_tabs, quoted))
        else:
            if char in ";|&" and not (
                char == "&" and _is_fd_redirect_ampersand(command, cursor)
            ):
                if specs:
                    post_heredoc_list_operator = True
                else:
                    owner_start = cursor + 1
            cursor += 1
    return cursor, specs, unknown_operator, post_heredoc_list_operator, owner_start


def _find_heredoc_close(
        command: str, body_start: int, delimiter: str, strip_tabs: bool) -> int | None:
    """Return the position after an exact shell heredoc terminator line."""
    cursor = body_start
    while True:
        newline = command.find("\n", cursor)
        after = len(command) if newline == -1 else newline + 1
        line = command[cursor:after].removesuffix("\n").removesuffix("\r")
        candidate = line.lstrip("\t") if strip_tabs else line
        if candidate == delimiter:
            return after
        if newline == -1:
            return None
        cursor = after


def strip_inert_heredoc_bodies(command: str) -> str:
    """Mask heredoc bodies that are provably inert data (see module docstring)."""
    # Runs on every terminal call: skip the state machine when no '<<' exists; stop past the last.
    if "<<" not in command:
        return command
    last_opener_index = command.rfind("<<")
    ranges: list[tuple[int, int]] = []
    command_start = 0
    while command_start <= last_opener_index:
        (
            command_end,
            specs,
            unknown_operator,
            post_heredoc_list_operator,
            owner_start,
        ) = _scan_heredoc_command_unit(command, command_start)
        if unknown_operator:
            return command
        if not specs:
            if command_end >= len(command):
                break
            command_start = command_end + 1
            continue
        if command_end >= len(command):
            return command  # opener with no body line: unterminated — leave visible
        body_cursor = command_end + 1
        body_ranges: list[tuple[int, int]] = []
        for delimiter, strip_tabs, _quoted in specs:
            close_end = _find_heredoc_close(command, body_cursor, delimiter, strip_tabs)
            if close_end is None:
                return command  # unterminated
            body_ranges.append((body_cursor, close_end))
            body_cursor = close_end
        if (
            all(quoted for _delimiter, _strip_tabs, quoted in specs)
            and not post_heredoc_list_operator
        ):
            masked_opener = _mask_simple_quotes(command[command_start:command_end])
            masked_owner = _mask_simple_quotes(command[owner_start:command_end])
            if not any(
                marker in masked_opener
                for marker in ("$(", "`", "<(", ">(", "(", ")", "{", "}")
            ) and _INERT_HEREDOC_CONSUMER_RE.search(masked_owner):
                ranges.extend(body_ranges)
        command_start = body_cursor
    # Single-pass rebuild (ranges are sorted and non-overlapping), bodies -> their newlines only.
    parts: list[str] = []
    previous = 0
    for start, end in ranges:
        parts += [command[previous:start], "\n" * command.count("\n", start, end)]
        previous = end
    return "".join(parts) + command[previous:]


def _scan_dollar_paren_end(command: str, start: int) -> int:
    """find the end of a $(...) command substitution."""
    depth = 1
    quote: str | None = None
    i = start + 2
    n = len(command)
    while i < n:
        ch = command[i]
        if quote is not None:
            if ch == "\\" and quote != "'" and i + 1 < n:
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
        elif ch in "'\"":
            quote = ch
            i += 1
        elif ch == "\\" and i + 1 < n:
            i += 2
        elif command.startswith("$(", i):
            depth += 1
            i += 2
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
            i += 1
        else:
            i += 1
    return n


def _scan_backtick_end(command: str, start: int) -> int:
    """find the end of a backtick command substitution."""
    i = start + 1
    n = len(command)
    while i < n:
        ch = command[i]
        if ch == "\\":
            i += 2
        elif ch == "`":
            return i + 1
        else:
            i += 1
    return n


def mask_heredoc_bodies_for_detection(command: str) -> str:
    """mask heredoc bodies and operators with spaces for shell detection passes.

    replaces heredoc bodies, declaration operators, and terminators with spaces
    of the same length, preserving exact byte offsets and newlines. for unquoted
    delimiters, nested command substitutions $(...) and backticks are preserved so
    that commands inside them remain visible to detection passes. unterminated
    heredocs fail closed (left untouched) so downstream guards see subsequent lines.
    """
    if "<<" not in command:
        return command

    chars = list(command)
    n = len(command)
    pos = 0
    quote: str | None = None
    line_heredocs: list[tuple[int, int, str, bool, bool]] = []

    while pos < n:
        ch = command[pos]
        if quote is not None:
            if ch == "\\" and quote != "'" and pos + 1 < n:
                pos += 2
                continue
            if ch == quote:
                quote = None
            pos += 1
            continue

        if ch in "'\"":
            quote = ch
            pos += 1
            continue
        if ch == "`":
            quote = ch
            pos += 1
            continue
        if ch == "\\" and pos + 1 < n:
            pos += 2
            continue
        if ch == "#" and (pos == 0 or command[pos - 1].isspace() or command[pos - 1] in ";&|()"):
            nl = command.find("\n", pos)
            pos = n if nl == -1 else nl
            continue
        if command.startswith("$((", pos):
            arith_depth = 2
            pos += 3
            while pos < n and arith_depth > 0:
                if command[pos] == "(":
                    arith_depth += 1
                elif command[pos] == ")":
                    arith_depth -= 1
                pos += 1
            continue
        if command.startswith("((", pos) and (pos == 0 or command[pos - 1].isspace() or command[pos - 1] in ";&|"):
            arith_depth = 2
            pos += 2
            while pos < n and arith_depth > 0:
                if command[pos] == "(":
                    arith_depth += 1
                elif command[pos] == ")":
                    arith_depth -= 1
                pos += 1
            continue

        if command.startswith("<<<", pos):
            pos += 3
            continue
        if command.startswith("<<", pos):
            parsed = _parse_heredoc_operator(command, pos)
            if parsed is not None:
                end_idx, delimiter, strip_tabs, is_q = parsed
                line_heredocs.append((pos, end_idx, delimiter, strip_tabs, is_q))
                pos = end_idx
                continue
            pos += 2
            continue

        if ch == "\n":
            pos += 1
            if line_heredocs:
                body_cursor = pos
                plan = []
                temp_cursor = body_cursor
                all_terminated = True
                for op_start, op_end, delimiter, strip_tabs, is_q in line_heredocs:
                    close_info = None
                    curr = temp_cursor
                    while True:
                        newline = command.find("\n", curr)
                        after = len(command) if newline == -1 else newline + 1
                        line = command[curr:after].removesuffix("\n").removesuffix("\r")
                        candidate = line.lstrip("\t") if strip_tabs else line
                        candidate_is_term = candidate == delimiter or (
                            len(candidate) == len(delimiter) and candidate.strip() == ""
                        )
                        if candidate_is_term:
                            close_info = (curr, after)
                            break
                        if newline == -1:
                            break
                        curr = after
                    if close_info is None:
                        all_terminated = False
                        break
                    term_start, term_after = close_info
                    plan.append((op_start, op_end, temp_cursor, term_start, term_start, term_after, is_q))
                    temp_cursor = term_after

                if not all_terminated:
                    # fail closed: unterminated heredoc, do not mask
                    line_heredocs.clear()
                    continue

                for _, _, b_start, b_end, term_start, term_after, is_q in plan:
                    if is_q:
                        for idx in range(b_start, b_end):
                            if chars[idx] not in "\r\n":
                                chars[idx] = " "
                    else:
                        idx = b_start
                        while idx < b_end:
                            if command.startswith("$(", idx):
                                sub_end = min(b_end, _scan_dollar_paren_end(command, idx))
                                idx = sub_end
                            elif command[idx] == "`":
                                sub_end = min(b_end, _scan_backtick_end(command, idx))
                                idx = sub_end
                            else:
                                if chars[idx] not in "\r\n":
                                    chars[idx] = " "
                                idx += 1
                    for idx in range(term_start, term_after):
                        if chars[idx] not in "\r\n":
                            chars[idx] = " "

                pos = temp_cursor
                line_heredocs.clear()
            continue

        pos += 1

    return "".join(chars)
