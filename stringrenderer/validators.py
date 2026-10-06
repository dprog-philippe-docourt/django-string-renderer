from typing import Any

from django.core.exceptions import ValidationError
from django.template import TemplateSyntaxError
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _

from stringrenderer import check_template_syntax, StringTemplateRenderer


@deconstructible
class TemplateSyntaxValidator:
    """
    Validate that a string is a template that ``StringTemplateRenderer`` can build.

    The keyword arguments are given to ``StringTemplateRenderer``, so they must match the ones used to render the
    template, e.g. ``TemplateSyntaxValidator(extra_tags=['i18n'], allowed_tags=['if', 'for', 'translate'])``.

    The message can use the "error" and "line" placeholders; the line is None when it is unknown. Any error that prevents
    building the template makes it invalid, since Django raises other errors than TemplateSyntaxError for some invalid
    templates, e.g. a StopIteration for {% if _("x %} or a RecursionError for a template nested too deeply. The messages
    of these errors, which mean nothing to the authors of the templates, are replaced by a generic one.
    """
    message = _('This template is not valid: %(error)s')
    message_with_line = _('This template is not valid (line %(line)s): %(error)s')
    code = 'invalid_template'

    def __init__(self, message: str | None = None, code: str | None = None, **renderer_options: Any) -> None:
        if message is not None:
            self.message = self.message_with_line = message
        if code is not None:
            self.code = code
        # The names are read once, so that the iterators are not used up by the first template checked.
        for option, read_names in (('extra_tags', list), ('allowed_tags', frozenset), ('allowed_filters', frozenset)):
            names = renderer_options.get(option)
            if names is not None and not isinstance(names, str):
                renderer_options[option] = read_names(names)
        self.renderer_options = renderer_options
        # Check the options now, rather than when the first value is validated.
        StringTemplateRenderer('', **renderer_options)

    def __call__(self, value: str) -> None:
        is_valid, error = check_template_syntax(value, **self.renderer_options)
        if not is_valid:
            token = getattr(error, 'token', None)
            line = getattr(token, 'lineno', None)
            raise ValidationError(self.message if line is None else self.message_with_line, code=self.code,
                                  params=dict(error=self._get_error_description(error), line=line))

    @staticmethod
    def _get_error_description(error: Exception | None) -> object:
        if isinstance(error, TemplateSyntaxError):
            return error
        if isinstance(error, RecursionError):
            return _('The template is nested too deeply.')
        return _('Unexpected error (%(type)s).') % dict(type=type(error).__name__)

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, TemplateSyntaxValidator) and self.message == other.message
                and self.message_with_line == other.message_with_line and self.code == other.code
                and self.renderer_options == other.renderer_options)
