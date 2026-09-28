# 쿠팡 파트너스 SNS 자동화

쿠팡 상품 링크 1개 → 채널별 원고(스레드·인스타·블로그) + 카드뉴스 + 숏폼 영상 생성 → 검수 후 **정해진 시간에 예약 게시**.

## 구현 현황

| 기획서 단계 | 상태 | 파일 |
|---|---|---|
| ① 상품 정보 + 딥링크 (파트너스 API) | ✅ | `collectors/coupang.py` |
| ② 채널별 원고 생성 (Claude) + 용어 사전·말투 | ✅ 규칙 위반 시 1회 자동 재생성 | `generators/copy.py`, `config/*.json` |
| ③ 카드뉴스 1080×1350 | ✅ | `generators/image.py` |
| ④ 숏폼 1080×1920 MP4 | ✅ 무음 + 자막 (TTS는 연동 지점만) | `generators/video.py` |
| ⑤ 검수 | ✅ CLI (`show`, `approve`) · 웹 화면은 다음 단계 | `main.py` |
| ⑥ 게시 대기열·슬롯 자동 배정 | ✅ 하루 한도·같은 상품 간격·랜덤 지연 | `scheduler.py` |
| ⑦ 스레드 자동 게시 | ✅ 본문 + 첫 답글에 링크 | `publishers/threads.py` |
| ⑦ 블로그 반자동 | ✅ 원고 패키지 + 알림 | `publishers/blog_package.py` |
| ⑦ 인스타그램 | ⏳ 함수 틀만 (7주차) | `publishers/instagram.py` |
| 안전장치 | ✅ 재시도 3회, 실패·한도 초과 알림, 긴급 정지, 토큰 자동 갱신 | `scheduler.py`, `notifier.py` |
| ⑧ 기록·분석 대시보드 | ⏳ 게시 기록만 DB에 저장 | `core/db.py` |

## 설치

```bash
pip install -r requirements.txt
playwright install chromium        # 카드뉴스·영상 렌더링용
cp .env.example .env               # 키 입력
```

`.env`에 넣을 것:
- `ANTHROPIC_API_KEY`: Claude API 키
- `COUPANG_ACCESS_KEY`, `COUPANG_SECRET_KEY`: 쿠팡 파트너스 Open API 키 (파트너스 승인 필요)
- `THREADS_USER_ID`, `THREADS_ACCESS_TOKEN`: Meta 개발자 앱에서 발급한 Threads 장기 토큰
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`: 알림용 (없으면 콘솔 출력)
- `TOKEN_ENCRYPTION_KEY`: 갱신된 토큰을 DB에 암호화 저장하는 키

## 사용법

```bash
# 1) 생성: 링크 + 검색어(상품명 일부) → 원고·카드뉴스 (+ --video 로 영상)
python main.py generate "https://www.coupang.com/vp/products/7335597976" --keyword "욕실 물때 클리너" --video

# 검색으로 못 찾으면 직접 입력
python main.py generate "<링크>" --name "상품명" --price 8900 --image "https://...jpg"

# 2) 검수
python main.py show output/20260928_7335597976/content.json

# 3) 승인 → 채널별 다음 빈 슬롯에 자동 배정 (또는 --at "2026-10-01 21:00")
python main.py approve output/20260928_7335597976/content.json --channels threads,blog

# 4) 스케줄러 실행 (24시간 켜 두는 서버에서)
python main.py run

# 관리
python main.py list                 # 대기열
python main.py stop / resume        # 긴급 정지 / 해제
python main.py retry 12             # 실패한 게시물 재배정
python main.py mark-posted 13 --url https://blog.naver.com/...   # 블로그 직접 발행 후
```

> 파트너스 API에는 "상품 ID로 상세 조회"가 없어서, **검색 API 결과에서 같은 상품 ID를 찾는 방식**으로 상품명·가격·이미지를 채웁니다. `--keyword`에 상품명 일부를 넣어 주세요. 쿠팡 페이지를 직접 크롤링하지 않습니다.

## 게시 흐름

```
approved → scheduled → posting → posted
                              ├→ package_ready (블로그: 원고 패키지 생성 → 직접 예약발행 → mark-posted)
                              ├→ failed (3회 재시도 후, 텔레그램 알림)
                              └→ held (하루 한도 초과)
```

- 스레드: 본문(끝에 파트너스 고지 문구) 게시 → 첫 답글에 추적 링크
- 블로그: `output/blog/{날짜}/{id}_{상품ID}/`에 `제목.txt`·`본문.txt`(고지 문구 상단)·`태그.txt`·`이미지/` 생성
- 슬롯·한도·간격은 `config/schedule.json`, 말투는 `config/tone.json`, 스레드 용어는 `config/threads_lexicon.json` (한 달에 한 번 갱신 권장)

## 테스트

```bash
python -m pytest -q
```

## 다음 단계 (기획서 로드맵 기준)

- 웹 검수 화면 (미리보기·문구 수정·재생성·채널 체크)
- TTS 연동 (`generators/video.py`의 `synthesize_speech`)
- 인스타그램 캐러셀·릴스 게시 (카드뉴스를 R2/S3에 올려 공개 URL 필요)
- 조회·반응·파트너스 수익 기록 대시보드
