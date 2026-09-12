"""Accessibility rules judged against a rendered page, not against its markup.

Reading the HTML tells you what the author wrote. It does not tell you whether
the text is legible on the colour behind it, whether a control is big enough to
hit, whether focus is visible, or whether the page still fits at 320 CSS pixels.
So the browser collects what it actually rendered, and this module judges that
snapshot.

Collection and judgement are deliberately separate: the rules here are pure and
testable without a browser, and any collector that produces the same snapshot -
Chromium today, something else later - is judged the same way.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

CRITERIA: Mapping[str, str] = {
    "1.3.1": "Info and Relationships",
    "1.4.3": "Contrast (Minimum)",
    "1.4.4": "Resize Text",
    "1.4.10": "Reflow",
    "2.4.1": "Bypass Blocks",
    "2.4.2": "Page Titled",
    "2.4.3": "Focus Order",
    "2.4.7": "Focus Visible",
    "2.5.8": "Target Size (Minimum)",
    "3.1.1": "Language of Page",
    "4.1.2": "Name, Role, Value",
    "4.1.3": "Status Messages",
}
LEVELS = ("problem", "attention")
INTERACTIVE_TAGS = frozenset({"a", "button", "input", "select", "textarea", "summary"})
NAME_EXEMPT_TYPES = frozenset({"hidden"})
MINIMUM_TARGET = 24.0
LARGE_TEXT_PX = 18.66
LARGE_BOLD_PX = 14.0
NORMAL_CONTRAST = 4.5
LARGE_CONTRAST = 3.0
REFLOW_WIDTH = 320
SUPPORTED_LANGUAGES = ("uk", "en")


def _channel(value: float) -> float:
    scaled = value / 255.0
    return scaled / 12.92 if scaled <= 0.04045 else ((scaled + 0.055) / 1.055) ** 2.4


def relative_luminance(colour: Sequence[float]) -> float:
    red, green, blue = (float(part) for part in tuple(colour)[:3])
    return (
        0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)
    )


def contrast_ratio(
    foreground: Sequence[float], background: Sequence[float]
) -> float:
    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def required_contrast(font_size_px: float, bold: bool) -> float:
    size = float(font_size_px or 0)
    if size >= LARGE_TEXT_PX or (bold and size >= LARGE_BOLD_PX):
        return LARGE_CONTRAST
    return NORMAL_CONTRAST


@dataclass(frozen=True)
class Element:
    """One rendered thing, as the browser measured it."""

    selector: str
    tag: str
    role: str = ""
    name: str = ""
    text: str = ""
    visible: bool = True
    disabled: bool = False
    focusable: bool = False
    focus_style_changes: bool = True
    width: float = 0.0
    height: float = 0.0
    inline: bool = False
    exempt_target: bool = False
    font_size_px: float = 16.0
    bold: bool = False
    foreground: tuple[float, float, float] | None = None
    background: tuple[float, float, float] | None = None
    input_type: str = ""

    @property
    def interactive(self) -> bool:
        return self.tag in INTERACTIVE_TAGS or bool(self.role in {
            "button", "link", "checkbox", "radio", "textbox", "combobox", "tab",
        })

    @property
    def needs_name(self) -> bool:
        return (
            self.interactive
            and self.visible
            and not self.disabled
            and self.input_type not in NAME_EXEMPT_TYPES
        )


@dataclass(frozen=True)
class PageSnapshot:
    url: str
    title: str = ""
    lang: str = ""
    viewport_width: int = 0
    document_width: float = 0.0
    elements: tuple[Element, ...] = ()
    headings: tuple[str, ...] = ()
    landmarks: tuple[str, ...] = ()
    live_regions: tuple[str, ...] = ()
    status_without_live: tuple[str, ...] = ()
    first_focusable: str = ""
    skip_link_target: str = ""
    navigation_links: int = 0
    focus_order: tuple[str, ...] = ()

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "PageSnapshot":
        """Read what a collector produced, tolerating fields it did not fill."""
        elements = tuple(
            Element(
                selector=str(item.get("selector", "")),
                tag=str(item.get("tag", "")).casefold(),
                role=str(item.get("role", "")),
                name=str(item.get("name", "")).strip(),
                text=str(item.get("text", "")).strip(),
                visible=bool(item.get("visible", True)),
                disabled=bool(item.get("disabled", False)),
                focusable=bool(item.get("focusable", False)),
                focus_style_changes=bool(item.get("focus_style_changes", True)),
                width=float(item.get("width", 0) or 0),
                height=float(item.get("height", 0) or 0),
                inline=bool(item.get("inline", False)),
                exempt_target=bool(item.get("exempt_target", False)),
                font_size_px=float(item.get("font_size_px", 16) or 16),
                bold=bool(item.get("bold", False)),
                foreground=_colour(item.get("foreground")),
                background=_colour(item.get("background")),
                input_type=str(item.get("input_type", "")).casefold(),
            )
            for item in payload.get("elements", ())
        )
        return cls(
            url=str(payload.get("url", "")),
            title=str(payload.get("title", "")).strip(),
            lang=str(payload.get("lang", "")).strip(),
            viewport_width=int(payload.get("viewport_width", 0) or 0),
            document_width=float(payload.get("document_width", 0) or 0),
            elements=elements,
            headings=tuple(str(value) for value in payload.get("headings", ())),
            landmarks=tuple(str(value) for value in payload.get("landmarks", ())),
            live_regions=tuple(str(value) for value in payload.get("live_regions", ())),
            status_without_live=tuple(
                str(value) for value in payload.get("status_without_live", ())
            ),
            first_focusable=str(payload.get("first_focusable", "")),
            skip_link_target=str(payload.get("skip_link_target", "")),
            navigation_links=int(payload.get("navigation_links", 0) or 0),
            focus_order=tuple(str(value) for value in payload.get("focus_order", ())),
        )


def _colour(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    return tuple(float(part) for part in value[:3])  # type: ignore[return-value]


@dataclass(frozen=True)
class Issue:
    criterion: str
    level: str
    summary: str
    target: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        if self.criterion not in CRITERIA:
            raise ValueError(f"Unknown success criterion: {self.criterion}")
        if self.level not in LEVELS:
            raise ValueError(f"Unknown issue level: {self.level}")

    @property
    def record(self) -> dict[str, str]:
        return {
            "criterion": self.criterion,
            "criterion_name": CRITERIA[self.criterion],
            "level": self.level,
            "summary": self.summary,
            "target": self.target,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class AuditResult:
    snapshot: PageSnapshot
    issues: tuple[Issue, ...]

    @property
    def problems(self) -> tuple[Issue, ...]:
        return tuple(issue for issue in self.issues if issue.level == "problem")

    @property
    def passed(self) -> bool:
        return not self.problems

    @property
    def record(self) -> dict[str, Any]:
        return {
            "url": self.snapshot.url,
            "viewport_width": self.snapshot.viewport_width,
            "passed": self.passed,
            "problems": len(self.problems),
            "attention": len(self.issues) - len(self.problems),
            "issues": [issue.record for issue in self.issues],
        }

    def report(self) -> str:
        lines = [
            f"{self.snapshot.url} @ {self.snapshot.viewport_width}px: "
            f"{'ok' if self.passed else 'FAILED'}"
        ]
        for issue in self.issues:
            lines.append(
                f"  [{issue.level}] {issue.criterion} {CRITERIA[issue.criterion]}: "
                f"{issue.summary}" + (f" — {issue.target}" if issue.target else "")
            )
        return "\n".join(lines)


def audit(snapshot: PageSnapshot | Mapping[str, Any]) -> AuditResult:
    """Judge one rendered page. Every finding names the criterion it comes from."""
    page = (
        snapshot if isinstance(snapshot, PageSnapshot)
        else PageSnapshot.from_payload(snapshot)
    )
    issues: list[Issue] = []
    issues.extend(_document_issues(page))
    issues.extend(_element_issues(page))
    return AuditResult(page, tuple(issues))


def _document_issues(page: PageSnapshot) -> list[Issue]:
    issues: list[Issue] = []
    language = page.lang.split("-")[0].casefold()
    if not page.lang:
        issues.append(Issue(
            "3.1.1", "problem", "Сторінка не оголошує мову.",
            detail="Без lang читалка з екрана вимовляє текст чужою вимовою.",
        ))
    elif language not in SUPPORTED_LANGUAGES:
        issues.append(Issue(
            "3.1.1", "attention", f"Мова сторінки — {page.lang}.",
            detail="Основний шлях підтримується українською та англійською.",
        ))
    if not page.title:
        issues.append(Issue("2.4.2", "problem", "Сторінка без заголовка вкладки."))
    first_level = [heading for heading in page.headings if heading == "h1"]
    if not first_level:
        issues.append(Issue(
            "1.3.1", "attention", "На сторінці немає заголовка першого рівня.",
        ))
    elif len(first_level) > 1:
        issues.append(Issue(
            "1.3.1", "attention",
            f"Заголовків першого рівня {len(first_level)}, а має бути один.",
        ))
    if "main" not in page.landmarks:
        issues.append(Issue(
            "1.3.1", "attention", "На сторінці немає орієнтира main.",
        ))
    # 2.4.1 asks for a bypass only where there is a repeated block to bypass.
    # A page whose content starts immediately has nothing to skip.
    if page.navigation_links and not page.skip_link_target:
        issues.append(Issue(
            "2.4.1", "attention", "Немає посилання, що пропускає навігацію.",
            detail=f"Перед вмістом стоїть посилань: {page.navigation_links}.",
        ))
    elif (
        page.skip_link_target
        and page.first_focusable
        and page.first_focusable != page.skip_link_target
    ):
        issues.append(Issue(
            "2.4.1", "attention",
            "Посилання «до вмісту» не перше у фокусі.",
            target=page.first_focusable,
        ))
    if page.viewport_width and page.document_width > page.viewport_width + 1:
        criterion = "1.4.10" if page.viewport_width <= REFLOW_WIDTH else "1.4.4"
        issues.append(Issue(
            criterion, "problem",
            f"Сторінка ширша за вікно: {page.document_width:.0f} проти "
            f"{page.viewport_width}.",
            detail="Зʼявляється горизонтальне прокручування, і частина керування "
                   "виходить за екран.",
        ))
    for selector in page.status_without_live:
        issues.append(Issue(
            "4.1.3", "attention",
            "Повідомлення про стан не оголошується читалкою.",
            target=selector,
            detail="Додайте aria-live, щоб зміна тексту була почута без "
                   "переміщення фокуса.",
        ))
    if page.focus_order and len(page.focus_order) != len(set(page.focus_order)):
        issues.append(Issue(
            "2.4.3", "attention", "У порядку фокуса є повтори.",
        ))
    return issues


def _element_issues(page: PageSnapshot) -> list[Issue]:
    issues: list[Issue] = []
    for element in page.elements:
        if not element.visible:
            continue
        if element.needs_name and not element.name:
            issues.append(Issue(
                "4.1.2", "problem", "Керування без доступної назви.",
                target=element.selector,
                detail=f"<{element.tag}> не має ні тексту, ні мітки, ні aria-label.",
            ))
        issues.extend(_contrast_issue(element))
        issues.extend(_target_issue(element))
        if (
            element.focusable
            and not element.disabled
            and not element.focus_style_changes
        ):
            issues.append(Issue(
                "2.4.7", "problem", "Фокус на елементі нічим не позначений.",
                target=element.selector,
                detail="Той, хто працює з клавіатури, не бачить, де він.",
            ))
    return issues


def _contrast_issue(element: Element) -> list[Issue]:
    if element.foreground is None or element.background is None:
        return []
    if not element.text and not element.name:
        return []
    ratio = contrast_ratio(element.foreground, element.background)
    needed = required_contrast(element.font_size_px, element.bold)
    if ratio + 0.005 >= needed:
        return []
    return [Issue(
        "1.4.3", "problem",
        f"Контраст тексту {ratio:.2f}:1 замість {needed:g}:1.",
        target=element.selector,
        detail=f"Розмір шрифту {element.font_size_px:.0f}px"
               + (", напівжирний" if element.bold else "")
               + f"; текст: {(element.text or element.name)[:40]!r}",
    )]


def _target_issue(element: Element) -> list[Issue]:
    if not element.interactive or element.disabled or element.exempt_target:
        return []
    if element.inline:
        # An inline link inside a sentence is explicitly excepted by 2.5.8.
        return []
    if not element.width or not element.height:
        return []
    if min(element.width, element.height) + 0.5 >= MINIMUM_TARGET:
        return []
    return [Issue(
        "2.5.8", "problem",
        f"Ціль {element.width:.0f}×{element.height:.0f} менша за "
        f"{MINIMUM_TARGET:.0f}×{MINIMUM_TARGET:.0f}.",
        target=element.selector,
        detail="У маленьку ціль важко влучити пальцем або тремтячою рукою.",
    )]


def audit_pages(payloads: Iterable[Mapping[str, Any]]) -> tuple[AuditResult, ...]:
    return tuple(audit(payload) for payload in payloads)


def summarise(results: Sequence[AuditResult]) -> dict[str, Any]:
    return {
        "pages": [result.record for result in results],
        "passed": all(result.passed for result in results),
        "problems": sum(len(result.problems) for result in results),
        "criteria_checked": [
            {"criterion": key, "name": value} for key, value in sorted(CRITERIA.items())
        ],
    }


COLLECTOR_SCRIPT = r"""
() => {
  const interactive = 'a, button, input, select, textarea, summary, [role], [tabindex]';
  const rgb = value => {
    const match = String(value || '').match(/rgba?\(([^)]+)\)/);
    if (!match) return null;
    const parts = match[1].split(',').map(part => parseFloat(part.trim()));
    if (parts.length >= 4 && parts[3] === 0) return null;
    return parts.slice(0, 3);
  };
  const backgroundOf = node => {
    let current = node;
    while (current && current !== document.documentElement) {
      const colour = rgb(getComputedStyle(current).backgroundColor);
      if (colour) return colour;
      current = current.parentElement;
    }
    const body = rgb(getComputedStyle(document.body).backgroundColor);
    return body || [255, 255, 255];
  };
  const nameOf = node => {
    const label = node.getAttribute('aria-label');
    if (label) return label.trim();
    const labelled = node.getAttribute('aria-labelledby');
    if (labelled) {
      const target = document.getElementById(labelled);
      if (target) return (target.textContent || '').trim();
    }
    if (node.labels && node.labels.length) {
      return Array.from(node.labels).map(item => item.textContent.trim()).join(' ');
    }
    const title = node.getAttribute('title');
    if (title) return title.trim();
    if (node.tagName === 'INPUT' && node.type === 'submit') return node.value || '';
    return (node.textContent || '').trim();
  };
  const seen = new Map();
  const selectorOf = node => {
    if (node.id) return `#${node.id}`;
    const tag = node.tagName.toLowerCase();
    const text = (node.textContent || '').trim().slice(0, 24);
    const base = text ? `${tag}[${text}]` : tag;
    // Repeated labels are normal on a settings page; a stable index keeps the
    // focus-order check about order rather than about naming.
    const count = (seen.get(base) || 0) + 1;
    seen.set(base, count);
    return count === 1 ? base : `${base}#${count}`;
  };
  // Split on top-level commas only: a comma inside :is(...) or :where(...) is
  // part of one selector, and splitting there produces invalid fragments.
  const splitSelector = text => {
    const parts = [];
    let depth = 0, current = '';
    for (const character of text) {
      if (character === '(') depth += 1;
      if (character === ')') depth -= 1;
      if (character === ',' && depth === 0) { parts.push(current); current = ''; continue; }
      current += character;
    }
    if (current.trim()) parts.push(current);
    return parts;
  };
  const focusSelectors = [];
  const walk = list => {
    for (const rule of list) {
      if (rule.selectorText && rule.selectorText.includes(':focus')) {
        for (const part of splitSelector(rule.selectorText)) {
          const base = part.trim().replace(/:focus-visible|:focus-within|:focus/g, '');
          if (base) focusSelectors.push(base);
        }
      }
      // A plain style rule now also exposes an (empty) cssRules list because of
      // CSS nesting, so recurse only when there is something in it.
      if (rule.cssRules && rule.cssRules.length) walk(Array.from(rule.cssRules));
    }
  };
  for (const sheet of Array.from(document.styleSheets)) {
    try { walk(Array.from(sheet.cssRules || [])); } catch (error) { continue; }
  }
  // A ring declared for :focus-visible is the correct modern pattern, and a
  // programmatic focus() would not trigger it. So ask the stylesheet whether a
  // focus rule applies to this element rather than poking the live style.
  const focusVisible = node => focusSelectors.some(selector => {
    try { return node.matches(selector); } catch (error) { return false; }
  });
  const nodes = Array.from(document.querySelectorAll(interactive));
  const elements = nodes.map(node => {
    const style = getComputedStyle(node);
    const box = node.getBoundingClientRect();
    const visible = style.display !== 'none' && style.visibility !== 'hidden'
      && Number(style.opacity) !== 0 && (box.width > 0 || box.height > 0);
    const tabbable = !node.disabled && visible && node.tabIndex >= 0;
    return {
      selector: selectorOf(node),
      tag: node.tagName.toLowerCase(),
      role: node.getAttribute('role') || '',
      name: nameOf(node),
      text: (node.textContent || '').trim(),
      visible,
      disabled: Boolean(node.disabled),
      focusable: tabbable,
      focus_style_changes: tabbable ? focusVisible(node) : true,
      width: box.width,
      height: box.height,
      inline: style.display === 'inline' && node.tagName === 'A',
      exempt_target: node.hasAttribute('data-target-exempt'),
      font_size_px: parseFloat(style.fontSize) || 16,
      bold: parseInt(style.fontWeight, 10) >= 700,
      foreground: rgb(style.color),
      background: backgroundOf(node),
      input_type: (node.getAttribute('type') || '').toLowerCase(),
    };
  });
  const statuses = Array.from(document.querySelectorAll('[role="status"], #status, #summary, #notice'));
  const skip = document.querySelector('a.skip, a[href^="#main"]');
  const tabbables = nodes.filter(node => !node.disabled && node.tabIndex >= 0
    && node.getBoundingClientRect().width > 0);
  return {
    url: location.pathname,
    title: document.title,
    lang: document.documentElement.lang || '',
    viewport_width: window.innerWidth,
    document_width: document.documentElement.scrollWidth,
    elements,
    headings: Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'))
      .filter(node => node.getClientRects().length > 0)
      .map(node => node.tagName.toLowerCase()),
    landmarks: Array.from(document.querySelectorAll('main, nav, header, footer, aside, [role]'))
      .map(node => (node.getAttribute('role') || node.tagName.toLowerCase())),
    live_regions: Array.from(document.querySelectorAll('[aria-live]')).map(selectorOf),
    status_without_live: statuses.filter(node => !node.hasAttribute('aria-live'))
      .map(selectorOf),
    navigation_links: document.querySelectorAll('header a, nav a').length,
    first_focusable: tabbables.length ? selectorOf(tabbables[0]) : '',
    skip_link_target: skip ? selectorOf(skip) : '',
    focus_order: tabbables.map(selectorOf),
  };
}
"""
