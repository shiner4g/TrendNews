#!/usr/bin/env python3
# TrendNews crawler + page builder — run by .github/workflows/update.yml
# TrendBoard(커뮤니티 버전)의 뉴스 버전. 국내 언론사 9곳의 기사를 분야별
# (주요뉴스/정치/경제/사회/생활/세계/IT/칼럼/랭킹)로 골라 볼 수 있게 한 화면에 모아 보여줌.
#
# 데이터 출처는 네이버 언론사 개별 홈(media.naver.com/press/<press_id>)의 탭들임:
#  - 주요뉴스: 홈(/press/<id>), 분야: /press/<id>?sid=100.. , 랭킹: /press/<id>/ranking
#  - 분야 탭은 언론사마다 달라서(예: MBC는 IT/칼럼 없음) 홈의 탭 목록으로 먼저 확인함.
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
    return set(re.findall(r'href="/press/\d+\?sid=(\d+)"', h))


# 분야 탭: (키, 표시 이름, 네이버 sid). main/ranking은 sid 없는 특수 탭.
CATEGORIES = [
    ("main", "주요뉴스"),
    ("100", "정치"),
    ("101", "경제"),
    ("102", "사회"),
    ("103", "생활"),
    ("104", "세계"),
    ("105", "IT"),
    ("110", "칼럼"),
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
  .category-bar { max-width: 1620px; margin: 12px auto 0; display: flex; flex-direction: column; gap: 5px; }
  .category-row { display: flex; flex-wrap: wrap; gap: 4px; }
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
  .post-title { flex: 1 1 auto; font-size: var(--post-size); color: var(--text); text-decoration: none; line-height: 1.4; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
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
      <button id="collapseAll" type="button" class="icon-btn" title="모두 접기" aria-label="모두 접기">⊟</button>
      <button id="expandAll" type="button" class="icon-btn" title="모두 펼치기" aria-label="모두 펼치기">⊞</button>
    </div>
  </div>
  <div class="updated" id="updatedAt">불러오는 중...</div>
  <nav class="category-bar" id="categoryBar" aria-label="분야 선택"></nav>
</header>
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
    }
    // dir: 1 = 다음 분야(오른쪽에서 들어옴), -1 = 이전 분야(왼쪽에서 들어옴), 0 = 애니메이션 없음
    function setCategory(key, dir) {
      if (key === currentCategory) return;
      currentCategory = key;
      try { localStorage.setItem(CATEGORY_KEY, currentCategory); } catch (e) {}
      renderCategoryBar();
      render();
      if (dir) {
        const cls = dir > 0 ? 'slide-from-right' : 'slide-from-left';
        grid.classList.remove('slide-from-right', 'slide-from-left');
        void grid.offsetWidth; // 같은 클래스를 연속으로 줘도 애니메이션이 다시 재생되도록 리플로우
        grid.classList.add(cls);
      }
    }
    function stepCategory(delta) {
      const idx = CATEGORIES.findIndex(function (c) { return c[0] === currentCategory; });
      const next = idx + delta;
      if (idx === -1 || next < 0 || next >= CATEGORIES.length) return false; // 양 끝에서는 순환하지 않음
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
      return 'https://media.naver.com/press/' + pressId + '?sid=' + currentCategory;
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
        if (!section.posts || section.posts.length === 0) {
          const empty = document.createElement('div'); empty.className = 'empty-note';
          empty.textContent = section.unavailable ? '이 언론사에는 해당 분야가 없습니다.' : (section.error ? ('불러오지 못했습니다 (' + section.error + ')') : '표시할 뉴스가 없습니다.');
          card.appendChild(empty);
        } else {
          const list = document.createElement('ol'); list.className = 'post-list';
          section.posts.slice(0, currentPostCount).forEach(function (post, idx) {
            const li = document.createElement('li');
            // 랭킹은 조회수(공개하는 언론사만), 나머지 분야는 "1시간전" 같은 상대 시각을 뱃지로 표시
            const badge = post.views != null ? post.views : (post.time || '');
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
      if (target.closest('#categoryBar') || target.closest('.drag-handle') || target.closest('.font-controls') || target.closest('.count-controls')) return true;
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
    h = fetch(f"https://media.naver.com/press/{press_id}?sid={key}", "utf-8")
    return parse_press_edit(h)


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

        for key, _label in CATEGORIES:
            try:
                if key == "main" and home_error:
                    raise ValueError(home_error)
                # 홈을 못 받았으면 어떤 분야가 있는 언론사인지 알 수 없으니, 분야 탭은
                # 있는 걸로 치고 시도함(실패하면 캐시로 대체됨).
                effective_tabs = tabs if not home_error else {k for k, _ in CATEGORIES}
                posts = crawl_section(key, press_id, effective_tabs, home_html)
                if posts is None:
                    sections[key] = {"posts": [], "unavailable": True}
                elif not posts:
                    raise ValueError("no posts parsed - site markup may have changed")
                else:
                    if key == "ranking":
                        posts.sort(key=lambda x: x["views"] or 0, reverse=True)
                    sections[key] = {"posts": posts[:TOP_N], "error": None}
            except Exception as e:
                cached = prev_sections.get(key)
                if cached and cached.get("posts"):
                    sections[key] = {"posts": cached["posts"], "error": None, "stale": True}
                else:
                    sections[key] = {"posts": [], "error": str(e)}
                print(f"[warn] {name}/{key} failed: {e}")
            if key not in ("main",):
                time.sleep(0.2)  # 한 언론사에 몰아서 요청하지 않도록 살짝 간격을 둠

        result["communities"].append({"name": name, "pressId": press_id, "sections": sections})

    data_json = json.dumps(result, ensure_ascii=False)
    page = PAGE_TEMPLATE.replace("__DATA_JSON__", data_json)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(page)

    print("Wrote", OUT_PATH, "-", len(page), "bytes")


if __name__ == "__main__":
    main()
