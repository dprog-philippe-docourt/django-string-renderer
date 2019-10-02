from django.test import SimpleTestCase, override_settings

from stringrenderer import *

TEST_STRINGS = [
    "Hello {{ recipient.first_name }} {{ recipient.last_name }}!",
    "Hello {{recipient.first_name}} {{recipient.last_name}}!",
    "Hello {{ recipient.first_name|lower }} {{ recipient.last_name|upper }}!",
    "Hello {{ recipient.first_name|lower }} {{ recipient.last_name|upper }}!",
    "{%if recipient.age -gte 18%}{{recipient.first_name}} is an adult{%endif%}",
    "{% if recipient.age -lt 14 %}{{recipient.first_name}} is less than 14{% endif %}",
    "{%if recipient.age == '-gte 18'%}{%else%}False{%endif%}",
    "{%if recipient.age == '-gte 18'%}{% else %}False{%endif%}",
]


class Recipient(object):
    def __init__(self, first_name, last_name, age):
        self.first_name = first_name
        self.last_name = last_name
        self.age = age


recipient1 = Recipient('John', 'Doe', 30)
recipient2 = Recipient('Marie', 'Dupont', 12)
recipient3 = Recipient('<STRONG>Bob</STRONG>', 'Dupond', 18)

TEST_CONTEXTS = [
    dict(recipient=recipient1),
    dict(recipient=recipient1),
    dict(recipient=recipient1),
    dict(recipient=recipient3),
    dict(recipient=recipient1),
    dict(recipient=recipient2),
    dict(recipient=recipient2),
    dict(recipient=recipient3),
]

EXPECTED_RESULTS = [
    "Hello John Doe!",
    "Hello John Doe!",
    "Hello john DOE!",
    "Hello &lt;strong&gt;bob&lt;/strong&gt; DUPOND!",
    "John is an adult",
    "Marie is less than 14",
    "False",
    "False",
]

EXPECTED_RESULTS_WITHOUT_ESCAPE = [
    "Hello John Doe!",
    "Hello John Doe!",
    "Hello john DOE!",
    "Hello <strong>bob</strong> DUPOND!",
    "John is an adult",
    "Marie is less than 14",
    "False",
    "False",
]


@override_settings(TEMPLATES=[{'BACKEND': 'django.template.backends.django.DjangoTemplates'}])
class TestRendering(SimpleTestCase):
    def test_rendering_with_default_options(self):
        for i, test_string in enumerate(TEST_STRINGS):
            renderer = StringTemplateRenderer(test_string)
            result = renderer.render_template(TEST_CONTEXTS[i])
            self.assertEqual(EXPECTED_RESULTS[i], result)

    def test_rendering_without_auto_escape(self):
        for i, test_string in enumerate(TEST_STRINGS):
            renderer = StringTemplateRenderer(test_string, auto_escape=False)
            result = renderer.render_template(TEST_CONTEXTS[i])
            self.assertEqual(EXPECTED_RESULTS_WITHOUT_ESCAPE[i], result)
