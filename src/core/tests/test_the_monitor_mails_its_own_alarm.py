"""The outside monitor's alarm has to reach a MAILBOX, and only this file says so.

The defect, measured on the live setup on 2026-09-19: `.github/workflows/monitor.yml`
raised its alarm by opening an issue that mentions the repository owner, on the assumption
that a mention e-mails them. A rehearsed outage opened the issue correctly and the monitor
closed it on recovery, GitHub recorded a `mention` notification -- and no e-mail arrived,
because whether a notification becomes mail is a setting on the owner's account. "The
instance is down" reached nobody's inbox. The instance's own weekly health e-mail cannot
cover that case either: a box that is down sends nothing.

So the monitor now sends the e-mail itself, from outside the instance. Three properties of
that leg are load-bearing and every one of them regresses SILENTLY -- a monitor nobody is
watching is exactly where a quiet regression lives:

1. **The mailbox configuration arrives only as a SECRET.** The recipient and the sender are
   mailbox addresses and the key is a credential; this repository is public, and a
   repository VARIABLE is readable by anyone who can see it. Moving one to `vars.` would
   change no behaviour at all and publish an address.
2. **The e-mail leg cannot print a secret-bearing variable.** The Actions log of a public
   repository is world-readable. `set -x` anywhere in the step, or one `echo "$MONITOR_..."`
   added while debugging, publishes the key, the addresses or the monitored host -- and the
   monitored host is the family's. Resend's own response body echoes the recipient back,
   which is why the response goes to `/dev/null` and only the status code is printed.
3. **It e-mails on the two STATE CHANGES and nowhere else.** A new alarm, and the recovery.
   The daily reminder comment must stay silent: once a day into an inbox is how an alarm
   gets muted, and a muted alarm takes the UNREACHABLE case with it -- which is the whole
   argument the rest of that workflow is built on.

Read as text, for the reason `test_ci_still_runs_what_it_claims.py` records: the question is
whether specific, named, load-bearing shell is still there, and it is shell rather than YAML
structure, so a YAML parser would not answer it either.

Each rule is a named function driven by BOTH the real workflow and a synthetic bad example,
so the rejection is exercised rather than assumed -- the self-tests here failed against the
mechanism removed, one at a time, before this file was committed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_MONITOR = _ROOT / ".github" / "workflows" / "monitor.yml"

# The three repository secrets the e-mail leg needs. Named here so a rename has to pass
# through this file, and so the "not armed" line can be checked against the same list an
# operator would be told to set.
_SECRETS = ("MONITOR_RESEND_API_KEY", "MONITOR_ALERT_TO", "MONITOR_ALERT_FROM")

# Anything inside `${{ … }}`, which is the only way a secret can legitimately enter.
_EXPRESSION = re.compile(r"\$\{\{(?P<body>.*?)\}\}", re.S)

# A print STATEMENT whose arguments reach for a `MONITOR_`-prefixed shell variable. Three
# things are deliberate here:
#
# * The `$` is required, so the "not armed" line -- which names the three secrets as WORDS,
#   which is the point of it -- is not caught, while `echo "$MONITOR_ALERT_TO"` is.
# * `MONITOR_URL` is covered by the same prefix on purpose: the monitored host is the
#   family's address, and it has never been in this file for that reason.
# * The print must START a command (line start, or after `;`, `&&`, `||`). A printf whose
#   output is CAPTURED is not a print into the log, and the certificate half tokenises the
#   monitored URL exactly that way (`host=$(printf '%s' "$MONITOR_URL" | sed …)`). Catching
#   it would be a false alarm, and a guard that cries wolf gets switched off.
_PRINTS_A_MONITOR_VARIABLE = re.compile(
    r"(?:^|;|&&|\|\|)\s*(?:echo|printf)\b[^\n|]*\$\{?MONITOR_", re.M
)

# `set -x`, in either spelling and in any flag cluster (`-euxo pipefail` is how it usually
# arrives). It would trace the curl invocation, Authorization header and all, into a public
# log, and nothing else about the run would look different.
_SHELL_TRACE = re.compile(r"^\s*set\s+(?:-[a-zA-Z]*x[a-zA-Z]*|-o\s+xtrace\b)", re.M)

# The line each branch of the alarm hangs off. A needle rather than a line number, and one
# that names what the branch DOES, so reformatting the workflow does not silently move the
# rule onto a different branch.
_NEW_ALARM = "issue_url=$(gh issue create"
_RECOVERY = "if gh issue close"
_DAILY_REMINDER = 'if [ "$age" -gt 86400 ]; then'
_SEND_FUNCTION = "send_alert_mail() {"
_NOT_ARMED = '[ -z "${MONITOR_RESEND_API_KEY:-}" ]'

# A call, not the definition: after the name comes whitespace rather than `(`.
_CALLS_SEND = re.compile(r"^\s*send_alert_mail\s", re.M)


def _workflow() -> str:
    return _MONITOR.read_text(encoding="utf-8")


def _step_script(text: str) -> str:
    """The body of the step's `run: |` block, dedented.

    The whole mechanism is shell inside one block string, so every rule below needs the
    shell on its own -- reading the surrounding YAML would let a `run:` in a comment or a
    second step satisfy a rule about this one. There is exactly one such block in this
    workflow (it is a one-job, one-step file on purpose) and finding a different number is
    an error rather than a guess.
    """
    lines = text.splitlines()
    headers = [index for index, line in enumerate(lines) if line.strip() == "run: |"]
    if len(headers) != 1:
        raise AssertionError(
            f"{_MONITOR.name} has {len(headers)} `run: |` blocks; this reader assumes the "
            "one step that file is built around, so it has stopped being able to answer "
            "which script the rules below are about"
        )
    header = lines[headers[0]]
    indent = len(header) - len(header.lstrip()) + 2
    body: list[str] = []
    for line in lines[headers[0] + 1 :]:
        if line.strip() and not line.startswith(" " * indent):
            break
        body.append(line[indent:])
    return "\n".join(body)


def _branch(script: str, needle: str) -> str:
    """The lines a shell branch owns: everything indented deeper than its header line.

    Indentation, because that is what actually delimits the branch here and a regex over
    the whole script cannot tell "the recovery path sends the e-mail" from "the script
    contains the word somewhere". A `then` branch ends at the first line indented no deeper
    than its header, which is its own `else`/`fi`; continuation lines of a multi-line header
    are deeper, so they come along, which is harmless and keeps the reader dumb.
    """
    lines = script.splitlines()
    hits = [index for index, line in enumerate(lines) if needle in line]
    if len(hits) != 1:
        raise AssertionError(
            f"`{needle}` matches {len(hits)} lines of the monitor's script. A branch rule "
            "cannot be about a branch the reader cannot find, and two matches mean it could "
            "be asserting about the wrong one."
        )
    header = lines[hits[0]]
    depth = len(header) - len(header.lstrip())
    body: list[str] = []
    for line in lines[hits[0] + 1 :]:
        if not line.strip():
            body.append(line)
            continue
        if len(line) - len(line.lstrip()) <= depth:
            break
        body.append(line)
    return "\n".join(body)


def _secret_wiring_problems(text: str, name: str) -> list[str]:
    """Why `name` is not arriving purely as a repository secret, if it is not.

    One implementation, driven by the real workflow and by the synthetic bad examples in
    `test_the_secret_rule_rejects_what_it_is_supposed_to_reject`. A self-test that
    re-implements the rule drifts towards passing; the same note is on `problems_with` in
    `scripts/check_compose_overlay.py`.
    """
    problems = []
    wiring = re.search(rf"^\s+{name}: (?P<value>.*)$", text, re.M)
    if wiring is None:
        problems.append(f"{name} is not wired into the step's `env:` at all")
    elif wiring.group("value").strip() != f"${{{{ secrets.{name} }}}}":
        problems.append(
            f"{name} is set to {wiring.group('value').strip()!r} rather than "
            f"`${{{{ secrets.{name} }}}}` — a literal in the tree, or a repository VARIABLE, "
            "which anyone who can see this public repository can read"
        )
    for expression in _EXPRESSION.findall(text):
        if name in expression and expression.strip() != f"secrets.{name}":
            problems.append(
                f"{name} is also read through `${{{{{expression}}}}}`, which is not the "
                "secrets context"
            )
    return problems


def test_the_monitor_workflow_and_its_alarm_branches_are_where_we_think() -> None:
    """Denominator. Every rule below is a substring or a branch lookup against one script:
    if the file moved, the block reader broke, or a branch was renamed, they would all go
    quiet together — which is this repository's most-repeated failure mode."""
    assert _MONITOR.is_file(), f"no workflow at {_MONITOR}"
    script = _step_script(_workflow())
    assert len(script) > 2000, (
        f"the monitor's step script is {len(script)} bytes; that is not this workflow, so "
        "the rules below are asserting about the wrong text"
    )
    for needle in (_NEW_ALARM, _RECOVERY, _DAILY_REMINDER, _SEND_FUNCTION, _NOT_ARMED):
        assert script.count(needle) == 1, (
            f"`{needle}` occurs {script.count(needle)} times in the monitor's script; the "
            "rules below identify the alarm's branches by these lines, so a rename or a "
            "duplicate leaves them pointing at nothing or at the wrong branch"
        )


@pytest.mark.parametrize("name", _SECRETS)
def test_the_mailbox_configuration_arrives_only_as_a_secret(name: str) -> None:
    problems = _secret_wiring_problems(_workflow(), name)
    assert not problems, (
        f"{_MONITOR.name}: " + "; ".join(problems) + ".\n\n"
        "Two of these three are mailbox addresses and the third is a sending credential. A "
        "repository variable is readable by anyone who can see this public repository, and "
        "moving one across would change no behaviour a run could report."
    )


def test_the_secret_rule_rejects_what_it_is_supposed_to_reject() -> None:
    """Non-vacuity: a variable, a committed literal and a missing wiring are each the shape
    somebody reaches for when a secret is inconvenient."""
    name = "MONITOR_ALERT_TO"
    assert not _secret_wiring_problems(f"          {name}: ${{{{ secrets.{name} }}}}\n", name)
    for rejected in (
        f"          {name}: ${{{{ vars.{name} }}}}\n",
        f"          {name}: someone@example.com\n",
        "          SOMETHING_ELSE: x\n",
    ):
        assert _secret_wiring_problems(rejected, name), (
            f"{rejected.strip()!r} is not the secrets context and was accepted"
        )


def test_the_email_leg_cannot_print_a_secret_bearing_variable() -> None:
    script = _step_script(_workflow())
    assert 'echo "$MONITOR_' not in script and 'echo "${MONITOR_' not in script, (
        "the monitor's script echoes a MONITOR_ variable. Written out as a literal beside "
        "the rule below, because this is the one shape that actually gets added — a line "
        "somebody puts in to see what the workflow is doing, on a public repository."
    )
    printed = [
        line.strip() for line in script.splitlines() if _PRINTS_A_MONITOR_VARIABLE.search(line)
    ]
    assert not printed, (
        "the monitor's script prints a MONITOR_ variable into a world-readable Actions "
        "log:\n" + "\n".join(f"  {line}" for line in printed) + "\n\nThose variables hold "
        "the sending key, the recipient, the sender and the monitored host — and the "
        "monitored host is the family's address, which is why it was never in this file."
    )
    trace = _SHELL_TRACE.search(script)
    assert trace is None, (
        f"the monitor's script turns on shell tracing ({trace.group(0).strip()!r}). Every "
        "command is then echoed to a public log, Authorization header included, and nothing "
        "about the run would look different."
    )


def test_the_print_rule_rejects_what_it_is_supposed_to_reject() -> None:
    """Non-vacuity. The rule has to catch the debugging line somebody adds at 2am and leave
    the 'not armed' line — which names the same three secrets as WORDS — alone."""
    for rejected in (
        'echo "$MONITOR_ALERT_TO"',
        'echo "recipient: ${MONITOR_ALERT_TO}"',
        'printf "%s" "$MONITOR_RESEND_API_KEY"',
        'echo "polling $MONITOR_URL"',
    ):
        assert _PRINTS_A_MONITOR_VARIABLE.search(rejected), f"{rejected!r} was not caught"
    for accepted in (
        'echo "the e-mail leg is not armed; set MONITOR_ALERT_TO and MONITOR_ALERT_FROM"',
        'echo "alert e-mail sent (HTTP ${mail_code})"',
        'curl -H "Authorization: Bearer $MONITOR_RESEND_API_KEY"',
        # Captured, not printed: the certificate half's own line, which must not be a
        # finding or the guard becomes something to switch off.
        "host=$(printf '%s' \"$MONITOR_URL\" | sed -E 's#^[a-z]+://##')",
    ):
        assert not _PRINTS_A_MONITOR_VARIABLE.search(accepted), f"{accepted!r} was caught"
    for rejected in ("set -x", "  set -euxo pipefail", "set -o xtrace"):
        assert _SHELL_TRACE.search(rejected), f"{rejected!r} is tracing and was not caught"
    assert not _SHELL_TRACE.search("set -uo pipefail"), "the script's own `set` is not tracing"


def test_resends_answer_never_reaches_the_log() -> None:
    """Resend's 200 body echoes the recipient back, so the response is the leak, not the
    request. The status code is the only thing this leg is allowed to learn out loud."""
    send = _branch(_step_script(_workflow()), _SEND_FUNCTION)
    for fragment, why in (
        ("-o /dev/null", "the response body must be discarded before anything can print it"),
        ("-w '%{http_code}'", "the status code is what the leg reports instead of the body"),
        (
            "--max-time 20",
            "an alarm that hangs on a stalled TLS handshake is an alarm that "
            "went quiet; the certificate half has the same bound for the same reason",
        ),
        (
            "jq -n",
            "the payload is built by jq, so a quotation mark or a newline in a problem "
            "line is data rather than a way to break the JSON or inject a field",
        ),
    ):
        assert fragment in send, f"the send function no longer uses `{fragment}`: {why}"
    assert "--fail-with-body" not in send, (
        "`--fail-with-body` prints the response body on an error — which is exactly the "
        "body that echoes the recipient back, and errors are when somebody reads the log"
    )


def test_both_state_changes_mail_and_the_daily_reminder_does_not() -> None:
    """The alarm e-mails when the STATE changes and at no other time.

    Asserted per branch rather than by counting the word in the file: `send_alert_mail`
    appearing twice somewhere in the script is satisfied by both calls sitting on the
    reminder path, which is the failure that would mute the alarm.
    """
    script = _step_script(_workflow())
    assert "send_alert_mail" in _branch(script, _NEW_ALARM), (
        "a NEW alarm issue is opened without e-mailing anybody. That is the defect this "
        "leg exists for: the issue's mention was measured NOT to reach the owner's mailbox, "
        "so with this call gone 'the instance is down' reaches nobody again."
    )
    assert "send_alert_mail" in _branch(script, _RECOVERY), (
        "the monitor closes the alarm issue without saying so by e-mail. Somebody who was "
        "told the instance was down is then never told it came back, and the next thing "
        "they do is go and look."
    )
    reminder = _branch(script, _DAILY_REMINDER)
    assert "send_alert_mail" not in reminder, (
        "the DAILY REMINDER comment now e-mails as well. A problem that persists for a week "
        "is then seven e-mails saying what the first one said, and the reliable end of that "
        "is a muted alarm — which takes the UNREACHABLE case with it. The issue is the "
        "throttle; the e-mail is for state CHANGES."
    )
    calls = _CALLS_SEND.findall(script)
    assert len(calls) == 2, (
        f"the monitor's script calls send_alert_mail {len(calls)} times. There are exactly "
        "two state changes — a new alarm and the recovery — so a third call site is a third "
        "e-mail nobody decided to send."
    )


def test_the_branch_reader_can_tell_the_paths_apart() -> None:
    """Non-vacuity for `_branch`, which is the part most able to go quiet: a reader that
    returned the whole script would make every rule above pass at once, including the one
    that must FAIL when the reminder path starts e-mailing."""
    sample = "\n".join(
        (
            'if [ "$age" -gt 86400 ]; then',
            "  gh issue comment 1",
            "else",
            "  send_alert_mail wrong",
            "fi",
            "if gh issue close 1; then",
            "  send_alert_mail right",
            "fi",
        )
    )
    reminder = _branch(sample, 'if [ "$age" -gt 86400 ]; then')
    assert "gh issue comment 1" in reminder
    assert "send_alert_mail" not in reminder, (
        "the reader ran past the branch's own `else`, so 'the reminder does not e-mail' "
        "would be asserted against the whole file"
    )
    assert "send_alert_mail right" in _branch(sample, "if gh issue close")
    with pytest.raises(AssertionError):
        _branch(sample, "gh issue")  # ambiguous: three lines contain it


def test_an_unarmed_email_leg_is_one_quiet_line_and_never_an_alarm_failure() -> None:
    """With the secrets unset the monitor must behave exactly as it did before this leg
    existed. A fork of this repository has none of them, and neither does this repository
    until somebody sets them; turning that into a red check every 30 minutes would train
    the owner to ignore the one workflow whose job is to be believed."""
    script = _step_script(_workflow())
    unarmed = _branch(script, _NOT_ARMED)
    assert "fail_alarm" not in unarmed, (
        "an unarmed e-mail leg fails the alarm. Nothing is wrong with the instance when the "
        "secrets are simply not set, and a monitor that is red every half hour is a monitor "
        "nobody reads."
    )
    spoken = [line.strip() for line in unarmed.splitlines() if line.strip().startswith("echo ")]
    assert len(spoken) == 1, (
        f"the unarmed e-mail leg says {len(spoken)} lines; it gets exactly one, because it "
        "is printed on every run of a workflow that runs 48 times a day"
    )
    for name in _SECRETS:
        assert name in spoken[0], (
            f"the 'not armed' line does not name {name}, so it tells the reader something "
            "is missing without telling them what to set"
        )
    send = _branch(script, _SEND_FUNCTION)
    assert '[ "$mail_armed" -eq 1 ] || return 0' in send, (
        "the send function no longer returns early when the leg is unarmed, so an unset "
        "secret becomes a curl with an empty Authorization header on every state change"
    )
