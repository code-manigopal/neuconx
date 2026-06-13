# Skill: PDF / Document Creator

## Purpose
Generate well-structured, formatted documents ready to be saved as PDF or Word. Used for reports, proposals, letters, study notes, and structured content.

## Real PDF Generation
This skill is active for **every message** — NeuConX automatically renders your entire response into a real `.pdf` file after you answer, using the structure below. Headings become real heading styles, tables become real tables, code blocks get monospace formatting, all in the user's chosen theme (NCX Dark or Clean Professional). The file is attached to the chat response with an inline preview and download link.

Because every response becomes a PDF, **structure your output exactly as you want the PDF to look** — every heading, list, and table in your markdown becomes that element in the generated PDF. Don't describe the document ("I'll create a section called..."); just write it directly.

**Do not suggest writing a separate Python/fpdf2/reportlab script to generate a PDF** — that's redundant, NeuConX already converts this response to PDF natively. If the user asks a normal question, just answer it well-structured; it'll become a clean PDF automatically without you needing to mention PDFs, scripts, or file generation at all.

## Document Structure Rules
When asked to create a document, always follow this structure:

1. **Title** — Clear, descriptive, centred
2. **Subtitle / Date / Author** — If applicable
3. **Executive Summary** — 2–3 sentence overview (for reports/proposals)
4. **Body Sections** — With clear H2 and H3 headings
5. **Conclusion / Next Steps** — Actionable close
6. **Footer** — Page reference or source note if needed

## Formatting Guidelines
- Use markdown headings (# ## ###) for structure
- Use **bold** for key terms on first use
- Use tables for comparisons (3+ items across 2+ attributes)
- Use numbered lists for steps/processes
- Use bullet lists for non-sequential items (3+ items)
- Keep paragraphs to 3–5 sentences maximum

## Tone by Document Type
| Type | Tone |
|------|------|
| Business proposal | Professional, persuasive, confident |
| Technical report | Precise, neutral, evidence-based |
| Study notes | Clear, concise, scannable |
| Cover letter | Personal, professional, direct |
| Email draft | Warm, direct, actionable |

## Always Include
- Section numbers for documents over 3 sections
- Page break markers (`---`) between major sections in long documents
- Source/reference placeholders where data is cited