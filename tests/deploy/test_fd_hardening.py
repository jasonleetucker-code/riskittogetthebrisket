"""File-descriptor hardening and observability, pinned.

Incident of 2026-08-12.  ``socket.accept()`` raised
``OSError: [Errno 24] Too many open files`` 1,212 times from PID 887292,
first at 16:47:46 local.  The kernel kept completing TCP handshakes into
the listen backlog while the application answered nothing, so nginx
connected in 0.4 ms and then waited its full 300 s ``proxy_read_timeout``.

Two facts, and the gap between them is what these tests hold open:

* the unit declared no ``LimitNOFILE``, so the process ran with the
  distro's **1024 soft** default — the number EMFILE is raised against;
* nothing anywhere reported the descriptor count on the way up, so the
  first signal was total unavailability.

What accumulated is **unresolved**.  A healthy process measures ~16
descriptors and stayed flat across a full observation window, so 1024
was not a tight budget — it was a floor something managed to reach.
These tests therefore pin *defence in depth and visibility*, and
deliberately do not pretend to pin a fix.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "deploy" / "systemd" / "dynasty.service.template"
HEALTHCHECK = REPO_ROOT / "deploy" / "systemd" / "dynasty-healthcheck.sh"
INVENTORY = REPO_ROOT / "deploy" / "diagnostics" / "fd_inventory.sh"


class TestTheUnitDeclaresAnExplicitFileDescriptorLimit:
    def test_limitnofile_is_set(self):
        assert re.search(r"^LimitNOFILE=", UNIT.read_text(), re.M), (
            "dynasty.service.template sets no LimitNOFILE, so the process "
            "inherits the distro's 1024 soft default — the limit EMFILE was "
            "raised against on 2026-08-12"
        )

    def test_the_soft_limit_is_raised_and_the_hard_limit_is_not(self):
        """``soft:hard`` — systemd.exec's documented split.

        Raising the soft limit lets the process open more; leaving the
        hard limit at what the host already permitted means this grants
        no new ceiling.
        """
        m = re.search(r"^LimitNOFILE=(\d+):(\d+)\s*$", UNIT.read_text(), re.M)
        assert m, "LimitNOFILE should use systemd's soft:hard form"
        soft, hard = int(m.group(1)), int(m.group(2))
        assert soft > 1024, f"soft limit {soft} is not above the 1024 default that failed"
        assert soft <= hard, f"soft {soft} exceeds hard {hard}"
        assert hard == 524288, (
            f"hard limit changed to {hard}; it was 524288 before the incident and "
            "raising it is a separate decision from raising the soft limit"
        )

    def test_the_limit_is_documented_as_defence_not_a_fix(self):
        """A number without its reasoning gets 'tuned' away later."""
        text = UNIT.read_text()
        assert "Errno 24" in text, "the limit does not reference the incident that motivated it"
        assert "NOT THE FIX" in text.upper(), (
            "nothing records that this is defence in depth — a later reader "
            "will take it for the root-cause repair"
        )


class TestSomethingWatchesTheDescriptorCount:
    """It must work when the process cannot answer HTTP.

    That is the whole requirement: during the incident the backend served
    nothing, so any metric exposed by the application itself would have
    been unavailable exactly when it was needed.
    """

    def test_the_watch_lives_in_the_out_of_process_healthcheck(self):
        text = HEALTHCHECK.read_text()
        assert "fd_watch" in text, (
            "no FD watch in the minutely healthcheck — the only monitor here "
            "that does not depend on the backend answering"
        )

    def test_it_reads_proc_rather_than_asking_the_application(self):
        text = HEALTHCHECK.read_text()
        assert "/proc/${pid}/fd" in text
        assert "/api/fd" not in text, (
            "the FD count must not come from an application endpoint; the "
            "process being unable to answer is the condition being watched"
        )

    def test_thresholds_are_absolute_and_far_below_the_limit(self):
        """80% of 8192 would only fire once it is already unrecoverable.

        Normal is ~16 descriptors, so the alarm belongs near normal, not
        near the ceiling.
        """
        text = HEALTHCHECK.read_text()
        warn = int(re.search(r'FD_WARN="\$\{FD_WARN:-(\d+)\}"', text).group(1))
        crit = int(re.search(r'FD_CRIT="\$\{FD_CRIT:-(\d+)\}"', text).group(1))
        emerg = int(re.search(r'FD_EMERG="\$\{FD_EMERG:-(\d+)\}"', text).group(1))
        assert warn < crit < emerg, "thresholds must escalate"
        assert warn <= 256, f"warning at {warn} is too late for a ~16-descriptor baseline"
        assert emerg <= 1024, (
            f"emergency at {emerg} is above the 1024 that actually failed — the "
            "alarm would arrive after the outage"
        )

    def test_it_reports_and_never_restarts(self):
        """The liveness rule is the only thing allowed to restart.

        A second, independent restart trigger added during an incident
        repair is how a bounce loop nobody predicted gets shipped.
        """
        text = HEALTHCHECK.read_text()
        fd_block = text[text.index("fd_watch()") : text.index("# LIVENESS probe")]
        assert (
            "systemctl restart" not in fd_block
        ), "the FD watch restarts the service; it must only report"

    def test_a_warning_names_which_kind_of_descriptor_is_growing(self):
        """Which family grows is the first question a responder has.

        It is also unrecoverable once the process is gone — which is
        precisely why this incident's cause is unresolved.
        """
        text = HEALTHCHECK.read_text()
        for field in ("sockets=", "files=", "anon=", "soft_limit="):
            assert field in text, f"FD warning does not report {field}"


class TestTheDiagnosticDoesNotMisreadItsOwnEvidence:
    def test_file_nr_is_not_labelled_free(self):
        """The middle column is unused-but-allocated, not 'free'.

        On modern kernels it is essentially always 0, so reading it as
        remaining capacity inverts the meaning.
        """
        text = INVENTORY.read_text()
        assert "allocated / free / max" not in text
        assert "allocated / unused / max" in text

    def test_lsof_is_not_presented_as_an_fd_count(self):
        """lsof lists mappings, cwd and the text segment too.

        Its REG rows exceed the open regular-file descriptors, so the
        canonical count has to come from /proc/PID/fd.
        """
        text = INVENTORY.read_text()
        assert "NOT an FD count" in text
        assert "canonical" in text
