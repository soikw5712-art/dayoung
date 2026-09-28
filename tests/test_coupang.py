import hashlib
import hmac

import pytest

from collectors.coupang import CoupangError, CoupangPartnersClient, extract_product_id, fetch_product, sign


@pytest.mark.parametrize("url,expected", [
    ("https://www.coupang.com/vp/products/7335597976?itemId=18&vendorItemId=85", "7335597976"),
    ("https://m.coupang.com/vm/products/123456?itemId=1", "123456"),
    ("https://www.coupang.com/np/search?q=abc", None),
])
def test_extract_product_id(url, expected):
    assert extract_product_id(url) == expected


def test_sign_matches_coupang_spec():
    header = sign("GET", "/v2/x", "a=1", "secret", "access", signed_date="260928T010203Z")
    expected = hmac.new(b"secret", b"260928T010203ZGET/v2/xa=1", hashlib.sha256).hexdigest()
    assert header == f"CEA algorithm=HmacSHA256, access-key=access, signed-date=260928T010203Z, signature={expected}"


class FakeClient(CoupangPartnersClient):
    def __init__(self, results):
        self.results, self.sub_id = results, None

    def search(self, keyword, limit=10):
        return self.results

    def deeplink(self, url):
        return "https://link.coupang.com/a/xyz"


def test_fetch_product_matches_search_result_by_id():
    client = FakeClient([
        {"productId": 1, "productName": "다른 상품", "productPrice": 1000},
        {"productId": 7335597976, "productName": "물때 클리너", "productPrice": 8900,
         "productImage": "https://img/1.jpg", "isRocket": True, "categoryName": "생활용품"},
    ])
    p = fetch_product("https://www.coupang.com/vp/products/7335597976", keyword="물때", client=client)
    assert (p.name, p.price, p.is_rocket, p.affiliate_url) == ("물때 클리너", 8900, True, "https://link.coupang.com/a/xyz")


def test_fetch_product_manual_fallback_and_missing_info():
    client = FakeClient([])
    p = fetch_product("https://www.coupang.com/vp/products/5", manual={"name": "수동 입력", "price": 100}, client=client)
    assert p.name == "수동 입력"
    with pytest.raises(CoupangError):
        fetch_product("https://www.coupang.com/vp/products/5", client=client)
