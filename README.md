# TrendNews

[TrendBoard](https://github.com/shiner4g/TrendBoard)의 뉴스 버전입니다. 국내 주요
언론사 10곳(연합뉴스 · 조선일보 · 중앙일보 · 한겨레 · 경향신문 · YTN · SBS · KBS ·
MBC · JTBC)의 "많이 본 뉴스" TOP5를 한 화면에 모아 보여줍니다.

## 🔗 https://shiner4g.github.io/TrendNews/

- GitHub Pages + GitHub Actions로 동작합니다 (TrendBoard와 동일한 구조). PC/모바일
  어디서나 그냥 웹사이트로 열립니다.
- 매시 13분에 GitHub Actions가 `crawl.py`를 실행해서 새로 갱신합니다.
- 데이터 출처: 네이버뉴스 랭킹 페이지
  (`https://news.naver.com/main/ranking/popularDay.naver`) 딱 하나입니다. 이 페이지가
  언론사별로 TOP5를 이미 매겨서 보여주기 때문에, TrendBoard처럼 저희가 조회수로
  다시 정렬할 필요가 없습니다 (애초에 이 페이지는 실제 조회수 숫자를 공개하지
  않습니다). 대신 각 기사 옆 뱃지에는 "N시간전" 같은 상대 시각이 표시됩니다.
- 이 페이지는 **EUC-KR 인코딩**으로 내려옵니다 - `crawl.py`에서 `encoding="euc-kr"`로
  읽는 이유입니다. (UTF-8로 읽으면 한글이 깨집니다.)
- 카드 드래그로 순서 변경, 카드별/전체 접기·펼치기, 글자 크기 조절 등
  TrendBoard와 동일한 UI 기능을 그대로 가져왔습니다.
- 특정 언론사 랭킹을 그 회차에 못 가져오면 직전 성공 데이터로 대체되고
  "· 캐시"라고 표시됩니다.
- 언론사 목록/개수를 바꾸려면 `crawl.py` 상단의 `PRESS_LIST`를 수정하세요. 언론사
  ID는 네이버뉴스 고정 `press_id`입니다 (오랫동안 안 바뀜).

## 참고

- 개인적 용도로만 사용하세요.
- GitHub Actions의 예약 실행은 저장소가 60일 이상 활동이 없으면 자동으로 꺼질 수
  있습니다 (GitHub 정책). 그럴 땐 저장소의 Actions 탭에서 다시 켜면 됩니다.
- TrendBoard와 마찬가지로, GitHub의 스케줄 cron은 "best-effort"라 정시에 요청이
  몰리면 지연될 수 있어서 어중간한 분(13분)으로 맞춰뒀습니다.
