#!/usr/bin/env python3
"""네이버 검색 API 수집기 — 블로그 / 카페 / 지식iN.

사용:
    export NAVER_CLIENT_ID=... NAVER_CLIENT_SECRET=...
    python src/collect.py                  # queries.txt 로 수집
    python src/collect.py queries_hygiene.txt   # 위생 사전 검증용 별도 수집
    python src/collect.py --demo           # 네트워크 없이 자체 검사
"""
import hashlib, html, json, os, re, sys, time
import urllib.error, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
ENDPOINTS = ("blog", "cafearticle", "kin")
SORTS = ("sim", "date")
PER_PAGE = 100
MAX_START = 1001          # API 상한: start 최대 1000
SLEEP = 0.12
TAG = re.compile(r"<[^>]+>")

ID = os.environ.get("NAVER_CLIENT_ID")
SECRET = os.environ.get("NAVER_CLIENT_SECRET")


def clean(s):
    return html.unescape(TAG.sub("", s or "")).strip()


def hid(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def record(endpoint, query, sort, rank, item):
    """가명화하며 레코드 생성 — 원본 link 와 닉네임은 저장하지 않는다."""
    return {
        "source": endpoint,
        "query": query,
        "sort": sort,
        "rank": rank,
        "doc_id": hid(item["link"]),
        "author": hid(item["bloggername"]) if item.get("bloggername") else "",
        "board": item.get("cafename", ""),
        "postdate": item.get("postdate", ""),
        "title": clean(item.get("title")),
        "text": clean(item.get("description")),
    }


def fetch(endpoint, query, start, sort):
    qs = urllib.parse.urlencode(
        {"query": query, "display": PER_PAGE, "start": start, "sort": sort}
    )
    req = urllib.request.Request(
        f"https://openapi.naver.com/v1/search/{endpoint}.json?{qs}",
        headers={"X-Naver-Client-Id": ID, "X-Naver-Client-Secret": SECRET},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)["items"]
        except urllib.error.HTTPError as e:
            if e.code == 400:          # start 상한 초과 — 더 볼 것 없음
                return []
            if e.code in (401, 403):   # 키 문제는 재시도해도 같음
                sys.exit(f"인증 실패 {e.code}: 키 확인 필요")
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
        except urllib.error.URLError:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    return []


def collect(queries, tag):
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / f"naver_{tag}_{time.strftime('%Y%m%d')}.jsonl"
    ckpt = RAW / f"_checkpoint_{tag}.txt"
    done = set(ckpt.read_text(encoding="utf-8").splitlines()) if ckpt.exists() else set()
    seen, n = set(), 0

    with out.open("a", encoding="utf-8") as f, ckpt.open("a", encoding="utf-8") as ck:
        for q in queries:
            for ep in ENDPOINTS:
                for sort in SORTS:
                    key = f"{ep}|{sort}|{q}"
                    if key in done:
                        continue
                    for start in range(1, MAX_START, PER_PAGE):
                        items = fetch(ep, q, start, sort)
                        if not items:
                            break
                        for i, it in enumerate(items):
                            r = record(ep, q, sort, start + i, it)
                            if r["doc_id"] in seen:
                                continue
                            seen.add(r["doc_id"])
                            f.write(json.dumps(r, ensure_ascii=False) + "\n")
                            n += 1
                        f.flush()
                        time.sleep(SLEEP)
                    ck.write(key + "\n")
                    ck.flush()
                    print(f"  {key} → 누적 {n}", file=sys.stderr)
    print(f"저장: {out}", file=sys.stderr)
    return n


def demo():
    assert clean("<b>산후</b>조리원 &amp; 위생") == "산후조리원 & 위생"
    assert clean(None) == ""
    assert hid("https://x/1") == hid("https://x/1") != hid("https://x/2")
    r = record("blog", "산후조리", "sim", 3, {
        "link": "https://x/1",
        "title": "<b>오로</b> 언제까지",
        "description": "회음부 <b>좌욕</b> 해야 하나요",
        "bloggername": "맘맘",
    })
    assert r["text"] == "회음부 좌욕 해야 하나요"
    assert r["title"] == "오로 언제까지"
    assert "link" not in r and r["author"] != "맘맘"
    assert r["rank"] == 3
    print("ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        sys.exit()
    if not (ID and SECRET):
        sys.exit("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수 없음")
    name = sys.argv[1] if len(sys.argv) > 1 else "queries.txt"
    qs = [
        l.strip()
        for l in (ROOT / "src" / name).read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.startswith("#")
    ]
    tag = Path(name).stem
    print(f"[{tag}] 쿼리 {len(qs)}개 · 예상 요청 {len(qs) * 60:,} (한도 25,000/day)", file=sys.stderr)
    print(f"총 {collect(qs, tag)} 레코드", file=sys.stderr)
