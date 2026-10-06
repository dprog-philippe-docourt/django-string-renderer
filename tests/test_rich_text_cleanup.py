import itertools

from django.template import TemplateSyntaxError
from django.test import SimpleTestCase, override_settings

from stringrenderer import check_template_syntax, StringTemplateRenderer
from tests.test_compatibility import CORPUS, load_tinymce_captures, OPTIONS

CONTEXT = dict(a=5, b=1, name='Bob', age=20, recipient=dict(first_name='Hélène', age=20))


def render(template_string, context=None, **kwargs):
    return StringTemplateRenderer(template_string, **kwargs).render_template(context or CONTEXT)


@override_settings(DEBUG=True)
class RichTextCleanupTests(SimpleTestCase):
    """
    Templates that version 0.5.0 could not build, because of the artifacts of rich text editors.
    """
    def test_same_comparison_operator_used_twice(self):
        self.assertEqual('yes', render('{% if a -gt 3 and b -gt 0 %}yes{% endif %}'))
        self.assertEqual('', render('{% if a -gt 3 and b -gt 0 %}yes{% endif %}', dict(a=2, b=1)))

    def test_comparison_operator_after_string_literal(self):
        self.assertEqual('yes', render('{% if name == "Bob" and age -gte 18 %}yes{% endif %}'))
        for operator, expected in (('-gt', ''), ('-gte', 'yes'), ('-lt', ''), ('-lte', 'yes')):
            with self.subTest(operator=operator):
                self.assertEqual(expected, render(f"{{% if name == 'Bob' and age {operator} 20 %}}yes{{% endif %}}"))

    def test_comparison_operator_inside_string_literal_is_kept(self):
        self.assertEqual('yes', render('{% if name == "-gt" and age -gte 18 %}yes{% endif %}', dict(name='-gt', age=20)))

    def test_non_breaking_spaces_inside_tags(self):
        for space in ('&nbsp;', '&#160;', ' ', ' '):
            with self.subTest(space=space):
                self.assertEqual('Bob', render(f'{{% if age{space}-gte 18 %}}{{{{{space}name{space}}}}}{{% endif %}}'))

    def test_non_breaking_space_inside_string_literal_is_kept(self):
        self.assertEqual('Hi&nbsp;there', render('{% if name == "Bob" and age -gte 18 %}{{ missing|default:"Hi&nbsp;there" }}{% endif %}'))

    def test_invisible_characters_inside_tags(self):
        self.assertEqual('Bob', render('{{​name﻿ }}'))

    def test_typographic_quotes(self):
        for literal in ('“Bob”', '”Bob”', '„Bob“', '‘Bob’', '’Bob’', '“Bob"'):
            with self.subTest(literal=literal):
                self.assertEqual('yes', render(f'{{% if name == {literal} %}}yes{{% endif %}}'))

    def test_apostrophe_inside_string_literal_is_kept(self):
        self.assertEqual('l’été', render("{% if name == 'Bob' and age -gte 18 %}{{ missing|default:'l’été' }}{% endif %}"))

    def test_formatting_inside_tags(self):
        self.assertEqual('Hello Bob', render('Hello {{ <strong>name</strong> }}'))
        self.assertEqual('<b>yes</b>', render('{% if <em>age</em> -gte 18 %}<b>yes</b>{% endif %}'))
        self.assertEqual('yes', render('{% if <span style="color: red;">age</span> -gte <span>18</span> %}yes{% endif %}'))

    def test_html_inside_string_literal_is_kept(self):
        self.assertEqual('<b>Bob</b>', render('{% if name == "Bob" and age -gte 18 %}{{ missing|default:"<b>Bob</b>" }}{% endif %}'))

    def test_text_comments_and_verbatim_blocks_are_kept(self):
        self.assertEqual(
            '<b>x</b>&nbsp;{{ <b>v</b> }} {% if a -gt 1 %}',
            render('{% if a -gt 3 and b -gt 0 %}<b>x</b>&nbsp;{% endif %}{# <b>c</b> #}'
                   '{% verbatim %}{{ <b>v</b> }} {% if a -gt 1 %}{% endverbatim %}'),
        )

    def test_auto_escape_and_extra_tags_are_applied(self):
        template_string = '{% if age&nbsp;-gte 18 %}{{ html }} {% translate "Hello" %}{% endif %}'
        context = dict(age=20, html='<b>Bob</b>')
        self.assertEqual('&lt;b&gt;Bob&lt;/b&gt; Hello', render(template_string, context, extra_tags=['i18n']))
        self.assertEqual('<b>Bob</b> Hello', render(template_string, context, extra_tags=['i18n'], auto_escape=False))

    def test_error_of_the_cleaned_template_is_raised(self):
        with self.assertRaisesMessage(TemplateSyntaxError, "'foo'"):
            render('{% if age&nbsp;-gte 18 %}{% foo %}{% endif %}')

    def test_check_template_syntax(self):
        self.assertEqual((True, None), StringTemplateRenderer('{% if a -gt 3 and b -gt 0 %}yes{% endif %}').check_template_syntax())
        is_valid, error = StringTemplateRenderer('{% if age&nbsp;-gte 18 %}{% foo %}{% endif %}').check_template_syntax()
        self.assertFalse(is_valid)
        self.assertIn("'foo'", str(error))

    def test_check_template_syntax_function_checks_templates_like_the_renderer(self):
        self.assertEqual((True, None), check_template_syntax('{% if a -gte 3 %}yes{% endif %}'))
        self.assertEqual((True, None), check_template_syntax('{% if age&nbsp;-gte 18 %}{% translate "Hello" %}{% endif %}',
                                                             extra_tags=['i18n'], auto_escape=False))
        # The renderer cannot render templates that extend another one.
        self.assertFalse(check_template_syntax('{% extends "base.html" %}')[0])
        templates = CORPUS + [capture['stored'] for capture in load_tinymce_captures()]
        for template_string, options in itertools.product(templates, OPTIONS):
            with self.subTest(template_string=template_string, options=options):
                self.assertEqual(StringTemplateRenderer(template_string, **options).check_template_syntax()[0],
                                 check_template_syntax(template_string, **options)[0])

    def test_tinymce_captures(self):
        for capture in load_tinymce_captures():
            with self.subTest(config=capture['config'], case=capture['case']):
                if capture['case'] == 'typed-comparison':
                    # Comparison operators typed in a rich text editor are escaped: "-gte" and the like must be used.
                    self.assertFalse(StringTemplateRenderer(capture['stored']).check_template_syntax()[0])
                else:
                    render(capture['stored'])


class ErrorDisplayTests(SimpleTestCase):
    def test_template_that_cannot_be_built(self):
        self.assertIn('The template cannot be built!', render('{% foo %}'))
        with override_settings(DEBUG=True), self.assertRaises(TemplateSyntaxError):
            render('{% foo %}')

    def test_error_message_is_escaped(self):
        result = render('{{ name|"<b>x</b>" }}')
        self.assertIn('&lt;b&gt;x&lt;/b&gt;', result)
        self.assertNotIn('<b>x</b>', result)

    def test_template_that_cannot_be_rendered(self):
        result = render('{% include "missing<b>.html" %}')
        self.assertIn('The template cannot be rendered!', result)
        self.assertIn('missing&lt;b&gt;.html', result)
