import random

import pytest

from core.config import DISCLOSURE, load_json
from generators.copy import (CopyGenerator, InstagramPost, ThreadsPost, apply_disclosure, build_system_prompt,
                             build_user_prompt, count_terms, lint_content, pick_style, save_content)
from tests.fixtures import sample_content, sample_product

LEX, TONE, STYLE = load_json("threads_lexicon.json"), load_json("tone.json"), load_json("threads_style.json")


def test_clean_content_passes_lint():
    assert lint_content(sample_content(), LEX, TONE) == []


def test_lint_catches_rule_violations():
    bad = sample_content(
        threads=ThreadsPost(body="스친 맞팔 스팔 스하리 부탁 https://x", reply_link_text=""),
        instagram=InstagramPost(caption="스친들 무조건 사", hashtags=[]),
    )
    problems = "\n".join(lint_content(bad, LEX, TONE))
    for expected in ["'스하리'", "용어 3회", "링크", "instagram: 스레드 용어 '스친'", "'무조건'"]:
        assert expected in problems


@pytest.mark.parametrize("style", list(STYLE["styles"]))
def test_system_prompt_includes_style_example(style):
    prompt = build_system_prompt(LEX, TONE, STYLE, style)
    assert "스하리" in prompt and TONE["persona"] in prompt
    assert STYLE["styles"][style]["example"] in prompt and f"스타일: {style}" in prompt


def test_pick_style():
    assert pick_style(STYLE, "정보추천") == "정보추천"
    assert pick_style(STYLE, "random", random.Random(1)) in STYLE["styles"]
    with pytest.raises(ValueError):
        pick_style(STYLE, "없는스타일")


def test_count_terms_prefers_longest():
    assert count_terms("스친이들 안녕, 스치니 최고, 스친들", list(LEX["use"])) == 3


def test_memo_controls_experience_claims():
    p = sample_product()
    assert "직접 써본 척하지 말고" in build_user_prompt(p)
    p.memo = "일주일 써봤는데 냄새가 셈"
    assert "<memo>" in build_user_prompt(p) and "냄새가 셈" in build_user_prompt(p)


def test_hashtag_in_threads_is_flagged():
    bad = sample_content(threads=ThreadsPost(body="이거 좋아 #살림템", reply_link_text="링크"))
    assert any("해시태그" in p for p in lint_content(bad, LEX, TONE))


def test_link_in_body_option():
    data = apply_disclosure(sample_content(), sample_product(), {"link_position": "body", "topic_tag": "상품추천"})
    assert data["threads"]["reply"] is None and data["threads"]["topic_tag"] == "상품추천"
    assert data["threads"]["body"].index("https://link.coupang.com/a/abc123") < data["threads"]["body"].index(DISCLOSURE)


def test_disclosure_on_every_channel():
    data = apply_disclosure(sample_content(), sample_product(), STYLE, "담백후기")
    assert data["threads"]["topic_tag"] == "상품추천" and data["threads"]["style"] == "담백후기"
    assert data["threads"]["body"].endswith(DISCLOSURE)
    assert data["threads"]["reply"].endswith("https://link.coupang.com/a/abc123")
    assert DISCLOSURE in data["instagram"]["caption"] and "#욕실청소" in data["instagram"]["caption"]
    assert data["blog"]["disclosure"] == DISCLOSURE
    assert len(data["threads"]["body"]) <= 500


class FakeResponse:
    def __init__(self, parsed):
        self.parsed_output, self.stop_reason = parsed, "end_turn"


class FakeMessages:
    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(self.outputs.pop(0))


class FakeClient:
    def __init__(self, outputs):
        self.messages = FakeMessages(outputs)


def test_generator_retries_once_with_feedback(tmp_path):
    bad = sample_content(instagram=InstagramPost(caption="스친들 이거 봐", hashtags=[]))
    client = FakeClient([bad, sample_content()])
    gen = CopyGenerator(client=client, model="claude-sonnet-5")
    content, problems = gen.generate(sample_product())
    assert problems == [] and len(client.messages.calls) == 2
    assert "스레드 용어" in client.messages.calls[1]["messages"][-1]["content"]
    photo = tmp_path / "IMG_1.JPG"
    photo.write_bytes(b"jpg")
    path = save_content(sample_product(), content, problems, gen.model, base=tmp_path,
                        style_cfg=STYLE, style=gen.style, photos=[str(photo)])
    assert path.name == "content.json" and path.parent.name.endswith("_7335597976")
    assert (path.parent / "photos" / "photo_01.jpg").exists()
