"""Claude API로 채널별 홍보 원고 생성 (스레드 / 인스타 / 블로그 / 카드뉴스 / 영상 대본)."""
from __future__ import annotations

import json
import random
import re
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
from pydantic import BaseModel, Field

from collectors.coupang import Product
from core.config import DISCLOSURE, env, load_json, output_dir

THREADS_MAX_CHARS = 500  # Threads API 게시물 글자 수 제한


class ThreadsPost(BaseModel):
    body: str = Field(description="스레드 본문. 링크·고지문구·해시태그 제외, 400자 이내")
    reply_link_text: str = Field(description="링크와 함께 첫 답글로 달 짧은 문구 (링크 제외)")


class InstagramPost(BaseModel):
    caption: str = Field(description="캡션. 링크 넣지 말고 '프로필 링크' 안내")
    hashtags: list[str] = Field(description="해시태그 5~10개, # 없이")


class BlogSection(BaseModel):
    heading: str
    text: str


class BlogPost(BaseModel):
    title: str
    sections: list[BlogSection]
    tags: list[str]


class ChannelContent(BaseModel):
    threads: ThreadsPost
    instagram: InstagramPost
    blog: BlogPost
    card_texts: list[str] = Field(description="카드뉴스 3~5장 문구. 1장=표지 후킹, 마지막=추천 대상/마무리")
    video_script: list[str] = Field(description="숏폼 장면별 자막 3~5개. 1번=3초 후킹")


def build_system_prompt(lexicon: dict, tone: dict, style_cfg: dict, style: str) -> str:
    use_terms = "\n".join(f"- {k}: {v}" for k, v in lexicon.get("use", {}).items())
    caution_terms = "\n".join(f"- {k}: {v}" for k, v in lexicon.get("caution", {}).items())
    format_rules = "\n".join(f"- {r}" for r in lexicon.get("format_rules", []))
    common_rules = "\n".join(f"- {r}" for r in style_cfg.get("common_rules", []))
    chosen = style_cfg["styles"][style]
    banned = ", ".join(tone.get("banned", []))
    max_chars = style_cfg.get("max_body_chars", 400)
    link_rule = ("본문에 링크를 넣지 마. 링크는 코드가 본문 끝(고지 문구 앞)에 붙인다."
                 if style_cfg.get("link_position") == "body"
                 else "본문에 링크를 넣지 마. 링크는 코드가 첫 답글에 붙인다.")
    return f"""너는 쿠팡 파트너스 상품을 SNS에 소개하는 개인 계정 운영자야.
하나의 상품으로 스레드·인스타그램·네이버 블로그 원고와 카드뉴스·숏폼 문구를 만든다.

# 페르소나
- {tone.get('persona')}
- 광고 티를 줄이고 일상 글처럼. 단점이나 아쉬운 점도 하나는 솔직하게 (스타일상 어색하면 생략 가능).
- 직접 써본 경험은 사용자가 준 memo에 있는 내용만 체험담으로 쓴다. memo가 없으면 체험을 지어내지 말고
  "요즘 많이 쓰던데", "찾아보니", "이런 사람한테 좋을 듯" 같은 추천·정보 시점으로 쓴다.

# 스레드 스타일: {style}
{chosen['description']}

실제 인기 글 예시 (말투·리듬·구성만 참고, 문장 베끼기 금지):
<example>
{chosen['example']}
</example>

# 스레드 공통 규칙
{common_rules}
{format_rules}
- 본문은 {max_chars}자 이내 (고지 문구가 뒤에 붙고, 스레드는 500자 제한)
- {link_rule}

# 스레드 전용 용어 (threads 원고에만, {tone.get('slang_level')}, 어색하면 쓰지 않는 게 우선)
{use_terms}

# 절대 쓰면 안 되는 용어 (모든 채널)
{caution_terms}

# 인스타그램
- 스레드 용어 쓰지 말 것. 이모지 {tone.get('emoji_level')}. 캡션 안 링크는 클릭이 안 되니 "프로필 링크" 안내.

# 네이버 블로그
- 스레드 용어 쓰지 말 것. 존댓말 리뷰형, 소제목 4~6개, 전체 1,500자 이상.
- 제목은 검색에 잡히게 상품 종류 키워드 포함.

# 공통 원칙
- 과장·허위 효능 금지. 건강기능식품·화장품은 효능·효과 단정 표현 금지 (예: "뾰루지가 안 난다", "살이 빠진다" 같은 단정 X, "나는 괜찮았어" 같은 개인 느낌은 memo에 있을 때만).
- 가격을 언급하면 반드시 "게시 시점 기준"이라고 붙여.
- 모르는 스펙은 지어내지 말 것. 상품명·가격·memo 등 주어진 정보만 사실로 사용.
- 금지 표현: {banned}
- 쿠팡 파트너스 고지 문구는 코드가 자동으로 붙이니 넣지 마."""


def pick_style(style_cfg: dict, style: str | None = None, rng: random.Random | None = None) -> str:
    styles = list(style_cfg["styles"])
    style = style or style_cfg.get("default_style", "random")
    if style == "random":
        return (rng or random).choice(styles)
    if style not in styles:
        raise ValueError(f"알 수 없는 스타일: {style} (가능: {', '.join(styles)}, random)")
    return style


def build_user_prompt(product: Product) -> str:
    facts = {
        "상품명": product.name,
        "가격(원)": product.price,
        "할인율(%)": product.discount_rate,
        "로켓배송": product.is_rocket,
        "카테고리": product.category,
    }
    facts = {k: v for k, v in facts.items() if v is not None}
    prompt = "아래 상품으로 원고를 만들어줘.\n\n" + json.dumps(facts, ensure_ascii=False, indent=2)
    if product.memo:
        prompt += f"\n\n<memo>\n{product.memo}\n</memo>\n(내가 직접 써본 느낌이야. 체험담은 이 안에서만)"
    else:
        prompt += "\n\n(memo 없음: 직접 써본 척하지 말고 추천·정보 시점으로)"
    return prompt


def count_terms(text: str, terms: list[str]) -> int:
    """용어 사용 횟수 (긴 용어 우선 매칭: '스친이'를 '스친'으로 중복 세지 않음)."""
    if not terms:
        return 0
    pattern = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return len(re.findall(pattern, text))


def lint_content(content: ChannelContent, lexicon: dict, tone: dict, max_chars: int = 400) -> list[str]:
    """용어·금지어 규칙 위반을 찾아 문제 목록을 반환 (빈 리스트면 통과)."""
    problems: list[str] = []
    use_terms = list(lexicon.get("use", {}))
    caution_terms = [t for t in lexicon.get("caution", {}) if "-" not in t]  # "쓰-로 시작하는 표현" 같은 설명형 제외
    banned = tone.get("banned", [])

    texts = {
        "threads": content.threads.body + "\n" + content.threads.reply_link_text,
        "instagram": content.instagram.caption + " " + " ".join(content.instagram.hashtags),
        "blog": content.blog.title + "\n" + "\n".join(s.heading + "\n" + s.text for s in content.blog.sections),
        "card_texts": "\n".join(content.card_texts),
        "video_script": "\n".join(content.video_script),
    }
    for channel, text in texts.items():
        for term in caution_terms + banned:
            if term in text:
                problems.append(f"{channel}: 금지 표현 '{term}' 사용")
        if channel in ("instagram", "blog"):
            for term in use_terms:
                if term in text:
                    problems.append(f"{channel}: 스레드 용어 '{term}'는 스레드에만 사용")

    slang_count = count_terms(content.threads.body, use_terms)
    if slang_count > 2:
        problems.append(f"threads: 스레드 용어 {slang_count}회 사용 (게시물당 1~2개)")
    if "http" in content.threads.body:
        problems.append("threads: 본문에 링크를 넣지 말 것")
    if re.search(r"#\S", content.threads.body):
        problems.append("threads: 해시태그 쓰지 말 것 (토픽 태그로 대체)")
    limit = min(max_chars, THREADS_MAX_CHARS - len(DISCLOSURE) - 60)  # 고지 + (본문 링크일 때) 링크 여유
    if len(content.threads.body) > limit:
        problems.append(f"threads: 본문이 너무 김 ({len(content.threads.body)}자, {limit}자 이내)")
    if not 3 <= len(content.card_texts) <= 5:
        problems.append(f"card_texts: {len(content.card_texts)}장 (3~5장이어야 함)")
    return problems


def apply_disclosure(content: ChannelContent, product: Product, style_cfg: dict | None = None,
                     style: str | None = None) -> dict:
    """모든 채널 원고에 고지 문구와 추적 링크를 붙인 최종 dict."""
    style_cfg = style_cfg or {}
    data = content.model_dump()
    body = content.threads.body.rstrip()
    link_line = f"{content.threads.reply_link_text.strip()}\n{product.affiliate_url}"
    if style_cfg.get("link_position") == "body":
        data["threads"]["body"] = f"{body}\n\n{link_line}\n\n{DISCLOSURE}"
        data["threads"]["reply"] = None
    else:
        data["threads"]["body"] = f"{body}\n\n{DISCLOSURE}"
        data["threads"]["reply"] = link_line
    data["threads"]["topic_tag"] = style_cfg.get("topic_tag")
    data["threads"]["style"] = style
    data["instagram"]["caption"] = (
        f"{content.instagram.caption.rstrip()}\n\n"
        + " ".join(f"#{h.lstrip('#')}" for h in content.instagram.hashtags)
        + f"\n\n{DISCLOSURE}"
    )
    data["blog"]["disclosure"] = DISCLOSURE  # 블로그는 본문 상단에 배치
    data["blog"]["link"] = product.affiliate_url
    return data


class CopyGenerator:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str | None = None):
        self.client = client or anthropic.Anthropic()
        self.model = model or env("CLAUDE_MODEL", "claude-sonnet-5")
        self.lexicon = load_json("threads_lexicon.json")
        self.tone = load_json("tone.json")
        self.style_cfg = load_json("threads_style.json")
        self.style: str | None = None

    def _call(self, messages: list[dict]) -> ChannelContent:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=build_system_prompt(self.lexicon, self.tone, self.style_cfg, self.style),
            messages=messages,
            output_format=ChannelContent,
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("Claude가 이 상품의 원고 생성을 거절했습니다.")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise RuntimeError(f"원고 생성이 완료되지 않았습니다 (stop_reason={response.stop_reason}).")
        return response.parsed_output

    def generate(self, product: Product, style: str | None = None) -> tuple[ChannelContent, list[str]]:
        """원고 생성. 규칙 위반이 있으면 피드백을 주고 한 번 다시 생성한다."""
        self.style = pick_style(self.style_cfg, style)
        max_chars = self.style_cfg.get("max_body_chars", 400)
        messages = [{"role": "user", "content": build_user_prompt(product)}]
        content = self._call(messages)
        problems = lint_content(content, self.lexicon, self.tone, max_chars)
        if problems:
            messages += [
                {"role": "assistant", "content": content.model_dump_json()},
                {"role": "user", "content": "다음 문제를 고쳐서 전체를 다시 만들어줘:\n- " + "\n- ".join(problems)},
            ]
            content = self._call(messages)
            problems = lint_content(content, self.lexicon, self.tone, max_chars)
        return content, problems


def save_content(product: Product, content: ChannelContent, problems: list[str],
                 model: str, base: Path | None = None, style_cfg: dict | None = None,
                 style: str | None = None, photos: list[str] | None = None) -> Path:
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    folder = (base or output_dir()) / f"{today}_{product.product_id}"
    folder.mkdir(parents=True, exist_ok=True)
    data = apply_disclosure(content, product, style_cfg, style)

    # 스레드에 같이 올릴 실제 사진 (내가 찍은 사진 권장, 최대 10장)
    saved = []
    for i, src in enumerate((photos or [])[:10], start=1):
        src_path = Path(src).expanduser()
        if not src_path.exists():
            raise FileNotFoundError(f"사진 파일이 없습니다: {src}")
        dest = folder / "photos" / f"photo_{i:02d}{src_path.suffix.lower()}"
        dest.parent.mkdir(exist_ok=True)
        shutil.copy(src_path, dest)
        saved.append(str(dest.relative_to(folder)))
    data["threads"]["photos"] = saved
    data["product"] = product.to_dict()
    data["meta"] = {
        "generated_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
        "model": model,
        "lint_warnings": problems,
        "price_note": "가격은 게시 시점 기준",
    }
    path = folder / "content.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
