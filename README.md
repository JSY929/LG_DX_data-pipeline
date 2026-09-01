# LG_DX_data-pipeline

네이버 카페 게시글을 검색어와 기간 기준으로 수집해 CSV, PKL, JSONL 형식으로 저장하는 데이터 수집 프로젝트입니다.

## 주요 노트북

- `cafe_crwaler.ipynb`: 기존 게시판·키워드 기반 카페 수집 노트북
- `cafe_keyword.ipynb`: 전체게시판(게시판 ID 0)에서 임산부 키워드 8개와 위생관리 행동 키워드 40개를 조합한 320개 검색어로 게시글을 수집하는 노트북. 첫 번째 셀에서 필수 Python 패키지를 설치할 수 있습니다.

수집한 게시글은 URL 기준으로 중복 제거되며, 여러 검색어에 노출된 게시글은 `matched_keywords`에 검색어가 `|` 구분자로 함께 기록됩니다. 결과 컬럼은 `cafe_name`, `cafe_id`, `menu_id`, `matched_keywords`, `date`, `title`, `content`, `comments`, `url`만 사용합니다. 실행 환경 설정과 주의사항은 `guide.md`를 참고하세요.
