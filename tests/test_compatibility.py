import json
import os
import pathlib
import unittest

from django.test import SimpleTestCase

from tests.compatibility import check_compatibility
from tests.tests import TEST_STRINGS

FIXTURES_DIR = pathlib.Path(__file__).parent / 'fixtures'

# Templates covering the features of version 0.5.0 and the artifacts of rich text editors.
CORPUS = [
    "Hello {{ name }}!",
    "Hello {{name}}!",
    "{{ name|lower }} {{ name|upper }} {{ html }} {{ html|safe }}",
    "{% if a -gte 3 %}a{% endif %}{% if a -gt 3 %}b{% endif %}{% if b -lte 1 %}c{% endif %}{% if b -lt 2 %}d{% endif %}",
    "{%if a -gte 3%}yes{%endif%}",
    "{% if a -gt 3 and b -lt 2 %}yes{% endif %}",
    "{% if a -gt 3 and b -gt 0 %}yes{% endif %}",
    "{% if age is None or age -lt 18 %}minor{% endif %}",
    '{% if name == "Bob" %}yes{% endif %}',
    '{% if name == "Bob" and age -gte 18 %}yes{% endif %}',
    "{% if name == '-gte 18' %}{% else %}no{% endif %}",
    "{{ name|default:'-gt' }}",
    "{% block main-ltr %}x{% endblock main-ltr %}",
    "&quot;Hello&quot; {{ name }} &#39;you&#39;",
    '<a title="&quot;quoted&quot;">{{ name }}</a>',
    "{{ name|default:&quot;Bob&quot; }}",
    "Hello&nbsp;{{ name }}&nbsp;!",
    "Hello {{ name }} !",
    "{% if age&nbsp;-gte 18 %}adult{% endif %}",
    "{% if age -gte 18 %}adult{% endif %}",
    "{{&nbsp;name }}",
    "{{ <strong>name</strong> }}",
    '{% if name == “Bob” %}yes{% endif %}',
    "{{ note|default:'l’été' }}",
    "<p>{% if age -gte 18 %}</p><p>Adult</p><p>{% endif %}</p>",
    "<b>Jean</b> <i>Dupont</i>\n<p> {{ name }} </p>",
    "{# <b>comment</b> -gt #}{{ name }}",
    "{% comment %}{{ <b>x</b> }} {% if a -gt 1 %}{% endcomment %}{{ name }}",
    "{% verbatim %}{{ <b>x</b> }} {% if a -gt 1 %}{% endverbatim %}{{ name }}",
    "{% verbatim myblock %}{% endverbatim %}{% endverbatim myblock %}",
    "{% autoescape off %}{{ html }}{% endautoescape %}",
    "{% for member in members %}{{ member }}{% if not forloop.last %}, {% endif %}{% empty %}none{% endfor %}",
    "{% with total=members|length %}{{ total }}{% endwith %}",
    "{% spaceless %}<p> a </p> <p>b</p>{% endspaceless %}",
    "{% firstof missing name 'nobody' %}",
    "{% cycle 'odd' 'even' as parity %}{{ parity }}",
    "{% now 'Y' as year %}{{ year }}",
    '{{ date|date:"d.m.Y" }}',
    "{% templatetag openblock %} {% templatetag closevariable %}",
    "{% load i18n %}{% translate 'Hello' %}",
    "{% if a > 3 %}raw comparison{% endif %}",
    "{% if a &gt;= 3 %}escaped comparison{% endif %}",
    "{% foo %}",
    "{% if a %}unclosed",
    "{{ a{{x }}",
    "",
]

OPTIONS = [
    {},
    {'auto_escape': False},
    {'extra_tags': ['i18n']},
    {'extra_tags': ['i18n', 'static'], 'auto_escape': False},
]


def load_tinymce_captures():
    with open(FIXTURES_DIR / 'tinymce.json', encoding='utf-8') as fixture_file:
        return json.load(fixture_file)['captures']


def load_tinymce_templates():
    return [capture['stored'] for capture in load_tinymce_captures()]


class CompatibilityTests(SimpleTestCase):
    def test_templates_built_by_version_0_5_0_are_prepared_identically(self):
        templates = CORPUS + TEST_STRINGS + load_tinymce_templates()
        entries = [dict(template=template, **options) for template in templates for options in OPTIONS]
        report = check_compatibility(entries)
        self.assertEqual([], report.differences, str(report))
        self.assertGreater(report.checked, 200, str(report))
        self.assertGreater(len(report.fixed), 20, str(report))

    @unittest.skipUnless(os.environ.get('STRINGRENDERER_CORPUS'), 'STRINGRENDERER_CORPUS is not set.')
    def test_external_corpus(self):
        with open(os.environ['STRINGRENDERER_CORPUS'], encoding='utf-8') as corpus_file:
            report = check_compatibility(json.load(corpus_file))
        self.assertEqual([], report.differences, str(report))
