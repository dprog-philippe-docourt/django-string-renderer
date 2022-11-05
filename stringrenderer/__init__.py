import re
from typing import Optional, List, Tuple

from django.conf import settings
from django.template import engines, Template, TemplateSyntaxError
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _


COMPARISON_OP_REGEX = [
            (r'{%\1>=', re.compile("\\{%([^\"\'\\}]+)-gte")),
            (r'{%\1>', re.compile("\\{%([^\"\'\\}]+)-gt")),
            (r'{%\1<=', re.compile("\\{%([^\"\'\\}]+)-lte")),
            (r'{%\1<', re.compile("\\{%([^\"\'\\}]+)-lt")),
        ]


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

    def check_template_syntax(self):
        return check_template_syntax(self.get_prepared_template_string())

    @property
    def template_engine(self):
        return engines[self.engine_name]

    def _get_or_create_template(self):
        if self._template:
            return self._template
        self._template = self._make_template_from_string()
        return self._template

    def _make_template_from_string(self):
        prepared_template_string = self.get_prepared_template_string()
        template_engine = self.template_engine
        try:
            template = template_engine.from_string(prepared_template_string)
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
            template = template_engine.from_string(rendered_html)
            if settings.DEBUG:
                raise
        return template

    def get_prepared_template_string(self):
        """
        Get a prepared version of the raw template string - passed to the ctor - according to renderer configuration.
        """
        prepared_template_string = self.template_string.replace("&#39;", "'").replace("&quot;", '"')
        for regex in COMPARISON_OP_REGEX:
            prepared_template_string = regex[1].sub(regex[0], prepared_template_string)
        if self.extra_tags:
            load_tags = '{%load ' + ' '.join(self.extra_tags) + '%}'
        else:
            load_tags = ''
        prepared_template_string = prepared_template_string if self.auto_escape else '{% autoescape off %}' + prepared_template_string + '{% endautoescape %}'
        prepared_template_string = load_tags + '{%spaceless%}' + prepared_template_string + '{%endspaceless%}'
        return prepared_template_string

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
