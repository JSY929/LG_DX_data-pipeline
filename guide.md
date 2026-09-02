# 실행 가이드

## 환경 설정

Python 3.10 환경에서 Jupyter와 다음 패키지가 필요합니다.

```powershell
pip install jupyter pandas beautifulsoup4 selenium
```

Chrome 브라우저와 현재 Chrome 버전에 맞는 Selenium 실행 환경도 필요합니다. 노트북의 `CHROME_PROFILE_PATH`는 기본적으로 `C:\selenium_profile\naver_cafe`를 사용합니다. 해당 위치를 사용할 수 없다면 쓰기 가능한 전용 경로로 변경하세요.

## 실행 방법

1. Jupyter에서 `cafe_keyword.ipynb`를 엽니다.
2. 첫 번째 패키지 설치 셀을 실행합니다. 이미 설치된 패키지는 그대로 유지됩니다.
3. 패키지를 처음 설치했다면 필요에 따라 Jupyter 커널을 다시 시작합니다.
4. 카페 ID, 검색 기간, 최대 페이지 수, Chrome 프로필 경로를 확인합니다.
5. 크롤링 코드 셀을 실행합니다.
6. 처음 실행할 때 열린 Chrome 창에서 네이버에 로그인하고, 콘솔에서 Enter를 누릅니다.
7. 결과는 `crawling_results` 폴더에 CSV, PKL, JSONL로 저장됩니다.

저장 결과에는 `cafe_name`, `cafe_id`, `menu_id`, `matched_keywords`, `date`, `title`, `content`, `comments`, `url` 컬럼만 포함됩니다. 담당자 정보와 댓글 개수 컬럼은 저장하지 않습니다.

`cafe_keyword.ipynb`는 `PREGNANT_KEYWORDS`와 `MANAGEMENT_KEYWORDS`의 모든 조합을 `임산부키워드 관리키워드` 형태로 생성하고 전체게시판 ID `0`에서 검색합니다.

## 예외 및 주의사항

- 검색 조합이 320개이고 조합마다 최대 20페이지를 확인하므로 실행 시간이 길고 네이버 접근 제한이 발생할 수 있습니다. 필요하면 `MAX_PAGE`, `LIST_WAIT`, `ARTICLE_WAIT`를 보수적으로 조정하세요.
- 로그인 세션이 만료되거나 접근 제한 문구가 감지되면 수집이 중단됩니다. 재로그인 후 다시 실행하세요.
- 네이버 카페 화면 구조가 변경되면 `.article`, `.title_text`, `.date`, 댓글 및 본문 CSS 선택자를 수정해야 할 수 있습니다.
- 카페 가입 상태나 게시글 권한에 따라 일부 글은 수집되지 않을 수 있습니다.
- 서비스 이용약관과 개인정보 보호 기준을 준수하고, 수집 데이터의 이용 권한을 확인하세요.
