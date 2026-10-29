#!/usr/bin/env python3
# TrendNews crawler + page builder — run by .github/workflows/update.yml
# TrendBoard(커뮤니티 버전)의 뉴스 버전. 국내 언론사 9곳의 기사를 분야별
# (주요뉴스/정치/경제/사회/생활/세계/IT/칼럼/랭킹)로 골라 볼 수 있게 한 화면에 모아 보여줌.
#
# 데이터 출처는 네이버 언론사 개별 홈(media.naver.com/press/<press_id>)의 탭들임:
#  - 주요뉴스: 홈(/press/<id>), 분야: /press/<id>?sid=100.. , 랭킹: /press/<id>/ranking
#  - 분야 탭은 언론사마다 달라서(예: MBC는 IT/칼럼 없음) 홈의 탭 목록으로 먼저 확인함.
#  - 랭킹 말고 분야 탭들은 원래 "그냥 최신글"이라서, 네이버가 댓글 수를 채워넣을 때 쓰는
#    API(POST media.naver.com/commonComment/listCount)로 댓글 수를 받아 댓글 많은 순으로 정렬함.
# 랭킹 탭 데이터 출처 상세: (https://media.naver.com/press/<press_id>/ranking?type=popular). 네이버뉴스
# 메인 랭킹 페이지(news.naver.com/main/ranking/popularDay.naver)는 언론사당 TOP5만
# 주고 실제 조회수 숫자도 공개를 안 해서(2026-10-18 최초 버전에서 썼다가 발견한
# 한계), 언론사별 단독 페이지(media.naver.com)로 바꿈 - 이쪽은 TOP10 + 실제 조회수
# 숫자를 줌. 이 페이지는 UTF-8이고(메인 랭킹 페이지는 EUC-KR이었음), 언론사마다
# 따로 요청해야 해서 요청 수는 늘었지만(언론사 수만큼), 데이터 품질이 훨씬 좋음.

import urllib.request
import urllib.parse
import re
import html
import json
import datetime
import os
import time

TOP_N = 10
OUT_PATH = "index.html"


def fetch(url, encoding, method="GET", data=None, extra_headers=None):
    parsed = urllib.parse.urlsplit(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Referer": referer,
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if extra_headers:
        headers.update(extra_headers)
    body = data.encode("utf-8") if isinstance(data, str) else data
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
    return raw.decode(encoding, errors="replace")


def decode_entities(s):
    return html.unescape(s)


def strip_tags(s):
    return decode_entities(re.sub(r"<[^>]+>", "", s)).strip()


def parse_naver_press(h):
    # 언론사 단독 랭킹 페이지엔 탭(많이 본/댓글 많은/섹션별)마다
    # <div class="press_ranking_box">가 여러 개 들어있는데, "많이 본 랭킹"이라는
    # 제목을 가진 블록이 두 개 있음 - 그중 처음 것만 실제 서버 렌더링 데이터이고,
    # 나중 것은 "{{title}}" 같은 placeholder만 든 JS 템플릿(탭 전환용)이라
    # 비어있음. 그래서 첫 "많이 본 랭킹" 타이틀 뒤의 <ul class="press_ranking_list">
    # 안에서만 추출함.
    idx = h.find(">많이 본 랭킹<")
    if idx == -1:
        return []
    ul_start = h.find('<ul class="press_ranking_list">', idx)
    if ul_start == -1:
        return []
    ul_end = h.find("</ul>", ul_start)
    section = h[ul_start:ul_end] if ul_end != -1 else h[ul_start : ul_start + 20000]
    posts = []
    # 언론사마다 조회수 공개 여부가 다름(일부는 숫자를 아예 안 보여줌) - 그래서
    # 조회수는 있으면 쓰고 없으면 None으로 둠(0으로 잘못 표시하지 않기 위해).
    # 어차피 리스트 자체가 이미 네이버가 매긴 순위(1~10위) 순서라서, 조회수 숫자가
    # 없어도 순서 자체는 정확함.
    for chunk in section.split('<li class="as_thumb">')[1:]:
        url_m = re.search(r'<a href="(https://n\.news\.naver\.com/article/[^"]+)" class="_es_pc_link"', chunk)
        title_m = re.search(r'<strong class="list_title">([\s\S]*?)</strong>', chunk)
        if not url_m or not title_m:
            continue
        views = None
        view_m = re.search(r'<span class="list_view">\s*<span class="blind">조회수</span>\s*([\d,]+)', chunk)
        if view_m:
            views = int(view_m.group(1).replace(",", ""))
        posts.append(
            {
                "title": strip_tags(title_m.group(1)),
                "url": decode_entities(url_m.group(1)),
                "comments": 0,
                "views": views,
            }
        )
    return posts


def parse_press_edit(h):
    # 언론사 홈(주요뉴스)과 분야 탭(정치/경제/...)은 같은 press_edit_news_* 마크업을 씀.
    # 조회수는 없고 "1시간전" 같은 상대 시각만 있어서 time 필드로 넘김.
    posts = []
    for chunk in h.split('<li class="press_edit_news_item')[1:]:
        url_m = re.search(r'<a href="(https://n\.news\.naver\.com/article/[^"]+)" class="press_edit_news_link', chunk)
        title_m = re.search(r'<span class="press_edit_news_title">([\s\S]*?)</span>', chunk)
        if not url_m or not title_m:
            continue
        time_m = re.search(r'<b>([^<]*)</b>', chunk[:3000])
        posts.append(
            {
                "title": strip_tags(title_m.group(1)),
                "url": decode_entities(url_m.group(1)),
                "views": None,
                "time": time_m.group(1).strip() if time_m else None,
            }
        )
    return posts


def parse_press_main(h):
    # 주요뉴스 = 언론사 홈의 처음 두 press_edit_news_list(편집 헤드라인 6개 + "뉴스 더 보기" 6개).
    # 그 뒤로 나오는 리스트들은 분야별 목록이 반복되는 것들이라 쓰지 않음.
    parts = h.split('<ul class="press_edit_news_list')
    posts = []
    for part in parts[1:3]:
        end = part.find("</ul>")
        posts.extend(parse_press_edit(part[:end] if end != -1 else part))
    return posts


def parse_press_tabs(h):
    # 이 언론사가 가진 분야 탭(sid) 목록 - 없는 분야(예: MBC의 IT/칼럼)는 요청하면 302로
    # 홈으로 돌려보내서, 그걸 분야 데이터로 착각하지 않도록 탭 목록으로 먼저 확인함.
    tabs = set(re.findall(r'href="/press/\d+\?sid=(\d+)"', h))
    # 신문사(지면)가 있는 언론사만 "신문보기" 탭이 있음 (MBC/연합뉴스/시사IN은 없음)
    if re.search(r'href="/press/\d+/newspaper"', h):
        tabs.add("newspaper")
    return tabs


def parse_newspaper(h):
    # 신문보기 페이지는 면(A1, A2, ...)마다 <div class="newspaper_wrp"> 블록이 하나씩이고
    # 그 안에 그 면의 기사들이 <li>로 들어있음. 기사가 있는 면만 나와서 번호가 띄엄띄엄함
    # (예: 1,2,3,4,5,6,8,10 - 7면과 9면은 빠짐). 그래서 "1~3면" 필터는 목록 순서가 아니라
    # 면 번호 자체로 걸어야 하고, 매일경제(A/B/C 섹션)·중앙일보(A/E 섹션)처럼 섹션이
    # 나뉜 신문은 첫 섹션(A)만 "본지"로 취급해서 B1/C1 같은 게 1면으로 잡히지 않게 함.
    posts = []
    seen = set()
    first_sec = None
    # 주의: 한겨레/한국일보/매일경제/전자신문은 1면 블록만 class가 "newspaper_wrp type_main"이라서
    # (경향/중앙은 "newspaper_wrp" 그대로) class 전체를 정확히 맞추면 1면이 통째로 빠짐.
    for block in re.split(r'<div class="newspaper_wrp[^"]*">', h)[1:]:
        lab_m = re.search(r'<span class="page_notation"><em>([^<]*)</em>', block)
        if not lab_m:
            continue
        label = lab_m.group(1).strip()
        sm = re.match(r"^([A-Za-z]*)(\d+)$", label)
        if not sm:
            continue
        sec, num = sm.group(1), int(sm.group(2))
        if first_sec is None:
            first_sec = sec
        for li in block.split("<li>")[1:]:
            url_m = re.search(r'<a\s[^>]*href="(https://n\.news\.naver\.com/article/newspaper/[^"]+)"', li)
            title_m = re.search(r"<strong>([\s\S]*?)</strong>", li)
            if not url_m or not title_m:
                continue
            url = decode_entities(url_m.group(1))
            if url in seen:
                continue
            seen.add(url)
            posts.append(
                {
                    "title": strip_tags(title_m.group(1)),
                    "url": url,
                    "page": label,
                    "pageNo": num,
                    "main": sec == first_sec,
                }
            )
    return posts


# 분야 탭: (키, 표시 이름, 네이버 sid). main/ranking/newspaper는 sid 없는 특수 탭.
CATEGORIES = [
    ("main", "주요뉴스"),
    ("100", "정치"),
    ("101", "경제"),
    ("102", "사회"),
    ("103", "생활"),
    ("104", "세계"),
    ("105", "IT"),
    ("110", "칼럼"),
    ("newspaper", "지면"),
    ("ranking", "랭킹"),
]

# 언론사 ID는 네이버뉴스의 고정 press_id (수년간 안 바뀜). 통신사/방송/종합지/경제지/
# 시사주간지/IT전문지를 섞어서 특정 성향에 치우치지 않도록 구성함.
PRESS_LIST = [
    ("MBC", "214"),
    ("연합뉴스", "001"),
    ("경향신문", "032"),
    ("한겨레", "028"),
    ("한국일보", "469"),
    ("매일경제", "009"),
    ("중앙일보", "025"),
    ("시사IN", "308"),
    ("전자신문", "030"),
]

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TrendNews</title>
<style>
  :root { --bg: #f4f5f7; --card-bg: #ffffff; --border: #e3e5e8; --text: #222; --text-sub: #888; --accent: #3b82f6; --badge-bg: #eef2ff; --post-size: 16px; }
  :root[data-theme="dark"] { --bg: #16181d; --card-bg: #1f2228; --border: #2c2f36; --text: #e6e6e6; --text-sub: #8a8f98; --accent: #6ea8fe; --badge-bg: #1d2740; }
  @media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg: #16181d; --card-bg: #1f2228; --border: #2c2f36; --text: #e6e6e6; --text-sub: #8a8f98; --accent: #6ea8fe; --badge-bg: #1d2740; } }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 24px 16px 60px; background: var(--bg); color: var(--text); font-family: "Malgun Gothic", "Apple SD Gothic Neo", "Segoe UI", sans-serif; }
  header { max-width: 1620px; margin: 0 auto 24px; }
  .header-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  header h1 { margin: 0; font-size: 20px; letter-spacing: -0.5px; }
  .header-icons { display: flex; gap: 8px; flex: 0 0 auto; }
  .icon-btn { border: 1px solid var(--border); background: var(--card-bg); color: var(--text); border-radius: 6px; width: 34px; height: 34px; padding: 0; display: inline-flex; align-items: center; justify-content: center; font-size: 18px; line-height: 1; cursor: pointer; }
  .icon-btn:hover { border-color: var(--accent); color: var(--accent); }
  .updated { font-size: 15px; color: var(--text-sub); text-align: center; margin-top: 8px; }
  .icon-btn.active { border-color: var(--accent); color: var(--accent); }
  .icon-btn.text-btn { width: auto; padding: 0 10px; font-size: 13px; font-weight: 700; white-space: nowrap; }
  .top-panel { max-width: 1620px; margin: 10px auto 0; background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; }
  .top-panel[hidden] { display: none; }
  .top-list { display: flex; flex-wrap: wrap; gap: 6px 8px; }
  .top-chip { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--border); background: var(--bg); color: var(--text); border-radius: 14px; padding: 4px 11px 4px 8px; font-size: 14px; line-height: 1.4; cursor: pointer; font-family: inherit; }
  .top-chip:hover { border-color: var(--accent); color: var(--accent); }
  .top-chip.active { background: var(--accent); border-color: var(--accent); color: #fff; }
  .tk-rank { font-size: 12px; font-weight: 700; color: var(--accent); min-width: 14px; text-align: center; font-variant-numeric: tabular-nums; }
  .top-chip.active .tk-rank { color: #fff; }
  .tk-word { font-weight: 700; }
  .tk-cnt { font-size: 12px; opacity: 0.7; font-variant-numeric: tabular-nums; }
  .search-bar { max-width: 1620px; margin: 10px auto 0; display: flex; align-items: center; gap: 8px; }
  .search-bar[hidden] { display: none; }
  .search-bar input { flex: 1 1 auto; min-width: 0; border: 1px solid var(--border); background: var(--card-bg); color: var(--text); border-radius: 8px; padding: 8px 12px; font-size: 16px; font-family: inherit; }
  .search-bar input:focus { outline: 2px solid var(--accent); outline-offset: -1px; border-color: var(--accent); }
  .search-close { flex: 0 0 auto; border: 1px solid var(--border); background: var(--card-bg); color: var(--text-sub); border-radius: 8px; width: 36px; height: 36px; font-size: 15px; cursor: pointer; }
  .search-close:hover { border-color: var(--accent); color: var(--accent); }
  .search-results { max-width: 1620px; margin: 16px auto 0; }
  .search-results[hidden], .grid[hidden], .category-bar[hidden] { display: none; }
  .search-head { cursor: default; }
  .search-head:hover { background: color-mix(in srgb, var(--card-bg) 92%, var(--text)); }
  .sr-src { flex: 0 0 auto; max-width: 32%; display: flex; flex-direction: column; font-size: 12px; line-height: 1.4; color: var(--text-sub); }
  .sr-outlet { font-weight: 700; color: var(--text); }
  .post-title mark { background: color-mix(in srgb, var(--accent) 28%, transparent); color: inherit; border-radius: 2px; padding: 0 1px; }
  .category-bar { max-width: 1620px; margin: 12px auto 0; display: flex; flex-direction: column; gap: 5px; }
  .category-row { display: flex; flex-wrap: wrap; gap: 5px 10px; }
  .category-btn { flex: 0 0 auto; border: 1px solid var(--border); background: var(--card-bg); color: var(--text); border-radius: 12px; padding: 3px 10px; font-size: 14px; line-height: 1.4; cursor: pointer; white-space: nowrap; }
  .category-btn:hover { border-color: var(--accent); color: var(--accent); }
  .category-btn.active { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 700; }
  .grid { max-width: 1620px; margin: 24px auto 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(520px, 100%), 1fr)); gap: 18px; }
  @keyframes slideFromRight { from { opacity: 0; transform: translateX(28px); } to { opacity: 1; transform: none; } }
  @keyframes slideFromLeft { from { opacity: 0; transform: translateX(-28px); } to { opacity: 1; transform: none; } }
  .grid.slide-from-right { animation: slideFromRight 0.2s ease-out; }
  .grid.slide-from-left { animation: slideFromLeft 0.2s ease-out; }
  @media (prefers-reduced-motion: reduce) { .grid.slide-from-right, .grid.slide-from-left { animation: none; } }
  .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; display: flex; flex-direction: column; transition: opacity 0.15s, border-color 0.15s; }
  .card.dragging { opacity: 0.4; }
  .card.drag-over { border-color: var(--accent); }
  .card-header { padding: 14px 16px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 8px; background: color-mix(in srgb, var(--card-bg) 92%, var(--text)); cursor: pointer; }
  .card-header:hover { background: color-mix(in srgb, var(--card-bg) 85%, var(--text)); }
  .card-header:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .drag-handle { flex: 0 0 auto; color: var(--text-sub); font-size: 16px; letter-spacing: -1px; user-select: none; cursor: grab; touch-action: none; }
  .drag-handle:active { cursor: grabbing; }
  .card-header .title { font-weight: 700; font-size: 18px; color: var(--text); text-decoration: none; }
  .card-header a.title:hover { color: var(--accent); text-decoration: underline; }
  .card-header a.title:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 2px; }
  .card-header .board { margin-left: auto; font-size: 15px; color: var(--text-sub); }
  .toggle-icon { flex: 0 0 auto; color: var(--text-sub); font-size: 14px; padding: 2px 4px; line-height: 1; }
  .card.collapsed .post-list, .card.collapsed .empty-note { display: none; }
  ol.post-list { list-style: none; margin: 0; padding: 6px 0; }
  ol.post-list li { display: flex; align-items: baseline; gap: 8px; padding: 9px 16px; border-bottom: 1px dashed var(--border); }
  ol.post-list li:last-child { border-bottom: none; }
  .post-title { flex: 1 1 auto; font-size: var(--post-size); color: var(--text); text-decoration: none; line-height: 1.4; white-space: normal; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; }
  .paper-filter { max-width: 1620px; margin: 8px auto 0; display: flex; flex-wrap: wrap; align-items: center; gap: 5px 8px; }
  .paper-filter[hidden] { display: none; }
  .paper-btn { border: 1px solid var(--border); background: var(--card-bg); color: var(--text); border-radius: 12px; padding: 2px 10px; font-size: 13px; line-height: 1.4; cursor: pointer; white-space: nowrap; }
  .paper-btn:hover { border-color: var(--accent); color: var(--accent); }
  .paper-btn.active { border-color: var(--accent); color: var(--accent); font-weight: 700; }
  .post-title:hover { color: var(--accent); text-decoration: underline; }
  .post-title:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 2px; }
  .views { flex: 0 0 auto; font-size: calc(var(--post-size) - 2px); color: var(--accent); background: var(--badge-bg); border-radius: 10px; padding: 1px 7px; font-weight: 600; min-width: 20px; text-align: center; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .empty-note { padding: 24px 16px; color: var(--text-sub); font-size: 16px; text-align: center; }
  footer { max-width: 1620px; margin: 36px auto 0; text-align: center; }
  .controls { display: flex; justify-content: center; align-items: center; gap: 16px; flex-wrap: wrap; margin-top: 10px; }
  .controls button { border: 1px solid var(--border); background: var(--card-bg); color: var(--text); border-radius: 6px; padding: 5px 14px; font-size: 14px; cursor: pointer; }
  .controls button:hover { border-color: var(--accent); color: var(--accent); }
  .font-controls, .count-controls { display: inline-flex; align-items: center; gap: 6px; }
  .font-controls button, .count-controls button { padding: 5px 12px; line-height: 1.4; }
  #fontSizeLabel { min-width: 44px; display: inline-block; text-align: center; font-size: 14px; color: var(--text-sub); font-variant-numeric: tabular-nums; }
  #postCountLabel { min-width: 20px; display: inline-block; text-align: center; font-size: 14px; color: var(--text-sub); font-variant-numeric: tabular-nums; }
  .count-controls .count-desc { font-size: 14px; color: var(--text-sub); }
</style>
</head>
<body>
<header>
  <div class="header-top">
    <h1>TrendNews</h1>
    <div class="header-icons">
      <button id="topBtn" type="button" class="icon-btn text-btn" title="자주 나온 키워드 Top 10" aria-label="자주 나온 키워드 Top 10" aria-expanded="false">Top 10</button>
      <button id="searchBtn" type="button" class="icon-btn" title="뉴스 검색" aria-label="뉴스 검색" aria-expanded="false"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><line x1="15.5" y1="15.5" x2="21" y2="21"/></svg></button>
      <button id="collapseAll" type="button" class="icon-btn" title="모두 접기" aria-label="모두 접기">⊟</button>
      <button id="expandAll" type="button" class="icon-btn" title="모두 펼치기" aria-label="모두 펼치기">⊞</button>
    </div>
  </div>
  <div class="updated" id="updatedAt">불러오는 중...</div>
  <div class="top-panel" id="topPanel" hidden></div>
  <div class="search-bar" id="searchBar" hidden>
    <input type="search" id="searchInput" placeholder="스크랩된 뉴스에서 검색 (띄어쓰기로 여러 단어)" autocomplete="off" enterkeyhint="search" aria-label="뉴스 검색">
    <button type="button" id="searchClose" class="search-close" aria-label="검색 닫기" title="검색 닫기">✕</button>
  </div>
  <nav class="category-bar" id="categoryBar" aria-label="분야 선택"></nav>
  <div class="paper-filter" id="paperFilter" hidden>
    <button type="button" class="paper-btn" data-range="1-1">1면</button>
    <button type="button" class="paper-btn" data-range="1-10">1~10</button>
    <button type="button" class="paper-btn" data-range="11-20">11~20</button>
    <button type="button" class="paper-btn" data-range="21-30">21~30</button>
    <button type="button" class="paper-btn" data-range="31-">31~</button>
  </div>
</header>
<div class="search-results" id="searchResults" hidden></div>
<div class="grid" id="grid"></div>
<footer>
  <div class="controls">
    <button id="resetOrder" type="button">순서 초기화</button>
    <span class="font-controls">
      <span id="fontSizeLabel">16px</span>
      <button id="fontDec" type="button" aria-label="글자 작게">가-</button>
      <button id="fontInc" type="button" aria-label="글자 크게">가+</button>
    </span>
  </div>
  <div class="controls">
    <span class="count-controls">
      <span class="count-desc">언론당 기사 개수</span>
      <span id="postCountLabel">7</span>
      <button id="postCountDec" type="button" aria-label="기사 개수 줄이기">-</button>
      <button id="postCountInc" type="button" aria-label="기사 개수 늘리기">+</button>
    </span>
  </div>
</footer>
<script>
  const COMMUNITY_DATA = __DATA_JSON__;
  (function () {
    const STORAGE_KEY = 'communityViewerOrder';
    const COLLAPSE_KEY = 'communityViewerCollapsed';
    const FONT_KEY = 'communityViewerFontSize';
    const FONT_MIN = 12;
    const FONT_MAX = 26;
    const FONT_DEFAULT = 16;
    const COUNT_KEY = 'communityViewerPostCount';
    const COUNT_MIN = 1;
    const COUNT_MAX = 10;
    const COUNT_DEFAULT = 7;
    const grid = document.getElementById('grid');
    const updatedEl = document.getElementById('updatedAt');
    const resetLink = document.getElementById('resetOrder');
    const fontDecBtn = document.getElementById('fontDec');
    const fontIncBtn = document.getElementById('fontInc');
    const fontSizeLabel = document.getElementById('fontSizeLabel');
    const postCountLabel = document.getElementById('postCountLabel');
    const postCountDecBtn = document.getElementById('postCountDec');
    const postCountIncBtn = document.getElementById('postCountInc');
    const collapseAllBtn = document.getElementById('collapseAll');
    const expandAllBtn = document.getElementById('expandAll');

    function getFontSize() {
      const raw = parseInt(localStorage.getItem(FONT_KEY), 10);
      return (!isNaN(raw) && raw >= FONT_MIN && raw <= FONT_MAX) ? raw : FONT_DEFAULT;
    }
    function setFontSize(px) {
      px = Math.max(FONT_MIN, Math.min(FONT_MAX, px));
      document.documentElement.style.setProperty('--post-size', px + 'px');
      try { localStorage.setItem(FONT_KEY, String(px)); } catch (e) {}
      fontSizeLabel.textContent = px + 'px';
      return px;
    }
    let currentFontSize = setFontSize(getFontSize());
    fontDecBtn.addEventListener('click', function () { currentFontSize = setFontSize(currentFontSize - 1); });
    fontIncBtn.addEventListener('click', function () { currentFontSize = setFontSize(currentFontSize + 1); });

    function getPostCount() {
      const raw = parseInt(localStorage.getItem(COUNT_KEY), 10);
      return (!isNaN(raw) && raw >= COUNT_MIN && raw <= COUNT_MAX) ? raw : COUNT_DEFAULT;
    }
    function setPostCount(n) {
      n = Math.max(COUNT_MIN, Math.min(COUNT_MAX, n));
      try { localStorage.setItem(COUNT_KEY, String(n)); } catch (e) {}
      postCountLabel.textContent = String(n);
      return n;
    }
    let currentPostCount = setPostCount(getPostCount());
    postCountDecBtn.addEventListener('click', function () { currentPostCount = setPostCount(currentPostCount - 1); render(); });
    postCountIncBtn.addEventListener('click', function () { currentPostCount = setPostCount(currentPostCount + 1); render(); });

    if (typeof COMMUNITY_DATA === 'undefined' || !COMMUNITY_DATA.communities) { updatedEl.textContent = '데이터가 없습니다.'; return; }
    updatedEl.textContent = '마지막 업데이트: ' + COMMUNITY_DATA.generatedAt;
    function getSavedOrder() { try { const raw = localStorage.getItem(STORAGE_KEY); const arr = raw ? JSON.parse(raw) : null; return Array.isArray(arr) ? arr : null; } catch (e) { return null; } }
    function saveOrder(names) { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(names)); } catch (e) {} }
    function applyOrder(communities, order) {
      if (!order) return communities.slice();
      const byName = {}; communities.forEach(function (c) { byName[c.name] = c; });
      const ordered = [];
      order.forEach(function (name) { if (byName[name]) { ordered.push(byName[name]); delete byName[name]; } });
      communities.forEach(function (c) { if (byName[c.name]) ordered.push(c); });
      return ordered;
    }
    function getCollapsedSet() {
      try {
        const raw = localStorage.getItem(COLLAPSE_KEY);
        const arr = raw ? JSON.parse(raw) : [];
        return new Set(Array.isArray(arr) ? arr : []);
      } catch (e) { return new Set(); }
    }
    function saveCollapsedSet(set) { try { localStorage.setItem(COLLAPSE_KEY, JSON.stringify(Array.from(set))); } catch (e) {} }
    const collapsedSet = getCollapsedSet();

    // ---------- 분야 선택 (주요뉴스/정치/.../랭킹) ----------
    const CATEGORY_KEY = 'trendNewsCategory';
    const CATEGORIES = COMMUNITY_DATA.categories || [['main', '주요뉴스']];
    const categoryBar = document.getElementById('categoryBar');
    function getSavedCategory() {
      try {
        const raw = localStorage.getItem(CATEGORY_KEY);
        if (raw && CATEGORIES.some(function (c) { return c[0] === raw; })) return raw;
      } catch (e) {}
      return CATEGORIES[0][0];
    }
    let currentCategory = getSavedCategory();
    function renderCategoryBar() {
      categoryBar.innerHTML = '';
      // 한 줄에 최대한 다 나오게 하고, 화면 폭이 모자랄 때만 자연스럽게 다음 줄로 넘어감(flex-wrap)
      const row = document.createElement('div');
      row.className = 'category-row';
      categoryBar.appendChild(row);
      CATEGORIES.forEach(function (c) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'category-btn' + (c[0] === currentCategory ? ' active' : '');
        btn.textContent = c[1];
        btn.addEventListener('click', function () { setCategory(c[0], 0); });
        row.appendChild(btn);
      });
      renderPaperFilter();
    }
    // dir: 1 = 다음 분야(오른쪽에서 들어옴), -1 = 이전 분야(왼쪽에서 들어옴), 0 = 애니메이션 없음
    function playSlide(dir) {
      if (!dir) return;
      const cls = dir > 0 ? 'slide-from-right' : 'slide-from-left';
      grid.classList.remove('slide-from-right', 'slide-from-left');
      void grid.offsetWidth; // 같은 클래스를 연속으로 줘도 애니메이션이 다시 재생되도록 리플로우
      grid.classList.add(cls);
    }
    function setCategory(key, dir) {
      if (key === currentCategory) return;
      currentCategory = key;
      try { localStorage.setItem(CATEGORY_KEY, currentCategory); } catch (e) {}
      if (key === 'newspaper') paperPick = {}; // 지면 탭에 들어올 때마다 랜덤 추첨을 새로 함
      renderCategoryBar();
      render();
      playSlide(dir);
    }
    function stepCategory(delta) {
      if (!searchResults.hidden) return false; // 검색 결과를 보는 중에는 분야 이동(스와이프/키)을 하지 않음
      // 지면 탭 안에서는 좌우 이동이 "다음/이전 면 범위"(1면 → 1~10 → 11~20 → 21~30 → 31~)이고,
      // 맨 끝(31~)을 넘어가면 다음 분야(랭킹), 맨 앞(1면) 이전으로 가면 이전 분야(칼럼)로 넘어감.
      if (currentCategory === 'newspaper') {
        const pi = PAPER_RANGES.indexOf(paperRange);
        const pj = pi + delta;
        if (pi !== -1 && pj >= 0 && pj < PAPER_RANGES.length) {
          setPaperRange(PAPER_RANGES[pj], delta);
          return true;
        }
      }
      const idx = CATEGORIES.findIndex(function (c) { return c[0] === currentCategory; });
      const next = idx + delta;
      if (idx === -1 || next < 0 || next >= CATEGORIES.length) return false; // 양 끝에서는 순환하지 않음
      // 스와이프로 지면 탭에 들어올 때: 오른쪽으로(다음) 들어오면 첫 범위(1면)부터,
      // 왼쪽으로(이전) 들어오면 마지막 범위(31~)부터 보이게 함.
      if (CATEGORIES[next][0] === 'newspaper') {
        paperRange = delta > 0 ? PAPER_RANGES[0] : PAPER_RANGES[PAPER_RANGES.length - 1];
        try { localStorage.setItem(PAPER_KEY, paperRange); } catch (e) {}
      }
      setCategory(CATEGORIES[next][0], delta);
      return true;
    }
    function categoryName() {
      const found = CATEGORIES.filter(function (c) { return c[0] === currentCategory; })[0];
      return found ? found[1] : '';
    }
    function categoryUrl(pressId) {
      if (!pressId) return '';
      if (currentCategory === 'main') return 'https://media.naver.com/press/' + pressId;
      if (currentCategory === 'ranking') return 'https://media.naver.com/press/' + pressId + '/ranking?type=popular';
      if (currentCategory === 'newspaper') return 'https://media.naver.com/press/' + pressId + '/newspaper';
      return 'https://media.naver.com/press/' + pressId + '?sid=' + currentCategory;
    }

    // ---------- 지면 탭 전용: 면 범위 (1면 / 1~10 / 11~20 / 21~30 / 31~) ----------
    // 1면은 그 면 기사를 전부 보여주고, 나머지 범위는 그 범위 기사 중 "언론당 기사 개수"만큼만
    // 무작위로 골라서 보여줌 (고른 기사는 면 순서대로 정렬해서 표시).
    const PAPER_KEY = 'trendNewsPaperRange';
    const PAPER_RANGES = ['1-1', '1-10', '11-20', '21-30', '31-'];
    const paperFilter = document.getElementById('paperFilter');
    function getSavedPaperRange() {
      try {
        let raw = localStorage.getItem(PAPER_KEY);
        if (raw === '1') raw = '1-1'; // 예전 저장값 호환
        if (PAPER_RANGES.indexOf(raw) !== -1) return raw;
      } catch (e) {}
      return '1-1';
    }
    let paperRange = getSavedPaperRange();
    // 무작위 추첨 결과는 (언론사, 범위)별로 캐시해 둠 - 접기/펼치기, 카드 순서 변경 같은
    // 다른 동작으로 화면이 다시 그려질 때마다 기사가 뒤바뀌지 않게 하려고. 범위 버튼을 누를 때
    // (같은 범위를 다시 눌러도), 스와이프로 범위를 넘길 때, 지면 탭에 들어올 때 새로 뽑음.
    let paperPick = {};
    function renderPaperFilter() {
      paperFilter.hidden = currentCategory !== 'newspaper';
      Array.from(paperFilter.querySelectorAll('.paper-btn')).forEach(function (b) {
        b.classList.toggle('active', b.getAttribute('data-range') === paperRange);
      });
    }
    function setPaperRange(range, dir) {
      paperRange = range;
      try { localStorage.setItem(PAPER_KEY, paperRange); } catch (e) {}
      paperPick = {};
      renderPaperFilter();
      render();
      playSlide(dir || 0);
    }
    Array.from(paperFilter.querySelectorAll('.paper-btn')).forEach(function (b) {
      b.addEventListener('click', function () { setPaperRange(b.getAttribute('data-range'), 0); });
    });
    // candidates 중 count개를 무작위로 고르되, 화면에는 원래(면) 순서대로 보여줌
    function pickRandom(candidates, count, cacheKey) {
      let picked = paperPick[cacheKey];
      if (!picked) {
        const idx = candidates.map(function (_, i) { return i; });
        for (let i = idx.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          const t = idx[i]; idx[i] = idx[j]; idx[j] = t;
        }
        picked = idx; // 전부 섞어서 저장해 두고, 기사 개수를 늘리면 같은 순서에서 더 가져옴
        paperPick[cacheKey] = picked;
      }
      return picked.slice(0, count).sort(function (a, b) { return a - b; }).map(function (i) { return candidates[i]; });
    }

    let currentOrder = applyOrder(COMMUNITY_DATA.communities, getSavedOrder());
    resetLink.addEventListener('click', function (e) { e.preventDefault(); localStorage.removeItem(STORAGE_KEY); currentOrder = COMMUNITY_DATA.communities.slice(); render(); });

    collapseAllBtn.addEventListener('click', function () {
      currentOrder.forEach(function (c) { collapsedSet.add(c.name); });
      saveCollapsedSet(collapsedSet);
      render();
    });
    expandAllBtn.addEventListener('click', function () {
      collapsedSet.clear();
      saveCollapsedSet(collapsedSet);
      render();
    });

    // ---------- drag-to-reorder (Pointer Events, not native HTML5 DnD) ----------
    let dragSrcIndex = null;
    let dragActive = false;

    function attachDragHandle(handle, card, index) {
      handle.style.touchAction = 'none';
      handle.addEventListener('pointerdown', function (e) {
        dragSrcIndex = index;
        dragActive = true;
        card.classList.add('dragging');
        try { handle.setPointerCapture(e.pointerId); } catch (err) {}
      });
      handle.addEventListener('pointermove', function (e) {
        if (!dragActive) return;
        const el = document.elementFromPoint(e.clientX, e.clientY);
        const targetCard = el && el.closest ? el.closest('.card') : null;
        Array.from(grid.querySelectorAll('.card.drag-over')).forEach(function (c) { c.classList.remove('drag-over'); });
        if (targetCard && targetCard !== card) targetCard.classList.add('drag-over');
      });
      function endDrag(e) {
        if (!dragActive) return;
        dragActive = false;
        card.classList.remove('dragging');
        Array.from(grid.querySelectorAll('.card.drag-over')).forEach(function (c) { c.classList.remove('drag-over'); });
        const el = document.elementFromPoint(e.clientX, e.clientY);
        const targetCard = el && el.closest ? el.closest('.card') : null;
        if (targetCard && targetCard !== card) {
          const targetIndex = Array.from(grid.children).indexOf(targetCard);
          if (dragSrcIndex !== null && targetIndex !== -1 && targetIndex !== dragSrcIndex) {
            const reordered = currentOrder.slice();
            const moved = reordered.splice(dragSrcIndex, 1)[0];
            reordered.splice(targetIndex, 0, moved);
            currentOrder = reordered;
            saveOrder(currentOrder.map(function (c) { return c.name; }));
            render();
          }
        }
        dragSrcIndex = null;
      }
      handle.addEventListener('pointerup', endDrag);
      handle.addEventListener('pointercancel', endDrag);
    }

    function render() {
      grid.innerHTML = '';
      currentOrder.forEach(function (community, index) {
        const section = (community.sections || {})[currentCategory] || {};
        const boardUrl = categoryUrl(community.pressId);
        const card = document.createElement('div'); card.className = 'card';
        const isCollapsed = collapsedSet.has(community.name);
        if (isCollapsed) card.classList.add('collapsed');

        const header = document.createElement('div'); header.className = 'card-header';
        header.setAttribute('role', 'button');
        header.setAttribute('tabindex', '0');
        header.setAttribute('aria-expanded', String(!isCollapsed));
        header.innerHTML = '<span class="drag-handle" aria-hidden="true">⠿</span>' + (boardUrl ? '<a class="title" href="' + escapeAttr(boardUrl) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(community.name) + '</a>' : '<span class="title">' + escapeHtml(community.name) + '</span>') + '<span class="board">' + escapeHtml(categoryName()) + (section.stale ? ' · 캐시' : '') + '</span><span class="toggle-icon" aria-hidden="true">' + (isCollapsed ? '▸' : '▾') + '</span>';
        card.appendChild(header);

        attachDragHandle(header.querySelector('.drag-handle'), card, index);

        const toggleIcon = header.querySelector('.toggle-icon');
        function toggleCollapse() {
          const nowCollapsed = card.classList.toggle('collapsed');
          if (nowCollapsed) { collapsedSet.add(community.name); } else { collapsedSet.delete(community.name); }
          saveCollapsedSet(collapsedSet);
          toggleIcon.textContent = nowCollapsed ? '▸' : '▾';
          header.setAttribute('aria-expanded', String(!nowCollapsed));
        }
        header.addEventListener('click', function (e) {
          if (e.target.closest('.drag-handle') || e.target.closest('.title')) return;
          toggleCollapse();
        });
        header.addEventListener('keydown', function (e) {
          if (e.target.closest('.drag-handle') || e.target.closest('.title')) return;
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleCollapse(); }
        });
        // 보여줄 기사 목록 결정. 지면 탭: 선택한 면 범위의 기사 중, 1면은 전부 / 그 외 범위는
        // "언론당 기사 개수"만큼 무작위로 골라서 보여줌. 나머지 분야는 기존처럼 개수만큼 자름.
        let visible = section.posts || [];
        const isPaper = currentCategory === 'newspaper';
        if (isPaper) {
          const parts = paperRange.split('-'); // '11-20' -> ['11','20'], '31-' -> ['31','']
          const lo = Number(parts[0]);
          const hi = parts[1] === '' ? Infinity : Number(parts[1]);
          visible = visible.filter(function (p) { return p.main && p.pageNo >= lo && p.pageNo <= hi; });
          if (paperRange !== '1-1') visible = pickRandom(visible, currentPostCount, community.name + '|' + paperRange);
        } else {
          visible = visible.slice(0, currentPostCount);
        }
        if (visible.length === 0) {
          const empty = document.createElement('div'); empty.className = 'empty-note';
          if (section.unavailable) empty.textContent = isPaper ? '이 언론사는 신문 지면보기가 없습니다.' : '이 언론사에는 해당 분야가 없습니다.';
          else if (section.error) empty.textContent = '불러오지 못했습니다 (' + section.error + ')';
          else empty.textContent = isPaper ? '해당 면의 기사가 없습니다.' : '표시할 뉴스가 없습니다.';
          card.appendChild(empty);
        } else {
          const list = document.createElement('ol'); list.className = 'post-list';
          visible.forEach(function (post, idx) {
            const li = document.createElement('li');
            // 랭킹 탭: 조회수(공개하는 언론사만). 지면 탭: 몇 면 기사인지("A1면").
            // 그 외 분야: 댓글 많은 순이므로 댓글 수를 보여줌
            // (댓글 수를 못 받아온 경우에만 "1시간전" 같은 기사 시각으로 대체)
            let badge;
            if (currentCategory === 'ranking') badge = post.views != null ? post.views : '';
            else if (isPaper) badge = post.page ? post.page + '면' : '';
            else if (post.comments != null) badge = String(post.comments);
            else badge = post.time || '';
            li.innerHTML = '<a class="post-title" href="' + escapeAttr(post.url) + '" target="_blank" rel="noopener noreferrer" title="' + escapeAttr(post.title) + '">' + escapeHtml(post.title) + '</a>' + (badge !== '' ? '<span class="views">' + escapeHtml(badge) + '</span>' : '');
            list.appendChild(li);
          });
          card.appendChild(list);
        }
        grid.appendChild(card);
      });
    }
    // ---------- 좌우 스와이프/스크롤로 이전·다음 분야 이동 ----------
    // 터치: 손가락을 왼쪽으로 밀면 다음 분야, 오른쪽으로 밀면 이전 분야.
    // 세로 스크롤과 헷갈리지 않게 "가로로 충분히 길고 세로 이동의 2배 이상"일 때만 반응함.
    // 분야 바(자체 가로 스크롤), 카드 드래그 핸들(순서 변경), 가로 스크롤되는 요소에서
    // 시작한 제스처는 무시함.
    const SWIPE_MIN_X = 60;
    let swipeStart = null;
    function isSwipeBlocked(target) {
      if (!target || !target.closest) return false;
      if (target.closest('#categoryBar') || target.closest('#paperFilter') || target.closest('#searchBar') || target.closest('#topPanel') || target.closest('.drag-handle') || target.closest('.font-controls') || target.closest('.count-controls')) return true;
      for (let el = target; el && el !== document.body; el = el.parentElement) {
        if (el.scrollWidth > el.clientWidth + 1) {
          const ox = getComputedStyle(el).overflowX;
          if (ox === 'auto' || ox === 'scroll') return true;
        }
      }
      return false;
    }
    document.addEventListener('touchstart', function (e) {
      if (e.touches.length !== 1 || dragActive || isSwipeBlocked(e.target)) { swipeStart = null; return; }
      swipeStart = { x: e.touches[0].clientX, y: e.touches[0].clientY };
    }, { passive: true });
    document.addEventListener('touchend', function (e) {
      if (!swipeStart || dragActive) { swipeStart = null; return; }
      const t = e.changedTouches[0];
      const dx = t.clientX - swipeStart.x;
      const dy = t.clientY - swipeStart.y;
      swipeStart = null;
      if (Math.abs(dx) < SWIPE_MIN_X || Math.abs(dx) < Math.abs(dy) * 2) return;
      stepCategory(dx < 0 ? 1 : -1);
    }, { passive: true });
    document.addEventListener('touchcancel', function () { swipeStart = null; }, { passive: true });

    // 마우스/트랙패드: 가로 스크롤(deltaX)이 세로보다 확실히 클 때만 반응. 한 번의 스와이프에
    // 휠 이벤트가 수십 개 연달아 오기 때문에 값을 누적하고, 한 번 넘기면 잠시 쉼.
    let wheelAcc = 0;
    let wheelLockUntil = 0;
    let wheelResetTimer = null;
    document.addEventListener('wheel', function (e) {
      if (Math.abs(e.deltaX) <= Math.abs(e.deltaY) * 1.5 || isSwipeBlocked(e.target)) return;
      const now = Date.now();
      if (now < wheelLockUntil) return;
      wheelAcc += e.deltaX;
      clearTimeout(wheelResetTimer);
      wheelResetTimer = setTimeout(function () { wheelAcc = 0; }, 200);
      if (Math.abs(wheelAcc) >= 80) {
        const moved = stepCategory(wheelAcc > 0 ? 1 : -1);
        wheelAcc = 0;
        wheelLockUntil = now + (moved ? 700 : 150);
      }
    }, { passive: true });

    // 키보드: →/← 키로 다음/이전 분야 이동. Alt/Ctrl/Cmd/Shift가 같이 눌렸으면(Alt+←는
    // 브라우저 뒤로가기 등) 건드리지 않고, 입력창에 포커스가 있을 때도 무시함.
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || e.defaultPrevented || dragActive) return;
      const t = e.target;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      stepCategory(e.key === 'ArrowRight' ? 1 : -1);
    });

    // ---------- 뉴스 검색: 이미 수집해 둔 기사(이 페이지에 들어있는 데이터) 안에서만 찾음 ----------
    // 모든 언론사 x 모든 분야(주요뉴스~랭킹, 지면 포함)의 기사 제목을 대상으로 하고,
    // 띄어쓰기로 나눈 단어가 전부 들어있는 기사만 보여줌(대소문자 구분 없음).
    // 같은 기사가 여러 분야/지면에 중복으로 있으면 한 번만 보여주고 분야는 함께 표시함.
    const searchBtn = document.getElementById('searchBtn');
    const searchBar = document.getElementById('searchBar');
    const searchInput = document.getElementById('searchInput');
    const searchClose = document.getElementById('searchClose');
    const searchResults = document.getElementById('searchResults');
    const SEARCH_MAX = 300;
    function hasMetric(p) { return p.comments != null || p.views != null; }
    function buildSearchIndex() {
      const byKey = {};
      const list = [];
      currentOrder.forEach(function (community) {
        const secs = community.sections || {};
        CATEGORIES.forEach(function (c) {
          const sec = secs[c[0]];
          if (!sec || !sec.posts) return;
          sec.posts.forEach(function (post) {
            const title = String(post.title || '');
            const key = community.name + '|' + title.split(' ').join('').toLowerCase();
            let item = byKey[key];
            if (!item) {
              item = { outlet: community.name, cats: [], post: post, catKey: c[0], hay: title.toLowerCase() };
              byKey[key] = item;
              list.push(item);
            } else if (hasMetric(post) && !hasMetric(item.post)) {
              item.post = post; // 댓글 수/조회수가 있는 쪽 정보를 대표로 씀
              item.catKey = c[0];
            }
            if (item.cats.indexOf(c[1]) === -1) item.cats.push(c[1]);
          });
        });
      });
      return list;
    }
    function searchBadge(post, catKey) {
      if (catKey === 'ranking') return post.views != null ? String(post.views) : '';
      if (catKey === 'newspaper') return post.page ? post.page + '면' : '';
      if (post.comments != null) return String(post.comments);
      return post.time || '';
    }
    function highlight(text, terms) {
      const lower = text.toLowerCase();
      const marks = [];
      terms.forEach(function (t) {
        let i = 0;
        while ((i = lower.indexOf(t, i)) !== -1) { marks.push([i, i + t.length]); i += t.length; }
      });
      marks.sort(function (a, b) { return a[0] - b[0]; });
      const merged = [];
      marks.forEach(function (m) {
        const last = merged[merged.length - 1];
        if (last && m[0] <= last[1]) last[1] = Math.max(last[1], m[1]);
        else merged.push([m[0], m[1]]);
      });
      let out = '';
      let pos = 0;
      merged.forEach(function (m) {
        out += escapeHtml(text.slice(pos, m[0])) + '<mark>' + escapeHtml(text.slice(m[0], m[1])) + '</mark>';
        pos = m[1];
      });
      return out + escapeHtml(text.slice(pos));
    }
    function hideResults() {
      searchResults.hidden = true;
      searchResults.innerHTML = '';
      grid.hidden = false;
      categoryBar.hidden = false;
      renderPaperFilter();
    }
    function showResults(items, terms, query) {
      grid.hidden = true;
      categoryBar.hidden = true;
      paperFilter.hidden = true;
      searchResults.hidden = false;
      searchResults.innerHTML = '';
      const card = document.createElement('div');
      card.className = 'card';
      const head = document.createElement('div');
      head.className = 'card-header search-head';
      head.innerHTML = '<span class="title">검색 결과</span><span class="board">' + items.length + '건' + (items.length > SEARCH_MAX ? ' (상위 ' + SEARCH_MAX + '건만 표시)' : '') + '</span>';
      if (!searchBar.hidden) card.appendChild(head); // 키워드로 볼 때(검색창 없음)는 '검색 결과' 머리줄을 생략
      if (items.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'empty-note';
        empty.textContent = "'" + query + "'에 해당하는 기사가 없습니다. (이미 수집된 기사 안에서만 검색합니다)";
        card.appendChild(empty);
      } else {
        const list = document.createElement('ol');
        list.className = 'post-list';
        items.slice(0, SEARCH_MAX).forEach(function (it) {
          const li = document.createElement('li');
          const badge = searchBadge(it.post, it.catKey);
          li.innerHTML = '<span class="sr-src"><span class="sr-outlet">' + escapeHtml(it.outlet) + '</span><span class="sr-cats">' + escapeHtml(it.cats[0]) + '</span></span>' +
            '<a class="post-title" href="' + escapeAttr(it.post.url) + '" target="_blank" rel="noopener noreferrer" title="' + escapeAttr(it.post.title) + '">' + highlight(String(it.post.title || ''), terms) + '</a>' +
            (badge !== '' ? '<span class="views">' + escapeHtml(badge) + '</span>' : '');
          list.appendChild(li);
        });
        card.appendChild(list);
      }
      searchResults.appendChild(card);
    }
    function runSearch() {
      const q = searchInput.value.trim();
      if (!q) { hideResults(); return; }
      const terms = q.toLowerCase().split(' ').filter(function (t) { return t !== ''; });
      const items = buildSearchIndex().filter(function (it) {
        return terms.every(function (t) { return it.hay.indexOf(t) !== -1; });
      });
      showResults(items, terms, q);
    }
    function openSearch() {
      searchBar.hidden = false;
      searchBtn.classList.add('active');
      searchBtn.setAttribute('aria-expanded', 'true');
      searchInput.focus();
      runSearch();
    }
    function closeSearch() {
      searchBar.hidden = true;
      searchBtn.classList.remove('active');
      searchBtn.setAttribute('aria-expanded', 'false');
      searchInput.value = '';
      hideResults();
      markTopActive();
    }
    searchBtn.addEventListener('click', function () { if (searchBar.hidden) openSearch(); else closeSearch(); });
    searchClose.addEventListener('click', closeSearch);
    searchInput.addEventListener('input', runSearch);
    searchInput.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.preventDefault(); closeSearch(); } });

    // ---------- Top 10 키워드: 지금 여러 언론이 함께 다루는 단어 ----------
    // 형태소 분석기 없이 가볍게: 제목을 단어로 쪼개고 끝의 조사(는/을/에서 등)를 떼어낸 뒤,
    // 그 단어가 나온 언론사 수(많을수록 위) -> 기사 수 순으로 상위 10개를 보여줌. 누르면 그 단어로 검색함.
    // 한국/미국/대통령/삼성처럼 언제나 나오는 뻔한 단어는 TOP_STOP에 넣어 제외함 (더 빼고 싶으면 여기에 추가).
    const topBtn = document.getElementById('topBtn');
    const topPanel = document.getElementById('topPanel');
    const TOP_N_KEYWORDS = 10;
    const TOP_STOP = {};
    ('속보 단독 종합 사진 영상 포토 그래픽 카드 사설 칼럼 만평 기고 논설 시론 독자 부고 인사 운세 날씨 오늘 내일 어제 이번 지난 올해 내년 지난해 지난달 이달 이날 이후 이전 전날 현재 오전 오후 최근 모두 다시 이미 가장 계속 관련 대한 위해 통해 대해 따라 대신 때문 가운데 이상 이하 이내 앞서 한편 우리 지금 여기 하루 이틀 주말 한때 뉴스 기자 오늘의 만에 시대 이유 공개 전환 지원 개발 확대 강화 추진 발표 계획 가능 필요 사실 결과 상황 문제 방안 세계 ai 인공지능 대통령 한국 삼성 삼성전자 정보 서울 미국 중국 일본 정부 국민 기업 시장 경제 사회 정치 국내 해외 글로벌 전국 가능성 사람 역대 논란 피해 최초 최대 최고 전망 예정 우려 영향 규모 현장 발생 the and for with from').split(' ').forEach(function (w) { TOP_STOP[w] = true; });
    const JOSA_STRONG = ['에서', '에게', '으로', '까지', '부터', '이라', '라고', '에는', '에도', '에만', '보다', '처럼', '한테', '은', '는', '을', '를'];
    const JOSA_WEAK = ['의', '가', '도', '이', '로', '과', '와', '만', '에'];
    const VERB_END = ['다', '하며', '하고', '하는', '하게', '해야', '으며', '했던', '하던'];
    function splitWords(lowerTitle) {
      return lowerTitle.split(/[^0-9a-z가-힣]+/).filter(function (t) { return t !== ''; });
    }
    function endsWithAny(tok, list) {
      for (let i = 0; i < list.length; i++) {
        if (tok.length >= list[i].length && tok.slice(tok.length - list[i].length) === list[i]) return list[i];
      }
      return '';
    }
    function stemOf(tok, rawSet) {
      const s = endsWithAny(tok, JOSA_STRONG);
      if (s && tok.length - s.length >= 2) return tok.slice(0, tok.length - s.length);
      // '의/가/도' 같은 한 글자 조사는 '민주주의', '전문가'처럼 단어 일부일 수 있어서,
      // 떼어낸 단어가 다른 제목에서 단독으로도 쓰인 경우에만 뗌
      const w = endsWithAny(tok, JOSA_WEAK);
      if (w && tok.length - w.length >= 2) {
        const stem = tok.slice(0, tok.length - w.length);
        if (rawSet[stem]) return stem;
      }
      return tok;
    }
    function computeTopKeywords() {
      const items = buildSearchIndex();
      const rawSet = {};
      const wordLists = items.map(function (it) {
        const words = splitWords(it.hay);
        words.forEach(function (t) { rawSet[t] = true; });
        return words;
      });
      const df = {};
      wordLists.forEach(function (words) {
        const seen = {};
        words.forEach(function (tok) {
          if (tok.length < 2 || '0123456789'.indexOf(tok.charAt(0)) !== -1) return;
          if (endsWithAny(tok, VERB_END)) return;
          const stem = stemOf(tok, rawSet);
          if (stem.length < 2 || TOP_STOP[stem] || TOP_STOP[tok] || seen[stem]) return;
          seen[stem] = true;
          df[stem] = (df[stem] || 0) + 1;
        });
      });
      const cands = Object.keys(df).filter(function (w) { return df[w] >= 2; }).sort(function (a, b) { return df[b] - df[a]; }).slice(0, 80);
      // 검색 결과 건수와 일치하도록, 최종 건수는 검색과 같은 방식(제목에 단어가 포함된 기사 수)으로 다시 셈.
      // 한 언론만 계속 쓰는 단어보다 여러 언론이 함께 다루는 단어가 '지금 뜨는' 이슈이므로 언론사 수를 먼저 봄.
      const out = cands.map(function (w) {
        let n = 0;
        const outlets = {};
        items.forEach(function (it) { if (it.hay.indexOf(w) !== -1) { n++; outlets[it.outlet] = true; } });
        return { word: w, count: n, outlets: Object.keys(outlets).length };
      }).filter(function (k) { return k.outlets >= 2; });
      out.sort(function (a, b) { return b.outlets - a.outlets || b.count - a.count || b.word.length - a.word.length; });
      return out.slice(0, TOP_N_KEYWORDS);
    }
    function markTopActive() {
      const cur = searchInput.value.trim().toLowerCase();
      const chips = topPanel.querySelectorAll('.top-chip');
      for (let i = 0; i < chips.length; i++) {
        chips[i].classList.toggle('active', cur !== '' && chips[i].getAttribute('data-word') === cur);
      }
    }
    // 키워드를 누르면 검색창을 띄우지 않고(모바일에서 키보드가 올라와 기사를 가리므로) 결과만 보여줌.
    // 선택 중인 키워드를 다시 누르면 해제되어 원래 화면으로 돌아감.
    function pickKeyword(word) {
      if (searchInput.value.trim().toLowerCase() === word) {
        searchInput.value = '';
        hideResults();
      } else {
        searchInput.value = word;
        runSearch();
      }
      markTopActive();
    }
    function renderTopPanel() {
      const top = computeTopKeywords();
      topPanel.innerHTML = '';
      const list = document.createElement('div');
      list.className = 'top-list';
      top.forEach(function (k, i) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'top-chip';
        b.setAttribute('data-word', k.word);
        b.innerHTML = '<span class="tk-rank">' + (i + 1) + '</span><span class="tk-word">' + escapeHtml(k.word) + '</span><span class="tk-cnt">' + k.count + '</span>';
        b.addEventListener('click', function () { pickKeyword(k.word); });
        list.appendChild(b);
      });
      topPanel.appendChild(list);
      markTopActive();
    }
    topBtn.addEventListener('click', function () {
      const show = topPanel.hidden;
      topPanel.hidden = !show;
      topBtn.classList.toggle('active', show);
      topBtn.setAttribute('aria-expanded', show ? 'true' : 'false');
      if (show) {
        renderTopPanel();
      } else if (searchBar.hidden && searchInput.value !== '') {
        // 키워드로 보던 결과는 패널을 닫으면 함께 닫음 (검색창이 없어서 따로 닫을 방법이 없으므로)
        searchInput.value = '';
        hideResults();
      }
    });
    searchInput.addEventListener('input', markTopActive);

    renderCategoryBar();
    render();
    function escapeHtml(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
    function escapeAttr(s) { return escapeHtml(s).replace(/"/g, '&quot;'); }
  })();
</script>
</body>
</html>
"""


def load_prev_data():
    if not os.path.exists(OUT_PATH):
        return {}
    try:
        with open(OUT_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        m = re.search(r"const COMMUNITY_DATA = (\{.*?\});", content, re.S)
        if not m:
            return {}
        data = json.loads(m.group(1))
        prev = {}
        for c in data.get("communities", []):
            sections = c.get("sections")
            if sections is None and c.get("posts"):
                # 분야 선택 기능이 생기기 전 형식(posts가 바로 붙어있던 때)은 랭킹 탭 캐시로 취급
                sections = {"ranking": {"posts": c["posts"]}}
            prev[c["name"]] = sections or {}
        return prev
    except Exception:
        return {}


def crawl_section(key, press_id, tabs, home_html):
    """분야 하나(key)의 기사 목록을 가져옴. 반환: 게시글 리스트 (없는 분야면 None)."""
    if key == "main":
        return parse_press_main(home_html)
    if key == "ranking":
        h = fetch(f"https://media.naver.com/press/{press_id}/ranking?type=popular", "utf-8")
        return parse_naver_press(h)
    if key not in tabs:
        return None
    if key == "newspaper":
        h = fetch(f"https://media.naver.com/press/{press_id}/newspaper", "utf-8")
        return parse_newspaper(h)
    h = fetch(f"https://media.naver.com/press/{press_id}?sid={key}", "utf-8")
    return parse_press_edit(h)


def gno_of(url):
    m = re.search(r"/article/(\d+)/(\d+)", url)
    return f"news{m.group(1)},{m.group(2)}" if m else None


def fetch_comment_counts(press_id, gnos):
    """네이버가 기사 목록 페이지에서 댓글 수를 채워넣을 때 쓰는 API를 그대로 호출함.
    POST /commonComment/listCount, gnos="news<언론사>,<기사ID>;..." (한 번에 여러 개 가능).
    화면엔 "30+", "100+"처럼 뭉뚱그려 보여주지만 API 응답 자체는 정확한 숫자임."""
    counts = {}
    gnos = sorted(set(g for g in gnos if g))
    for i in range(0, len(gnos), 100):
        chunk = gnos[i : i + 100]
        body = urllib.parse.urlencode({"gnos": ";".join(chunk)})
        text = fetch(
            "https://media.naver.com/commonComment/listCount",
            "utf-8",
            method="POST",
            data=body,
            extra_headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": f"https://media.naver.com/press/{press_id}",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        for item in json.loads(text)["message"]["result"]:
            c = item.get("count")
            counts[item["gno"]] = c if isinstance(c, int) and c >= 0 else 0
    return counts


def sort_by_comments(posts, counts):
    # 댓글 많은 순. 댓글 수가 같으면 원래 순서(네이버가 보여주는 순서=대체로 최신순)를 유지함.
    for p in posts:
        p["comments"] = counts.get(gno_of(p["url"]), 0)
    return sorted(posts, key=lambda p: -p["comments"])


def main():
    prev_by_name = load_prev_data()

    result = {
        "generatedAt": (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S") + " KST",
        "categories": [[k, n] for k, n in CATEGORIES],
        "communities": [],
    }

    for name, press_id in PRESS_LIST:
        prev_sections = prev_by_name.get(name, {})
        sections = {}
        home_html = ""
        tabs = set()
        home_error = None
        try:
            home_html = fetch(f"https://media.naver.com/press/{press_id}", "utf-8")
            tabs = parse_press_tabs(home_html)
        except Exception as e:
            home_error = str(e)
            print(f"[warn] {name} home failed: {e}")

        # 1단계: 분야별 기사 목록을 전부 받아둠 (key -> 게시글 리스트 / None(없는 분야) / Exception)
        fetched = {}
        for key, _label in CATEGORIES:
            try:
                if key == "main" and home_error:
                    raise ValueError(home_error)
                # 홈을 못 받았으면 어떤 분야가 있는 언론사인지 알 수 없으니, 분야 탭은
                # 있는 걸로 치고 시도함(실패하면 캐시로 대체됨).
                effective_tabs = tabs if not home_error else {k for k, _ in CATEGORIES}
                posts = crawl_section(key, press_id, effective_tabs, home_html)
                if posts is not None and not posts:
                    raise ValueError("no posts parsed - site markup may have changed")
                fetched[key] = posts
            except Exception as e:
                fetched[key] = e
            if key != "main":
                time.sleep(0.2)  # 한 언론사에 몰아서 요청하지 않도록 살짝 간격을 둠

        # 2단계: 랭킹 말고 분야 탭들은 "그냥 최신글"이라서, 이 언론사 기사 전체의 댓글 수를
        # 한 번에 받아와서(분야 하나당 요청 1번씩 하지 않고) 댓글 많은 순으로 정렬함.
        counts = None
        counts_error = None
        gnos = [
            gno_of(p["url"])
            for key, v in fetched.items()
            if key not in ("ranking", "newspaper") and isinstance(v, list)
            for p in v
        ]
        if gnos:
            try:
                counts = fetch_comment_counts(press_id, gnos)
            except Exception as e:
                counts_error = e
                print(f"[warn] {name} comment counts failed: {e}")

        for key, _label in CATEGORIES:
            v = fetched[key]
            cached = prev_sections.get(key)
            if v is None:
                sections[key] = {"posts": [], "unavailable": True}
            elif isinstance(v, Exception):
                if cached and cached.get("posts"):
                    sections[key] = {"posts": cached["posts"], "error": None, "stale": True}
                else:
                    sections[key] = {"posts": [], "error": str(v)}
                print(f"[warn] {name}/{key} failed: {v}")
            elif key == "newspaper":
                # 지면은 면 순서 그대로 전부 저장함 (몇 면까지 볼지는 화면에서 필터로 고름)
                sections[key] = {"posts": v[:400], "error": None}
            elif key == "ranking":
                v.sort(key=lambda x: x["views"] or 0, reverse=True)
                sections[key] = {"posts": v[:TOP_N], "error": None}
            elif counts is not None:
                sections[key] = {"posts": sort_by_comments(v, counts)[:TOP_N], "error": None}
            elif cached and cached.get("posts"):
                # 댓글 수를 못 받았으면 정렬을 못 하니, 직전에 정렬해둔 데이터를 씀
                sections[key] = {"posts": cached["posts"], "error": None, "stale": True}
            else:
                # 캐시도 없으면 빈 화면보다는 정렬 안 된 최신글이라도 보여줌 (시각 뱃지로 표시됨)
                sections[key] = {"posts": v[:TOP_N], "error": None}

        result["communities"].append({"name": name, "pressId": press_id, "sections": sections})

    data_json = json.dumps(result, ensure_ascii=False)
    page = PAGE_TEMPLATE.replace("__DATA_JSON__", data_json)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(page)

    print("Wrote", OUT_PATH, "-", len(page), "bytes")


if __name__ == "__main__":
    main()
