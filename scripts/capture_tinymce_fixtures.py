#!/usr/bin/env python
"""
Capture what TinyMCE stores when Django template snippets are loaded in or typed into the editor.

The captures are used by the tests as real-world templates, so that the renderer is checked against what the editor
actually produces. Run this script again when upgrading the supported TinyMCE version.

Usage:
    pip install playwright && playwright install chromium
    python scripts/capture_tinymce_fixtures.py <directory containing tinymce.min.js> tests/fixtures/tinymce.json

The TinyMCE directory can be the one shipped by django-tinymce, i.e. "<site-packages>/tinymce/static/tinymce".
"""
import json
import mimetypes
import pathlib
import sys

from playwright.sync_api import sync_playwright

ORIGIN = 'https://site.example'
PAGE_URL = ORIGIN + '/notifications/add/'

CONFIGS = {
    'tinymce-defaults': {},
    # The configuration recommended in the README.
    'recommended': {
        'entity_encoding': 'raw',
        'relative_urls': False,
        'convert_urls': False,
        'remove_script_host': False,
    },
}

# Content loaded in the editor, e.g. an existing message that is edited again.
LOADED = {
    'operator-alias': '<p>{% if recipient.age -gte 18 %}Adult{% endif %}</p>',
    'string-literals': '<p>{{ event.start_date|date:"d.m.Y" }} {% firstof recipient.nickname \'friend\' %}</p>',
    'accented-literal': '<p>{% if recipient.first_name == "Hélène" %}yes{% endif %} {{ event.note|default:"Réservé" }}</p>',
    'href-variable': '<p><a href="{{ recipient.profile_url }}">profile</a></p>',
    'href-same-host': f'<p><a href="{ORIGIN}/events/?id={{{{ event.pk }}}}">event</a></p>',
    'img-variable': '<p><img src="{{ club.logo_url }}" alt="logo"></p>',
    'nbsp-text': '<p>Hello&nbsp;{{ recipient.first_name }}&nbsp;!</p>',
    'typography': '<p>Prix&nbsp;: 10 € – « offre » l’été</p>',
    'bold-variable': '<p>Hello {{ <strong>recipient.first_name</strong> }}</p>',
    'block-tag-paragraphs': '<p>{% if recipient.age -gte 18 %}</p><p>Adult</p><p>{% endif %}</p>',
}

# Content typed key by key in an empty editor.
TYPED = {
    'typed-comparison': '{% if recipient.age >= 18 %}Adult{% endif %}',
    'typed-operator-alias': '{% if recipient.age -gte 18 %}Adult{% endif %}',
    'typed-double-space': 'Hello  {{ recipient.first_name }}',
    'typed-double-space-in-tag': '{% if recipient.age  -gte 18 %}Adult{% endif %}',
    'typed-accented-literal': '{{ event.note|default:"Réservé" }}',
}

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<script src="/static/tinymce/tinymce.min.js"></script></head>
<body><textarea id="editor"></textarea></body></html>"""


def main(tinymce_dir: pathlib.Path, output: pathlib.Path) -> None:
    def serve(route):
        url = route.request.url
        if url == PAGE_URL:
            return route.fulfill(status=200, body=PAGE, content_type='text/html')
        prefix = ORIGIN + '/static/tinymce/'
        if url.startswith(prefix):
            path = tinymce_dir / url[len(prefix):].split('?')[0]
            if path.is_file():
                content_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
                return route.fulfill(status=200, body=path.read_bytes(), content_type=content_type)
        return route.fulfill(status=404, body='')

    captures = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for config_name, config in CONFIGS.items():
            page = browser.new_page()
            page.route(ORIGIN + '/**', serve)
            page.goto(PAGE_URL)
            version = page.evaluate('() => tinymce.majorVersion + "." + tinymce.minorVersion')
            page.evaluate(
                "config => tinymce.init(Object.assign({selector: '#editor', license_key: 'gpl', menubar: false}, config))"
                ".then(editors => editors.length)",
                config,
            )
            for case, html in LOADED.items():
                stored = page.evaluate(
                    "html => { const editor = tinymce.get('editor'); editor.setContent(html); return editor.getContent(); }",
                    html,
                )
                captures.append({'config': config_name, 'case': case, 'mode': 'loaded', 'input': html, 'stored': stored})
            body = page.frame_locator('#editor_ifr').locator('body')
            for case, text in TYPED.items():
                page.evaluate("() => tinymce.get('editor').setContent('')")
                body.click()
                page.keyboard.type(text)
                stored = page.evaluate("() => tinymce.get('editor').getContent()")
                captures.append({'config': config_name, 'case': case, 'mode': 'typed', 'input': text, 'stored': stored})
            page.close()
        browser.close()

    output.write_text(json.dumps(
        {'tinymce_version': version, 'configs': CONFIGS, 'captures': captures}, ensure_ascii=False, indent=2,
    ) + '\n')
    print(f'{len(captures)} captures of TinyMCE {version} written to {output}')


if __name__ == '__main__':
    main(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]))
