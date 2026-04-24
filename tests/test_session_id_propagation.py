import inspect


def test_task_request_accepts_parent_session_id():
    from hermit_agent.gateway.routes.tasks import TaskRequest
    fields = TaskRequest.model_fields
    assert 'parent_session_id' in fields, 'TaskRequest must declare parent_session_id'
    field = fields['parent_session_id']
    assert field.is_required() is False, 'parent_session_id must be optional'


def test_task_request_omitting_parent_session_id_works():
    from hermit_agent.gateway.routes.tasks import TaskRequest
    req = TaskRequest(task='hello', cwd='/tmp', model='glm-5.1')
    assert req.parent_session_id is None


def test_task_request_with_parent_session_id():
    from hermit_agent.gateway.routes.tasks import TaskRequest
    req = TaskRequest(task='hello', cwd='/tmp', model='glm-5.1', parent_session_id='abc123def456')
    assert req.parent_session_id == 'abc123def456'


def test_gateway_client_create_task_accepts_parent_session_id():
    from hermit_agent.bridge_client import GatewayClient
    sig = inspect.signature(GatewayClient.create_task)
    assert 'parent_session_id' in sig.parameters, 'GatewayClient.create_task must accept parent_session_id'


def test_agent_loop_accepts_session_id_parameter():
    from hermit_agent.loop import AgentLoop
    sig = inspect.signature(AgentLoop.__init__)
    assert 'session_id' in sig.parameters, 'AgentLoop.__init__ must accept optional session_id'


def test_agent_loop_uses_supplied_session_id(monkeypatch):
    from hermit_agent.loop import AgentLoop
    from hermit_agent.permissions import PermissionMode
    from unittest.mock import MagicMock
    llm = MagicMock()
    llm.model = 'm'
    loop = AgentLoop(llm=llm, tools=[], cwd='/tmp', permission_mode=PermissionMode.ALLOW_READ, session_id='mysid12345ab')
    assert loop.session_id == 'mysid12345ab'


def test_agent_loop_generates_session_id_when_not_supplied():
    from hermit_agent.loop import AgentLoop
    from hermit_agent.permissions import PermissionMode
    from unittest.mock import MagicMock
    llm = MagicMock()
    llm.model = 'm'
    loop = AgentLoop(llm=llm, tools=[], cwd='/tmp', permission_mode=PermissionMode.ALLOW_READ)
    assert isinstance(loop.session_id, str)
    assert len(loop.session_id) == 12
