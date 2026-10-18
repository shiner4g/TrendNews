#!/usr/bin/env python3
# TrendNews crawler + page builder — run by .github/workflows/update.yml
# TrendBoard(커뮤니티 버전)의 뉴스 버전. 국내 언론사 9곳의 "많이 본 뉴스" TOP10을
# 한 화면에 모아 보여줌 - 구조/코드는 TrendBoard의 crawl.py를 그대로 가져왔음.
#
# 데이터 출처: 언론사별 단독 랭킹 페이지
# (https://media.naver.com/press/<press_id>/ranking?type=popular). 네이버뉴스
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


# 언론사 ID는 네이버뉴스의 고정 press_id (수년간 안 바뀜). 통신사/방송/종합지/경제지/
# 시사주간지/IT전문지를 섞어서 특정 성향에 치우치지 않도록 구성함.
COMMUNITIES = [
    {
        "name": "MBC", "board": "많이 본 뉴스", "encoding": "utf-8", "parse": parse_naver_press,
        "page_url": lambda n: "https://media.naver.com/press/214/ranking?type=popular",
        "pages": 1,
    },
    {
        "name": "연합뉴스", "board": "많이 본 뉴스", "encoding": "utf-8", "parse": parse_naver_press,
        "page_url": lambda n: "https://media.naver.com/press/001/ranking?type=popular",
        "pages": 1,
    },
    {
        "name": "경향신문", "board": "많이 본 뉴스", "encoding": "utf-8", "parse": parse_naver_press,
        "page_url": lambda n: "https://media.naver.com/press/032/ranking?type=popular",
        "pages": 1,
    },
    {
        "name": "한겨레", "board": "많이 본 뉴스", "encoding": "utf-8", "parse": parse_naver_press,
        "page_url": lambda n: "https://media.naver.com/press/028/ranking?type=popular",
        "pages": 1,
    },
    {
        "name": "한국일보", "board": "많이 본 뉴스", "encoding": "utf-8", "parse": parse_naver_press,
        "page_url": lambda n: "https://media.naver.com/press/469/ranking?type=popular",
        "pages": 1,
    },
    {
        "name": "매일경제", "board": "많이 본 뉴스", "encoding": "utf-8", "parse": parse_naver_press,
        "page_url": lambda n: "https://media.naver.com/press/009/ranking?type=popular",
        "pages": 1,
    },
    {
        "name": "중앙일보", "board": "많이 본 뉴스", "encoding": "utf-8", "parse": parse_naver_press,
        "page_url": lambda n: "https://media.naver.com/press/025/ranking?type=popular",
        "pages": 1,
    },
    {
        "name": "시사IN", "board": "많이 본 뉴스", "encoding": "utf-8", "parse": parse_naver_press,
        "page_url": lambda n: "https://media.naver.com/press/308/ranking?type=popular",
        "pages": 1,
    },
    {
        "name": "전자신문", "board": "많이 본 뉴스", "encoding": "utf-8", "parse": parse_naver_press,
        "page_url": lambda n: "https://media.naver.com/press/030/ranking?type=popular",
        "pages": 1,
    },
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
  .grid { max-width: 1620px; margin: 24px auto 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(520px, 100%), 1fr)); gap: 18px; }
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
  .views { flex: 0 0 auto; font-size: calc(var(--post-size) - 2px); color: var(--accent); background: var(--badge-bg); border-radius: 10px; padding: 1px 7px; font-weight: 600; min-width: 20px; text-align: center; font-variant-numeric: tabular-nums; }
  .empty-note { padding: 24px 16px; color: var(--text-sub); font-size: 16px; text-align: center; }
  footer { max-width: 1620px; margin: 36px auto 0; text-align: center; }
  .controls { display: flex; justify-content: center; align-items: center; gap: 16px; flex-wrap: wrap; margin-top: 10px; }
  .controls button { border: 1px solid var(--border); background: var(--card-bg); color: var(--text); border-radius: 6px; padding: 5px 14px; font-size: 14px; cursor: pointer; }
  .controls button:hover { border-color: var(--accent); color: var(--accent); }
  .font-controls { display: inline-flex; align-items: center; gap: 6px; }
  .font-controls button { padding: 5px 12px; line-height: 1.4; }
  #fontSizeLabel { min-width: 44px; display: inline-block; text-align: center; font-size: 14px; color: var(--text-sub); font-variant-numeric: tabular-nums; }
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
    const grid = document.getElementById('grid');
    const updatedEl = document.getElementById('updatedAt');
    const resetLink = document.getElementById('resetOrder');
    const fontDecBtn = document.getElementById('fontDec');
    const fontIncBtn = document.getElementById('fontInc');
    const fontSizeLabel = document.getElementById('fontSizeLabel');
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
        const card = document.createElement('div'); card.className = 'card';
        const isCollapsed = collapsedSet.has(community.name);
        if (isCollapsed) card.classList.add('collapsed');

        const header = document.createElement('div'); header.className = 'card-header';
        header.setAttribute('role', 'button');
        header.setAttribute('tabindex', '0');
        header.setAttribute('aria-expanded', String(!isCollapsed));
        header.innerHTML = '<span class="drag-handle" aria-hidden="true">⠿</span>' + (community.boardUrl ? '<a class="title" href="' + escapeAttr(community.boardUrl) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(community.name) + '</a>' : '<span class="title">' + escapeHtml(community.name) + '</span>') + '<span class="board">' + escapeHtml(community.board || '') + (community.stale ? ' · 캐시' : '') + '</span><span class="toggle-icon" aria-hidden="true">' + (isCollapsed ? '▸' : '▾') + '</span>';
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
        if (!community.posts || community.posts.length === 0) {
          const empty = document.createElement('div'); empty.className = 'empty-note';
          empty.textContent = community.error ? ('불러오지 못했습니다 (' + community.error + ')') : '표시할 뉴스가 없습니다.';
          card.appendChild(empty);
        } else {
          const list = document.createElement('ol'); list.className = 'post-list';
          community.posts.forEach(function (post, idx) {
            const li = document.createElement('li');
            li.innerHTML = '<a class="post-title" href="' + escapeAttr(post.url) + '" target="_blank" rel="noopener noreferrer" title="' + escapeAttr(post.title) + '">' + escapeHtml(post.title) + '</a>' + (post.views != null ? '<span class="views">' + post.views + '</span>' : '');
            list.appendChild(li);
          });
          card.appendChild(list);
        }
        grid.appendChild(card);
      });
    }
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
        return {c["name"]: c for c in data.get("communities", [])}
    except Exception:
        return {}


def main():
    prev_by_name = load_prev_data()

    result = {
        "generatedAt": (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S") + " KST",
        "communities": [],
    }

    for cfg in COMMUNITIES:
        try:
            seen_urls = set()
            posts = []
            page_errors = []
            for page_num in range(1, cfg.get("pages", 1) + 1):
                page_url = cfg["page_url"](page_num)
                page_body = cfg.get("page_body", lambda n: None)(page_num)
                try:
                    html_content = fetch(
                        page_url,
                        cfg["encoding"],
                        method=cfg.get("fetch_method", "GET"),
                        data=page_body,
                        extra_headers=cfg.get("fetch_headers"),
                    )
                    page_posts = cfg["parse"](html_content)
                except Exception as page_e:
                    page_errors.append(f"page {page_num}: {page_e}")
                    continue
                for post in page_posts:
                    if post["url"] not in seen_urls:
                        seen_urls.add(post["url"])
                        posts.append(post)
            if not posts:
                raise ValueError(
                    "no posts parsed - site markup may have changed"
                    + (f" ({'; '.join(page_errors)})" if page_errors else "")
                )
            # 일부 언론사는 조회수를 공개 안 해서 views가 None일 수 있음 - 그런
            # 경우 0 취급해서 정렬하되(같은 언론사 안에서는 전부 None이라 결과적으로
            # 원래 네이버 순위 순서가 그대로 유지됨), 화면에 실제로 뿌릴 때는
            # None을 0으로 바꿔치기하지 않음(아래 JS에서 처리).
            posts.sort(key=lambda x: x["views"] or 0, reverse=True)
            top = posts[:TOP_N]
            board_url = cfg.get("link_url", cfg["page_url"](1))
            result["communities"].append(
                {"name": cfg["name"], "board": cfg["board"], "posts": top, "error": None, "boardUrl": board_url}
            )
            if page_errors:
                print(f"[warn] {cfg['name']} had partial page failures: {'; '.join(page_errors)}")
        except Exception as e:
            board_url = cfg.get("link_url", cfg["page_url"](1))
            cached = None if cfg.get("no_cache") else prev_by_name.get(cfg["name"])
            if cached and cached.get("posts"):
                result["communities"].append(
                    {
                        "name": cfg["name"],
                        "board": cfg["board"],
                        "posts": cached["posts"],
                        "error": None,
                        "stale": True,
                        "boardUrl": board_url,
                    }
                )
            else:
                result["communities"].append(
                    {"name": cfg["name"], "board": cfg["board"], "posts": [], "error": str(e), "boardUrl": board_url}
                )
            print(f"[warn] {cfg['name']} failed: {e}")

    data_json = json.dumps(result, ensure_ascii=False)
    page = PAGE_TEMPLATE.replace("__DATA_JSON__", data_json)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(page)

    print("Wrote", OUT_PATH, "-", len(page), "bytes")


if __name__ == "__main__":
    main()
