#!/usr/bin/env python3
"""수요 기반 주제 선정 분석 — (1) 니즈 랭킹, (2) 미해결 질문 추출.

    python src/analyze.py [수집파일.jsonl]
    python src/analyze.py --demo
"""
import json, statistics as st, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data" / "raw", ROOT / "output"
LEX = json.load(open(ROOT / "src" / "lexicon.json", encoding="utf-8"))
EMO = LEX["감정/불안"]
PERIOD = LEX["시기(필터용)"]
CATS = {k: v for k, v in LEX.items() if k not in ("감정/불안", "시기(필터용)")}
RECENT = ("2024", "2025", "2026")
PRIOR = ("2021", "2022", "2023")


def blob(r):
    """제목 + 스니펫 + 본문. 본문 없는 레코드도 분류되게."""
    return f"{r.get('title','')} {r.get('summary','')} {r.get('text','')}"


def tag(r):
    t = blob(r)
    return {
        "cats": [c for c, ws in CATS.items() if any(w in t for w in ws)],
        "emo": any(w in t for w in EMO),
        "period": [w for w in PERIOD if w in t],
    }


ASK = ("?", "요?", "나요", "까요", "인가", "궁금", "질문", "어떻게", "어떤",
       "뭐가", "괜찮", "해도 되", "추천 부탁", "알려주", "도와", "고민")
TELL = ("후기", "리뷰", "추천합니다", "공유", "정리해", "팁", "경험담", "다녀왔",
        "이용기", "체험단", "협찬")


def is_question(r):
    """질문글만 남긴다. 후기·홍보글은 댓글 0이어도 '미해결'이 아니다."""
    t = (r.get("title") or "").strip()
    if any(w in t for w in TELL):
        return False
    return any(w in t for w in ASK)


def med(xs):
    return st.median(xs) if xs else 0


def rank(rows):
    """카테고리별 수요 지표. 빈도만 보면 검색어 편향에 속으니 반응까지 같이 본다."""
    tags = [tag(r) for r in rows]
    out = []
    for c in CATS:
        idx = [i for i, t in enumerate(tags) if c in t["cats"]]
        if not idx:
            continue
        sub = [rows[i] for i in idx]
        yr = Counter(r["postdate"][:4] for r in sub if r["postdate"])
        recent = sum(yr[y] for y in RECENT)
        prior = sum(yr[y] for y in PRIOR)
        out.append({
            "카테고리": c,
            "문서수": len(sub),
            "댓글중앙값": med([r["comments"] for r in sub]),
            "조회중앙값": med([r["reads"] for r in sub]),
            "무응답률": round(sum(1 for r in sub if r["comments"] == 0) / len(sub) * 100),
            "감정동반률": round(sum(1 for i in idx if tags[i]["emo"]) / len(sub) * 100),
            "최근3년": recent,
            "증가배수": round(recent / prior, 1) if prior else None,
        })
    return sorted(out, key=lambda d: d["댓글중앙값"], reverse=True)


def unanswered(rows, top=40):
    """답 못 받은 질문 중 조회수 높은 것 = 수요는 있는데 정보가 없는 지점."""
    q = [r for r in rows if r["comments"] == 0 and r["reads"] > 0 and is_question(r)]
    q.sort(key=lambda r: r["reads"], reverse=True)
    res = []
    for r in q[:top]:
        t = tag(r)
        res.append({"조회": r["reads"], "날짜": r["postdate"][:10], "제목": r["title"],
                    "카테고리": t["cats"], "감정": t["emo"], "검색어": r["query"]})
    return res


def demo():
    rows = [
        {"title": "젖병 소독기 곰팡이 어떻게 하나요", "summary": "", "text": "찝찝해요 불안",
         "comments": 0, "reads": 900, "postdate": "2025-01-02", "query": "젖병 소독"},
        {"title": "아기 빨래 세제", "summary": "", "text": "건조 어떻게",
         "comments": 8, "reads": 100, "postdate": "2022-01-02", "query": "아기 빨래"},
        {"title": "소독기 청소 후기", "summary": "", "text": "곰팡이 불안",
         "comments": 0, "reads": 5000, "postdate": "2025-02-02", "query": "소독기 청소"},
    ]
    assert rank(rows)  # 후기글 포함해도 랭킹은 계산됨
    t = tag(rows[0])
    assert "용품 소독" in t["cats"] and "청소/집안관리" in t["cats"], t
    assert t["emo"] is True and tag(rows[1])["emo"] is False
    r = rank(rows)
    assert {d["카테고리"] for d in r} >= {"세탁/의류", "용품 소독"}
    sew = next(d for d in r if d["카테고리"] == "세탁/의류")
    assert sew["문서수"] == 1 and sew["댓글중앙값"] == 8 and sew["무응답률"] == 0
    u = unanswered(rows)
    assert len(u) == 1 and u[0]["조회"] == 900, u        # 후기글은 제외돼야 함
    assert is_question({"title": "젖병 소독기 곰팡이 어떻게 하나요"})
    assert not is_question({"title": "소독기 세척 후기"})
    assert med([]) == 0
    print("ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo(); sys.exit()
    f = next((a for a in sys.argv[1:] if a.endswith(".jsonl")),
             str(sorted(RAW.glob("cafe_queries_*.jsonl"))[-1]))
    rows = [json.loads(l) for l in open(f, encoding="utf-8")]
    OUT.mkdir(exist_ok=True)

    tbl, unans = rank(rows), unanswered(rows)
    json.dump({"source": Path(f).name, "n": len(rows), "ranking": tbl, "unanswered": unans},
              open(OUT / "topic_candidates.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(f"\n=== 니즈 랭킹 (n={len(rows)}) ===")
    h = f"{'카테고리':<14}{'문서수':>7}{'댓글중앙':>9}{'조회중앙':>9}{'무응답%':>8}{'감정%':>7}{'증가배수':>9}"
    print(h); print("-" * len(h))
    for d in tbl:
        print(f"{d['카테고리']:<14}{d['문서수']:>7}{d['댓글중앙값']:>9}{d['조회중앙값']:>9}"
              f"{d['무응답률']:>8}{d['감정동반률']:>7}{str(d['증가배수'] or '-'):>9}")
    nq = sum(1 for r in rows if is_question(r))
    nu = sum(1 for r in rows if r["comments"] == 0 and is_question(r))
    print(f"\n=== 질문글 {nq}건 중 답 못 받은 것 {nu}건 · 조회수 상위 15 ===")
    for u in unans[:15]:
        print(f"  {u['조회']:>5}회 {u['날짜']}  {u['제목'][:44]}  {'/'.join(u['카테고리'])[:24]}")
    print(f"\n저장: {OUT}/topic_candidates.json")
