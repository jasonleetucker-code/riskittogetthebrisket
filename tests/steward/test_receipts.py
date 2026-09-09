from src.steward.receipts import NodeReceipt, graph_summary, owner_brief

def test_graph_summary_preserves_unknown_cost():
    summary = graph_summary([NodeReceipt("n", "DONE", 20, 10)])
    assert summary["total_node_latency_ms"] == 0
    assert summary["unknown_cost_nodes"] == 1

def test_owner_brief_is_compact_and_separates_owner_input():
    assert owner_brief(changed=["x"], owner_input=["approve"])["needs_owner_input"] == ["approve"]
