import itertools
from unittest import mock

from django.template import TemplateSyntaxError
from django.template.backends.django import DjangoTemplates
from django.test import SimpleTestCase, override_settings

from stringrenderer import _clean_tag_content, check_template_syntax, StringTemplateRenderer
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

    def test_escaped_comparison_characters(self):
        for operator, expected in (('&gt;', ''), ('&gt;=', 'yes'), ('&lt;', ''), ('&lt;=', 'yes'), ('&#62;=', 'yes'),
                                   ('&#x3C;=', 'yes'), ('&GT;=', 'yes')):
            with self.subTest(operator=operator):
                self.assertEqual(expected, render(f'{{% if age {operator} 20 %}}yes{{% endif %}}'))
        self.assertEqual('yes', render('{% if age &gt;= 18 and age -lt 30 and a &lt; age %}yes{% endif %}'))

    def test_escaped_comparison_characters_inside_string_literal_are_kept(self):
        self.assertEqual('yes', render('{% if name == "a&gt;b" and age &gt; 18 %}yes{% endif %}', dict(name='a&gt;b', age=20)))

    def test_escaped_comparison_characters_are_not_mistaken_for_html_tags(self):
        # The HTML tags are removed before the escaped characters are decoded.
        self.assertEqual(' if a <b> 0 and b ', _clean_tag_content(' if a &lt;b&gt; 0 and <strong>b</strong> ', is_block_tag=True))

    def test_escaped_comparison_characters_outside_block_tags_are_kept(self):
        self.assertEqual('&lt;b&gt; 5 &gt; 3', render('{% if a &gt; 3 %}&lt;b&gt; {{ a }} &gt; 3{% endif %}'))

    def test_non_breaking_spaces_inside_tags(self):
        for space in ('&nbsp;', '&#160;', ' ', ' '):
            with self.subTest(space=space):
                self.assertEqual('Bob', render(f'{{% if age{space}-gte 18 %}}{{{{{space}name{space}}}}}{{% endif %}}'))

    def test_non_breaking_space_inside_string_literal_is_kept(self):
        self.assertEqual('Hi&nbsp;there', render('{% if name == "Bob" and age -gte 18 %}{{ missing|default:"Hi&nbsp;there" }}{% endif %}'))

    def test_invisible_characters_inside_tags(self):
        self.assertEqual('Bob', render('{{​name﻿ }}'))

    def test_typographic_quotes(self):
        for literal in ('“Bob”', '”Bob”', '„Bob“', '‘Bob’', '’Bob’', '‚Bob‘', '“Bob"'):
            with self.subTest(literal=literal):
                self.assertEqual('yes', render(f'{{% if name == {literal} %}}yes{{% endif %}}'))

    def test_typographic_quote_entities(self):
        # TinyMCE stores the typographic quotes as named entities, unless entity_encoding is "raw".
        for literal in ('&ldquo;Bob&rdquo;', '&bdquo;Bob&ldquo;', '&lsquo;Bob&rsquo;', '&sbquo;Bob&lsquo;', '&#8220;Bob&#8221;',
                        '&#x201C;Bob&#x201d;'):
            with self.subTest(literal=literal):
                self.assertEqual('yes', render(f'{{% if name == {literal} %}}yes{{% endif %}}'))
        # The entities of other characters are kept.
        self.assertEqual('&eacute;', render('{% if age -gte 18 and a -gte 1 %}{{ missing|default:"&eacute;" }}{% endif %}'))

    def test_apostrophe_inside_string_literal_is_kept(self):
        self.assertEqual('l’été', render("{% if name == 'Bob' and age -gte 18 %}{{ missing|default:'l’été' }}{% endif %}"))

    def test_formatting_inside_tags(self):
        self.assertEqual('Hello Bob', render('Hello {{ <strong>name</strong> }}'))
        self.assertEqual('<b>yes</b>', render('{% if <em>age</em> -gte 18 %}<b>yes</b>{% endif %}'))
        self.assertEqual('yes', render('{% if <span style="color: red;">age</span> -gte <span>18</span> %}yes{% endif %}'))

    def test_line_breaks_inside_tags_separate_arguments(self):
        # The line breaks and the paragraphs separate the text around them, unlike the formatting of the text.
        self.assertEqual('Bob', render('{% firstof missing<br>name "nobody" %}{% if age&nbsp;-gte 18 %}{% endif %}'))
        self.assertEqual('yes', render('{% if age</p><p>-gte 18 %}yes{% endif %}'))
        self.assertEqual(' a bcd  e f ', _clean_tag_content(' a<br>b<strong>c</strong>d</p><p>e<BR/>f ', is_block_tag=True))

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
                render(capture['stored'])
        typed_comparisons = [capture['stored'] for capture in load_tinymce_captures() if capture['case'] == 'typed-comparison']
        self.assertEqual(['<p>{% if recipient.age &gt;= 18 %}Adult{% endif %}</p>'] * 2, typed_comparisons)
        self.assertEqual('<p>Adult</p>', render(typed_comparisons[0]))


class ErrorDisplayTests(SimpleTestCase):
    def test_error_message_does_not_mention_wrapping_tags(self):
        for template_string, expected_message in (
            ('{% if a %}', "Unclosed tag on line 1: 'if'. Looking for one of: elif, else, endif."),
            ('{% foo %}', "Invalid block tag on line 1: 'foo'. Did you forget to register or load this tag?"),
            ('{% if a -gt 1 and a -gt 0 %}{% foo %}', "Invalid block tag on line 1: 'foo', expected 'elif', 'else' or 'endif'."),
        ):
            for options in OPTIONS:
                with self.subTest(template_string=template_string, options=options):
                    is_valid, error = StringTemplateRenderer(template_string, **options).check_template_syntax()
                    self.assertTrue(str(error).startswith(expected_message), str(error))

    def test_any_error_preventing_building_the_template_is_returned(self):
        is_valid, error = check_template_syntax('{% if ' + 'not ' * 3000 + 'a %}{% endif %}')
        self.assertFalse(is_valid)
        self.assertIsInstance(error, RecursionError)

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


class TemplateBuildTests(SimpleTestCase):
    def assertCompilationCount(self, expected_count, template_string, **options):
        with mock.patch.object(DjangoTemplates, 'from_string', autospec=True,
                               side_effect=DjangoTemplates.from_string) as from_string:
            renderer = StringTemplateRenderer(template_string, **options)
            renderer.check_template_syntax()
            renderer.get_prepared_template_string()
            renderer.render_template(CONTEXT)
            renderer.render_template(CONTEXT)
        self.assertEqual(expected_count, from_string.call_count)

    def test_template_is_built_once(self):
        self.assertCompilationCount(1, '{{ name }}')
        # The template is built again once cleaned.
        self.assertCompilationCount(2, '{% if a -gt 3 and b -gt 0 %}yes{% endif %}')

    def test_template_body_is_built_only_for_errors_mentioning_wrapping_tags(self):
        self.assertCompilationCount(1, '{% foo %}', spaceless=False)
        self.assertCompilationCount(2, '{% foo %}')
