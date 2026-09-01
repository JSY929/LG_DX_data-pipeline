# -*- coding: utf-8 -*-
"""
네이버 카페 키워드 크롤러 (범용/스킬용)

naver_cafe_pregnancy_crawler.py 의 검증된 로그인/목록/상세 파싱 로직을 재사용하되,
- URL / 키워드를 실행 인자로 받고
- 이모티콘 제거 + 광고성 글 필터링 전처리를 추가하고
- 크롤링 시도마다 폴더를 만들어 JSONL로만 저장 (CSV 변환은 하지 않음 - 나중에 AI에게
  "이 jsonl에서 어떤 컬럼으로 CSV 만들어줘" 라고 별도로 요청할 것)
- 이전 크롤링 결과들과 URL 기준으로 중복 제거

사용 예:
    python crawl.py --url "https://cafe.naver.com/f-e/cafes/10298136/menus/46" \
        --keywords "다이어트,식단" --max-pages 20

첫 실행은 로그인 창이 뜹니다(headless 불가). 로그인에 성공하면 쿠키가 저장되어
다음부터는 자동으로 headless 로 돌아갑니다.
"""
import argparse
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    StaleElementReferenceException,
    InvalidSessionIdException,
    WebDriverException,
)
from webdriver_manager.chrome import ChromeDriverManager

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# 고정 설정
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIE_FILE = os.path.join(SCRIPT_DIR, "naver_cookies.json")  # 로그인 세션은 스킬 폴더에 고정 저장 (여러 프로젝트에서 재사용)
DEBUG_HTML = os.path.join(SCRIPT_DIR, "naver_cafe_debug.html")

TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
DATE_RE = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})")

# 광고성 글 판별용 기본 키워드 (필요하면 --ad-keywords 로 추가 가능)
DEFAULT_AD_KEYWORDS = [
    "협찬", "원고료", "제공받아", "제공받았", "유료광고", "소정의 원고료",
    "체험단", "이 글은 업체로부터", "쿠팡파트너스", "제휴마케팅", "공동구매",
    "카톡문의", "카톡상담", "오픈채팅", "문의주세요", "dm주세요", "판매합니다",
    "수익이 발생", "광고 포함", "네이버페이 포인트",
]

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U0001F000-\U0001F0FF"
    "\U00002600-\U000026FF"
    "\U0001F1E6-\U0001F1FF"
    "←-⇿"
    "⬀-⯿"
    "️"
    "]+",
    flags=re.UNICODE,
)


# ---------------------------------------------------------------------------
# 전처리
# ---------------------------------------------------------------------------

def clean_text(text: str) -> str:
    """이모티콘 제거 + 공백 정리"""
    if not text:
        return ""
    text = EMOJI_PATTERN.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_ad_post(title: str, content: str, ad_keywords) -> bool:
    combined = f"{title}\n{content}".lower()
    return any(kw.lower() in combined for kw in ad_keywords)


def contains_any(text: str, keywords) -> bool:
    return any(kw in text for kw in keywords)


# ---------------------------------------------------------------------------
# 이전 크롤링 결과와 URL 기준 중복 제거
# ---------------------------------------------------------------------------

def load_seen_urls(output_base_dir: str) -> set:
    seen = set()
    if not os.path.isdir(output_base_dir):
        return seen
    for root, _dirs, files in os.walk(output_base_dir):
        for fname in files:
            if not fname.endswith(".jsonl"):
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        url = rec.get("링크")
                        if url:
                            seen.add(url)
            except OSError:
                continue
    return seen


# ---------------------------------------------------------------------------
# 날짜 파싱
# ---------------------------------------------------------------------------

def parse_list_date(text: str, today: date):
    text = (text or "").strip()
    if TIME_RE.match(text):
        return today, today.strftime("%Y.%m.%d")
    m = DATE_RE.search(text)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            d_obj = date(y, mo, d)
            return d_obj, d_obj.strftime("%Y.%m.%d")
        except ValueError:
            return None, text
    return None, text


# ---------------------------------------------------------------------------
# 브라우저 / 로그인
# ---------------------------------------------------------------------------

def build_driver(headless: bool):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1400,1000")
    options.add_argument("--lang=ko-KR")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def save_cookies(driver):
    cookies = driver.get_cookies()
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False)
    print(f"[로그인] 쿠키 저장 완료: {COOKIE_FILE}")


def load_cookies(driver) -> bool:
    if not os.path.exists(COOKIE_FILE):
        return False
    driver.get("https://www.naver.com")
    time.sleep(1)
    with open(COOKIE_FILE, "r", encoding="utf-8") as f:
        cookies = json.load(f)
    for c in cookies:
        c.pop("sameSite", None)
        try:
            driver.add_cookie(c)
        except Exception:
            pass
    return True


def is_logged_in(driver) -> bool:
    return "nid.naver.com" not in driver.current_url


def ensure_login(driver, cafe_url: str, headless: bool):
    load_cookies(driver)
    driver.get(cafe_url)
    time.sleep(2)

    if is_logged_in(driver):
        print("[로그인] 저장된 쿠키로 로그인 확인됨.")
        return

    if headless:
        raise RuntimeError(
            "로그인이 필요합니다. --headless 없이 한 번 실행해서 "
            "브라우저 창에서 수동으로 로그인한 뒤 다시 시도해주세요."
        )

    print("[로그인] 저장된 세션이 없습니다. 브라우저 창에서 직접 로그인해주세요.")
    login_url = "https://nid.naver.com/nidlogin.login?url=" + cafe_url
    driver.get(login_url)

    timeout = 300
    waited = 0
    while not is_logged_in(driver) and waited < timeout:
        time.sleep(2)
        waited += 2
        if waited % 20 == 0:
            print(f"[로그인] 로그인 대기 중... ({waited}s / {timeout}s)")

    if not is_logged_in(driver):
        raise RuntimeError("로그인 대기 시간이 초과되었습니다. 다시 실행해주세요.")

    driver.get(cafe_url)
    time.sleep(2)
    save_cookies(driver)


# ---------------------------------------------------------------------------
# 목록 페이지 파싱
# ---------------------------------------------------------------------------

def is_notice_row(tr) -> bool:
    """상단 고정 공지글(체험단 모집 등 광고성 고정글) 여부"""
    try:
        tr.find_element(By.XPATH, ".//*[normalize-space(text())='공지']")
        return True
    except NoSuchElementException:
        return False


def get_list_rows(driver):
    rows = []
    trs = driver.find_elements(By.CSS_SELECTOR, "tr")
    for tr in trs:
        try:
            title_el = tr.find_element(By.CSS_SELECTOR, "a.article")
        except NoSuchElementException:
            continue

        if is_notice_row(tr):
            continue

        try:
            date_el = tr.find_element(By.CSS_SELECTOR, "td.td_normal.type_date")
            date_text = date_el.text.strip()
        except NoSuchElementException:
            date_text = ""

        title = title_el.text.strip()
        href = title_el.get_attribute("href")
        if not title or not href:
            continue
        rows.append((title, href, date_text))
    return rows


def get_current_page_number(driver):
    try:
        btn = driver.find_element(By.CSS_SELECTOR, "button.btn.number[aria-pressed='true']")
        return int(btn.text.strip())
    except Exception:
        return None


def goto_next_page(driver, current_page: int) -> bool:
    target = current_page + 1
    buttons = driver.find_elements(By.CSS_SELECTOR, "button.btn.number")
    for b in buttons:
        if b.text.strip() == str(target):
            b.click()
            time.sleep(1.5)
            return True

    next_group_candidates = driver.find_elements(
        By.CSS_SELECTOR, "button.btn.next, button[aria-label*='다음'], a.btn.next"
    )
    for b in next_group_candidates:
        try:
            if b.is_enabled() and b.is_displayed():
                b.click()
                time.sleep(1.5)
                buttons = driver.find_elements(By.CSS_SELECTOR, "button.btn.number")
                for b2 in buttons:
                    if b2.text.strip() == str(target):
                        b2.click()
                        time.sleep(1.5)
                        return True
        except Exception:
            continue

    with open(DEBUG_HTML, "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print(f"[페이지네이션] {target}페이지 버튼을 찾지 못했습니다. "
          f"디버그 HTML 저장: {DEBUG_HTML}")
    return False


# ---------------------------------------------------------------------------
# 상세 페이지 파싱
# ---------------------------------------------------------------------------

CONTENT_SELECTORS = [
    "div.se-main-container",
    "div.ContentRenderer",
    "div.article_container .content",
    "#app .content_view",
]

VIEW_COUNT_SELECTORS = [
    ".ArticleInfoView .count",
    "span.count",
    ".article_info .count",
]


def extract_content(driver) -> str:
    for sel in CONTENT_SELECTORS:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            text = el.text.strip()
            if text:
                return text
        except NoSuchElementException:
            continue
    return ""


def extract_view_count(driver) -> str:
    for sel in VIEW_COUNT_SELECTORS:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            text = el.text.strip()
            if text:
                return re.sub(r"[^\d,]", "", text) or text
        except NoSuchElementException:
            continue
    m = re.search(r"조회\s*([\d,]+)", driver.page_source)
    if m:
        return m.group(1)
    return ""


def expand_comments(driver):
    for _ in range(30):
        try:
            more_btns = driver.find_elements(By.XPATH, "//*[contains(text(), '더보기')]")
            clicked = False
            for b in more_btns:
                if b.is_displayed() and b.is_enabled():
                    try:
                        driver.execute_script("arguments[0].click();", b)
                        clicked = True
                        time.sleep(0.6)
                    except Exception:
                        pass
            if not clicked:
                break
        except StaleElementReferenceException:
            break


def extract_comments(driver):
    count_text = ""
    try:
        count_el = driver.find_element(By.CSS_SELECTOR, "a.button_comment strong.num")
        count_text = count_el.text.strip()
    except NoSuchElementException:
        pass

    expand_comments(driver)

    comments = []
    for el in driver.find_elements(By.CSS_SELECTOR, "span.text_comment"):
        txt = el.text.strip()
        if txt:
            comments.append(txt)

    if count_text:
        return f"{count_text}개 | " + " / ".join(comments)
    return " / ".join(comments)


def scrape_detail(driver, url: str, detail_handle: str, list_handle: str):
    result = {"content": "", "view_count": "", "comment_field": ""}
    driver.switch_to.window(detail_handle)
    try:
        driver.get(url)
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(1.5)
        result["content"] = extract_content(driver)
        result["view_count"] = extract_view_count(driver)
        result["comment_field"] = extract_comments(driver)
    except TimeoutException:
        print(f"  [경고] 상세 페이지 로딩 타임아웃: {url}")
    finally:
        driver.switch_to.window(list_handle)
    return result


# ---------------------------------------------------------------------------
# 메인 크롤링 루프
# ---------------------------------------------------------------------------

def append_jsonl(jsonl_path: str, record: dict):
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def crawl(driver, args, jsonl_path: str, seen_urls: set):
    today = date.today()
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date() if args.start_date else None
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date() if args.end_date else None
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    ad_keywords = list(DEFAULT_AD_KEYWORDS)
    if args.ad_keywords:
        ad_keywords += [k.strip() for k in args.ad_keywords.split(",") if k.strip()]

    saved_count = 0
    skipped_dup = 0
    skipped_ad = 0

    driver.get(args.url)
    time.sleep(2)
    list_handle = driver.current_window_handle

    driver.execute_script("window.open('about:blank');")
    detail_handle = [h for h in driver.window_handles if h != list_handle][0]

    page = get_current_page_number(driver) or 1
    stop_all = False
    seen_valid_row = False
    old_skip_streak = 0
    MAX_OLD_SKIP_STREAK = 30

    try:
        while not stop_all and page <= args.max_pages:
            print(f"\n[목록] {page}페이지 확인 중...")
            rows = get_list_rows(driver)
            if not rows:
                print("  더 이상 게시글이 없습니다.")
                break

            for title, href, date_text in rows:
                post_date, date_str = parse_list_date(date_text, today)

                if start_date is not None:
                    if post_date and post_date < start_date:
                        if not seen_valid_row:
                            old_skip_streak += 1
                            if old_skip_streak >= MAX_OLD_SKIP_STREAK:
                                print("  옛날 글이 너무 많이 이어져 안전하게 크롤링을 종료합니다.")
                                stop_all = True
                                break
                            continue
                        print(f"  날짜 범위 이전 글 도달 ({date_str}) -> 크롤링 종료")
                        stop_all = True
                        break
                    if end_date is not None and (post_date is None or post_date > end_date):
                        continue

                seen_valid_row = True
                old_skip_streak = 0

                if href in seen_urls:
                    skipped_dup += 1
                    continue
                seen_urls.add(href)

                print(f"  확인: {title[:40]} ({date_str})")

                try:
                    detail = scrape_detail(driver, href, detail_handle, list_handle)
                except (InvalidSessionIdException, WebDriverException) as e:
                    print(f"  [치명적 오류] 브라우저 세션이 끊어졌습니다. 지금까지 모은 결과만 저장합니다: {e}")
                    stop_all = True
                    break
                except Exception as e:
                    print(f"  [오류] 상세 페이지 처리 실패: {e}")
                    continue

                content = clean_text(detail["content"])
                title_clean = clean_text(title)

                if keywords and not contains_any(f"{title_clean} {content}", keywords):
                    continue

                if is_ad_post(title_clean, content, ad_keywords):
                    skipped_ad += 1
                    if not args.keep_ads:
                        continue

                record = {
                    "제목": title_clean,
                    "링크": href,
                    "본문": content,
                    "조회수": detail["view_count"],
                    "작성일": date_str,
                    "댓글": detail["comment_field"],
                    "검색키워드": keywords,
                    "광고의심": is_ad_post(title_clean, content, ad_keywords),
                    "수집일시": datetime.now().isoformat(timespec="seconds"),
                }
                append_jsonl(jsonl_path, record)
                saved_count += 1
                time.sleep(0.8)

            if stop_all:
                break

            try:
                if not goto_next_page(driver, page):
                    break
            except (InvalidSessionIdException, WebDriverException) as e:
                print(f"  [치명적 오류] 페이지 이동 중 세션이 끊어졌습니다. 지금까지 모은 결과만 저장합니다: {e}")
                break
            page += 1
    except (InvalidSessionIdException, WebDriverException) as e:
        print(f"[치명적 오류] 브라우저 세션이 끊어졌습니다. 지금까지 모은 결과만 저장합니다: {e}")

    return saved_count, skipped_dup, skipped_ad


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="네이버 카페 키워드 크롤러")
    p.add_argument("--url", required=True, help="크롤링할 카페 게시판/메뉴 URL")
    p.add_argument("--keywords", required=True, help="쉼표로 구분된 검색 키워드 (제목+본문 중 하나라도 포함하면 저장)")
    p.add_argument("--start-date", default=None, help="YYYY-MM-DD (미지정 시 날짜 필터 없음)")
    p.add_argument("--end-date", default=None, help="YYYY-MM-DD (미지정 시 오늘까지)")
    p.add_argument("--max-pages", type=int, default=50, help="최대 목록 페이지 수 (기본 50)")
    p.add_argument("--headless", action="store_true", help="강제로 headless 모드 사용 (로그인 세션 있을 때만 가능)")
    p.add_argument("--visible", action="store_true", help="쿠키가 있어도 강제로 브라우저 창을 띄움 (재로그인용)")
    p.add_argument("--ad-keywords", default=None, help="기본 광고 판별 키워드에 추가할 쉼표 구분 키워드")
    p.add_argument("--keep-ads", action="store_true", help="광고로 의심되는 글도 저장 (광고의심 필드로 표시만 함)")
    p.add_argument("--output-dir", default=None, help="결과 저장 base 폴더 (기본: 실행 위치/crawl_results)")
    return p.parse_args()


def main():
    args = parse_args()

    output_base = args.output_dir or os.path.join(os.getcwd(), "crawl_results")
    os.makedirs(output_base, exist_ok=True)

    run_id = time.strftime("%Y%m%d_%H%M%S")
    keyword_slug = re.sub(r"[^0-9A-Za-z가-힣]+", "_", args.keywords)[:40].strip("_") or "run"
    run_dir = os.path.join(output_base, f"{keyword_slug}_{run_id}")
    os.makedirs(run_dir, exist_ok=True)
    jsonl_path = os.path.join(run_dir, "results.jsonl")

    print(f"[실행 폴더] {run_dir}")

    seen_urls = load_seen_urls(output_base)
    print(f"[중복 제거] 이전 크롤링 결과에서 URL {len(seen_urls)}건 확인됨. 동일 URL은 건너뜁니다.")

    default_headless = os.path.exists(COOKIE_FILE) and not args.visible
    headless = args.headless if args.headless else default_headless

    driver = build_driver(headless)
    saved_count = skipped_dup = skipped_ad = 0
    try:
        ensure_login(driver, args.url, headless)
        saved_count, skipped_dup, skipped_ad = crawl(driver, args, jsonl_path, seen_urls)
    except Exception as e:
        print(f"[치명적 오류] {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

        meta = {
            "url": args.url,
            "keywords": args.keywords,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "saved_count": saved_count,
            "skipped_duplicate": skipped_dup,
            "skipped_ad_suspected": skipped_ad,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        }
        with open(os.path.join(run_dir, "run_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        print(f"\n[완료] 저장 {saved_count}건 / 중복 제외 {skipped_dup}건 / 광고의심 {skipped_ad}건")
        print(f"[JSONL] {jsonl_path}")
        print("CSV로 변환하려면 이 jsonl 파일을 놓고 AI에게 '어떤 컬럼으로 CSV 만들어줘'라고 별도로 요청하세요.")


if __name__ == "__main__":
    main()
