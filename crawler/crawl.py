# -*- coding: utf-8 -*-
"""
매일 아침 4개 구독 서비스의 도서 베스트 순위와 밀리의서재 공개예정 도서 목록을
긁어와서 data.json / history.json / upcoming.json 을 만드는 스크립트.

대상:
    - 교보문고 SAM 무제한 베스트 (sam.kyobobook.co.kr, 브라우저 렌더링 필요)
    - 교보문고 SAM 프리미엄 베스트 (sam.kyobobook.co.kr, 브라우저 렌더링 필요)
    - 밀리의서재 일간 랭킹 (apis.millie.co.kr 공개 API. 데이터센터 IP의 일반
      HTTP 요청은 403으로 막혀서 브라우저 탭 안에서 fetch()로 호출해야 함)
    - 예스24 크레마클럽 인기 (cremaclub.yes24.com 공개 API, requests만으로 수집 가능)
    - 밀리의서재 공개예정 도서 (apis.millie.co.kr 공개 API, 위와 동일하게 브라우저 필요)

실행 방법:
    pip install -r requirements.txt
    playwright install --with-deps chromium
    python crawl.py

결과물:
    ../data.json      - 오늘자 4개 서비스 순위 (index.html 1번 탭)
    ../history.json   - 날짜별 순위 히스토리 누적 (최근 90일)
    ../upcoming.json  - 밀리의서재 공개예정 도서 목록 (index.html 2번 탭)

밀리의서재 랭킹 API/예스24 크레마클럽 목록에는 출판사 정보가 없어서, 화면과
엑셀 다운로드에 실제로 노출되는 TOP 20에 한해 각 책의 상세 페이지에서 출판사를
추가로 조회한다 (PUB_LOOKUP_LIMIT).

※ 사이트 구조가 바뀌면 아래 SELECTORS / API 부분만 고치면 됩니다.
   (2026-08-18에 실제 응답을 확인해서 작성됨)
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ---------- 기본 설정 ----------
KST = timezone(timedelta(hours=9))
NOW_KST = datetime.now(KST)
# 각 서비스의 "일간" 랭킹은 전날 하루치 활동을 집계해서 보여준다
# (예: 밀리의서재는 오늘 접속해도 화면에 어제 날짜가 찍혀 있음).
# 그래서 크롤러가 실행된 날짜가 아니라, 그 랭킹이 실제로 반영하는 날짜를
# "오늘"로 기록한다.
TODAY = (NOW_KST - timedelta(days=1)).strftime("%Y-%m-%d")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root
DATA_JSON = os.path.join(BASE_DIR, "data.json")
HISTORY_JSON = os.path.join(BASE_DIR, "history.json")
UPCOMING_JSON = os.path.join(BASE_DIR, "upcoming.json")

STORES = ["kyobo_unlimited", "kyobo_premium", "millie", "yes24_crema"]
STORE_URLS = {
    "kyobo_unlimited": "https://sam.kyobobook.co.kr/dig/sam/landing/best",
    "kyobo_premium": "https://sam.kyobobook.co.kr/dig/sam/landing/best?pageDvsn=premium",
    "millie": "https://apis.millie.co.kr/public/rank/millie/",
    "yes24_crema": "https://cremaclub.yes24.com/Bookclub/GetBookclubSumGoodsList",
}
RANK_LIMIT = 50
HISTORY_MAX_DAYS = 90
PUB_LOOKUP_LIMIT = 20  # 화면/엑셀에 실제로 노출되는 개수(TOP 20)만큼만 출판사를 조회

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def norm_title(title: str) -> str:
    """서로 다른 서비스의 같은 책을 매칭하기 위해 제목을 정규화."""
    t = re.sub(r"[\s\(\)\[\]『』《》〈〉·:：,.\-!?'\"“”‘’]", "", title or "")
    return t.lower()


def first_publisher(name: str) -> str:
    """공동 출판/임프린트 등으로 "숲,(주)숲코퍼레이션"처럼 콤마로 여러 출판사가
    함께 오는 경우가 있어, 화면에는 첫 번째 출판사명만 표기한다."""
    if not name:
        return ""
    return name.split(",")[0].strip()


# ---------- 서비스별 크롤링 함수 ----------
def scrape_kyobo_sam(page, url):
    """교보문고 SAM (무제한/프리미엄) 일간 베스트.
    sam.kyobobook.co.kr는 클라이언트 렌더링 페이지이며, 기존 교보문고 eBook
    베스트 페이지(ebook.kyobobook.co.kr)와 동일한 #prdList / div.prodDt
    컴포넌트를 재사용하고 있어 같은 셀렉터로 수집한다.
    """
    page.goto(url, wait_until="networkidle", timeout=60000)
    page.wait_for_selector("div#prdList div.prodDt", timeout=20000)
    items = page.query_selector_all("div#prdList > div.prodDt")
    results = []
    for li in items:
        rank_el = li.query_selector("em.rank")
        if not rank_el:
            continue
        try:
            rank = int(rank_el.inner_text().strip())
        except ValueError:
            continue

        title_el = li.query_selector("h3 a")
        title = title_el.inner_text().strip() if title_el else ""
        href = title_el.get_attribute("href") if title_el else ""
        pid = href.rstrip("/").split("/")[-1] if href else ""

        info_spans = li.query_selector_all("p.prodDt_info > span")
        texts = [s.inner_text().strip() for s in info_spans]
        author = texts[0] if len(texts) > 0 else ""
        pub = first_publisher(texts[1]) if len(texts) > 1 else ""

        results.append(
            {"t": rank, "title": title, "author": author, "pub": pub, "pid": pid, "ship": ""}
        )
    return results


def fetch_json_via_browser(page, url, params=None):
    """apis.millie.co.kr는 데이터센터 IP(예: GitHub Actions 러너)에서 오는
    일반 HTTP 클라이언트(requests 등) 요청을 403으로 차단한다. 이미 열려있는
    Playwright 브라우저 탭 안에서 fetch()를 실행하면 실제 브라우저의 요청으로
    처리되어 차단되지 않는다."""
    full_url = url
    if params:
        full_url = url + "?" + urlencode(params)
    return page.evaluate(
        """async (u) => {
            const res = await fetch(u, {headers: {"Accept": "application/json"}});
            if (!res.ok) throw new Error("HTTP " + res.status + " for " + u);
            return await res.json();
        }""",
        full_url,
    )


def fetch_millie_publisher(page, book_seq):
    """밀리의서재 랭킹 API 응답에는 출판사 정보가 없어 책 상세 API에서 따로 가져온다."""
    if not book_seq:
        return ""
    try:
        data = fetch_json_via_browser(
            page, f"https://apis.millie.co.kr/public/content/books/detail/{book_seq}/"
        )
        return first_publisher((data.get("content_info") or {}).get("publisher") or "")
    except Exception:
        return ""


def scrape_millie_rank(page, limit=RANK_LIMIT):
    """밀리의서재 일간 종합 랭킹 (공개 API, 브라우저 탭 안에서 fetch).
    같은 랭킹 안에 전자책판과 오디오북판이 같은 제목으로 함께 섞여 나온다
    (예: 'A' 전자책 3위, 'A' 오디오북 6위). 제목만으로 병합하면 서로 다른
    상품인데도 같은 책으로 합쳐져 순위가 사라져 버리므로, 오디오북 여부를
    함께 표기해서 병합 시 구분되게 한다.
    """
    params = {"adult": 0, "offset": 0, "size": limit, "range": "day", "book_type_code": "01"}
    data = fetch_json_via_browser(page, STORE_URLS["millie"], params)
    items = data.get("data", [])
    results = []
    for idx, b in enumerate(items, start=1):
        badge = b.get("badge") or {}
        pid = b.get("book_seq") or b.get("book_id") or ""
        pub = fetch_millie_publisher(page, pid) if idx <= PUB_LOOKUP_LIMIT else ""
        results.append(
            {
                "t": idx,
                "title": b.get("book_name", ""),
                "author": b.get("author", ""),
                "pub": pub,
                "pid": pid,
                "ship": "",
                "audio": bool(badge.get("is_audiobook")),
            }
        )
    return results


def fetch_yes24_publisher(goods_no):
    """예스24 크레마클럽 목록에도 출판사 정보가 없어 상품 상세 페이지(schema.org
    JSON-LD)에서 따로 가져온다."""
    if not goods_no:
        return ""
    try:
        r = requests.get(
            f"https://www.yes24.com/Product/Goods/{goods_no}",
            headers={"User-Agent": UA},
            timeout=15,
        )
        r.raise_for_status()
        m = re.search(r'"publisher"\s*:\s*\{[^}]*?"name"\s*:\s*"([^"]+)"', r.text)
        return first_publisher(m.group(1)) if m else ""
    except Exception:
        return ""


def scrape_yes24_crema(limit=RANK_LIMIT):
    """예스24 크레마클럽 인기(BEST) 목록 (공개 AJAX 엔드포인트, 브라우저 불필요)."""
    params = {"pageNo": 1, "pageSize": limit, "dispNo": "", "order": 10, "pageGb": "BEST"}
    r = requests.get(
        STORE_URLS["yes24_crema"], params=params, headers={"User-Agent": UA}, timeout=20
    )
    r.raise_for_status()
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    items = soup.select("ul#ulBestBookClubGoods > li")
    results = []
    for idx, li in enumerate(items, start=1):
        rank_el = li.select_one(".info_row.info_rank em")
        title_el = li.select_one("a.gd_name")
        author_el = li.select_one(".authPub.info_auth")
        add_btn = li.select_one("a.btn_addBC")
        try:
            rank = int(rank_el.get_text(strip=True)) if rank_el else idx
        except ValueError:
            rank = idx
        title = title_el.get_text(strip=True) if title_el else ""
        author = author_el.get_text(strip=True) if author_el else ""
        pid = add_btn.get("data-goods-no") if add_btn else ""
        pub = fetch_yes24_publisher(pid) if idx <= PUB_LOOKUP_LIMIT else ""

        results.append(
            {"t": rank, "title": title, "author": author, "pub": pub, "pid": pid or "", "ship": ""}
        )
    return results


def scrape_upcoming(page, limit=60):
    """밀리의서재 공개예정 도서 목록 (전체 탭, 공개 API, 브라우저 탭 안에서 fetch)."""
    url = "https://apis.millie.co.kr/public/curation/coming-soon/books/"
    params = {
        "category": "total",
        "book_type_code": "01",
        "adult_yn": "N",
        "order_by": "popular",
        "limit": limit,
        "offset": 0,
    }
    data = fetch_json_via_browser(page, url, params)
    books = []
    for b in data.get("results", []) or []:
        badge = b.get("badge") or {}
        books.append(
            {
                "id": b.get("content_seq") or "",
                "title": b.get("book_name", ""),
                "author": b.get("author", ""),
                "cover": b.get("cover_image_url", ""),
                "open_date": (b.get("service_open_date") or "").split(" ")[0],
                "is_audiobook": bool(badge.get("is_audiobook")),
                "is_series": bool(badge.get("is_series")),
                "is_comic": bool(badge.get("is_comic")),
            }
        )
    return {"updated": NOW_KST.isoformat(), "count": data.get("count", len(books)), "books": books}


# ---------- 병합 / 전일 대비 계산 ----------
def build_books(scraped: dict) -> list:
    """서로 다른 서비스 결과를 같은 책끼리 묶는다 (제목 정규화 매칭).
    오디오북판은 전자책판과 제목이 같아도 별개 상품이므로 병합 키를 분리한다.
    """
    merged = {}
    for store, items in scraped.items():
        for it in items:
            base_key = norm_title(it["title"])
            if not base_key:
                continue
            is_audio = bool(it.get("audio"))
            key = base_key + "__audio" if is_audio else base_key
            if key not in merged:
                merged[key] = {
                    "isbn": key,
                    "title": it["title"],
                    "author": it["author"],
                    "pub": it["pub"],
                }
            else:
                # 먼저 처리된 서비스에 저자/출판사가 비어 있으면 나중 서비스 값으로 채운다
                entry = merged[key]
                if not entry.get("pub") and it.get("pub"):
                    entry["pub"] = it["pub"]
                if not entry.get("author") and it.get("author"):
                    entry["author"] = it["author"]
            merged[key][store] = {
                "t": it["t"],
                "pid": it["pid"],
                "ship": it.get("ship", ""),
                "audio": is_audio,
            }
    return list(merged.values())


def load_prev_snapshot():
    """어제자 data.json 전체를 읽어온다 (없으면 None)."""
    if not os.path.exists(DATA_JSON):
        return None
    try:
        with open(DATA_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def resolve_prev_date(old):
    if not old:
        return None
    # 같은 날짜 라벨로 재실행된 경우(수동 재시도 등으로 하루에 여러 번 도는 경우)
    # old의 today가 이미 이번 TODAY와 같으므로, 그대로 쓰면 prev == today가
    # 되어 "전날(오늘과 같은 날짜) 대비"라는 잘못된 라벨이 남는다. 그럴 땐
    # 기존 prev 값을 그대로 유지한다.
    return old.get("prev") if old.get("today") == TODAY else old.get("today")


def build_pid_ranks(old):
    """이전 data.json에서 (서비스, 상품ID) -> 순위 매핑을 읽어온다."""
    pid_ranks = {s: {} for s in STORES}
    if not old:
        return pid_ranks
    for cat in old.get("data", {}).values():
        for b in cat.get("books", []):
            for s in STORES:
                v = b.get(s)
                if v and v.get("pid"):
                    pid_ranks[s][v["pid"]] = v["t"]
    return pid_ranks


def extract_store_items(old, store):
    """이전 data.json에서 특정 서비스의 book 목록을 그대로 복원한다.
    오늘 그 서비스 수집이 실패했을 때, 화면에 마지막으로 성공한 데이터를
    계속 보여주기 위한 폴백으로 쓰인다."""
    items = []
    if not old:
        return items
    for cat in old.get("data", {}).values():
        for b in cat.get("books", []):
            v = b.get(store)
            if v:
                items.append(
                    {
                        "t": v["t"],
                        "title": b.get("title", ""),
                        "author": b.get("author", ""),
                        "pub": b.get("pub", ""),
                        "pid": v.get("pid", ""),
                        "ship": v.get("ship", ""),
                        "audio": bool(v.get("audio")),
                    }
                )
    return items


def apply_prev_ranks(books: list, pid_ranks: dict):
    for b in books:
        for s in STORES:
            v = b.get(s)
            if v:
                v["p"] = pid_ranks.get(s, {}).get(v["pid"])  # 없으면 None(=신규 NEW)


# ---------- 히스토리 누적 ----------
def update_history(output: dict, stale_stores: dict):
    if os.path.exists(HISTORY_JSON):
        try:
            with open(HISTORY_JSON, encoding="utf-8") as f:
                hist = json.load(f)
        except Exception:
            hist = {"dates": [], "books": {}}
    else:
        hist = {"dates": [], "books": {}}

    if TODAY in hist["dates"]:
        idx = hist["dates"].index(TODAY)
    else:
        hist["dates"].append(TODAY)
        idx = len(hist["dates"]) - 1
        for bk in hist["books"].values():
            for cat_series in bk.get("series", {}).values():
                for arr in cat_series.values():
                    arr.append(None)

    n = len(hist["dates"])
    for b in output["data"]["all"]["books"]:
        key = b["isbn"]
        bk = hist["books"].setdefault(
            key, {"title": b["title"], "author": b["author"], "pub": b["pub"], "series": {}}
        )
        bk["title"], bk["author"], bk["pub"] = b["title"], b["author"], b["pub"]
        cat_series = bk["series"].setdefault("all", {})
        for s in STORES:
            arr = cat_series.setdefault(s, [None] * n)
            while len(arr) < n:
                arr.append(None)
            # 오늘 수집이 실패해 이전 데이터를 그대로 보여주는 서비스는, 실제로는
            # 오늘자 순위가 아니므로 히스토리에는 "데이터 없음"으로 남긴다
            # (그래야 과거 날짜 조회 시 실제로 없던 날에 가짜 순위가 찍히지 않는다).
            v = None if s in stale_stores else b.get(s)
            arr[idx] = v["t"] if v else None
        b["hkey"] = key  # index.html이 히스토리 팝업에서 사용

    # 90일 넘으면 앞부분 자르기
    if len(hist["dates"]) > HISTORY_MAX_DAYS:
        cut = len(hist["dates"]) - HISTORY_MAX_DAYS
        hist["dates"] = hist["dates"][cut:]
        for bk in hist["books"].values():
            for cat_series in bk.get("series", {}).values():
                for k in list(cat_series.keys()):
                    cat_series[k] = cat_series[k][cut:]

    with open(HISTORY_JSON, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


# ---------- 메인 ----------
def main():
    old = load_prev_snapshot()
    pid_ranks = build_pid_ranks(old)
    prev_date = resolve_prev_date(old)
    old_stale = (old.get("stale_stores") if old else None) or {}

    scraped = {}
    errors = {}
    upcoming = None

    # 1) requests만으로 되는 서비스 (예스24 크레마클럽 - 데이터센터 IP도 허용됨)
    try:
        scraped["yes24_crema"] = scrape_yes24_crema()
        print(f"[OK] yes24_crema: {len(scraped['yes24_crema'])}건 수집")
    except Exception as e:
        scraped["yes24_crema"] = []
        errors["yes24_crema"] = str(e)
        print(f"[FAIL] yes24_crema: {e}", file=sys.stderr)

    # 2) 브라우저가 필요한 나머지: 교보문고 SAM(DOM 렌더링), 밀리의서재(탭 안에서 fetch)
    #    밀리의서재 API(apis.millie.co.kr)는 GitHub Actions 같은 데이터센터 IP의
    #    일반 HTTP 요청은 403으로 막아서, 반드시 브라우저 탭 안에서 호출해야 한다.
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="ko-KR", user_agent=UA)
        page.set_default_timeout(60000)

        for store in ("kyobo_unlimited", "kyobo_premium"):
            try:
                scraped[store] = scrape_kyobo_sam(page, STORE_URLS[store])
                print(f"[OK] {store}: {len(scraped[store])}건 수집")
            except Exception as e:
                scraped[store] = []
                errors[store] = str(e)
                print(f"[FAIL] {store}: {e}", file=sys.stderr)

        try:
            page.goto("https://www.millie.co.kr/v4/now/millie-ranking", wait_until="domcontentloaded", timeout=60000)
            scraped["millie"] = scrape_millie_rank(page)
            print(f"[OK] millie: {len(scraped['millie'])}건 수집")
        except Exception as e:
            scraped["millie"] = []
            errors["millie"] = str(e)
            print(f"[FAIL] millie: {e}", file=sys.stderr)

        try:
            upcoming = scrape_upcoming(page)
            print(f"[OK] upcoming: {len(upcoming['books'])}건 수집")
        except Exception as e:
            errors["upcoming"] = str(e)
            print(f"[FAIL] upcoming: {e}", file=sys.stderr)

        browser.close()

    # 오늘 수집에 실패한 서비스는 화면이 텅 비지 않도록 마지막으로 성공한
    # 데이터를 그대로 이어서 보여주고, 몇 번째 날짜 데이터인지(stale_stores)를
    # 함께 기록해 화면에 "미업데이트" 안내를 띄울 수 있게 한다.
    stale_stores = {}
    for s in STORES:
        if s not in errors:
            continue
        fallback_items = extract_store_items(old, s)
        if fallback_items:
            scraped[s] = fallback_items
        last_good = old_stale.get(s) or (old.get("today") if old else None)
        if last_good:
            stale_stores[s] = last_good

    books = build_books(scraped)
    apply_prev_ranks(books, pid_ranks)

    output = {
        "today": TODAY,
        "prev": prev_date,
        "surge_gap": 4,
        "categories": [{"id": "all", "label": "전체"}],
        "data": {"all": {"books": books}},
        "stale_stores": stale_stores,
    }

    update_history(output, stale_stores)  # books에 hkey 채워짐 (output과 같은 객체 참조)

    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"완료: 총 {len(books)}권, data.json / history.json 저장됨")

    if upcoming is not None:
        with open(UPCOMING_JSON, "w", encoding="utf-8") as f:
            json.dump(upcoming, f, ensure_ascii=False, indent=2)
        print(f"완료: 공개예정 도서 {len(upcoming['books'])}권, upcoming.json 저장됨")

    if errors:
        print(f"일부 수집 실패: {list(errors.keys())} (다음 실행 때 재시도됩니다)")


if __name__ == "__main__":
    main()
