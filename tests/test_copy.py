from core.config import DISCLOSURE, load_json
from generators.copy import (BlogPost, BlogSection, CopyGenerator, InstagramPost, ThreadsPost,
                             apply_disclosure, build_system_prompt, lint_content, save_content)
from tests.fixtures import sample_content, sample_product

LEX, TONE = load_json("threads_lexicon.json"), load_json("tone.json")


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


def test_system_prompt_includes_lexicon_and_tone():
    prompt = build_system_prompt(LEX, TONE)
    assert "스친" in prompt and "스하리" in prompt and TONE["persona"] in prompt


def test_disclosure_on_every_channel():
    data = apply_disclosure(sample_content(), sample_product())
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
    path = save_content(sample_product(), content, problems, gen.model, base=tmp_path)
    assert path.name == "content.json" and path.parent.name.endswith("_7335597976")
