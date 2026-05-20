"""
Form Probe Script
==================
Opens the Karama registration page in a VISIBLE browser,
dumps every form element (inputs, selects, textareas, buttons, checkboxes)
with their IDs, names, types, and labels to 'form_elements.txt'.

Run this ONCE, then share the output file with me.

Usage:
    pip install playwright
    python -m playwright install chromium
    python probe_form.py
"""

import asyncio
from playwright.async_api import async_playwright

TARGET = "http://karama.smcegy.com/karama/Register.aspx"
OUTPUT = "form_elements.txt"


async def probe():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        page = await browser.new_page(viewport={"width": 1366, "height": 900})

        print(f"Navigating to {TARGET} ...")
        await page.goto(TARGET, wait_until="networkidle", timeout=60_000)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(3000)

        elements = await page.evaluate("""() => {
            const results = [];
            const els = document.querySelectorAll(
                'input, select, textarea, button, [type="submit"], [role="checkbox"]'
            );
            els.forEach(el => {
                const rect = el.getBoundingClientRect();
                const label = el.closest('tr, .form-group, label, div')
                    ?.querySelector('label, .label, td:first-child')
                    ?.innerText?.trim() || '';

                let options = [];
                if (el.tagName === 'SELECT') {
                    options = Array.from(el.options).slice(0, 15).map(o => ({
                        value: o.value,
                        text: o.text.trim(),
                        selected: o.selected
                    }));
                }

                results.push({
                    tag: el.tagName,
                    type: el.type || '',
                    id: el.id || '',
                    name: el.name || '',
                    className: el.className || '',
                    value: el.value?.substring(0, 80) || '',
                    placeholder: el.placeholder || '',
                    visible: rect.width > 0 && rect.height > 0,
                    label: label.substring(0, 60),
                    options: options
                });
            });
            return results;
        }""")

        lines = []
        lines.append(f"Page Title: {await page.title()}")
        lines.append(f"URL: {page.url}")
        lines.append(f"Total form elements found: {len(elements)}")
        lines.append("=" * 100)

        for i, el in enumerate(elements, 1):
            lines.append(f"\n--- Element #{i} ---")
            lines.append(f"  Tag:         {el['tag']}")
            lines.append(f"  Type:        {el['type']}")
            lines.append(f"  ID:          {el['id']}")
            lines.append(f"  Name:        {el['name']}")
            lines.append(f"  Class:       {el['className']}")
            lines.append(f"  Value:       {el['value']}")
            lines.append(f"  Placeholder: {el['placeholder']}")
            lines.append(f"  Visible:     {el['visible']}")
            lines.append(f"  Label:       {el['label']}")
            if el.get('options'):
                lines.append(f"  Options ({len(el['options'])} shown):")
                for opt in el['options']:
                    sel = " [SELECTED]" if opt['selected'] else ""
                    lines.append(f"    value={opt['value']!r}  text={opt['text']!r}{sel}")

        full_html = await page.content()

        output = "\n".join(lines)
        with open(OUTPUT, "w", encoding="utf-8") as f:
            f.write(output)

        with open("page_source.html", "w", encoding="utf-8") as f:
            f.write(full_html)

        print(f"\nDone! {len(elements)} elements written to '{OUTPUT}'")
        print(f"Full HTML saved to 'page_source.html'")
        print("You can close the browser window now.")

        await page.wait_for_timeout(10_000)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(probe())
