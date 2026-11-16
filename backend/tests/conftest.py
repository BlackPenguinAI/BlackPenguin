"""Offline model seam for the newly shared decision stage.

Older regression providers contain interpretation/composition packets only. Their
business assertions now run through LangGraph with a deterministic decision LLM.
Dedicated observation suites retain their actual HTTP mocks and rejection cases.
No production module has a test-specific path or model fallback.
"""
import json
from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def offline_graph_decision(request,monkeypatch):
    own={'test_sales_observation_loop.py','test_sales_observation_repair.py',
         'test_sales_observation_repair2.py','test_sales_unified_graph.py','test_sales_graph_repair1.py','test_sales_graph_repair2.py','test_sales_graph_repair3.py'}
    if Path(str(request.fspath)).name in own:return
    from app.modules.sales_agent import observation_loop
    original=observation_loop.run
    async def decision(messages,schema):
        data=json.loads(messages[1]['content'])
        keys=list(data['available_tools'])[:4]
        return json.dumps({'action':'read' if keys else 'respond','tool_ids':keys})
    async def run(*args,**kwargs):
        kwargs.setdefault('infer',decision)
        return await original(*args,**kwargs)
    monkeypatch.setattr(observation_loop,'run',run)
