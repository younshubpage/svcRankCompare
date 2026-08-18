# 구독 서비스 도서 베스트셀러 비교

교보문고 SAM(무제한/프리미엄) · 밀리의서재 · 예스24 크레마클럽, 4개 구독 서비스의
일간 베스트 순위를 매일 아침 자동으로 긁어와서 비교하고, 밀리의서재 공개예정 도서
목록도 함께 보여주는 페이지입니다.

## 화면 구성 (탭 2개)

1. **서점별 보기** — 4개 서비스의 일간 베스트 순위를 나란히 비교합니다. 전날 대비
   순위 변동(급등/상승/하락/신규), 도서 클릭 시 최근 순위 히스토리 차트, 엑셀 다운로드,
   과거 날짜 조회 기능을 제공합니다.
2. **밀리의서재 공개예정** — 밀리의서재에서 곧 공개될 도서를 목록으로 보여줍니다
   (밀리의서재 `공개예정` 페이지의 디자인 톤을 반영).

## 폴더 구성

```
svcRankCompare/
├── index.html                          ← 화면 (이 파일이 웹사이트로 보임)
├── crawler/
│   ├── crawl.py                        ← 매일 데이터를 긁어오는 스크립트
│   └── requirements.txt
└── .github/
    └── workflows/
        └── crawl.yml                   ← "매일 아침 자동 실행해라" 설정
```

`data.json` / `history.json` / `upcoming.json` 은 크롤러가 처음 실행되면 자동으로
생성됩니다 (지금은 없어도 됩니다 — 화면은 그동안 샘플 데이터로 보여줍니다).

## 데이터 출처

| 서비스 | 수집 방식 |
|---|---|
| 교보문고 SAM 무제한 / 프리미엄 | `sam.kyobobook.co.kr` 페이지를 브라우저(Playwright)로 렌더링해서 수집 |
| 밀리의서재 (일간 랭킹) | `apis.millie.co.kr` 공개 API (`/public/rank/millie/`) |
| 예스24 크레마클럽 | `cremaclub.yes24.com` 공개 목록 엔드포인트 (`/Bookclub/GetBookclubSumGoodsList`) |
| 밀리의서재 공개예정 도서 | `apis.millie.co.kr` 공개 API (`/public/curation/coming-soon/books/`) |

사이트 구조나 API가 바뀌면 `crawler/crawl.py`의 해당 함수만 고치면 됩니다.

## 설정 순서 (한 번만 하면 됨)

### 1. GitHub Pages 켜기 (웹사이트 주소 발급)

1. 저장소 페이지에서 **Settings → Pages**
2. **Source**를 `Deploy from a branch`로 선택
3. Branch를 원하는 브랜치 / `/(root)`로 선택 → **Save**
4. 몇 분 기다리면 상단에 주소가 뜸 (예: `https://내아이디.github.io/svcRankCompare/`)

### 2. 자동 실행이 파일을 저장할 수 있게 권한 켜기

크롤러가 매일 결과를 저장소에 커밋(저장)해야 하는데, 기본적으로는 권한이 막혀있어서
켜줘야 합니다.

1. 저장소 페이지에서 **Settings → Actions → General**
2. 맨 아래 **Workflow permissions** 항목에서
   **"Read and write permissions"** 선택 → **Save**

### 3. 한 번 수동으로 실행해서 테스트

1. 저장소 페이지에서 **Actions** 탭 클릭
2. 왼쪽에 **Daily Bestseller Crawl** 클릭
3. 오른쪽 **Run workflow** 버튼 클릭 → 다시 **Run workflow**
4. 1~3분 정도 기다리면 실행 완료 (초록 체크 표시)
5. 저장소에 `data.json`, `history.json`, `upcoming.json` 파일이 새로 생겼는지 확인
6. 아까 그 웹사이트 주소로 들어가서 실제 순위/공개예정 목록이 뜨는지 확인
   (SAMPLE 표시가 사라지고 진짜 책 제목들이 보이면 성공)

이후로는 **매일 한국시간 오전 7시**에 자동으로 실행됩니다.
(더 이르게/늦게 하고 싶으면 `.github/workflows/crawl.yml` 파일의
`cron: '0 22 * * *'` 부분의 숫자를 바꾸면 됩니다 — UTC 기준 시간이라 한국시간보다
9시간 느립니다)

## 로컬에서 미리 돌려보기

```bash
pip install -r crawler/requirements.txt
playwright install --with-deps chromium
python crawler/crawl.py
python -m http.server 8000   # repo 루트에서 실행 후 http://localhost:8000 접속
```

## 문제가 생기면

- **Actions 탭에서 빨간 X(실패) 표시가 뜬다** → 클릭해서 로그를 열어보면
  어느 서비스에서 실패했는지, 왜 실패했는지 나옵니다. 사이트 쪽에서 화면 구조나
  API를 바꾸면 크롤러도 같이 고쳐야 할 수 있습니다. 4개 서비스 중 일부만 실패해도
  나머지는 정상적으로 갱신되고, 실패한 서비스는 화면에 "데이터를 불러오지
  못했습니다" 안내가 뜹니다.
- **화면에 계속 SAMPLE 데이터만 보인다** → `data.json`/`upcoming.json`이 아직 안
  만들어졌거나, GitHub Pages가 옛날 버전을 캐싱하고 있는 걸 수도 있어요. 위 "수동
  실행"부터 다시 확인해보세요.
