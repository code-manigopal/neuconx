"""
NeuConX — Document Generator
Hybrid PDF engine: weasyprint (HTML/CSS, best styling) when available,
reportlab (pure-Python, always works, no system deps) as guaranteed fallback.

SECURITY:
- No user-controlled file paths — filenames are generated server-side (uuid)
- Content is rendered as text, never executed
- weasyprint import is optional and isolated — failure never crashes the app
"""

import re
import uuid
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Optional weasyprint ────────────────────────────────────────────────────────
WEASYPRINT_AVAILABLE = False
try:
    from weasyprint import HTML as _WeasyHTML
    WEASYPRINT_AVAILABLE = True
except Exception as e:
    logger.info(f"weasyprint not available — PDF generation will use reportlab only ({type(e).__name__})")

# ── reportlab (always required) ──────────────────────────────────────────────
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    ListFlowable, ListItem, Preformatted, HRFlowable, PageBreak
)
from reportlab.lib.enums import TA_LEFT


# ── Themes ─────────────────────────────────────────────────────────────────────
THEMES = {
    'ncx': {
        'name': 'NCX Dark',
        'page_bg':    '#080B12',
        'text':       '#C8D6E5',
        'heading':    '#00D4FF',
        'accent':     '#00B386',
        'muted':      '#7A8B9A',
        'code_bg':    '#0F1924',
        'code_text':  '#A8E6CF',
        'table_head_bg': '#00B4C8',
        'table_head_text': '#080B12',
        'table_row_alt': '#101A24',
        'border':     '#1E2D3D',
    },
    'professional': {
        'name': 'Clean Professional',
        'page_bg':    '#FFFFFF',
        'text':       '#1A1A1A',
        'heading':    '#0A4A6E',
        'accent':     '#0A4A6E',
        'muted':      '#5A6470',
        'code_bg':    '#F5F7F8',
        'code_text':  '#1A1A1A',
        'table_head_bg': '#0A4A6E',
        'table_head_text': '#FFFFFF',
        'table_row_alt': '#F0F4F7',
        'border':     '#DDE3E8',
    },
}


# ── Markdown tokenizer (mirrors static/js/app.js simpleMdTokenize) ─────────────
def tokenize_markdown(src: str) -> list:
    """Block-level markdown tokenizer. Same logic as the frontend's
    simpleMdTokenize so PDF output matches what the user sees in chat."""
    tokens = []
    lines = src.split('\n')
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        # Fenced code block
        if line.startswith('```'):
            lang = line[3:].strip()
            code = []
            i += 1
            while i < n and not lines[i].startswith('```'):
                code.append(lines[i])
                i += 1
            i += 1
            tokens.append({'type': 'code', 'lang': lang, 'text': '\n'.join(code)})
            continue

        # Heading
        hm = re.match(r'^(#{1,6})\s+(.+)$', line)
        if hm:
            tokens.append({'type': 'heading', 'depth': len(hm.group(1)), 'text': hm.group(2)})
            i += 1
            continue

        # HR
        if re.match(r'^(?:---+|===+|\*\*\*+)\s*$', line.strip()):
            tokens.append({'type': 'hr'})
            i += 1
            continue

        # Blockquote
        if line.startswith('> '):
            bq = []
            while i < n and lines[i].startswith('> '):
                bq.append(lines[i][2:])
                i += 1
            tokens.append({'type': 'blockquote', 'text': '\n'.join(bq)})
            continue

        # Unordered list
        if re.match(r'^[\-\*\+] ', line):
            items = []
            while i < n and re.match(r'^[\-\*\+] ', lines[i]):
                items.append(re.sub(r'^[\-\*\+] ', '', lines[i]))
                i += 1
            tokens.append({'type': 'ul', 'items': items})
            continue

        # Ordered list
        if re.match(r'^\d+[\.\)] ', line):
            items = []
            while i < n and re.match(r'^\d+[\.\)] ', lines[i]):
                items.append(re.sub(r'^\d+[\.\)] ', '', lines[i]))
                i += 1
            tokens.append({'type': 'ol', 'items': items})
            continue

        # Table
        if '|' in line and i + 1 < n and re.search(r'\|[\s\-:]+\|', lines[i + 1]):
            headers = [c.strip() for c in line.split('|') if c.strip()]
            i += 2
            rows = []
            while i < n and '|' in lines[i] and lines[i].strip():
                rows.append([c.strip() for c in lines[i].split('|') if c.strip()])
                i += 1
            tokens.append({'type': 'table', 'headers': headers, 'rows': rows})
            continue

        # Paragraph
        p_lines = []
        while (i < n and lines[i].strip()
               and not re.match(r'^#{1,6} ', lines[i])
               and not lines[i].startswith('```')
               and not re.match(r'^[\-\*\+] ', lines[i])
               and not re.match(r'^\d+[\.\)] ', lines[i])
               and not lines[i].startswith('> ')
               and not re.match(r'^(?:---+|===+|\*\*\*+)\s*$', lines[i].strip())
               and not ('|' in lines[i] and i + 1 < n and re.search(r'\|[\s\-:]+\|', lines[i + 1]))):
            p_lines.append(lines[i])
            i += 1
        if p_lines:
            tokens.append({'type': 'paragraph', 'text': '\n'.join(p_lines)})

    return tokens


# ── Inline markdown -> safe XML for reportlab Paragraph ────────────────────────
def _inline_to_rl_xml(text: str) -> str:
    """Convert **bold**, *italic*, `code` to reportlab's mini-XML, escaping
    everything else so user content can never break the markup."""
    # Escape XML special chars first
    text = (text.replace('&', '&amp;')
                 .replace('<', '&lt;')
                 .replace('>', '&gt;'))
    # Inline code (do before bold/italic so backticks don't interfere)
    text = re.sub(r'`([^`]+)`', r'<font face="Courier">\1</font>', text)
    # Bold
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    # Italic
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', text)
    return text


# ── reportlab PDF builder ────────────────────────────────────────────────────
def _build_reportlab_pdf(content: str, out_path: Path, theme_key: str, title: str = None):
    theme = THEMES.get(theme_key, THEMES['professional'])
    tokens = tokenize_markdown(content)

    page_bg   = colors.HexColor(theme['page_bg'])
    text_col  = colors.HexColor(theme['text'])
    head_col  = colors.HexColor(theme['heading'])
    muted_col = colors.HexColor(theme['muted'])
    code_bg   = colors.HexColor(theme['code_bg'])
    code_text = colors.HexColor(theme['code_text'])
    th_bg     = colors.HexColor(theme['table_head_bg'])
    th_text   = colors.HexColor(theme['table_head_text'])
    row_alt   = colors.HexColor(theme['table_row_alt'])
    border    = colors.HexColor(theme['border'])

    styles = getSampleStyleSheet()

    base = ParagraphStyle('NCXBody', parent=styles['Normal'],
                           fontName='Helvetica', fontSize=10.5, leading=15,
                           textColor=text_col, spaceAfter=8)

    h_styles = {}
    sizes = {1: 22, 2: 17, 3: 14, 4: 12, 5: 11, 6: 11}
    for depth, size in sizes.items():
        h_styles[depth] = ParagraphStyle(
            f'NCXHeading{depth}', parent=styles['Heading%d' % min(depth, 6)],
            fontName='Helvetica-Bold', fontSize=size, leading=size + 6,
            textColor=head_col, spaceBefore=12, spaceAfter=6,
        )

    quote_style = ParagraphStyle('NCXQuote', parent=base, fontName='Helvetica-Oblique',
                                  textColor=muted_col, leftIndent=18, spaceAfter=8)

    bullet_style = ParagraphStyle('NCXBullet', parent=base, leftIndent=16,
                                   bulletIndent=4, spaceAfter=3)

    code_style = ParagraphStyle('NCXCode', parent=base, fontName='Courier',
                                 fontSize=9, leading=12, textColor=code_text,
                                 backColor=code_bg, borderPadding=8,
                                 spaceAfter=8)

    elements = []

    if title:
        elements.append(Paragraph(_inline_to_rl_xml(title), h_styles[1]))
        elements.append(Spacer(1, 6))
        elements.append(HRFlowable(width='100%', color=border, thickness=0.75))
        elements.append(Spacer(1, 10))

    for token in tokens:
        ttype = token['type']

        if ttype == 'heading':
            depth = min(token['depth'], 6)
            elements.append(Paragraph(_inline_to_rl_xml(token['text']), h_styles[depth]))

        elif ttype == 'paragraph':
            text = _inline_to_rl_xml(token['text']).replace('\n', '<br/>')
            elements.append(Paragraph(text, base))

        elif ttype in ('ul', 'ol'):
            items = []
            for idx, item in enumerate(token['items']):
                if ttype == 'ol':
                    items.append(ListItem(
                        Paragraph(_inline_to_rl_xml(item), bullet_style),
                        leftIndent=16, value=idx + 1,
                    ))
                else:
                    items.append(ListItem(
                        Paragraph(_inline_to_rl_xml(item), bullet_style),
                        leftIndent=16,
                    ))
            elements.append(ListFlowable(
                items, bulletType='bullet' if ttype == 'ul' else '1',
                start='circle' if ttype == 'ul' else 1,
                bulletFontName='Helvetica', bulletColor=text_col,
            ))
            elements.append(Spacer(1, 6))

        elif ttype == 'code':
            # Preformatted preserves whitespace/monospacing exactly
            code_text_block = token['text']
            pre = Preformatted(code_text_block, code_style, dedent=0)
            elements.append(pre)
            elements.append(Spacer(1, 6))

        elif ttype == 'table':
            headers = token['headers']
            rows = token['rows']
            cell_style = ParagraphStyle('NCXCell', parent=base, fontSize=9, leading=12, spaceAfter=0)
            header_style = ParagraphStyle('NCXCellHead', parent=cell_style,
                                           fontName='Helvetica-Bold', textColor=th_text)

            table_data = []
            table_data.append([Paragraph(_inline_to_rl_xml(h), header_style) for h in headers])
            for row in rows:
                # Pad short rows
                padded = row + [''] * (len(headers) - len(row))
                table_data.append([Paragraph(_inline_to_rl_xml(c), cell_style) for c in padded[:len(headers)]])

            col_width = (A4[0] - 30 * mm) / max(len(headers), 1)
            t = Table(table_data, colWidths=[col_width] * len(headers), repeatRows=1)

            style_cmds = [
                ('BACKGROUND', (0, 0), (-1, 0), th_bg),
                ('TEXTCOLOR',  (0, 0), (-1, 0), th_text),
                ('GRID', (0, 0), (-1, -1), 0.5, border),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 5),
                ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]
            for ri in range(1, len(table_data)):
                if ri % 2 == 0:
                    style_cmds.append(('BACKGROUND', (0, ri), (-1, ri), row_alt))
            t.setStyle(TableStyle(style_cmds))
            elements.append(t)
            elements.append(Spacer(1, 10))

        elif ttype == 'blockquote':
            text = _inline_to_rl_xml(token['text']).replace('\n', '<br/>')
            elements.append(Paragraph(text, quote_style))

        elif ttype == 'hr':
            elements.append(Spacer(1, 4))
            elements.append(HRFlowable(width='100%', color=border, thickness=0.5))
            elements.append(Spacer(1, 8))

    def _on_page(canvas, doc):
        # Page background (for dark theme) + footer
        canvas.saveState()
        if theme_key == 'ncx':
            canvas.setFillColor(page_bg)
            canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(muted_col)
        canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {doc.page}")
        canvas.drawString(15 * mm, 10 * mm, "Generated by NeuConX")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=title or "NeuConX Document",
    )
    doc.build(elements, onFirstPage=_on_page, onLaterPages=_on_page)


# ── weasyprint PDF builder ──────────────────────────────────────────────────
def _markdown_to_html(content: str, theme_key: str, title: str = None) -> str:
    """Render markdown tokens to themed HTML for weasyprint."""
    theme = THEMES.get(theme_key, THEMES['professional'])
    tokens = tokenize_markdown(content)

    def inline(text):
        text = (text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
        text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
        text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', text)
        text = text.replace('\n', '<br>')
        return text

    body = []
    if title:
        body.append(f'<h1 class="doc-title">{inline(title)}</h1><hr>')

    for token in tokens:
        t = token['type']
        if t == 'heading':
            d = min(token['depth'], 6)
            body.append(f'<h{d}>{inline(token["text"])}</h{d}>')
        elif t == 'paragraph':
            body.append(f'<p>{inline(token["text"])}</p>')
        elif t in ('ul', 'ol'):
            tag = 'ul' if t == 'ul' else 'ol'
            items = ''.join(f'<li>{inline(i)}</li>' for i in token['items'])
            body.append(f'<{tag}>{items}</{tag}>')
        elif t == 'code':
            escaped = (token['text'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
            body.append(f'<pre><code>{escaped}</code></pre>')
        elif t == 'table':
            head = ''.join(f'<th>{inline(h)}</th>' for h in token['headers'])
            rows_html = ''
            for row in token['rows']:
                padded = row + [''] * (len(token['headers']) - len(row))
                rows_html += '<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in padded[:len(token['headers'])]) + '</tr>'
            body.append(f'<table><thead><tr>{head}</tr></thead><tbody>{rows_html}</tbody></table>')
        elif t == 'blockquote':
            body.append(f'<blockquote>{inline(token["text"])}</blockquote>')
        elif t == 'hr':
            body.append('<hr>')

    css = f"""
    @page {{
        size: A4;
        margin: 20mm;
        @bottom-left {{ content: "Generated by NeuConX"; font-size: 8px; color: {theme['muted']}; }}
        @bottom-right {{ content: "Page " counter(page); font-size: 8px; color: {theme['muted']}; }}
    }}
    body {{
        font-family: 'Helvetica', 'Arial', sans-serif;
        font-size: 10.5pt;
        line-height: 1.5;
        color: {theme['text']};
        background: {theme['page_bg']};
    }}
    h1, h2, h3, h4, h5, h6 {{ color: {theme['heading']}; font-weight: 700; margin-top: 1em; margin-bottom: 0.4em; }}
    h1.doc-title {{ font-size: 22pt; }}
    h1 {{ font-size: 18pt; }} h2 {{ font-size: 15pt; }} h3 {{ font-size: 13pt; }}
    h4, h5, h6 {{ font-size: 11pt; }}
    p {{ margin: 0 0 8px 0; }}
    code {{ font-family: 'Courier New', monospace; background: {theme['code_bg']}; color: {theme['code_text']}; padding: 1px 4px; border-radius: 3px; }}
    pre {{ background: {theme['code_bg']}; color: {theme['code_text']}; padding: 10px; border-radius: 4px; overflow-x: auto; font-family: 'Courier New', monospace; font-size: 9pt; }}
    pre code {{ background: none; padding: 0; }}
    table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 9.5pt; }}
    th {{ background: {theme['table_head_bg']}; color: {theme['table_head_text']}; text-align: left; padding: 6px 8px; }}
    td {{ border: 0.5px solid {theme['border']}; padding: 5px 8px; }}
    tr:nth-child(even) td {{ background: {theme['table_row_alt']}; }}
    blockquote {{ border-left: 3px solid {theme['accent']}; margin: 8px 0; padding: 4px 12px; color: {theme['muted']}; font-style: italic; }}
    hr {{ border: none; border-top: 0.75px solid {theme['border']}; margin: 10px 0; }}
    ul, ol {{ margin: 4px 0 8px 22px; padding: 0; }}
    li {{ margin-bottom: 3px; }}
    """

    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{''.join(body)}</body></html>"


def _build_weasyprint_pdf(content: str, out_path: Path, theme_key: str, title: str = None):
    html_str = _markdown_to_html(content, theme_key, title)
    _WeasyHTML(string=html_str).write_pdf(str(out_path))


# ── Public API ─────────────────────────────────────────────────────────────────
def generate_document_pdf(content: str, output_dir: Path, theme: str = 'professional',
                           title: str = None, engine: str = 'auto') -> dict:
    """
    Generate a themed PDF from markdown content.

    Hybrid engine selection:
    - 'auto' (default): use weasyprint if available (best CSS styling for
      headings/quotes/general layout); reportlab is the guaranteed fallback
      and is also more robust for documents with many/large tables, since
      it paginates Table flowables natively.
    - 'reportlab' / 'weasyprint': force a specific engine.

    Returns: {filename, path, engine_used, size}
    """
    if theme not in THEMES:
        theme = 'professional'

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"neuconx-doc-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.pdf"
    out_path = output_dir / filename

    # Heuristic: documents with 2+ tables lean on reportlab's native table
    # pagination even in 'auto' mode, since weasyprint table page-breaks
    # can be inconsistent across versions/system fonts.
    tokens = tokenize_markdown(content)
    table_count = sum(1 for t in tokens if t['type'] == 'table')

    engine_used = engine
    if engine == 'auto':
        if WEASYPRINT_AVAILABLE and table_count < 2:
            engine_used = 'weasyprint'
        else:
            engine_used = 'reportlab'

    try:
        if engine_used == 'weasyprint' and WEASYPRINT_AVAILABLE:
            _build_weasyprint_pdf(content, out_path, theme, title)
        else:
            engine_used = 'reportlab'
            _build_reportlab_pdf(content, out_path, theme, title)
    except Exception as e:
        # Hybrid fallback: if weasyprint fails at runtime for any reason
        # (missing Pango/Cairo on Windows etc.), fall back to reportlab.
        logger.warning(f"PDF engine '{engine_used}' failed ({type(e).__name__}: {str(e)[:150]}) — falling back to reportlab")
        engine_used = 'reportlab'
        _build_reportlab_pdf(content, out_path, theme, title)

    size = out_path.stat().st_size
    return {
        'filename': filename,
        'path': str(out_path),
        'engine_used': engine_used,
        'size': size,
        'theme': theme,
    }