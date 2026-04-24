import inspect


def test_loop_does_not_call_nonexistent_extract_and_save():
    import hermit_agent.loop as loop_mod
    src = inspect.getsource(loop_mod)
    assert 'kb.extract_and_save' not in src, \
        'loop.py still references the non-existent KBLearner.extract_and_save'


def test_kb_learner_has_required_methods():
    from hermit_agent.kb_learner import KBLearner
    assert hasattr(KBLearner, 'extract_from_conversation')
    assert hasattr(KBLearner, 'save_pending')


def test_loop_uses_correct_kb_methods():
    import hermit_agent.loop as loop_mod
    src = inspect.getsource(loop_mod)
    # After the fix, the KB auto-extract block should call both real methods.
    assert 'kb.extract_from_conversation' in src
    assert 'kb.save_pending' in src
