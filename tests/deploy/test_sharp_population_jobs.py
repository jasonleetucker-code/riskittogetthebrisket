from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_normal_deploy_installs_and_kicks_all_sharp_population_jobs():
    installer = (ROOT / "deploy" / "install-systemd-service.sh").read_text()
    deploy = (ROOT / "deploy" / "deploy.sh").read_text()
    assert "sharp_needs_install" in installer.split("daemon-reload", 1)[0]
    assert "sharprec_needs_install" in installer.split("daemon-reload", 1)[0]
    assert "ffpc_needs_install" in installer.split("daemon-reload", 1)[0]
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
