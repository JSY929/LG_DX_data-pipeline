#!/usr/bin/env python3
"""네이버 카페 수집기 (Playwright). 대상: 맘스홀릭 베이비 / 클럽 10094499 / 게시판 591.

JSON API 직접 호출. 페이지 렌더링을 거치지 않는다.
레코드 스키마·가명화는 collect.py 를 그대로 재사용.

사용:
    python src/cafe_crawl.py --login                          # 1회, 쿠키 저장
    python src/cafe_crawl.py --check                          # 쿠키 살았는지 확인
    python src/cafe_crawl.py queries_cleaning.txt --limit 30   # 테스트
    python src/cafe_crawl.py queries_cleaning.txt --limit 10000
    옵션: --no-body(제목·메타만, 빠름) --sleep 3(간격) --demo(자체검사)

주의: 로그인 쿠키는 data/.auth/ 에 평문 저장. 커밋 금지.
"""
import json, random, re, sys, time
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect import ROOT, RAW, clean, hid   # 가명화·정제 재사용

CAFE_NAME = "맘스홀릭 베이비"
CAFE_SLUG = "imsanbu"
CLUB_ID = "10094499"
MENU_ID = "392"           # 임신 중 질문방 (이전: 591 산후조리 질문방). --menu 로 덮어쓰기 가능
STATE = ROOT / "data" / ".auth" / "naver_state.json"

# 카페 검색창이 실제로 쏘는 요청 (--find-search 로 확인함)
SEARCH_API = ("https://apis.cafe.naver.com/search/v2/cafes/{club}/search/articles"
              "?query={q}&perPage={per}&page={p}&menuId={menu}"
              "&views=MEMBER_LEVEL%2CCOUNT%2CSALE_INFO%2CCAFE_MENU")   # 쉼표는 인코딩된 형태 그대로
ARTICLE_API = ("https://article.cafe.naver.com/gw/v4/cafes/{club}/articles/{aid}"
               "?query=&useCafeId=true&requestFrom=A")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HDRS = {"referer": f"https://cafe.naver.com/f-e/cafes/{CLUB_ID}/menus/{MENU_ID}",
        "origin": "https://cafe.naver.com",
        "accept": "application/json, text/plain, */*",
        "accept-language": "ko-KR,ko;q=0.9",
        "x-cafe-product": "pc"}

PER_PAGE = 15             # 검색창 기본값. 올리면 거부될 수 있음.
YEARS = 10                # 최근 N년만 수집. 그보다 오래된 글은 저장하지 않는다.
PAGE_CAP = 100            # 네이버 카페 검색 상한. 키워드당 100페이지(=1500건)에서 잘린다.
                          # 여기 걸리면 결과가 소진된 게 아니라 "잘린" 것이고, 잘려나가는 쪽은
                          # 오래된 글이라 연도 분포가 최신 쪽으로 왜곡된다. 해법은 두 가지:
                          #   1) 기간을 쪼개 검색 (구간마다 상한이 새로 적용됨)
                          #   2) menuId 를 빼서 게시판 전체로 넓히기
PAGES = 3
SLEEP = 2.0               # 요청 간 간격(초) + 0~1초 지터. 낮추지 말 것 — 차단 트리거.
BR = re.compile(r"<br\s*/?>|</p>|</div>", re.I)


# ---------- 파싱 (응답 스키마가 바뀌어도 버티도록 키 탐색 방식) ----------

def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def pick_articles(data):
    out, seen = [], set()
    for d in walk(data):
        aid = d.get("articleId") or d.get("articleid")
        title = d.get("subject") or d.get("title")
        if not aid or not isinstance(title, str) or str(aid) in seen:
            continue
        seen.add(str(aid))
        out.append(d)
    return out


def pick_body(data):
    for d in walk(data):
        for k in ("contentHtml", "content", "articleContent"):
            v = d.get(k)
            if isinstance(v, str) and len(v) > 20:
                return v
    return ""


def pick_comments(data):
    """본문 응답 안의 댓글 내용. 별도 요청 없이 article API 에 같이 온다."""
    for d in walk(data or {}):
        items = d.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict) and "content" in items[0]:
            return [to_text(x.get("content")) for x in items if x.get("content")]
    return []


def pick_board(data):
    """본문 응답 안의 게시판 이름 (menu 객체의 name)."""
    for d in walk(data or {}):
        if "name" in d and "menuType" in d and isinstance(d["name"], str) and d["name"]:
            return d["name"]
    return ""


def when(art):
    """addDate(ISO 문자열) 우선, 없으면 writeDate(epoch ms)."""
    v = art.get("addDate") or art.get("writeDate") or art.get("writeDateTimestamp")
    if isinstance(v, (int, float)):
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(v / 1000))
    return str(v or "")


def to_text(html_str):
    return clean(BR.sub("\n", html_str or ""))


def record(query, art, body=None):
    """수집 레코드. 작성자 닉네임은 저장하지 않는다(가명화 유지)."""
    aid = art.get("articleId") or art.get("articleid")
    comments = pick_comments(body) if body else []
    return {
        "cafe_name": CAFE_NAME,
        "club_id": CLUB_ID,
        "menu_id": str(art.get("menuId") or MENU_ID),
        "board": clean(pick_board(body)) if body else "",
        "keyword": query,
        "postdate": when(art),
        "title": clean(art.get("subject") or art.get("title")),
        "text": to_text(pick_body(body)) if body else "",
        "comments_text": comments,
        "comment_count": art.get("commentCount", art.get("replyCount", 0)),
        "url": f"https://cafe.naver.com/{CAFE_SLUG}/{aid}",
        "doc_id": hid(f"{CLUB_ID}/{aid}"),             # 중복 제거용
        "summary": clean(art.get("summary")),
        "hits": art.get("highlightKeywords") or [],
        "reads": art.get("readCount", 0),
    }


# ---------- 요청 ----------

def get(rq, url, what):
    """JSON 1건. 실패하면 추측 대신 상태코드와 응답 본문을 그대로 찍는다."""
    try:
        r = rq.get(url, timeout=20000)
    except Exception as e:
        print(f"  ! {what} 요청 실패: {e}", file=sys.stderr)
        return None
    if not r.ok:
        print(f"  ! {what} HTTP {r.status}\n    {url[:150]}\n    본문: {r.text()[:200] or '(빈 응답)'}", file=sys.stderr)
        for k in ("x-error-code", "x-error-message", "content-type", "location", "www-authenticate"):
            if r.headers.get(k):
                print(f"    {k}: {r.headers[k][:120]}", file=sys.stderr)
        if r.status in (401, 403):
            print("    → 로그인 만료. python src/cafe_crawl.py --login", file=sys.stderr)
        return None
    try:
        return r.json()
    except Exception:
        print(f"  ! {what} JSON 아님 (로그인 페이지 의심)\n    {r.text()[:200]}", file=sys.stderr)
        return None


def ctx(p):
    return p.request.new_context(storage_state=str(STATE), user_agent=UA, extra_http_headers=HDRS)


def login():
    from playwright.sync_api import sync_playwright
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=False)
        c = b.new_context()
        c.new_page().goto("https://nid.naver.com/nidlogin.login")
        input('브라우저에서 직접 로그인("로그인 상태 유지" 체크) 후 여기서 Enter: ')
        c.storage_state(path=str(STATE))
        b.close()
    print(f"쿠키 저장: {STATE}", file=sys.stderr)


def dump(q="젖병 소독"):
    """검색·본문 응답 원본을 저장하고 필드명을 훑는다. 날짜/게시판 필드 확정용."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        rq = ctx(p)
        sr = get(rq, SEARCH_API.format(club=CLUB_ID, q=quote_plus(q),
                                       per=PER_PAGE, p=1, menu=MENU_ID), "검색")
        arts = pick_articles(sr) if sr else []
        if not arts:
            print("검색 결과 없음"); rq.dispose(); return
        a = arts[0]
        aid = a.get("articleId") or a.get("articleid")
        ar = get(rq, ARTICLE_API.format(club=CLUB_ID, aid=aid), f"본문 {aid}")
        rq.dispose()

    (RAW / "_sample_search.json").write_text(json.dumps(sr, ensure_ascii=False, indent=1), encoding="utf-8")
    (RAW / "_sample_article.json").write_text(json.dumps(ar, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n[검색 결과 1건] 키 {len(a)}개")
    for k, v in a.items():
        print(f"  {k:24} = {str(v)[:70]}")
    want = ("date", "time", "menu", "board", "writ", "name", "comment", "read", "view")
    print("\n[본문 응답에서 날짜/게시판 후보]")
    for d in walk(ar):
        for k, v in d.items():
            if any(w in k.lower() for w in want) and not isinstance(v, (dict, list)):
                print(f"  {k:28} = {str(v)[:60]}")
    print(f"\n원본 저장: {RAW}/_sample_search.json , _sample_article.json")


CHECK_Q = "임신"           # 쿠키 확인용. 대상 게시판에 반드시 있는 흔한 말로.


def check():
    from playwright.sync_api import sync_playwright
    if not STATE.exists():
        print("쿠키 없음 → python src/cafe_crawl.py --login"); return 2
    with sync_playwright() as p:
        rq = ctx(p)
        d = get(rq, SEARCH_API.format(club=CLUB_ID, q=quote_plus(CHECK_Q),
                                      per=PER_PAGE, p=1, menu=MENU_ID), "검색")
        arts = pick_articles(d) if d else []
        if not arts:
            rq.dispose(); print("검색 실패 — 위 원인 참고"); return 1
        aid = arts[0].get("articleId") or arts[0].get("articleid")
        body = get(rq, ARTICLE_API.format(club=CLUB_ID, aid=aid), "본문")
        rq.dispose()
    if not body:
        print("검색은 되나 본문 401 — 비로그인 상태다. python src/cafe_crawl.py --login")
        return 1
    print(f"쿠키 유효 (검색 {len(arts)}건 + 본문 {len(to_text(pick_body(body)))}자). 수집 가능.")
    return 0


# ---------- 수집 ----------

def count_only(queries):
    """키워드당 요청 1회로 총 건수만 잰다. 수집 전에 키워드 고르는 용도."""
    from playwright.sync_api import sync_playwright
    cap = PAGE_CAP * PER_PAGE
    print(f"{'키워드':<16}{'총건수':>8}{'수집가능':>9}  비고")
    tot = 0
    with sync_playwright() as p:
        rq = ctx(p)
        for q in queries:
            d = get(rq, SEARCH_API.format(club=CLUB_ID, q=quote_plus(q),
                                          per=PER_PAGE, p=1, menu=MENU_ID), f"검색 {q}")
            n = next((x["totalArticleCount"] for x in walk(d or {})
                      if "totalArticleCount" in x), 0)
            got = min(n, cap)
            tot += got
            note = "잘림 — 기간 분할 필요" if n > cap else ("결과 없음" if n == 0 else "")
            print(f"{q:<16}{n:>8}{got:>9}  {note}")
            time.sleep(SLEEP)
        rq.dispose()
    print(f"\n합계 {tot}건 (중복 제거 전). 실제는 30~40% 줄어든다.")


def crawl(queries, tag, pages, limit=None, want_body=True, max_hours=None):
    from playwright.sync_api import sync_playwright
    if not STATE.exists():
        sys.exit("로그인 쿠키 없음. 먼저: python src/cafe_crawl.py --login")

    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / f"cafe_{tag}_{time.strftime('%Y%m%d')}.jsonl"
    ckpt = RAW / f"_ckpt_cafe_{tag}.txt"
    done = set(ckpt.read_text(encoding="utf-8").splitlines()) if ckpt.exists() else set()
    seen = {json.loads(l)["doc_id"] for l in out.open(encoding="utf-8")} if out.exists() else set()
    n, t0, fail, old = 0, time.time(), 0, 0
    cutoff = str(int(time.strftime("%Y")) - YEARS)      # 예: 2016
    stat = {}                 # 키워드별 (요청페이지, 저장건수) — 끝에 잘림 여부 보고

    def nap():
        time.sleep(SLEEP + random.random())

    def over_time():
        return max_hours and (time.time() - t0) / 3600 >= max_hours

    with sync_playwright() as p, out.open("a", encoding="utf-8") as f, ckpt.open("a", encoding="utf-8") as ck:
        rq = ctx(p)
        for q in queries:
            for pg in range(1, pages + 1):
                key = f"{q}|{pg}"
                if key in done:
                    continue
                data = get(rq, SEARCH_API.format(club=CLUB_ID, q=quote_plus(q),
                                                 per=PER_PAGE, p=pg, menu=MENU_ID), f"검색 {key}")
                arts = pick_articles(data) if data else []
                st = stat.setdefault(q, [0, 0])
                if not arts:
                    break                       # 결과 끝 또는 실패 — 다음 키워드로
                st[0] = pg
                for a in arts:
                    if (limit and n >= limit) or over_time():
                        break
                    aid = a.get("articleId") or a.get("articleid")
                    if hid(f"{CLUB_ID}/{aid}") in seen:
                        continue
                    if when(a)[:4] and when(a)[:4] < cutoff:   # 최근 YEARS 년만
                        old += 1
                        continue
                    seen.add(hid(f"{CLUB_ID}/{aid}"))
                    body = None
                    if want_body:               # 본문 1건당 요청 1회 = 전체 시간의 대부분
                        nap()
                        body = get(rq, ARTICLE_API.format(club=CLUB_ID, aid=aid), f"본문 {aid}")
                        if body:
                            fail = 0
                        else:
                            fail += 1
                            if fail >= 5:
                                sys.exit("본문 요청 5회 연속 실패 — 중단. --check 로 확인할 것")
                    f.write(json.dumps(record(q, a, body), ensure_ascii=False) + "\n")
                    n += 1; st[1] += 1
                f.flush()
                ck.write(key + "\n"); ck.flush()
                print(f"  {key} → 누적 {n} ({(time.time()-t0)/60:.1f}분)", file=sys.stderr)
                if (limit and n >= limit) or over_time():
                    break
                nap()
            if (limit and n >= limit) or over_time():
                why = f"목표 {limit}건 도달" if (limit and n >= limit) else f"제한 시간 {max_hours}h 도달"
                print(f"{why} — 중단", file=sys.stderr)
                break
        rq.dispose()

    # ---- 수집 품질 보고. 조용히 잘린 채 끝나는 걸 막는다 ----
    print(f"\n{'키워드':<14}{'페이지':>7}{'저장':>7}  상태", file=sys.stderr)
    cut, zero = [], []
    hit_limit = bool(limit and n >= limit)
    last_q = list(stat)[-1] if stat else None
    for q, (pg, got) in stat.items():
        if pg >= PAGE_CAP:
            state = "잘림 ⚠"; cut.append(q)
        elif pg == 0:
            state = "결과 0건"; zero.append(q)
        elif hit_limit and q == last_q:
            state = "중단(상한)"          # 결과가 끝난 게 아니라 --limit 에 걸린 것
        else:
            state = "소진"
        print(f"{q:<14}{pg:>7}{got:>7}  {state}", file=sys.stderr)
    for q in queries:
        if q not in stat:               # 상한에 걸려 요청 자체를 안 함 — 0건과 구분
            print(f"{q:<14}{'-':>7}{'-':>7}  미실행", file=sys.stderr)
    req = sum(pg for pg, _ in stat.values()) * PER_PAGE
    if req:
        print(f"\n요청 {req}건 → 저장 {n}건 (중복 제거 {100 - n*100//req}%)"
              f"{f' · {YEARS}년 초과 제외 {old}건' if old else ''}", file=sys.stderr)
    if cut:
        print(f"\n⚠ {len(cut)}개 키워드가 {PAGE_CAP}페이지 상한에 잘렸다: {', '.join(cut)}", file=sys.stderr)
        print("  → 소진이 아니라 잘린 것. 오래된 글이 빠져 연도 분포가 왜곡된다.", file=sys.stderr)
        print("  → 기간을 쪼개 검색하거나 menuId 를 빼서 범위를 넓혀야 한다.", file=sys.stderr)
    if zero:
        print(f"\n⚠ 결과 0건 키워드: {', '.join(zero)} — 표현을 바꿔야 한다.", file=sys.stderr)
    print(f"\n저장: {out} (총 {n})", file=sys.stderr)
    return n


def demo():
    fake = {"result": {"articleList": [
        {"articleId": 123, "subject": "젖병 <b>소독</b> 어떻게", "menuName": "출산준비",
         "writerInfo": {"nickName": "맘맘"}, "commentCount": 7, "readCount": 300,
         "menuId": 591, "addDate": "2026-08-31T13:00:59.727",
         "summary": "있는 <b>젖병</b>&amp;깔대기 <b>소독</b>해서", "highlightKeywords": ["소독", "젖병"]},
        {"articleId": 123, "subject": "중복글"}, {"noise": True}]}}
    arts = pick_articles(fake)
    assert len(arts) == 1, arts
    fake_body = {"result": {
        "article": {"contentHtml": "소독기 vs <b>열탕</b><br>어느 쪽이 나을까요 &amp; 시간은요"},
        "menu": {"name": "임신 중 질문방", "menuType": "B"},
        "comments": {"items": [{"content": "저는 열탕 했어요", "writer": {"nick": "맘맘"}},
                               {"content": "소독기 추천!"}]}}}
    r = record("젖병 소독", arts[0], fake_body)
    assert r["text"] == "소독기 vs 열탕\n어느 쪽이 나을까요 & 시간은요", repr(r["text"])
    assert r["title"] == "젖병 소독 어떻게"
    assert r["comments_text"] == ["저는 열탕 했어요", "소독기 추천!"], r["comments_text"]
    assert r["board"] == "임신 중 질문방"
    assert r["url"] == f"https://cafe.naver.com/{CAFE_SLUG}/123"
    assert r["cafe_name"] == CAFE_NAME and r["club_id"] == CLUB_ID and r["menu_id"] == "591"
    assert "맘맘" not in json.dumps(r, ensure_ascii=False)     # 닉네임 미저장
    assert r["comment_count"] == 7 and r["keyword"] == "젖병 소독"
    assert record("q", arts[0])["text"] == "" and record("q", arts[0])["comments_text"] == []
    assert pick_body({"a": "짧음"}) == ""
    assert r["postdate"] == "2026-08-31T13:00:59.727"
    assert r["summary"] == "있는 젖병&깔대기 소독해서" and r["hits"] == ["소독", "젖병"]
    assert when({"writeDate": 1788148859727}).startswith("2026-"), when({"writeDate": 1788148859727})
    assert pick_board({"menu": {"name": "산후조리 질문방", "menuType": "B"}}) == "산후조리 질문방"
    u = SEARCH_API.format(club=CLUB_ID, q=quote_plus("젖병 소독"), per=15, p=2, menu=MENU_ID)
    assert "query=%EC%A0%96%EB%B3%91+%EC%86%8C%EB%8F%85" in u and "page=2" in u, u
    print("ok")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--demo" in argv:
        demo(); sys.exit()
    if "--login" in argv:
        login(); sys.exit()
    if "--menu" in argv:                      # 게시판 바꿀 때 상수 안 건드리고
        MENU_ID = argv[argv.index("--menu") + 1]
        HDRS["referer"] = f"https://cafe.naver.com/f-e/cafes/{CLUB_ID}/menus/{MENU_ID}"
    if "--sleep" in argv:
        SLEEP = float(argv[argv.index("--sleep") + 1])
    if "--check" in argv:
        sys.exit(check())
    if "--count" in argv:
        name = next((a for a in argv if a.endswith(".txt")), "queries_pregnancy.txt")
        count_only([l.strip() for l in (ROOT / "src" / name).read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.startswith("#")])
        sys.exit()
    if "--dump" in argv:
        i = argv.index("--dump")
        dump(argv[i + 1] if len(argv) > i + 1 and not argv[i + 1].startswith("--") else "젖병 소독")
        sys.exit()
    max_hours = float(argv[argv.index("--max-hours") + 1]) if "--max-hours" in argv else None
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
    pages = (int(argv[argv.index("--pages") + 1]) if "--pages" in argv
             else (200 if limit else PAGES))
    name = next((a for a in argv if not a.startswith("--") and a.endswith(".txt")),
                "queries_cleaning.txt")
    qs = [l.strip() for l in (ROOT / "src" / name).read_text(encoding="utf-8").splitlines()
          if l.strip() and not l.startswith("#")]
    tag = Path(name).stem
    print(f"[{tag}] 키워드 {len(qs)} × {pages}페이지 · 상한 {limit or '없음'}"
          f"{' · 본문 생략' if '--no-body' in argv else ''} · 간격 {SLEEP}~{SLEEP+1}초", file=sys.stderr)
    crawl(qs, tag, pages, limit=limit, want_body="--no-body" not in argv, max_hours=max_hours)
