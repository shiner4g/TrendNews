#!/usr/bin/env python3
# TrendNews crawler + page builder — run by .github/workflows/update.yml
# TrendBoard(커뮤니티 버전)의 뉴스 버전. 국내 주요 언론사 10곳의 "많이 본 뉴스"
# TOP5를 한 화면에 모아 보여줌.
#
# 데이터 출처는 네이버뉴스 랭킹 페이지(언론사별 많이 본 뉴스) 하나뿐임:
# https://news.naver.com/main/ranking/popularDay.naver
# 이 페이지는 "언론사별로 TOP5"를 미리 랭킹매겨서 보여주는 방식이라(실제 조회수
# 숫자는 공개하지 않음), TrendBoard처럼 우리가 조회수로 재정렬할 필요가 없음 -
# 네이버가 이미 매긴 순위를 그대로 씀. 대신 각 기사의 "N시간전" 같은 상대 시각을
# 뱃지에 표시함 (조회수 자리 대신).
#
# 주의: 이 페이지는 EUC-KR 인코딩으로 내려옴 (meta charset="euc-kr") - UTF-8로
# 읽으면 한글이 깨지니 encoding="euc-kr" 그대로 유지할 것.

import urllib.request
import urllib.parse
import re
import html
import json
import datetime
import os

TOP_N = 5  # 네이버가 언론사당 TOP5까지만 줘서, 이 값을 늘려도 더 나오진 않음
OUT_PATH = "index.html"

RANKING_URL = "https://news.naver.com/main/ranking/popularDay.naver"

# 언론사 ID는 네이버뉴스의 고정 press_id (수년간 안 바뀜). 통신사 1 + 지상파/종편
# 방송 5 + 종합일간지(보수/진보 균형) 4 로 구성 - 특정 성향에 치우치지 않도록
# 일부러 섞음. 필요하면 이 리스트에 추가/삭제만 하면 됨.
PRESS_LIST = [
    {"id": "001", "name": "연합뉴스"},
    {"id": "023", "name": "조선일보"},
    {"id": "025", "name": "중앙일보"},
    {"id": "028", "name": "한겨레"},
    {"id": "032", "name": "경향신문"},
    {"id": "052", "name": "YTN"},
    {"id": "055", "name": "SBS"},
    {"id": "056", "name": "KBS"},
    {"id": "214", "name": "MBC"},
    {"id": "437", "name": "JTBC"},
]


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


def parse_naver_ranking(h):
    # 페이지 하나에 81개 언론사 박스가 전부 들어있어서, 한 번만 받아 여기서
    # 언론사별로 쪼갬 (언론사마다 따로 요청하면 같은 페이지를 10번 중복으로 받게 됨).
    result = {}
    blocks = h.split('<div class="rankingnews_box">')
    for block in blocks[1:]:
        head = block[:600]
        pid_m = re.search(r"media\.naver\.com/press/(\d+)/ranking", head)
        if not pid_m:
            continue
        press_id = pid_m.group(1)
        posts = []
        for m in re.finditer(
            r'<a href="(https://n\.news\.naver\.com/article/[^"]+)" class="list_title[^"]*"[^>]*>([^<]*)</a>\s*'
            r'<span class="list_time\s*">([^<]*)</span>',
            block,
        ):
            posts.append(
                {
                    "title": decode_entities(m.group(2).strip()),
                    "url": decode_entities(m.group(1)),
                    "time": decode_entities(m.group(3).strip()),
                }
            )
        if posts:
            result[press_id] = posts
    return result


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
  .meta { flex: 0 0 auto; font-size: calc(var(--post-size) - 2px); color: var(--accent); background: var(--badge-bg); border-radius: 10px; padding: 1px 7px; font-weight: 600; min-width: 20px; text-align: center; font-variant-numeric: tabular-nums; white-space: nowrap; }
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
  const NEWS_DATA = __DATA_JSON__;
  (function () {
    const STORAGE_KEY = 'trendNewsOrder';
    const COLLAPSE_KEY = 'trendNewsCollapsed';
    const FONT_KEY = 'trendNewsFontSize';
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

    if (typeof NEWS_DATA === 'undefined' || !NEWS_DATA.communities) { updatedEl.textContent = '데이터가 없습니다.'; return; }
    updatedEl.textContent = '마지막 업데이트: ' + NEWS_DATA.generatedAt;
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

    let currentOrder = applyOrder(NEWS_DATA.communities, getSavedOrder());
    resetLink.addEventListener('click', function (e) { e.preventDefault(); localStorage.removeItem(STORAGE_KEY); currentOrder = NEWS_DATA.communities.slice(); render(); });

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
            li.innerHTML = '<a class="post-title" href="' + escapeAttr(post.url) + '" target="_blank" rel="noopener noreferrer" title="' + escapeAttr(post.title) + '">' + escapeHtml(post.title) + '</a><span class="meta">' + escapeHtml(post.time || '') + '</span>';
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
        m = re.search(r"const NEWS_DATA = (\{.*?\});", content, re.S)
        if not m:
            return {}
        data = json.loads(m.group(1))
        return {c["name"]: c for c in data.get("communities", [])}
    except Exception:
        return {}


def main():
    prev_by_name = load_prev_data()

    try:
        html_content = fetch(RANKING_URL, "euc-kr")
        parsed = parse_naver_ranking(html_content)
        fetch_error = None
    except Exception as e:
        parsed = {}
        fetch_error = str(e)

    result = {
        "generatedAt": (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S") + " KST",
        "communities": [],
    }

    for press in PRESS_LIST:
        board_url = f"https://media.naver.com/press/{press['id']}/ranking?type=popular"
        posts = parsed.get(press["id"])
        if posts:
            result["communities"].append(
                {
                    "name": press["name"],
                    "board": "많이 본 뉴스",
                    "posts": posts[:TOP_N],
                    "error": None,
                    "boardUrl": board_url,
                }
            )
            continue
        cached = prev_by_name.get(press["name"])
        if cached and cached.get("posts"):
            result["communities"].append(
                {
                    "name": press["name"],
                    "board": "많이 본 뉴스",
                    "posts": cached["posts"],
                    "error": None,
                    "stale": True,
                    "boardUrl": board_url,
                }
            )
        else:
            err = fetch_error or "해당 언론사 랭킹을 찾지 못함 - 사이트 마크업이 바뀌었을 수 있음"
            result["communities"].append(
                {"name": press["name"], "board": "많이 본 뉴스", "posts": [], "error": err, "boardUrl": board_url}
            )
        if fetch_error:
            print(f"[warn] ranking page fetch failed: {fetch_error}")

    data_json = json.dumps(result, ensure_ascii=False)
    page = PAGE_TEMPLATE.replace("__DATA_JSON__", data_json)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(page)

    print("Wrote", OUT_PATH, "-", len(page), "bytes")


if __name__ == "__main__":
    main()
