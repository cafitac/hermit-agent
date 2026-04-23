from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import Mock

from hermit_agent.mcp_actions import dispatch_channel_action


@dataclass
class _Action:
    kind: str
    question: str = ''
    options: tuple[str, ...] = ()
    message: str | None = None
    prompt_kind: str = ''
    tool: str = ''
    method: str = ''


def test_dispatch_channel_action_routes_each_supported_kind():
    notify_channel = Mock()
    notify_done = Mock()
    notify_error = Mock()
    notify_running = Mock()

    dispatch_channel_action(
        task_id='task-1',
        action=_Action(kind='prompt', question='Continue?', options=('Yes', 'No'), prompt_kind='waiting', tool='ask', method='item/tool/requestUserInput'),
        notify_channel=notify_channel,
        notify_done=notify_done,
        notify_error=notify_error,
        notify_running=notify_running,
    )
    dispatch_channel_action(
        task_id='task-1',
        action=_Action(kind='done', message='Finished'),
        notify_channel=notify_channel,
        notify_done=notify_done,
        notify_error=notify_error,
        notify_running=notify_running,
    )
    dispatch_channel_action(
        task_id='task-1',
        action=_Action(kind='error', message='Boom'),
        notify_channel=notify_channel,
        notify_done=notify_done,
        notify_error=notify_error,
        notify_running=notify_running,
    )
    dispatch_channel_action(
        task_id='task-1',
        action=_Action(kind='running'),
        notify_channel=notify_channel,
        notify_done=notify_done,
        notify_error=notify_error,
        notify_running=notify_running,
    )

    notify_channel.assert_called_once_with('task-1', 'Continue?', ['Yes', 'No'], prompt_kind='waiting', tool_name='ask', method='item/tool/requestUserInput')
    notify_done.assert_called_once_with('task-1', 'Finished')
    notify_error.assert_called_once_with('task-1', 'Boom')
    notify_running.assert_called_once_with('task-1')


def test_dispatch_channel_action_truncates_done_messages_to_200_chars():
    notify_done = Mock()
    long_message = 'x' * 250

    dispatch_channel_action(
        task_id='task-2',
        action=_Action(kind='done', message=long_message),
        notify_channel=Mock(),
        notify_done=notify_done,
        notify_error=Mock(),
        notify_running=Mock(),
    )

    notify_done.assert_called_once_with('task-2', 'x' * 200)
