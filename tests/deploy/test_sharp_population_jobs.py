from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _daemon_reload_condition(installer: str) -> str:
    """The ``if [[ ... ]]`` line gating the shared ``daemon-reload``.

    This used to be spelled ``installer.split("daemon-reload", 1)[0]`` —
    "the flag appears somewhere before the first daemon-reload in the
    file". That is a positional proxy for the real claim, and it broke
    the moment a ``daemon-reload`` appeared earlier in the file (the
    shared ``install_simple_timer`` helper, which reloads for itself).
    Nothing about the sharp jobs had changed. Assert the claim directly.
    """
    return next(
        line
        for line in installer.split("\n")
        if line.lstrip().startswith("if [[") and line.count("_needs_install}") > 1
    )


def test_normal_deploy_installs_and_kicks_all_sharp_population_jobs():
    installer = (ROOT / "deploy" / "install-systemd-service.sh").read_text()
    deploy = (ROOT / "deploy" / "deploy.sh").read_text()
    reload_condition = _daemon_reload_condition(installer)
    assert "sharp_needs_install" in reload_condition
    assert "sharprec_needs_install" in reload_condition
    assert "ffpc_needs_install" in reload_condition
    assert 'start --no-block "${sharprec_service_name}.service"' in installer
    assert 'start --no-block "${ffpc_service_name}.service"' in installer
    assert 'is-enabled "${timer_unit}"' in deploy


def test_ffpc_timer_is_daily_and_records_bootstrap_has_large_budget():
    timer = (ROOT / "deploy" / "systemd" / "dynasty-ffpc-sharp.timer.template").read_text()
    records = (ROOT / "deploy" / "systemd" / "dynasty-sharp-records.service.template").read_text()
    assert "OnCalendar=*-*-* 05:20:00 UTC" in timer
    assert "Persistent=true" in timer
    assert "crawl_sharp_records.py --budget 5000" in records
    assert "TimeoutStartSec=3600" in records
