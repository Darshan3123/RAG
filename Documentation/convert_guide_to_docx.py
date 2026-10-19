"""
Converter script: API_SPECIFICATION_AND_PARTITION_GUIDE.md -> API_SPECIFICATION_AND_PARTITION_GUIDE.docx
Generates an executive-ready, beautifully styled Word document.
"""

import os
import re
import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tcPr.append(tcMar)

def set_cell_shading(cell, color_hex):
    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
    cell._tc.get_or_add_tcPr().append(shading)

def set_cell_borders(cell, top="CCCCCC", bottom="CCCCCC", left=None, right=None):
    tcPr = cell._tc.get_or_add_tcPr()
    borders_xml = f'<w:tcBorders {nsdecls("w")}>'
    if top:
        borders_xml += f'<w:top w:val="single" w:sz="4" w:space="0" w:color="{top}"/>'
    else:
        borders_xml += '<w:top w:val="none"/>'
    if bottom:
        borders_xml += f'<w:bottom w:val="single" w:sz="4" w:space="0" w:color="{bottom}"/>'
    else:
        borders_xml += '<w:bottom w:val="none"/>'
    if left:
        borders_xml += f'<w:left w:val="single" w:sz="4" w:space="0" w:color="{left}"/>'
    else:
        borders_xml += '<w:left w:val="none"/>'
    if right:
        borders_xml += f'<w:right w:val="single" w:sz="4" w:space="0" w:color="{right}"/>'
    else:
        borders_xml += '<w:right w:val="none"/>'
    borders_xml += '</w:tcBorders>'
    tcPr.append(parse_xml(borders_xml))

def add_code_block(doc, code_text, lang=""):
    """Adds a shaded monospace code box."""
    # Create a 1x1 table for reliable background shading and border
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.columns[0].width = Inches(6.8)
    
    cell = table.cell(0, 0)
    set_cell_shading(cell, "F3F4F6")
    
    # Left blue accent border, light gray for others
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="4" w:space="0" w:color="E5E7EB"/>'
        f'<w:bottom w:val="single" w:sz="4" w:space="0" w:color="E5E7EB"/>'
        f'<w:left w:val="single" w:sz="24" w:space="0" w:color="2563EB"/>'
        f'<w:right w:val="single" w:sz="4" w:space="0" w:color="E5E7EB"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)
    set_cell_margins(cell, top=120, bottom=120, left=180, right=150)
    
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.05
    
    lines = code_text.split("\n")
    for idx, line in enumerate(lines):
        if idx > 0:
            p = cell.add_paragraph()
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.05
        
        run = p.add_run(line if line else " ")
        run.font.name = "Consolas"
        run.font.size = Pt(8.5)
        run.font.color.rgb = RGBColor(30, 41, 59)
    
    # Add small spacer after code block
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(4)

def add_callout(doc, text_lines):
    """Adds a callout block with a left border and subtle shading."""
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.columns[0].width = Inches(6.8)
    cell = table.cell(0, 0)
    set_cell_shading(cell, "EFF6FF")
    
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:top w:val="none"/>'
        f'<w:bottom w:val="none"/>'
        f'<w:left w:val="single" w:sz="24" w:space="0" w:color="3B82F6"/>'
        f'<w:right w:val="none"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)
    set_cell_margins(cell, top=100, bottom=100, left=180, right=140)
    
    for idx, line in enumerate(text_lines):
        if idx == 0:
            p = cell.paragraphs[0]
        else:
            p = cell.add_paragraph()
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(2)
        render_formatted_runs(p, line, default_color=RGBColor(30, 58, 138), font_size=Pt(9.5))

def render_formatted_runs(paragraph, text, default_color=RGBColor(30, 41, 59), font_size=Pt(10), default_bold=False):
    """Parses markdown bold, italic, code spans and adds runs."""
    # Pattern to match **bold**, `code`, *italic*
    tokens = re.split(r'(\*\*.*?\*\*|`.*?`|\*.*?\*)', text)
    for token in tokens:
        if not token:
            continue
        if token.startswith("**") and token.endswith("**") and len(token) >= 4:
            run = paragraph.add_run(token[2:-2])
            run.bold = True
            run.font.color.rgb = default_color
            run.font.size = font_size
            run.font.name = "Segoe UI"
        elif token.startswith("`") and token.endswith("`") and len(token) >= 2:
            run = paragraph.add_run(token[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt(font_size.pt * 0.92)
            run.font.color.rgb = RGBColor(194, 24, 91) # Berry pink for inline code
        elif token.startswith("*") and token.endswith("*") and len(token) >= 2:
            run = paragraph.add_run(token[1:-1])
            run.italic = True
            run.font.color.rgb = default_color
            run.font.size = font_size
            run.font.name = "Segoe UI"
        else:
            run = paragraph.add_run(token)
            run.bold = default_bold
            run.font.color.rgb = default_color
            run.font.size = font_size
            run.font.name = "Segoe UI"

def build_docx(md_path, docx_path):
    doc = Document()
    
    # Page setup - 0.8 inch margins
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.85)
        section.right_margin = Inches(0.85)
    
    # Set base Normal style font
    style_normal = doc.styles['Normal']
    style_normal.font.name = 'Segoe UI'
    style_normal.font.size = Pt(10)
    style_normal.font.color.rgb = RGBColor(30, 41, 59)
    
    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    lines = md_text.splitlines()
    i = 0
    in_code_block = False
    code_lang = ""
    code_lines = []
    
    in_table = False
    table_lines = []

    while i < len(lines):
        line = lines[i]

        # Handle Code Block Start/End
        if line.strip().startswith("```"):
            if in_code_block:
                # End of code block
                add_code_block(doc, "\n".join(code_lines), code_lang)
                code_lines = []
                in_code_block = False
            else:
                # Flush pending table if any
                if in_table:
                    render_table(doc, table_lines)
                    table_lines = []
                    in_table = False
                in_code_block = True
                code_lang = line.strip()[3:].strip()
            i += 1
            continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        # Handle Markdown Table
        if line.strip().startswith("|") and line.strip().endswith("|"):
            in_table = True
            table_lines.append(line.strip())
            i += 1
            continue
        elif in_table:
            render_table(doc, table_lines)
            table_lines = []
            in_table = False

        stripped = line.strip()

        # Handle empty lines
        if not stripped:
            i += 1
            continue

        # Handle Horizontal Rules
        if stripped in ("---", "***", "___"):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(6)
            pBdr = parse_xml(f'<w:pBdr {nsdecls("w")}><w:bottom w:val="single" w:sz="8" w:space="1" w:color="E2E8F0"/></w:pBdr>')
            p._p.get_or_add_pPr().append(pBdr)
            i += 1
            continue

        # Handle Blockquotes / Callout groups
        if stripped.startswith(">"):
            callout_lines = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                c_line = lines[i].strip()[1:].strip()
                if c_line:
                    callout_lines.append(c_line)
                i += 1
            add_callout(doc, callout_lines)
            continue

        # Handle Headings
        if stripped.startswith("# ") and not stripped.startswith("## "):
            title_text = stripped[2:].strip()
            # Clean emojis or keep them
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(12)
            p.paragraph_format.space_after = Pt(4)
            run = p.add_run(title_text)
            run.font.name = "Segoe UI"
            run.font.size = Pt(20)
            run.bold = True
            run.font.color.rgb = RGBColor(15, 44, 89) # Deep Navy
            i += 1
            continue

        if stripped.startswith("## "):
            h2_text = stripped[3:].strip()
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(14)
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.keep_with_next = True
            run = p.add_run(h2_text)
            run.font.name = "Segoe UI"
            run.font.size = Pt(14)
            run.bold = True
            run.font.color.rgb = RGBColor(30, 58, 138) # Royal Blue
            i += 1
            continue

        if stripped.startswith("### "):
            h3_text = stripped[4:].strip()
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(3)
            p.paragraph_format.keep_with_next = True
            run = p.add_run(h3_text)
            run.font.name = "Segoe UI"
            run.font.size = Pt(11.5)
            run.bold = True
            run.font.color.rgb = RGBColor(17, 94, 89) # Teal / Dark Slate
            i += 1
            continue

        if stripped.startswith("#### "):
            h4_text = stripped[5:].strip()
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.keep_with_next = True
            run = p.add_run(h4_text)
            run.font.name = "Segoe UI"
            run.font.size = Pt(10.5)
            run.bold = True
            run.font.color.rgb = RGBColor(71, 85, 105) # Slate
            i += 1
            continue

        # Handle Bullet points
        if stripped.startswith("* ") or stripped.startswith("- "):
            bullet_text = stripped[2:].strip()
            indent_level = (len(line) - len(line.lstrip())) // 2
            p = doc.add_paragraph(style='List Bullet')
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.left_indent = Inches(0.25 * (indent_level + 1))
            render_formatted_runs(p, bullet_text, default_color=RGBColor(30, 41, 59), font_size=Pt(9.5))
            i += 1
            continue

        # Handle Numbered Lists
        num_match = re.match(r'^(\d+)\.\s+(.*)$', stripped)
        if num_match:
            num_str = num_match.group(1)
            num_text = num_match.group(2)
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.left_indent = Inches(0.25)
            run_num = p.add_run(f"{num_str}. ")
            run_num.bold = True
            run_num.font.name = "Segoe UI"
            run_num.font.size = Pt(9.5)
            render_formatted_runs(p, num_text, default_color=RGBColor(30, 41, 59), font_size=Pt(9.5))
            i += 1
            continue

        # Standard Paragraph
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing = 1.15
        render_formatted_runs(p, stripped, default_color=RGBColor(30, 41, 59), font_size=Pt(10))
        i += 1

    # Cleanup any trailing table or code block
    if in_table:
        render_table(doc, table_lines)
    if in_code_block:
        add_code_block(doc, "\n".join(code_lines), code_lang)

    # Save document
    doc.save(docx_path)
    print(f"Successfully generated Word document: {docx_path}")

def render_table(doc, table_lines):
    """Parses markdown table lines and creates an executive styled Word table."""
    if len(table_lines) < 2:
        return
    
    # Filter header separator line (|---|---|...)
    parsed_rows = []
    for line in table_lines:
        cells = [c.strip() for c in line.strip('|').split('|')]
        # check if this is separator line
        if all(re.match(r'^:?-+:?$', c) for c in cells if c):
            continue
        parsed_rows.append(cells)
        
    if not parsed_rows:
        return
        
    num_cols = max(len(r) for r in parsed_rows)
    table = doc.add_table(rows=len(parsed_rows), cols=num_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    
    for r_idx, row_data in enumerate(parsed_rows):
        is_header = (r_idx == 0)
        row = table.rows[r_idx]
        
        # Set cantSplit so rows don't break awkwardly across pages
        trPr = row._tr.get_or_add_trPr()
        trPr.append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))
        if is_header:
            trPr.append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))
            
        for c_idx in range(num_cols):
            cell = row.cells[c_idx]
            cell_text = row_data[c_idx] if c_idx < len(row_data) else ""
            
            # Styling
            if is_header:
                set_cell_shading(cell, "1E3A8A") # Navy Blue Header
                set_cell_margins(cell, top=120, bottom=120, left=140, right=140)
                set_cell_borders(cell, top="1E3A8A", bottom="1E3A8A", left="3B82F6", right="3B82F6")
            else:
                bg_color = "FFFFFF" if r_idx % 2 != 0 else "F8FAFC"
                set_cell_shading(cell, bg_color)
                set_cell_margins(cell, top=90, bottom=90, left=140, right=140)
                set_cell_borders(cell, top="E2E8F0", bottom="E2E8F0", left="E2E8F0", right="E2E8F0")
                
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
            if is_header:
                render_formatted_runs(p, cell_text, default_color=RGBColor(255, 255, 255), font_size=Pt(9.5), default_bold=True)
            else:
                render_formatted_runs(p, cell_text, default_color=RGBColor(30, 41, 59), font_size=Pt(9))

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(4)

if __name__ == "__main__":
    base_dir = r"c:\Projects\GeM\Scrapper & RAG Pipeline\Documentation"
    md_file = os.path.join(base_dir, "API_SPECIFICATION_AND_PARTITION_GUIDE.md")
    docx_file = os.path.join(base_dir, "API_SPECIFICATION_AND_PARTITION_GUIDE.docx")
    build_docx(md_file, docx_file)
