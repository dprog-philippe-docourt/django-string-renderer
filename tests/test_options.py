import re

from django.template import TemplateSyntaxError
from django.test import SimpleTestCase, override_settings
from django.utils.safestring import SafeString

from stringrenderer import _remove_block_tag_paragraphs, StringTemplateRenderer
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

    def test_paragraphs_with_text_or_variables_are_kept(self):
        self.assertEqual('<p>Hello</p>', self.render('<p>{% if name %}Hello{% endif %}</p>'))
        self.assertEqual('<p>Bob</p>', self.render('<p>{% if name %}{{ name }}{% endif %}</p>'))

    def test_verbatim_blocks_are_kept(self):
        self.assertEqual('<p>{% if a %}</p>', self.render('{% verbatim %}<p>{% if a %}</p>{% endverbatim %}'))

    def test_only_paragraph_markup_is_removed(self):
        markup = re.compile(r'</?p(?:\s[^<>]*)?>|\s|&nbsp;|<br\s*/?>', re.IGNORECASE)
        for template_string in CORPUS + load_tinymce_templates() + ['<p>{% if a %}x{% endif %}</p><p>{% if a %}</p>']:
            with self.subTest(template_string=template_string):
                result = _remove_block_tag_paragraphs(template_string)
                self.assertEqual(markup.sub('', template_string), markup.sub('', result))
                self.assertEqual(template_string.count('\n'), result.count('\n'))

    @override_settings(DEBUG=True)
    def test_line_numbers_of_syntax_errors_are_kept(self):
        with self.assertRaises(TemplateSyntaxError) as error:
            self.render('<p>{% if a %}\n</p>{% foo %}')
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
