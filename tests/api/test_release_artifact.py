"""Release identity is bound to exact source, locks and built frontend bytes."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from src.api.build_identity import (
    _ARTIFACT_ID_KEYS,
    FRONTEND_TREE_DIGEST_VERSION,
    _artifact_id,
    _frontend_tree_digest,
    create_release_manifest,
    resolve_runtime_release_identity,
    verify_release_manifest,
)

SHA = "a" * 40


@pytest.fixture
def release_tree(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/HEAD").write_text(SHA + "\n", encoding="utf-8")
    (tmp_path / "frontend/.next/static").mkdir(parents=True)
    (tmp_path / "frontend/package-lock.json").write_text(
        '{"lockfileVersion":3}\n', encoding="utf-8"
    )
    (tmp_path / "requirements.lock.txt").write_text("fastapi==0.141.1\n", encoding="utf-8")
    build = tmp_path / "frontend/.next"
    (build / "BUILD_ID").write_text("build-123\n", encoding="utf-8")
    (build / "static/chunk.js").write_bytes(b"compiled javascript")
    (build / "cache").mkdir()
    (build / "cache/trace").write_bytes(b"ephemeral cache")
    write_route_manifests(build)
    return tmp_path, build


def write_route_manifests(build: Path) -> None:
    """The two Next route manifests every real build emits."""
    (build / "server/app/login").mkdir(parents=True, exist_ok=True)
    (build / "server/app-paths-manifest.json").write_text(
        json.dumps(
            {
                "/page": "app/page.js",
                "/login/page": "app/login/page.js",
                "/sitemap.xml/route": "app/sitemap.xml/route.js",
            }
        ),
        encoding="utf-8",
    )
    (build / "server/pages-manifest.json").write_text(
        json.dumps({"/404": "pages/404.html"}), encoding="utf-8"
    )
    # Build-time ISR seed and compiled route bundle -- covered, never runtime.
    (build / "server/app/login.html").write_bytes(b"<html>seed</html>")
    (build / "server/app/login/page.js").write_bytes(b"compiled route")


def manifest(root: Path, build: Path, commit: str = SHA) -> dict:
    return create_release_manifest(
        root,
        build,
        commit=commit,
        node_version="v20.19.0",
        run_id="123",
        built_at_utc="2026-10-03T00:00:00Z",
    )


def test_artifact_identity_is_content_addressed_and_verifiable(release_tree):
    root, build = release_tree
    first = manifest(root, build)
    second = create_release_manifest(
        root,
        build,
        commit=SHA,
        node_version="v20.19.0",
        run_id="456",
        built_at_utc="2026-10-04T00:00:00Z",
    )
    assert first["artifact_id"] == second["artifact_id"]
    assert first["identity"]["backend_artifact_sha256"] is None
    assert first["backend_artifact_unavailable_reason"]
    verify_release_manifest(first, root, build, expected_commit=SHA)
    (build / "cache/trace").write_bytes(b"different disposable cache")
    assert manifest(root, build)["artifact_id"] == first["artifact_id"]


def test_every_identity_input_changes_artifact_id(release_tree):
    root, build = release_tree
    baseline = manifest(root, build)["artifact_id"]
    (root / ".git/HEAD").write_text("b" * 40 + "\n", encoding="utf-8")
    assert manifest(root, build, "b" * 40)["artifact_id"] != baseline
    (root / ".git/HEAD").write_text(SHA + "\n", encoding="utf-8")

    lock = root / "requirements.lock.txt"
    lock.write_text("fastapi==0.141.2\n", encoding="utf-8")
    assert manifest(root, build)["artifact_id"] != baseline
    lock.write_text("fastapi==0.141.1\n", encoding="utf-8")

    frontend_lock = root / "frontend/package-lock.json"
    frontend_lock.write_text('{"lockfileVersion":4}\n', encoding="utf-8")
    assert manifest(root, build)["artifact_id"] != baseline
    frontend_lock.write_text('{"lockfileVersion":3}\n', encoding="utf-8")

    (build / "static/chunk.js").write_bytes(b"tampered javascript")
    assert manifest(root, build)["artifact_id"] != baseline


def test_mismatched_commit_or_corrupted_bytes_are_refused(release_tree):
    root, build = release_tree
    built = manifest(root, build)
    with pytest.raises(ValueError, match="Git SHA mismatch"):
        verify_release_manifest(built, root, build, expected_commit="b" * 40)

    with pytest.raises(ValueError, match="differs from the checkout"):
        manifest(root, build, "b" * 40)

    (build / "static/chunk.js").write_bytes(b"modified")
    with pytest.raises(ValueError, match="frontend bytes mismatch"):
        verify_release_manifest(built, root, build, expected_commit=SHA)


def test_manifest_identity_cannot_be_relabelled(release_tree):
    root, build = release_tree
    built = manifest(root, build)
    forged = copy.deepcopy(built)
    forged["artifact_id"] = "0" * 64
    with pytest.raises(ValueError, match="identity mismatch"):
        verify_release_manifest(forged, root, build, expected_commit=SHA)

    forged = copy.deepcopy(built)
    forged["identity"]["backend_artifact_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="backend identity is unsupported"):
        verify_release_manifest(forged, root, build, expected_commit=SHA)


def test_running_identity_reports_verified_bytes_and_unknown_backend(release_tree):
    root, build = release_tree
    absent = resolve_runtime_release_identity(root, commit=SHA)
    assert absent["frontend_artifact_id"] is None
    assert absent["frontend_artifact_unavailable_reason"] == "manifest_missing"
    assert absent["dependency_lock_sha256"]

    built = manifest(root, build)
    (root / ".release-manifest.json").write_text(json.dumps(built), encoding="utf-8")
    running = resolve_runtime_release_identity(root, commit=SHA)
    assert running["frontend_artifact_id"] == built["artifact_id"]
    assert running["frontend_build_id"] == "build-123"
    assert running["frontend_artifact_unavailable_reason"] is None
    assert running["backend_artifact_sha256"] is None
    assert running["backend_artifact_unavailable_reason"]

    (build / "static/chunk.js").write_bytes(b"corrupted after deployment")
    corrupt = resolve_runtime_release_identity(root, commit=SHA)
    assert corrupt["frontend_artifact_id"] is None
    assert corrupt["frontend_artifact_unavailable_reason"] == "manifest_invalid_or_mismatch"


def test_v2_backend_identity_requires_exact_archive_or_install_receipt(release_tree):
    root, build = release_tree
    archive = root / "backend-wheelhouse.tar"
    archive.write_bytes(b"tested backend artifact")
    built = create_release_manifest(
        root,
        build,
        commit=SHA,
        node_version="v20.19.0",
        backend_archive=archive,
    )
    assert built["schema_version"] == "calculator-release/v2"
    verify_release_manifest(built, root, build, expected_commit=SHA)
    archive.write_bytes(b"substituted backend artifact")
    with pytest.raises(ValueError, match="backend bytes mismatch"):
        verify_release_manifest(built, root, build, expected_commit=SHA)
    archive.unlink()
    with pytest.raises(ValueError, match="install receipt missing"):
        verify_release_manifest(built, root, build, expected_commit=SHA)
    identity = built["identity"]
    receipt = {
        "commit": SHA,
        "backend_artifact_sha256": identity["backend_artifact_sha256"],
        "python_lock_sha256": identity["python_lock_sha256"],
        "python_abi": identity["python_abi"],
        "pip_check": "passed",
        "installed_wheels_verified": 1,
    }
    (root / ".backend-artifact-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    verify_release_manifest(built, root, build, expected_commit=SHA)
    (root / ".release-manifest.json").write_text(json.dumps(built), encoding="utf-8")
    running = resolve_runtime_release_identity(root, commit=SHA)
    assert running["backend_artifact_sha256"] == identity["backend_artifact_sha256"]
    assert running["backend_artifact_unavailable_reason"] is None
    receipt["installed_wheels_verified"] = 0
    (root / ".backend-artifact-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="install receipt mismatch"):
        verify_release_manifest(built, root, build, expected_commit=SHA)
    receipt["installed_wheels_verified"] = 1
    receipt["pip_check"] = "failed"
    (root / ".backend-artifact-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="install receipt mismatch"):
        verify_release_manifest(built, root, build, expected_commit=SHA)


def test_workflow_packages_only_after_build_and_checks():
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/deploy.yml").read_text(
        encoding="utf-8"
    )
    assert (
        workflow.index("- name: Frontend bundle-size gate")
        < workflow.index("- name: Package tested release artifact")
        < workflow.index("- name: Upload tested release artifact")
    )
    assert "--exclude='frontend/.next/cache'" in workflow
    assert "sha256sum -c calculator-release.tar.sha256" in workflow


# --- Deploy-gate defect, run 37700964086: Next writes its runtime response
# cache into the served tree, so a post-start digest must not count it. --------


IN_FLIGHT_UUID = "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed"


def _route_cache(build: Path, kind: str, source: str) -> Path:
    owner = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return build / "server/route-cache" / kind / owner / "$"


def _serve_traffic(build: Path) -> None:
    """Exactly the file shapes `next start` wrote after first requests (measured)."""
    login = _route_cache(build, "APP_PAGE", "/login/page")
    (login / "login.segments/login").mkdir(parents=True)
    for name in ("login.html", "login.meta", "login.rsc"):
        (login / name).write_bytes(b"runtime " + name.encode())
    (login / "login.segments/_tree.segment.rsc").write_bytes(b"tree")
    (login / "login.segments/login/__PAGE__.segment.rsc").write_bytes(b"page")
    # Next 16.3.8 writeFileAtomic (node-fs-methods.js): `${f}.${randomUUID()}.tmp`.
    (login / f"login.html.{IN_FLIGHT_UUID}.tmp").write_bytes(b"in-flight atomic write")
    index = _route_cache(build, "APP_PAGE", "/page")
    index.mkdir(parents=True)
    (index / "index.html").write_bytes(b"home")
    sitemap = _route_cache(build, "APP_ROUTE", "/sitemap.xml/route")
    sitemap.mkdir(parents=True)
    (sitemap / "sitemap.xml.body").write_bytes(b"<urlset/>")
    (sitemap / "sitemap.xml.meta").write_bytes(b"{}")


def test_runtime_response_cache_does_not_change_the_verified_identity(release_tree):
    """FAILS on the pre-fix code: the live tree is verified after traffic."""
    root, build = release_tree
    built = manifest(root, build)
    assert built["identity"]["frontend_tree_digest_version"] == FRONTEND_TREE_DIGEST_VERSION
    _serve_traffic(build)
    verify_release_manifest(built, root, build, expected_commit=SHA)
    # ISR regeneration rewrites the same entries -- still the same artifact.
    regenerated = _route_cache(build, "APP_ROUTE", "/sitemap.xml/route")
    (regenerated / "sitemap.xml.body").write_bytes(b"<urlset>regenerated</urlset>")
    verify_release_manifest(built, root, build, expected_commit=SHA)
    (root / ".release-manifest.json").write_text(json.dumps(built), encoding="utf-8")
    running = resolve_runtime_release_identity(root, commit=SHA)
    assert running["frontend_artifact_id"] == built["artifact_id"]
    assert running["frontend_tree_digest_version"] == FRONTEND_TREE_DIGEST_VERSION


def _replace(path: str, content: bytes):
    return lambda build: (build / path).write_bytes(content)


@pytest.mark.parametrize(
    "mutate",
    [
        _replace("static/chunk.js", b"substituted chunk"),
        _replace("BUILD_ID", b"build-123\n "),
        _replace("server/app/login.html", b"<html>altered seed</html>"),
        _replace("server/app/login/page.js", b"altered bundle"),
        _replace("prerender-manifest.json", b'{"routes": {}}'),
        _replace("server/pages-manifest.json", b'{"/404": "pages/404.html", "/x": "pages/x.html"}'),
    ],
    ids=[
        "js_chunk",
        "build_id_bytes",
        "build_seed",
        "server_bundle",
        "prerender_manifest",
        "route_manifest",
    ],
)
def test_every_built_byte_outside_the_route_cache_is_still_covered(release_tree, mutate):
    root, build = release_tree
    built = manifest(root, build)
    _serve_traffic(build)
    mutate(build)
    with pytest.raises(ValueError, match="frontend bytes mismatch"):
        verify_release_manifest(built, root, build, expected_commit=SHA)


def _login_root(build: Path) -> Path:
    return _route_cache(build, "APP_PAGE", "/login/page")


@pytest.mark.parametrize(
    "smuggle",
    [
        # executable content hidden in the excluded directory
        lambda b: _login_root(b) / "evil.js",
        # a route the build never declared
        lambda b: _route_cache(b, "APP_PAGE", "/not/declared/page") / "x.html",
        # a declared route hash under the wrong kind
        lambda b: _route_cache(b, "APP_ROUTE", "/login/page") / "login.body",
        # outside the "$" pathname root
        lambda b: _login_root(b).parent / "x.html",
        # straight into the directory
        lambda b: b / "server/route-cache/chunk.html",
        # a temp file that is not Next's `<file>.<uuid>.tmp` shape
        lambda b: _login_root(b) / "login.html.tmp.k3j2h1",
        lambda b: _login_root(b) / f"login.js.{IN_FLIGHT_UUID}.tmp",
    ],
    ids=[
        "non_response_suffix",
        "undeclared_route",
        "wrong_kind",
        "outside_root",
        "flat",
        "foreign_tmp_shape",
        "tmp_of_non_response_file",
    ],
)
def test_route_cache_refuses_anything_next_would_not_write(release_tree, smuggle):
    root, build = release_tree
    built = manifest(root, build)
    target = smuggle(build)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"smuggled")
    with pytest.raises(ValueError, match="undeclared entry"):
        verify_release_manifest(built, root, build, expected_commit=SHA)


@pytest.mark.parametrize("name", ["server/app-paths-manifest.json", "server/pages-manifest.json"])
@pytest.mark.parametrize("content", [None, "not json", "[]", '{"no-leading-slash": "x"}'])
def test_missing_or_malformed_route_manifest_fails_closed(release_tree, name, content):
    root, build = release_tree
    built = manifest(root, build)
    if content is None:
        (build / name).unlink()
    else:
        (build / name).write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="route manifest"):
        verify_release_manifest(built, root, build, expected_commit=SHA)
    with pytest.raises(ValueError, match="route manifest"):
        manifest(root, build)


def test_tested_artifact_must_not_carry_a_route_cache(release_tree):
    root, build = release_tree
    _serve_traffic(build)
    with pytest.raises(ValueError, match="already contains a runtime route cache"):
        manifest(root, build)


def test_digest_version_is_bound_into_the_artifact_id(release_tree):
    root, build = release_tree
    built = manifest(root, build)
    for forged_version in ("other/v9", None):
        forged = copy.deepcopy(built)
        forged["identity"]["frontend_tree_digest_version"] = forged_version
        with pytest.raises(ValueError, match="digest version is unsupported"):
            verify_release_manifest(forged, root, build, expected_commit=SHA)
    # Dropping the field selects the legacy algorithm; the ID no longer matches.
    stripped = copy.deepcopy(built)
    del stripped["identity"]["frontend_tree_digest_version"]
    _serve_traffic(build)
    with pytest.raises(ValueError, match="identity mismatch"):
        verify_release_manifest(stripped, root, build, expected_commit=SHA)
    assert _artifact_id(stripped["identity"]) != built["artifact_id"]


def _legacy_manifest(root: Path, build: Path) -> dict:
    """A manifest exactly as the pre-fix code wrote it (the box's rollback window)."""
    built = manifest(root, build)
    identity = dict(built["identity"])
    del identity["frontend_tree_digest_version"]
    identity["frontend_tree_sha256"] = _frontend_tree_digest(build)
    legacy_fields = {key: identity[key] for key in _ARTIFACT_ID_KEYS}
    encoded = json.dumps(legacy_fields, sort_keys=True, separators=(",", ":")).encode()
    return {**built, "identity": identity, "artifact_id": hashlib.sha256(encoded).hexdigest()}


def _pre_fix_digest(build: Path) -> str:
    """Independent copy of the ORIGINAL ``_frontend_tree_digest`` (pre-#1707)."""
    files = []
    for path in sorted(build.rglob("*")):
        relative = path.relative_to(build)
        if relative.parts[0] == "cache" or not path.is_file():
            continue
        files.append((relative.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    return hashlib.sha256(
        json.dumps(files, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def test_legacy_manifest_without_route_cache_is_byte_identical(release_tree):
    root, build = release_tree
    legacy = _legacy_manifest(root, build)
    assert legacy["identity"]["frontend_tree_sha256"] == _pre_fix_digest(build)
    assert _artifact_id(legacy["identity"]) == legacy["artifact_id"]
    verify_release_manifest(legacy, root, build, expected_commit=SHA)
    (root / ".release-manifest.json").write_text(json.dumps(legacy), encoding="utf-8")
    running = resolve_runtime_release_identity(root, commit=SHA)
    assert running["frontend_artifact_id"] == legacy["artifact_id"]
    assert running["frontend_tree_digest_version"] == "legacy"
    (build / "static/chunk.js").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="frontend bytes mismatch"):
        verify_release_manifest(legacy, root, build, expected_commit=SHA)


def test_legacy_digest_without_route_cache_needs_no_route_manifests(release_tree):
    """A tree with no route cache hashes exactly as before -- no new requirement."""
    _, build = release_tree
    (build / "server/app-paths-manifest.json").unlink()
    (build / "server/pages-manifest.json").unlink()
    assert _frontend_tree_digest(build) == _pre_fix_digest(build)


def test_legacy_manifest_verifies_after_traffic(release_tree):
    """F3: a pre-fix release in the rollback window survives a post-traffic verify."""
    root, build = release_tree
    legacy = _legacy_manifest(root, build)
    _serve_traffic(build)
    verify_release_manifest(legacy, root, build, expected_commit=SHA)
    (root / ".release-manifest.json").write_text(json.dumps(legacy), encoding="utf-8")
    assert (
        resolve_runtime_release_identity(root, commit=SHA)["frontend_artifact_id"]
        == (legacy["artifact_id"])
    )
    (build / "server/app/login/page.js").write_bytes(b"altered bundle")
    with pytest.raises(ValueError, match="frontend bytes mismatch"):
        verify_release_manifest(legacy, root, build, expected_commit=SHA)


def test_legacy_manifest_refuses_an_undeclared_route_cache_entry(release_tree):
    root, build = release_tree
    legacy = _legacy_manifest(root, build)
    _serve_traffic(build)
    (_login_root(build) / "evil.js").write_bytes(b"smuggled")
    with pytest.raises(ValueError, match="undeclared entry"):
        verify_release_manifest(legacy, root, build, expected_commit=SHA)


def test_legacy_route_cache_without_route_manifests_fails_closed(release_tree):
    root, build = release_tree
    legacy = _legacy_manifest(root, build)
    _serve_traffic(build)
    (build / "server/app-paths-manifest.json").unlink()
    with pytest.raises(ValueError, match="route manifest"):
        verify_release_manifest(legacy, root, build, expected_commit=SHA)


def _shell_function(text: str, name: str) -> str:
    start = text.index(f"\n{name}() {{")
    return text[start : text.index("\n}\n", start)]


def test_deploy_and_rollback_assert_no_route_cache_before_next_starts():
    """The compensating pre-start guarantee for the route-cache exclusion (F2)."""
    repo = Path(__file__).resolve().parents[2]
    deploy = _shell_function(
        (repo / "deploy/deploy.sh").read_text(encoding="utf-8"), "deploy_frontend_atomic"
    )
    stop = deploy.index('"${SYSTEMCTL_BIN}" stop "${frontend_name}"')
    # Staging is refused BEFORE the stop, so a refusal leaves the old frontend serving.
    staged = deploy.index('if [[ -e "${staging_dir}/server/route-cache"')
    assert staged < stop
    assert "exit 1" in deploy[staged:stop]
    # ...and the live dir is re-checked between the swap and the start.
    guard = deploy.index('if [[ -e "${live_dir}/server/route-cache"')
    assert deploy.index('mv "${staging_dir}" "${live_dir}"') < guard
    assert guard < deploy.index('"${SYSTEMCTL_BIN}" start "${frontend_name}"')
    assert "exit 1" in deploy[guard : deploy.index('"${SYSTEMCTL_BIN}" start')]

    rollback = (repo / "deploy/rollback.sh").read_text(encoding="utf-8")
    guard = rollback.index('if [[ -e "${staging_dir}/server/route-cache"')
    assert guard < rollback.index('"${SYSTEMCTL_BIN}" stop "${frontend_name}"')
    assert guard < rollback.index('mv "${staging_dir}" "${live_dir}"')
    assert guard < rollback.index('"${SYSTEMCTL_BIN}" start "${frontend_name}"')
    assert "return 1" in rollback[guard : rollback.index('mv "${staging_dir}" "${live_dir}"')]


def test_deploy_still_verifies_the_live_tree_after_start():
    """The post-start check stays; the fix is in the digest, not the workflow."""
    repo = Path(__file__).resolve().parents[2]
    workflow = (repo / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    step = workflow.index("- name: Verify live frontend matches the tested artifact")
    assert workflow.index("- name: Post-deploy smoke test") < step
    assert (
        "python3 -m scripts.release_artifact verify --root '${APP_DIR}' --manifest "
        "'${DEPLOY_STATE_DIR}/last_successful_release_manifest.json'" in workflow[step:]
    )
