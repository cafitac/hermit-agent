from __future__ import annotations


def test_present_interaction_formats_permission_request_in_korean():
    from hermit_agent.interaction_presenter import present_interaction

    presented = present_interaction(
        question="[Permission request] bash\npwd\n\nAllow?",
        options=("Yes (once)", "Always allow (yolo)", "No"),
        prompt_kind="permission_ask",
    )

    assert presented.title == "Hermit 권한 요청"
    assert "명령: pwd" in presented.body
    assert "현재 작업 디렉터리를 확인하는 명령이야." in presented.body
    assert "선택지: Yes (once) / Always allow (yolo) / No" == presented.options_line
    assert presented.compact_summary == "<- [hermit-channel]\n권한 요청: pwd\n선택지: Yes (once) / Always allow (yolo) / No"


def test_canonicalize_reply_maps_korean_permission_answers():
    from hermit_agent.interaction_presenter import canonicalize_reply

    options = ("Yes (once)", "Always allow (yolo)", "No")
    assert canonicalize_reply(reply="이번만", options=options, prompt_kind="permission_ask") == "Yes (once)"
    assert canonicalize_reply(reply="계속 허용", options=options, prompt_kind="permission_ask") == "Always allow (yolo)"
    assert canonicalize_reply(reply="거절", options=options, prompt_kind="permission_ask") == "No"


def test_present_interaction_localizes_common_waiting_question_to_korean():
    from hermit_agent.interaction_presenter import present_interaction

    presented = present_interaction(
        question="Which environment should we use?",
        options=(),
        prompt_kind="waiting",
    )

    assert presented.title == "Hermit 입력 요청"
    assert presented.body == "어느 환경으로 진행할까요?"
    assert presented.options_line == "선택지: 자유 입력"
