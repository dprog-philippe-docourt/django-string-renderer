import re
import time
import traceback
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.template import TemplateSyntaxError
from django.template.utils import InvalidTemplateEngineError
from django.test import SimpleTestCase, override_settings
from django.utils.safestring import SafeString

from stringrenderer import _remove_block_tag_paragraphs, check_template_syntax, StringTemplateRenderer
from tests.test_compatibility import CORPUS, load_tinymce_templates

CONTEXT = dict(a=5, name='Bob', age=20)


def render(template_string, context=None, **kwargs):
    return StringTemplateRenderer(template_string, **kwargs).render_template(context or CONTEXT)


class SpacelessTests(SimpleTestCase):
    def test_whitespace_between_tags_is_removed_by_default(self):
        self.assertEqual('<b>Jean</b><i>Dupont</i>', render('<b>Jean</b> <i>Dupont</i>'))

    def test_whitespace_between_tags_is_kept(self):
        self.assertEqual(' <b>Jean</b> <i>Dupont</i>\n', render(' <b>Jean</b> <i>Dupont</i>\n', spaceless=False))


class UnescapeQuotesInTextTests(SimpleTestCase):
    TEMPLATE = '<a title="&quot;quoted&quot;">{{ missing|default:&quot;Bob&quot; }} &#39;s</a>'

    def test_quotes_are_unescaped_everywhere_by_default(self):
        self.assertEqual('<a title=""quoted"">Bob \'s</a>', render(self.TEMPLATE))

    def test_quotes_are_unescaped_inside_template_tags_only(self):
        self.assertEqual('<a title="&quot;quoted&quot;">Bob &#39;s</a>', render(self.TEMPLATE, unescape_quotes_in_text=False))


class RemoveBlockTagParagraphsTests(SimpleTestCase):
    def render(self, template_string, context=None):
        return render(template_string, context, remove_block_tag_paragraphs=True, spaceless=False)

    def test_paragraphs_kept_by_default(self):
        template_string = '<p>{% if age -gte 18 %}</p><p>Adult</p><p>{% endif %}</p>'
        self.assertEqual('<p></p><p>Adult</p><p></p>', render(template_string))

    def test_structural_block_tags_are_moved_out_of_their_paragraphs(self):
        template_string = '<p>{% if age -gte 18 %}</p>\n<p>Adult</p>\n<p>{% endif %}</p>'
        self.assertEqual('\n<p>Adult</p>\n', self.render(template_string))
        self.assertEqual('\n<p>Adult</p>\n', self.render(template_string.replace('-gte', '-gt').replace('18', '19')))
        self.assertEqual('', self.render(template_string, dict(age=10)).strip())

    def test_paragraph_with_attributes_spaces_and_line_breaks(self):
        template_string = '<p style="color: red;">&nbsp;{% for item in items %} <br></p><p>{{ item }}</p><P>{% endfor %}</P>'
        self.assertEqual('<p>1</p><p>2</p>', self.render(template_string, dict(items=[1, 2])))

    def test_assignment_tags_are_moved_out_of_their_paragraphs(self):
        template_string = '<p>{% firstof missing name "nobody" as who %}</p><p>{{ who }}</p>'
        self.assertEqual('<p>Bob</p>', self.render(template_string))

    def test_paragraphs_of_tags_producing_output_are_kept(self):
        self.assertEqual('<p>Bob</p>', self.render('<p>{% firstof missing name %}</p>'))
        self.assertEqual('<p>see as below</p>', self.render('<p>{% firstof missing "see as below" %}</p>'))
        # A named cycle produces its first value, unless it is silent.
        self.assertEqual('<p>x</p>', self.render('<p>{% cycle "x" "y" as c %}</p>'))
        self.assertEqual('<p>x</p>', self.render('<p>{% cycle "x" "y" as c silent %}</p><p>{{ c }}</p>'))

    def test_tags_of_a_block_are_moved_out_together(self):
        template_string = '<p>{% if a %}</p><p>x</p><p>{% else %}</p><p>y</p><p>{% endif %}</p>'
        self.assertEqual('{% if a %}<p>x</p>{% else %}<p>y</p>{% endif %}', _remove_block_tag_paragraphs(template_string))
        # When a tag of a block is in a paragraph with text, the paragraphs of the other tags of the block are kept,
        # since they would not be balanced anymore otherwise.
        for template_string in ('<p>{% if a %}</p><p>x {% endif %}tail</p>',
                                '<p>{% if a %}</p><p>x</p><p>{% else %}y</p><p>{% endif %}</p>',
                                '<p>{% if a %}</p><p>{% endif %}{% if name %}x</p><p>{% endif %}</p>'):
            for a in (False, True):
                with self.subTest(template_string=template_string, a=a):
                    self.assertEqual(template_string, _remove_block_tag_paragraphs(template_string))
                    self.assertEqual(render(template_string, dict(a=a, name='Bob'), spaceless=False),
                                     self.render(template_string, dict(a=a, name='Bob')))

    def test_tags_outside_of_paragraphs_do_not_keep_the_paragraphs_of_their_block(self):
        template_string = '<p>{% for item in items %}</p><p>{{ item }}</p>{% endfor %}'
        self.assertEqual('<p>1</p><p>2</p>', self.render(template_string, dict(items=[1, 2])))
        template_string = '{% if a %}<p>x</p><p>{% endif %}</p>'
        self.assertEqual('<p>x</p>', self.render(template_string, dict(a=True)))
        self.assertEqual('', self.render(template_string, dict(a=False)))
        # A tag in a paragraph with text still keeps the paragraphs of the other tags of its block.
        template_string = '{% if a %}<p>{% else %}</p><p>x {% endif %}</p>'
        self.assertEqual(template_string, _remove_block_tag_paragraphs(template_string))

    def test_tag_that_django_cannot_split(self):
        template_string = '<p>{% if a %}</p><p>{% firstof _("x %}</p><p>{% endif %}</p>'
        self.assertEqual('{% if a %}<p>{% firstof _("x %}</p>{% endif %}', _remove_block_tag_paragraphs(template_string))
        self.assertIn('The template cannot be built!',
                      render(template_string, remove_block_tag_paragraphs=True, on_error='html'))

    def test_nested_blocks(self):
        template_string = '<p>{% if a %}</p><p>{% for item in items %}</p><p>{{ item }}</p><p>{% endfor %}</p><p>{% endif %}</p>'
        self.assertEqual('<p>1</p><p>2</p>', self.render(template_string, dict(a=True, items=[1, 2])))
        # The inner block stays in its paragraphs, while the outer block is moved out of them.
        template_string = '<p>{% if a %}</p><p>{% if b %}</p><p>x {% endif %}y</p><p>{% endif %}</p>'
        self.assertEqual('{% if a %}<p>{% if b %}</p><p>x {% endif %}y</p>{% endif %}',
                         _remove_block_tag_paragraphs(template_string))

    def test_paragraphs_of_invalid_templates_are_kept(self):
        for template_string in ('<p>{% if a %}</p>', '<p>{% endif %}</p>', '<p>{% else %}</p>',
                                '<p>{% if a %}</p><p>{% endfor %}</p>'):
            with self.subTest(template_string=template_string):
                self.assertEqual(template_string, _remove_block_tag_paragraphs(template_string))

    def test_tags_cleaned_from_editor_artifacts_are_moved_out_of_their_paragraphs(self):
        template_string = '<p>{%&nbsp;if a %}</p><p>x</p><p>{% <strong>endif</strong>&nbsp;%}</p>'
        self.assertEqual('<p>x</p>', self.render(template_string, dict(a=True)))
        self.assertEqual('', self.render(template_string, dict(a=False)))

    def test_paragraphs_with_template_tags_in_their_attributes_are_kept(self):
        template_string = '<p class="{{ name }}">{% if a %}</p><p>{% endif %}</p>'
        self.assertEqual(template_string, _remove_block_tag_paragraphs(template_string))

    def test_tags_of_comment_blocks_are_ignored(self):
        template_string = '<p>{% comment %}</p><p>{% if a %}</p><p>{% endcomment %}</p><p>{% load i18n %}</p>'
        self.assertEqual('{% comment %}<p>{% if a %}</p>{% endcomment %}{% load i18n %}',
                         _remove_block_tag_paragraphs(template_string))

    def test_time_is_linear(self):
        for template_string in ('<p>{%' * 20000, '<p>{% if a %}</p>' * 10000 + '<p>{% endif %}</p>' * 10000):
            start = time.perf_counter()
            _remove_block_tag_paragraphs(template_string)
            self.assertLess(time.perf_counter() - start, 1)

    def test_paragraphs_with_text_or_variables_are_kept(self):
        self.assertEqual('<p>Hello</p>', self.render('<p>{% if name %}Hello{% endif %}</p>'))
        self.assertEqual('<p>Bob</p>', self.render('<p>{% if name %}{{ name }}{% endif %}</p>'))

    def test_verbatim_blocks_are_kept(self):
        self.assertEqual('<p>{% if a %}</p>', self.render('{% verbatim %}<p>{% if a %}</p>{% endverbatim %}'))

    def test_only_paragraph_markup_is_removed(self):
        markup = re.compile(r'</?p(?:\s[^<>{}]*)?>|\s|&nbsp;|<br\s*/?>', re.IGNORECASE)
        template_strings = CORPUS + load_tinymce_templates() + [
            '<p>{% if a %}x{% endif %}</p><p>{% if a %}</p>',
            '<p title="{% if a %}x{% endif %}">{% if a %}</p><p>{% endif %}</p>',
            '<p>\n{% if a %}\n</p>\n<p>{% for x in y %}{% endfor %}\n{% endif %}</p>',
        ]
        for template_string in template_strings:
            with self.subTest(template_string=template_string):
                result = _remove_block_tag_paragraphs(template_string)
                self.assertEqual(markup.sub('', template_string), markup.sub('', result))
                self.assertEqual(template_string.count('\n'), result.count('\n'))

    @override_settings(DEBUG=True)
    def test_line_numbers_of_syntax_errors_are_kept(self):
        self.assertEqual('\n{% if a %}\n{% endif %}', _remove_block_tag_paragraphs('<p>\n{% if a %}\n</p><p>{% endif %}</p>'))
        with self.assertRaises(TemplateSyntaxError) as error:
            self.render('<p>\n{% if a b c %}</p><p>{% endif %}</p>')
        self.assertEqual(2, error.exception.token.lineno)


class OnErrorTests(SimpleTestCase):
    BUILD_ERROR = '{% foo %}'
    RENDERING_ERROR = '{% include "missing.html" %}'

    def test_raise(self):
        for template_string in (self.BUILD_ERROR, self.RENDERING_ERROR):
            with self.subTest(template_string=template_string), self.assertRaises(Exception):
                render(template_string, on_error='raise')

    @override_settings(DEBUG=True)
    def test_html(self):
        self.assertIn('<h3 class="error">[ The template cannot be built! ]</h3>', render(self.BUILD_ERROR, on_error='html'))
        self.assertIn('<h3 class="error">[ The template cannot be rendered! ]</h3>', render(self.RENDERING_ERROR, on_error='html'))

    def test_text(self):
        result = render(self.BUILD_ERROR, on_error='text')
        self.assertTrue(result.startswith("[ The template cannot be built! ] Invalid block tag on line 1: 'foo'"))
        self.assertNotIsInstance(result, SafeString)
        self.assertEqual('[ The template cannot be rendered! ] missing.html', render(self.RENDERING_ERROR, on_error='text'))

    def test_callable(self):
        self.assertEqual('TemplateSyntaxError', render(self.BUILD_ERROR, on_error=lambda error: type(error).__name__))
        self.assertEqual('TemplateDoesNotExist', render(self.RENDERING_ERROR, on_error=lambda error: type(error).__name__))

    def test_invalid_value(self):
        with self.assertRaises(ValueError):
            StringTemplateRenderer('', on_error='ignore')

    def test_traceback_of_build_error_does_not_grow(self):
        renderer = StringTemplateRenderer(self.BUILD_ERROR, on_error='raise')
        traceback_lengths = set()
        for _ in range(3):
            # Not assertRaises, which removes the traceback of the error.
            try:
                renderer.render_template({})
            except TemplateSyntaxError as error:
                traceback_lengths.add(len(traceback.extract_tb(error.__traceback__)))
        self.assertEqual(1, len(traceback_lengths))

    def test_context_of_build_error_is_restored(self):
        renderer = StringTemplateRenderer(self.BUILD_ERROR, on_error='raise')
        build_error_context = renderer.check_template_syntax()[1].__context__
        try:
            raise ValueError('Unrelated error')
        except ValueError as unrelated_error:
            with self.assertRaises(TemplateSyntaxError) as error:
                renderer.render_template({})
            self.assertIs(unrelated_error, error.exception.__context__)
        with self.assertRaises(TemplateSyntaxError) as error:
            renderer.render_template({})
        self.assertIs(build_error_context, error.exception.__context__)

    def test_configuration_errors_are_raised(self):
        renderer = StringTemplateRenderer('Hello', engine_name='missing', on_error='html')
        with self.assertRaises(InvalidTemplateEngineError):
            renderer.render_template({})
        with self.assertRaises(InvalidTemplateEngineError):
            renderer.check_template_syntax()

    def test_unknown_tag_library_is_raised(self):
        renderer = StringTemplateRenderer('Hello', extra_tags=['i18n', 'missing'], on_error='html')
        with self.assertRaisesMessage(ImproperlyConfigured, "Unknown tag library in extra_tags: 'missing'."):
            renderer.render_template({})
        with self.assertRaises(ImproperlyConfigured):
            renderer.check_template_syntax()

    def test_errors_raised_while_preparing_the_template_are_handled(self):
        with mock.patch('stringrenderer._remove_block_tag_paragraphs', side_effect=ValueError('Preparation error')):
            self.assertEqual('[ The template cannot be built! ] Preparation error',
                             render('<p>{% if a %}</p>', remove_block_tag_paragraphs=True, on_error='text'))
            is_valid, error = check_template_syntax('<p>{% if a %}</p>', remove_block_tag_paragraphs=True)
        self.assertFalse(is_valid)
        self.assertEqual('Preparation error', str(error))
