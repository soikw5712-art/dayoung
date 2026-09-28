from collectors.coupang import Product
from generators.copy import BlogPost, BlogSection, ChannelContent, InstagramPost, ThreadsPost


def sample_product() -> Product:
    return Product(product_id="7335597976", name="욕실 물때 클리너 500ml", price=8900, image_url=None,
                   original_url="https://www.coupang.com/vp/products/7335597976",
                   affiliate_url="https://link.coupang.com/a/abc123")


def sample_content(**overrides) -> ChannelContent:
    data = dict(
        threads=ThreadsPost(body="스친들 욕실 물때 뭘로 닦아?\n\n나 이거 쓰고 청소 시간 반으로 줄었어\n\n너네는 뭐 써?",
                            reply_link_text="써본 거 여기"),
        instagram=InstagramPost(caption="욕실 청소 5분 컷 꿀템\n자세한 건 프로필 링크에서", hashtags=["욕실청소", "살림템"]),
        blog=BlogPost(title="욕실 물때 클리너 한 달 사용 후기",
                      sections=[BlogSection(heading="구매 이유", text="물때가 심해서요."),
                                BlogSection(heading="사용법", text="뿌리고 5분 두면 끝.")],
                      tags=["욕실청소"]),
        card_texts=["욕실 물때 5분 컷?", "뿌리고 5분", "냄새는 좀 셈", "자취생·맞벌이 추천"],
        video_script=["물때 청소 아직도 박박 문질러?", "뿌리고 5분 두면 끝", "가격은 프로필 링크에서"],
    )
    data.update(overrides)
    return ChannelContent(**data)
