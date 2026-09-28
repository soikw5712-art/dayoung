"""쿠팡 파트너스 Open API: 상품 ID 추출, 딥링크 변환, 상품 정보 조회.

※ 쿠팡 페이지를 직접 크롤링하지 않는다 (차단·약관 위반). 모든 정보는 파트너스 API로만 가져온다.
※ 파트너스 API에는 "상품 ID로 상세 조회" 엔드포인트가 없어서, 검색 API 결과에서 같은
  상품 ID를 찾는 방식으로 정보를 채운다. 못 찾으면 수동 입력값(--name 등)을 사용한다.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from dataclasses import asdict, dataclass, field
from urllib.parse import parse_qs, quote, urlparse

import requests

from core.config import env

DOMAIN = "https://api-gateway.coupang.com"
API_BASE = "/v2/providers/affiliate_open_api/apis/openapi/v1"

_PRODUCT_PATH = re.compile(r"/(?:vp|vm)/products/(\d+)")


class CoupangError(RuntimeError):
    pass


@dataclass
class Product:
    product_id: str
    name: str
    price: int | None
    image_url: str | None
    original_url: str
    affiliate_url: str
    discount_rate: int | None = None
    is_rocket: bool | None = None
    category: str | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def extract_product_id(url: str) -> str | None:
    """쿠팡 상품 URL에서 상품 ID 추출. 단축링크(link.coupang.com)는 None."""
    parsed = urlparse(url.strip())
    match = _PRODUCT_PATH.search(parsed.path)
    if match:
        return match.group(1)
    qs = parse_qs(parsed.query)
    for key in ("productId", "pageKey"):
        if qs.get(key) and qs[key][0].isdigit():
            return qs[key][0]
    return None


def resolve_short_link(url: str, timeout: float = 10) -> str:
    """link.coupang.com 단축링크의 리다이렉트 목적지만 확인 (페이지 본문은 읽지 않음)."""
    resp = requests.head(url, allow_redirects=True, timeout=timeout)
    return resp.url


def sign(method: str, path: str, query: str, secret_key: str, access_key: str,
         signed_date: str | None = None) -> str:
    """쿠팡 파트너스 HMAC-SHA256 Authorization 헤더 생성."""
    signed_date = signed_date or time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
    message = signed_date + method + path + query
    signature = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()
    return (f"CEA algorithm=HmacSHA256, access-key={access_key}, "
            f"signed-date={signed_date}, signature={signature}")


class CoupangPartnersClient:
    def __init__(self, access_key: str | None = None, secret_key: str | None = None,
                 sub_id: str | None = None, session: requests.Session | None = None):
        self.access_key = access_key or env("COUPANG_ACCESS_KEY", required=True)
        self.secret_key = secret_key or env("COUPANG_SECRET_KEY", required=True)
        self.sub_id = sub_id if sub_id is not None else env("COUPANG_SUB_ID")
        self.session = session or requests.Session()

    def _request(self, method: str, path: str, query: str = "", body: dict | None = None) -> dict:
        auth = sign(method, path, query, self.secret_key, self.access_key)
        url = DOMAIN + path + (f"?{query}" if query else "")
        resp = self.session.request(
            method, url,
            headers={"Authorization": auth, "Content-Type": "application/json;charset=UTF-8"},
            data=json.dumps(body) if body is not None else None,
            timeout=15,
        )
        try:
            data = resp.json()
        except ValueError:
            raise CoupangError(f"쿠팡 API 응답 오류 ({resp.status_code}): {resp.text[:200]}")
        if resp.status_code != 200 or str(data.get("rCode", "0")) != "0":
            raise CoupangError(f"쿠팡 API 오류 ({resp.status_code}): {data}")
        return data

    def deeplink(self, url: str) -> str:
        """일반 쿠팡 URL → 내 파트너스 추적 링크(단축 URL)."""
        body = {"coupangUrls": [url]}
        if self.sub_id:
            body["subId"] = self.sub_id
        data = self._request("POST", f"{API_BASE}/deeplink", body=body)
        items = data.get("data") or []
        if not items or not items[0].get("shortenUrl"):
            raise CoupangError(f"딥링크 변환 실패: {data}")
        return items[0]["shortenUrl"]

    def search(self, keyword: str, limit: int = 10) -> list[dict]:
        query = f"keyword={quote(keyword)}&limit={limit}"
        if self.sub_id:
            query += f"&subId={quote(self.sub_id)}"
        data = self._request("GET", f"{API_BASE}/products/search", query=query)
        return (data.get("data") or {}).get("productData") or []


def fetch_product(url: str, keyword: str | None = None, manual: dict | None = None,
                  client: CoupangPartnersClient | None = None) -> Product:
    """상품 링크 → Product. keyword가 있으면 검색 API로 상세 정보를 채운다.

    manual: {"name", "price", "image_url", "discount_rate", "is_rocket", "category"}
            검색으로 못 찾을 때 쓰거나, 검색 결과를 덮어쓸 값.
    """
    client = client or CoupangPartnersClient()
    manual = {k: v for k, v in (manual or {}).items() if v is not None}

    original_url = url
    product_id = extract_product_id(url)
    if product_id is None and "link.coupang.com" in url:
        original_url = resolve_short_link(url)
        product_id = extract_product_id(original_url)
    if product_id is None:
        raise CoupangError(f"상품 ID를 찾을 수 없는 링크입니다: {url}")

    info: dict = {}
    if keyword:
        for item in client.search(keyword):
            if str(item.get("productId")) == product_id:
                info = {
                    "name": item.get("productName"),
                    "price": item.get("productPrice"),
                    "image_url": item.get("productImage"),
                    "is_rocket": item.get("isRocket"),
                    "category": item.get("categoryName"),
                }
                break
    info.update(manual)
    if not info.get("name"):
        raise CoupangError(
            "상품 정보를 찾지 못했습니다. --keyword 로 검색어를 주거나 --name/--price/--image 로 직접 입력하세요."
        )

    return Product(
        product_id=product_id,
        name=info["name"],
        price=int(info["price"]) if info.get("price") is not None else None,
        image_url=info.get("image_url"),
        original_url=original_url,
        affiliate_url=client.deeplink(original_url),
        discount_rate=info.get("discount_rate"),
        is_rocket=info.get("is_rocket"),
        category=info.get("category"),
    )
