from scripts.performance_route_inventory import inspect_js, inventory


def write(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_dynamic_templates_aliases_cycles_and_literal_post(tmp_path):
    write(
        tmp_path,
        "frontend/app/players/[id]/page.jsx",
        "import {useThing} from '@/hooks/a'; useThing();",
    )
    write(
        tmp_path,
        "frontend/hooks/a.js",
        "import './b'; export function useThing(){fetch('/api/tool?secret=PRIVATE_SENTINEL', {method:'POST', body: JSON.stringify({})});}",
    )
    write(tmp_path, "frontend/hooks/b.js", "import './a';")
    write(
        tmp_path,
        "frontend/app/api/tool/route.js",
        "export async function POST(){return fetch(target, options)}",
    )
    result = inventory(tmp_path)
    assert result["pageTemplates"] == result["bffTemplates"] == 1
    page = next(r for r in result["routes"] if r["kind"] == "PAGE")
    assert page["template"] == "/players/[id]"
    assert len(page["moduleClosure"]) == 3
    assert page["requests"][0]["method"] == "POST"
    assert page["requests"][0]["target"] == "/api/tool"
    assert "PRIVATE_SENTINEL" not in str(result)
    assert not page["runtimePathComplete"]


def test_dynamic_target_method_spread_and_comments_never_claim_complete():
    _, requests, _, dynamic = inspect_js("""
      // fetch('/api/not-real')
      import(modulePath); fetch(`/api/players/${id}`);
      fetch('/api/a', opts); fetch('/api/b', {...opts, method:'POST'});
      fetch('/api/c', {method:verb}); fetch('/api/d');
    """)
    assert dynamic
    assert len(requests) == 5
    assert requests[0]["target"] is None
    assert [r["method"] for r in requests] == ["GET", None, None, None, "GET"]
    assert all(r["operationClassification"] == "UNKNOWN" for r in requests)


def test_unresolved_imports_bounds_and_backend_decorators(tmp_path):
    write(tmp_path, "frontend/app/page.jsx", "import '@/missing'; import './nested'; fetch(url)")
    write(tmp_path, "frontend/app/nested.js", "fetch('/api/a')")
    write(
        tmp_path,
        "server.py",
        "from fastapi import FastAPI, APIRouter\napp=FastAPI()\nrouter=APIRouter()\n@app.post('/api/a')\ndef a(): pass\n@router.get(PATH)\ndef b(): pass\n",
    )
    result = inventory(tmp_path, max_depth=0)
    assert result["problems"][0]["reason"] == "GRAPH_LIMIT"
    assert any(
        i["status"] == "UNRESOLVED" for i in result["modules"]["frontend/app/page.jsx"]["imports"]
    )
    assert result["backendServerDecorators"][1]["path"] is None
    assert result["backendServerDecorators"][0]["prefixResolution"] == "UNKNOWN"
    assert not result["routes"][0]["runtimePathComplete"]


def test_unknown_alias_external_url_and_duplicate_method(tmp_path):
    write(
        tmp_path,
        "frontend/app/page.tsx",
        "import x from '~private'; fetch('https://private/?token=SECRET'); fetch('/api/a', {method:'GET',method:'POST'});",
    )
    result = inventory(tmp_path)
    assert "SECRET" not in str(result)
    assert result["routes"][0]["requests"][0]["target"] is None
    assert result["routes"][0]["requests"][1]["method"] is None
    assert result["modules"]["frontend/app/page.tsx"]["imports"][0]["status"] == "EXTERNAL_PACKAGE"


def test_ancestor_layouts_are_possible_not_proven_route_requests(tmp_path):
    write(tmp_path, "frontend/app/layout.jsx", "import Shell from '@/Shell';")
    write(tmp_path, "frontend/Shell.jsx", "fetch('/api/shared')")
    write(tmp_path, "frontend/app/v1.2/page.jsx", "export default function Page(){}")
    result = inventory(tmp_path)
    page = result["routes"][0]
    assert page["template"] == "/v1.2"
    assert page["ancestorLayouts"] == ["frontend/app/layout.jsx"]
    assert page["requests"][0]["target"] == "/api/shared"
    assert page["requests"][0]["runtimeReachability"] == "UNKNOWN"
    assert len(result["modules"]["frontend/Shell.jsx"]["sha256"]) == 64


def test_file_size_limit_is_visible_instead_of_silent_empty_map(tmp_path):
    write(tmp_path, "frontend/app/page.jsx", "fetch('/api/oversized');" * 5)
    result = inventory(tmp_path, max_bytes=10)
    assert result["pageTemplates"] == 1
    assert result["problems"] == [{"path": "frontend/app/page.jsx", "reason": "FILE_SIZE_LIMIT"}]
    assert result["routes"][0]["requests"] == []
    assert not result["routes"][0]["runtimePathComplete"]


def test_groups_slots_and_intercepting_routes(tmp_path):
    write(tmp_path, "frontend/app/(private)/@main/players/[id]/page.jsx", "")
    write(tmp_path, "frontend/app/(private)/@modal/(.)players/[id]/page.jsx", "")
    result = inventory(tmp_path)
    assert any(r["template"] == "/players/[id]" for r in result["routes"])
    assert any(
        r["template"] is None and r["templateStatus"] == "UNKNOWN_INTERCEPTION"
        for r in result["routes"]
    )


def test_backend_owner_privacy_and_fake_js_exports(tmp_path):
    write(
        tmp_path,
        "frontend/app/api/a/route.js",
        "// export function GET(){}\nconst x='export function POST(){}'; export async function PATCH(){}",
    )
    write(
        tmp_path,
        "server.py",
        "from fastapi import FastAPI as API\napp=API()\n@other.get('https://host/SECRET')\ndef bad(): pass\n@app.get('/api/a?token=SECRET')\ndef query(): pass\n@app.post('/api/a')\ndef good(): pass\n",
    )
    result = inventory(tmp_path)
    assert "SECRET" not in str(result)
    assert result["modules"]["frontend/app/api/a/route.js"]["bffExportMethods"] == ["PATCH"]
    assert len(result["backendServerDecorators"]) == 2
    assert result["backendServerDecorators"][0]["path"] is None
    assert result["backendServerDecorators"][1]["path"] == "/api/a"
