#!/usr/bin/env python3
"""크롤링 결과 워드클라우드.

    python src/wordcloud_gen.py                    # 전체
    python src/wordcloud_gen.py --cat 손위생        # 카테고리별 (lexicon.json 기준)
    python src/wordcloud_gen.py --cat all          # 카테고리 6종 한 장에
    python src/wordcloud_gen.py --field title      # 제목만 (본문 제외)
    python src/wordcloud_gen.py --questions        # 후기글 빼고 질문글만 = 니즈 중심
    python src/wordcloud_gen.py --demo

형태소 분석기 대신 정규식 + 조사 제거. 자바 의존성(konlpy) 피하려는 선택.
ponytail: 명사 판별이 완벽하진 않다. 정확도가 문제되면 kiwipiepy 로 교체.
"""
import json, re, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import CATS, RAW, ROOT, blob, is_question, tag   # 사전·태깅 재사용

OUT = ROOT / "output"
FONT = "/System/Library/Fonts/Supplemental/AppleGothic.ttf"
HANGUL = re.compile(r"[가-힣]{2,}")
JOSA = re.compile(r"(으로|에서|에게|이랑|처럼|부터|까지|한테|께서|이나|보다|은|는|이|가|을|를|에|와|과|도|만|의|랑|나)$")
# 용언 활용형 제거. 단일 글자 어미로 자르면 '먼지'·'세제' 같은 명사가 잘려서 여러 글자만 본다.
ENDING = re.compile(r"(어요|아요|에요|예요|였어|았어|었어|겠어|겠네|해서|어서|아서|하고|하면|하지|하는|해주|시고|시는|셔서|"
                    r"는데|지만|니까|면서|거든|더라|습니다|합니다|였습|았습|었습|드려|해도|해야|되는|되고|된다|같아|같은|"
                    r"있어|있고|있는|있다|없어|없고|없는|없다|좋아|좋은|좋았|봤어|봤는|했어|했는|할까|일까|인가|나요|까요)$")

# 카페 글에 흔한 무의미어 + 검색어 자체(자기충족적이라 제외)
STOP = set("""
그냥 진짜 정말 너무 조금 다시 아주 완전 계속 하나 하는 해서 했는데 있는 없는 같아요 같은
저는 제가 우리 그런 이런 저런 그리고 그래서 근데 이제 지금 오늘 어제 내일 요즘 항상 가끔
아기 아가 애기 신생아 엄마 아빠 남편 시댁 친정 아이 baby 산후조리원 산후도우미 조리원 도우미
질문 답변 부탁 감사합니다 감사 안녕하세요 여러분 혹시 무엇 어디 언제 얼마 정도 경우 생각
사용 구매 제품 브랜드 추천 후기 리뷰 가격 할인 링크 사진 아래 위에 다들 분들 님들 자꾸
정도 동안 한번 먼저 사실 원래 미리 혼자 아직 모두 모든 특히 가장 제일 일단 따로 직접 함께
때문 등등 여기 저희 하루 오전 오후 아침 점심 저녁 첫째 둘째 부분 상태 느낌 어떻게 이렇게
그래 그거 저거 이거 무슨 어떤 이건 그건 관리 회복 도움 시간 매일 엄청 다시 바로 아주 완전
""".split())

# 접미사가 붙어도 걸러야 하는 말. STOP 은 완전일치라 '산후도우미님', '조리원생활' 을 못 잡는다.
# 여기 넣은 조각이 단어 안에 들어 있기만 하면 제거된다. 짧은 조각은 과잉 제거 주의.
STOP_PART = tuple("""
조리원 도우미 이모님 관리사
""".split())


def tokens(text):
    """한글 2글자 이상 → 조사 제거 → 불용어 제거."""
    out = []
    for w in HANGUL.findall(text):
        w = JOSA.sub("", w)
        if ENDING.search(w) or len(w) < 2 or w in STOP:
            continue
        if any(part in w for part in STOP_PART):
            continue
        out.append(w)
    return out


def freq(rows, field="all", topn=200):
    """문서 빈도(DF). 긴 글에서 한 단어가 반복돼 순위를 왜곡하는 걸 막는다."""
    c = Counter()
    for r in rows:
        t = r.get("title", "") if field == "title" else blob(r)
        c.update(set(tokens(t)))          # set = 글 하나당 1표
    return dict(c.most_common(topn))


def draw(ax, counts, title):
    from wordcloud import WordCloud
    if not counts:
        ax.text(.5, .5, f"{title}\n(데이터 없음)", ha="center", va="center"); ax.axis("off"); return
    wc = WordCloud(font_path=FONT, width=1000, height=700, background_color="white",
                   colormap="tab10", prefer_horizontal=.95, max_words=120,
                   relative_scaling=.4).generate_from_frequencies(counts)
    ax.imshow(wc, interpolation="bilinear"); ax.set_title(title, fontsize=14); ax.axis("off")


def demo():
    assert tokens("젖병을 소독기에 넣었는데 냄새가 났어요") == ["젖병", "소독기", "냄새"]   # 활용형 제거
    assert tokens("먼지 세제 위생 소독기") == ["먼지", "세제", "위생", "소독기"]            # 명사는 안 잘림
    assert tokens("좋았습니다 해주시고 있어요 그냥") == []
    assert tokens("산후도우미님이 조리원생활 이모님께") == []      # 접미사 붙어도 제거
    assert tokens("소독기") == ["소독기"]                        # 부분일치 과잉 제거 없는지
    assert tokens("아기 빨래 세제") == ["빨래", "세제"]          # '아기'는 불용어
    assert tokens("abc 123 ㅋㅋ 물") == []                      # 한글 2자 미만·비한글 제외
    rows = [{"title": "젖병 소독", "summary": "", "text": "소독 소독 소독"},
            {"title": "빨래 냄새", "summary": "", "text": "소독 안했어요"},
            {"title": "침구 세탁", "summary": "", "text": ""}]
    f = freq(rows)
    assert f["소독"] == 2, f          # 한 글에서 4번 나와도 1표. 두 글에 걸쳐 있으니 2
    assert f["빨래"] == 1 and f["세탁"] == 1
    assert freq(rows, field="title")["소독"] == 1
    print("ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo(); sys.exit()
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager, rcParams
    font_manager.fontManager.addfont(FONT)
    rcParams["font.family"] = font_manager.FontProperties(fname=FONT).get_name()
    rcParams["axes.unicode_minus"] = False

    argv = sys.argv[1:]
    field = argv[argv.index("--field") + 1] if "--field" in argv else "all"
    cat = argv[argv.index("--cat") + 1] if "--cat" in argv else None
    f = next((a for a in argv if a.endswith(".jsonl")), str(sorted(RAW.glob("cafe_queries_*.jsonl"))[-1]))
    rows = [json.loads(l) for l in open(f, encoding="utf-8")]
    if "--questions" in argv:          # 후기글 제외, 질문글만 = 니즈 중심
        rows = [r for r in rows if is_question(r)]
        print(f"질문글만: {len(rows)}건", file=sys.stderr)
    OUT.mkdir(exist_ok=True)

    if cat == "all":
        fig, axes = plt.subplots(2, 3, figsize=(21, 10))
        for ax, c in zip(axes.flat, CATS):
            sub = [r for r in rows if c in tag(r)["cats"]]
            draw(ax, freq(sub, field), f"{c} ({len(sub)}건)")
        png = OUT / ("wordcloud_by_category_q.png" if "--questions" in argv else "wordcloud_by_category.png")
    else:
        sub = [r for r in rows if cat in tag(r)["cats"]] if cat else rows
        fig, ax = plt.subplots(figsize=(12, 8))
        draw(ax, freq(sub, field), f"{cat or '전체'} ({len(sub)}건, {field})")
        png = OUT / f"wordcloud_{cat or 'all'}{'_q' if '--questions' in argv else ''}.png"

    fig.tight_layout(); fig.savefig(png, dpi=130, bbox_inches="tight")
    print(f"저장: {png}")
    top = freq([r for r in rows if not cat or cat == 'all' or cat in tag(r)['cats']], field, 20)
    print("상위 20:", ", ".join(f"{k}({v})" for k, v in top.items()))
