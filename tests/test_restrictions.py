from django import forms
from django.core.exceptions import ValidationError
from django.template import TemplateSyntaxError
from django.test import SimpleTestCase, override_settings

from stringrenderer import check_template_syntax, StringTemplateRenderer
from stringrenderer.validators import TemplateSyntaxValidator

CONTEXT = dict(a=5, name='Bob', items=[1, 2])


def check(template_string, **options):
    return StringTemplateRenderer(template_string, **options).check_template_syntax()


class AllowedTagsTests(SimpleTestCase):
    def test_every_tag_is_allowed_by_default(self):
        self.assertEqual((True, None), check('{% include "x.html" %}{% load i18n %}'))

    def test_allowed_tags(self):
        template_string = '{% if a -gt 1 %}{% for item in items %}{{ item }}{% empty %}none{% endfor %}{% else %}{% endif %}'
        self.assertEqual((True, None), check(template_string, allowed_tags=['if', 'for']))
        self.assertEqual('12', StringTemplateRenderer(template_string, allowed_tags=['if', 'for']).render_template(CONTEXT))

    def test_forbidden_tags(self):
        is_valid, error = check('{% if a %}\n{% include "x.html" %}{% now "Y" %}{% include "y.html" %}{% endif %}',
                                allowed_tags={'if'})
        self.assertFalse(is_valid)
        self.assertEqual("The tags 'include', 'now' are not allowed.", str(error))
        self.assertEqual(2, error.token.lineno)
        is_valid, error = check('{% load i18n %}', allowed_tags=[])
        self.assertEqual("The tag 'load' is not allowed.", str(error))

    def test_tags_loaded_with_extra_tags(self):
        self.assertEqual((True, None), check('{% translate "Hello" %}', extra_tags=['i18n'], allowed_tags=['translate']))
        self.assertFalse(check('{% translate "Hello" %}', extra_tags=['i18n'], allowed_tags=[])[0])

    def test_content_of_comments_and_verbatim_blocks_is_ignored(self):
        template_string = '{# {% include "x.html" %} #}{% comment %}{% include "x.html" %}{% endcomment %}{% verbatim %}{% include "x.html" %}{% endverbatim %}'
        self.assertEqual((True, None), check(template_string, allowed_tags=['comment', 'verbatim']))

    def test_cleaned_templates_are_checked(self):
        self.assertFalse(check('{% if a -gt 1 and a -gt 0 %}{% include "x.html" %}{% endif %}', allowed_tags=['if'])[0])

    def test_rendering_forbidden_tag(self):
        result = StringTemplateRenderer('{% now "Y" %}', allowed_tags=[]).render_template({})
        self.assertIn("The tag &#x27;now&#x27; is not allowed.", result)
        with override_settings(DEBUG=True), self.assertRaisesMessage(TemplateSyntaxError, "The tag 'now' is not allowed."):
            StringTemplateRenderer('{% now "Y" %}', allowed_tags=[]).render_template({})


class AllowedFiltersTests(SimpleTestCase):
    def test_allowed_filters(self):
        self.assertEqual((True, None), check('{{ name|lower|upper }}{% if items|length -gt 1 %}{% endif %}',
                                             allowed_filters=['lower', 'upper', 'length']))

    def test_forbidden_filters(self):
        is_valid, error = check('{{ name|lower|upper|safe }}{% if items|length -gt 1 %}{% endif %}', allowed_filters=['lower'])
        self.assertFalse(is_valid)
        self.assertEqual("The filters 'length', 'safe', 'upper' are not allowed.", str(error))
        self.assertEqual("The filter 'safe' is not allowed.", str(check('{{ name|safe }}', allowed_filters=[])[1]))

    def test_check_template_syntax_function(self):
        self.assertFalse(check_template_syntax('{{ name|safe }}', allowed_filters=[])[0])


class TemplateSyntaxValidatorTests(SimpleTestCase):
    def test_valid_template(self):
        TemplateSyntaxValidator()('{% if a -gte 3 %}{{ name }}{% endif %}')
        TemplateSyntaxValidator(extra_tags=['i18n'], allowed_tags=['translate'])('{% translate "Hello" %}')

    def test_invalid_template(self):
        with self.assertRaises(ValidationError) as error:
            TemplateSyntaxValidator()('Hello\n{% foo %}')
        self.assertEqual('invalid_template', error.exception.code)
        self.assertEqual(["This template is not valid (line 2): Invalid block tag on line 2: 'foo'. "
                          "Did you forget to register or load this tag?"], error.exception.messages)

    def test_forbidden_tag(self):
        with self.assertRaisesMessage(ValidationError, "This template is not valid (line 1): The tag 'now' is not allowed."):
            TemplateSyntaxValidator(allowed_tags=[])('{% now "Y" %}')
        with self.assertRaisesMessage(ValidationError, "This template is not valid: The filter 'safe' is not allowed."):
            TemplateSyntaxValidator(allowed_filters=[])('{{ name|safe }}')

    def test_custom_message_and_code(self):
        with self.assertRaises(ValidationError) as error:
            TemplateSyntaxValidator(message='Line %(line)s is wrong.', code='wrong')('\n{% foo %}')
        self.assertEqual('wrong', error.exception.code)
        self.assertEqual(['Line 2 is wrong.'], error.exception.messages)

    def test_deconstruction(self):
        validator = TemplateSyntaxValidator(extra_tags=['i18n'], allowed_tags=['if'])
        path, args, kwargs = validator.deconstruct()
        self.assertEqual('stringrenderer.validators.TemplateSyntaxValidator', path)
        self.assertEqual(dict(extra_tags=['i18n'], allowed_tags=['if']), kwargs)
        self.assertEqual(validator, TemplateSyntaxValidator(*args, **kwargs))
        self.assertNotEqual(validator, TemplateSyntaxValidator(extra_tags=['i18n']))

    def test_form_field(self):
        class MessageForm(forms.Form):
            message = forms.CharField(validators=[TemplateSyntaxValidator(allowed_tags=['if'])])

        self.assertTrue(MessageForm(dict(message='{% if a %}{{ name }}{% endif %}')).is_valid())
        form = MessageForm(dict(message='{% include "x.html" %}'))
        self.assertFalse(form.is_valid())
        self.assertEqual(["This template is not valid (line 1): The tag 'include' is not allowed."], form.errors['message'])
