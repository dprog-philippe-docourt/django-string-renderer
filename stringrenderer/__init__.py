import re
from typing import Optional, List, Tuple

from django.conf import settings
from django.template import engines, Template, TemplateSyntaxError
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext as _


def check_template_syntax(template_string: str) -> Tuple[bool, Optional[TemplateSyntaxError]]:
    try:
        Template(template_string)
    except TemplateSyntaxError as e:
        return False, e
    return True, None


class StringTemplateRenderer(object):
    def __init__(self, template_string: str, extra_tags: Optional[List[str]] = None, auto_escape: bool = True,
                 engine_name: str = 'django') -> None:
        self.template_string = template_string
        self._template = None
        self.auto_escape = auto_escape
        self.extra_tags = extra_tags or []
        self.engine_name = engine_name

    def render_template(self, context, request=None) -> str:
        template = self._get_or_create_template()
        return self._render_to_template(template=template, context=context, request=request)

    def _get_or_create_template(self):
        if self._template:
            return self._template
        template_template_string = self.template_string if self.auto_escape else '{% autoescape off %}' + str(
            self.template_string) + '{% endautoescape %}'
        self._template = self._make_template_from_string(template_template_string)
        return self._template

    def _make_template_from_string(self, template_string: str):
        template_string = template_string.replace("&#39;", "'").replace("&quot;", '"')
        comparison_op_regex = [
            (r'{%\1>=', re.compile("\\{%([^\"\'\\}]+)-gte")),
            (r'{%\1>', re.compile("\\{%([^\"\'\\}]+)-gt")),
            (r'{%\1<=', re.compile("\\{%([^\"\'\\}]+)-lte")),
            (r'{%\1<', re.compile("\\{%([^\"\'\\}]+)-lt")),
        ]
        for regex in comparison_op_regex:
            template_string = regex[1].sub(regex[0], template_string)
        if self.extra_tags:
            load_tags = '{%load ' + ' '.join(self.extra_tags) + '%}'
        else:
            load_tags = ''
        html_template_string = load_tags + '{%spaceless%}' + template_string + '{%endspaceless%}'
        django_engine = engines[self.engine_name]
        try:
            template = django_engine.from_string(html_template_string)
        except Exception as e:
            # In some rare cases exc_value.args can be empty or an invalid
            # unicode string.
            try:
                message = str(e.args[0])
            except (IndexError, UnicodeDecodeError):
                message = '({0})'.format(_("Could not get exception message."))
            rendered_html = '<h3 class="error">[ {0} ]</h3><p><i>{1}</i></p>'.format(
                _("The template cannot be built!"),
                message)
            template = django_engine.from_string(rendered_html)
            if settings.DEBUG:
                raise
        return template

    @staticmethod
    def _render_to_template(template, context, request=None):
        try:
            rendered_html = template.render(context=context, request=request)
        except Exception as e:
            # In some rare cases exc_value.args can be empty or an invalid
            # unicode string.
            try:
                message = str(e.args[0])
            except (IndexError, UnicodeDecodeError):
                message = '({0})'.format(_("Could not get exception message."))
            rendered_html = '<h3 class="error">[ {0} ]</h3><p><i>{1}</i></p>'.format(
                _("The template cannot be rendered!"),
                message)
            if settings.DEBUG:
                raise
        return mark_safe(rendered_html)
