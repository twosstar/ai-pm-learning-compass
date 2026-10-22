from __future__ import annotations

import re
from urllib.parse import urlparse

from app.services.browser import browser_service

URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
CODE_RE = re.compile(r"(?:提取码|访问码|密码|口令|code)\s*[:：\s]+([A-Za-z0-9_-]{3,32})", re.IGNORECASE)
QUESTION_LINE_RE = re.compile(
    r"^\s*(?:(?:问题|question|q)\s*\d{1,3}\s*[:：.、]|\d{1,3}\s*[.、:：)）]|[-*•])\s*",
    re.IGNORECASE,
)
SCROLL_STEP_MINIMUM = 500
LEGACY_SCROLL_COUNT_CUTOFF = 1000


def normalize_source_lines(text: str) -> list[str]:
    """Keep visual paragraph boundaries so the bank can recognize one question per line."""
    lines: list[str] = []
    for line in text.replace("\r", "\n").split("\n"):
        cleaned = re.sub(r"[\t \u00a0]+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def parse_source_text(source_type: str, source_text: str) -> tuple[str, str]:
    url_match = URL_RE.search(source_text)
    if not url_match:
        raise ValueError("请提供有效的网页链接。")
    url = url_match.group(0).rstrip("，。；;)")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("链接格式不正确。")
    code_match = CODE_RE.search(source_text)
    code = code_match.group(1) if code_match else ""
    if source_type == "quark" and "quark" not in parsed.netloc.casefold():
        raise ValueError("夸克导入需要 pan.quark.cn 分享链接。")
    return url, code


async def _fill_quark_code(page, code: str) -> None:
    if not code:
        return
    fields = page.locator("input")
    for index in range(await fields.count()):
        field = fields.nth(index)
        if not await field.is_visible():
            continue
        placeholder = (await field.get_attribute("placeholder") or "").casefold()
        name = (await field.get_attribute("name") or "").casefold()
        if any(word in f"{placeholder} {name}" for word in ("密码", "提取", "code", "访问")):
            await field.fill(code)
            break


async def _scroll_state(page) -> dict[str, int]:
    return await page.evaluate("""() => {
        const preferred = document.querySelector('.bear-web-x-container');
        const candidates = [
            preferred,
            ...Array.from(document.querySelectorAll('*')).filter((node) =>
                node.scrollHeight > node.clientHeight + 80
            ),
        ].filter(Boolean);
        const target = candidates.sort(
            (a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight)
        )[0];
        if (target) {
            return {
                top: Math.round(target.scrollTop),
                max: Math.max(0, Math.round(target.scrollHeight - target.clientHeight)),
                viewport: Math.round(target.clientHeight),
                useWindow: 0,
            };
        }
        return {
            top: Math.round(window.scrollY),
            max: Math.max(0, Math.round(document.documentElement.scrollHeight - window.innerHeight)),
            viewport: Math.round(window.innerHeight),
            useWindow: 1,
        };
    }""")


async def _scroll_to(page, position: int) -> dict[str, int]:
    return await page.evaluate("""position => {
        const preferred = document.querySelector('.bear-web-x-container');
        const candidates = [
            preferred,
            ...Array.from(document.querySelectorAll('*')).filter((node) =>
                node.scrollHeight > node.clientHeight + 80
            ),
        ].filter(Boolean);
        const target = candidates.sort(
            (a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight)
        )[0];
        if (target) {
            target.scrollTop = Math.max(0, Math.min(position, target.scrollHeight - target.clientHeight));
            return { top: Math.round(target.scrollTop), max: Math.max(0, Math.round(target.scrollHeight - target.clientHeight)), viewport: Math.round(target.clientHeight), useWindow: 0 };
        }
        window.scrollTo(0, Math.max(0, position));
        return { top: Math.round(window.scrollY), max: Math.max(0, Math.round(document.documentElement.scrollHeight - window.innerHeight)), viewport: Math.round(window.innerHeight), useWindow: 1 };
    }""", position)
    buttons = page.get_by_role("button")
    for index in range(await buttons.count()):
        button = buttons.nth(index)
        if await button.is_visible() and any(word in (await button.inner_text()) for word in ("提取", "访问", "打开", "确定")):
            await button.click()
            break


async def extract_scrollable_source(source_type: str, source_text: str, start_scroll: int = 0, max_scrolls: int = 100, max_questions: int = 100) -> dict:
    url, code = parse_source_text(source_type, source_text)
    page = await browser_service.page()
    scroll_count = 0
    chunks: list[str] = []
    seen_lines: set[str] = set()
    stop_reason = "到达底部"
    keep_open = False
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        if source_type == "quark":
            await _fill_quark_code(page, code)
        await page.wait_for_timeout(1200)
        if source_type == "feishu" and await page.locator("input[type='password']").count():
            keep_open = True
            return {"status": "needs_login", "source_locator": url, "message": "飞书需要登录，请在浏览器中完成登录后重新点击继续。"}
        if start_scroll:
            initial_state = await _scroll_state(page)
            resume_position = (
                start_scroll * max(int(initial_state["viewport"] * 0.8), SCROLL_STEP_MINIMUM)
                if start_scroll < LEGACY_SCROLL_COUNT_CUTOFF
                else start_scroll
            )
            await _scroll_to(page, resume_position)
            await page.wait_for_timeout(700)
        last_state = await _scroll_state(page)
        no_growth = 0
        for _ in range(max_scrolls):
            # Read the live document. Feishu virtualizes its editor and a detached
            # clone expands hidden blocks while losing visual line breaks, which
            # merges all "问题N：" entries into one unparseable paragraph.
            text = await page.evaluate("""() => {
                let text = document.body.innerText || '';
                document.querySelectorAll('table,.tbl,.table').forEach((table) => {
                    const tableText = table.innerText || '';
                    if (tableText) text = text.replace(tableText, '');
                });
                return text;
            }""")
            for line in normalize_source_lines(text):
                # The complete document is returned on every scroll. Keep each
                # line once, retaining question boundaries without repeating
                # the already-seen page on every iteration.
                if line not in seen_lines:
                    seen_lines.add(line)
                    chunks.append(line)
            estimated_questions = sum(1 for line in chunks if QUESTION_LINE_RE.match(line))
            if estimated_questions >= max_questions:
                last_state = await _scroll_to(
                    page, last_state["top"] + max(int(last_state["viewport"] * 0.8), SCROLL_STEP_MINIMUM)
                )
                stop_reason = "达到单次题目上限"
                break
            before = await _scroll_state(page)
            last_state = await _scroll_to(
                page, before["top"] + max(int(before["viewport"] * 0.8), SCROLL_STEP_MINIMUM)
            )
            await page.wait_for_timeout(700)
            scroll_count += 1
            if last_state["top"] <= before["top"] + 1:
                no_growth += 1
            else:
                no_growth = 0
            if last_state["top"] >= last_state["max"] - 8:
                stop_reason = "到达底部"
                break
            if no_growth >= 2:
                stop_reason = "连续两轮无新增内容"
                break
        else:
            stop_reason = "达到滚动上限"
        raw_text = "\n\n".join(chunks)
        return {"status": "ready", "source_locator": url, "raw_text": raw_text[:200_000], "character_count": len(raw_text), "scroll_count": scroll_count, "source_cursor": last_state["top"], "stop_reason": stop_reason, "message": "已提取正文，可生成题目预览。"}
    finally:
        if not keep_open:
            await page.close()


interview_source_service = extract_scrollable_source
