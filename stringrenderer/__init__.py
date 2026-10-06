import re
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.template import engines, TemplateSyntaxError
from django.template.base import tag_re
from django.utils.html import format_html
from django.utils.safestring import mark_safe, SafeString
from django.utils.translation import gettext as _


COMPARISON_OP_REGEX = [
            (r'{%\1>=', re.compile("\\{%([^\"\'\\}]+)-gte")),
            (r'{%\1>', re.compile("\\{%([^\"\'\\}]+)-gt")),
            (r'{%\1<=', re.compile("\\{%([^\"\'\\}]+)-lte")),
            (r'{%\1<', re.compile("\\{%([^\"\'\\}]+)-lt")),
        ]

_COMPARISON_OPERATORS = {'-gt': '>', '-gte': '>=', '-lt': '<', '-lte': '<='}

# Opening quotes of string literals inside template tags, each with the straight quote that replaces it and the
# characters that close the literal. Rich text editors and word processors often turn straight quotes into
# typographic ones.
_LITERAL_QUOTES = {
    '"': ('"', '"'),
    "'": ("'", "'"),
    '“': ('"', '”“"'),
    '”': ('"', '”"'),
    '„': ('"', '“”"'),
    '‘': ("'", "’‘'"),
    '’': ("'", "’'"),
}

# Outside of string literals, the code of a template tag is cleaned from the HTML tags added by formatting (e.g. bold
# text), from the non-breaking spaces and from the invisible characters inserted by rich text editors.
_HTML_TAG_REGEX = re.compile(r'</?[a-zA-Z][^<>]*>')
_TAG_CODE_CLEANUP_REGEX = re.compile(
    r'(?P<html>' + _HTML_TAG_REGEX.pattern + ')'
    r'|(?P<space>&nbsp;|&#160;|&#x[aA]0;|[\u00a0\u2007\u202f])'
    r'|(?P<invisible>[\u200b\ufeff])'
)
_COMPARISON_OPERATOR_REGEX = re.compile(r'(?<!\S)(-gte|-gt|-lte|-lt)(?!\S)')


def check_template_syntax(template_string: str, extra_tags: list[str] | None = None, auto_escape: bool = True,
                          engine_name: str = 'django') -> tuple[bool, TemplateSyntaxError | None]:
    """
    Check the syntax of a template the way ``StringTemplateRenderer`` builds it with the same arguments.
    """
    return StringTemplateRenderer(template_string, extra_tags=extra_tags, auto_escape=auto_escape,
                                  engine_name=engine_name).check_template_syntax()


def _clean_tag_code(code: str, is_block_tag: bool) -> str:
    def cleanup(match: re.Match) -> str:
        if match.group('html') or match.group('invisible'):
            return ''
        return ' '

    code = _TAG_CODE_CLEANUP_REGEX.sub(cleanup, code)
    if is_block_tag:
        code = _COMPARISON_OPERATOR_REGEX.sub(lambda match: _COMPARISON_OPERATORS[match.group(1)], code)
    return code


def _clean_tag_content(content: str, is_block_tag: bool) -> str:
    """
    Clean the content of a template tag (without its delimiters) written in a rich text editor.

    String literals are kept as is, except for their typographic quotes that are replaced by straight ones.
    """
    cleaned_parts = []
    code_start = 0
    position = 0
    while position < len(content):
        char = content[position]
        if char not in _LITERAL_QUOTES:
            # The quotes of the attributes of an HTML tag do not delimit string literals.
            html_tag = _HTML_TAG_REGEX.match(content, position) if char == '<' else None
            position = html_tag.end() if html_tag else position + 1
            continue
        straight_quote, closing_quotes = _LITERAL_QUOTES[char]
        cleaned_parts.append(_clean_tag_code(content[code_start:position], is_block_tag))
        end = position + 1
        while end < len(content) and content[end] not in closing_quotes:
            # Skip escaped characters, as Django does for string literals.
            end += 2 if content[end] == '\\' else 1
        if end >= len(content):
            # Unterminated literal: keep it untouched.
            cleaned_parts.append(content[position:])
            return ''.join(cleaned_parts)
        cleaned_parts.append(straight_quote + content[position + 1:end] + straight_quote)
        position = code_start = end + 1
    cleaned_parts.append(_clean_tag_code(content[code_start:], is_block_tag))
    return ''.join(cleaned_parts)


def _clean_template_tags(template_string: str) -> str:
    """
    Clean the variable and block tags of a template written in a rich text editor.

    The template is split into tags exactly like Django does, so the text, the comments and the content of verbatim
    blocks are left untouched.
    """
    bits = []
    verbatim_end = None
    in_tag = False
    for bit in tag_re.split(template_string):
        if in_tag and bit[:2] in ('{%', '{{'):
            is_block_tag = bit[:2] == '{%'
            cleaned_bit = bit[:2] + _clean_tag_content(bit[2:-2], is_block_tag) + bit[-2:]
            content = cleaned_bit[2:-2].strip()
            if verbatim_end:
                if is_block_tag and content == verbatim_end:
                    verbatim_end = None
                    bit = cleaned_bit
            else:
                if is_block_tag and content[:9] in ('verbatim', 'verbatim '):
                    verbatim_end = 'end' + content
                bit = cleaned_bit
        bits.append(bit)
        in_tag = not in_tag
    return ''.join(bits)


def _prepare_template_string(template_string: str, extra_tags: list[str], auto_escape: bool,
                             clean_tags: bool) -> str:
    prepared_template_string = template_string.replace("&#39;", "'").replace("&quot;", '"')
    if clean_tags:
        prepared_template_string = _clean_template_tags(prepared_template_string)
    else:
        for regex in COMPARISON_OP_REGEX:
            prepared_template_string = regex[1].sub(regex[0], prepared_template_string)
    if extra_tags:
        load_tags = '{%load ' + ' '.join(extra_tags) + '%}'
    else:
        load_tags = ''
    prepared_template_string = prepared_template_string if auto_escape else '{% autoescape off %}' + prepared_template_string + '{% endautoescape %}'
    prepared_template_string = load_tags + '{%spaceless%}' + prepared_template_string + '{%endspaceless%}'
    return prepared_template_string


def _build_template(template_string: str, extra_tags: list[str], auto_escape: bool,
                    compile_template: Callable[[str], Any]) -> tuple[Any, str, Exception | None]:
    """
    Build the template, and return it along with the prepared template string and the error raised, if any.

    The template string is first prepared exactly like in version 0.5.0, so that every template that could be built
    before is still rendered the same way. Only when it cannot be built, its tags are cleaned from the artifacts of rich
    text editors, and it is built again.
    """
    prepared_template_string = _prepare_template_string(template_string, extra_tags, auto_escape, clean_tags=False)
    try:
        return compile_template(prepared_template_string), prepared_template_string, None
    except Exception as e:
        error = e
    cleaned_template_string = _prepare_template_string(template_string, extra_tags, auto_escape, clean_tags=True)
    if cleaned_template_string == prepared_template_string:
        return None, prepared_template_string, error
    try:
        return compile_template(cleaned_template_string), cleaned_template_string, None
    except Exception as e:
        return None, cleaned_template_string, e


def _get_error_message(error: Exception) -> str:
    # In some rare cases exc_value.args can be empty or an invalid unicode string.
    try:
        return str(error.args[0])
    except (IndexError, UnicodeDecodeError):
        return '({0})'.format(_("Could not get exception message."))


def _make_error_html(title: str, error: Exception) -> SafeString:
    return format_html('<h3 class="error">[ {0} ]</h3><p><i>{1}</i></p>', title, _get_error_message(error))


class _ErrorTemplate:
    """
    Template that always renders the given HTML, which is therefore never interpreted as a template.
    """
    def __init__(self, html: SafeString) -> None:
        self.html = html

    def render(self, context: Any = None, request: Any = None) -> SafeString:
        return self.html


class StringTemplateRenderer(object):
    def __init__(self, template_string: str, extra_tags: list[str] | None = None, auto_escape: bool = True,
                 engine_name: str = 'django') -> None:
        self.template_string = template_string
        self._template = None
        self.auto_escape = auto_escape
        self.extra_tags = extra_tags or []
        self.engine_name = engine_name

    def render_template(self, context, request=None) -> str:
        template = self._get_or_create_template()
        return self._render_to_template(template=template, context=context, request=request)

    def check_template_syntax(self) -> tuple[bool, TemplateSyntaxError | None]:
        """
        Check the syntax of the template the way the renderer builds it.
        """
        _template, _prepared_template_string, error = self._build_template()
        if error is None:
            return True, None
        if isinstance(error, TemplateSyntaxError):
            return False, error
        raise error

    @property
    def template_engine(self):
        return engines[self.engine_name]

    def _get_or_create_template(self):
        if self._template:
            return self._template
        self._template = self._make_template_from_string()
        return self._template

    def _build_template(self) -> tuple[Any, str, Exception | None]:
        return _build_template(self.template_string, self.extra_tags, self.auto_escape,
                               self.template_engine.from_string)

    def _make_template_from_string(self):
        template, _prepared_template_string, error = self._build_template()
        if error is not None:
            if settings.DEBUG:
                raise error
            template = _ErrorTemplate(_make_error_html(_("The template cannot be built!"), error))
        return template

    def get_prepared_template_string(self) -> str:
        """
        Get the prepared version of the raw template string - passed to the ctor - that the renderer builds, according
        to the renderer configuration.
        """
        _template, prepared_template_string, _error = self._build_template()
        return prepared_template_string

    @staticmethod
    def _render_to_template(template, context, request=None):
        try:
            rendered_html = template.render(context=context, request=request)
        except Exception as e:
            rendered_html = _make_error_html(_("The template cannot be rendered!"), e)
            if settings.DEBUG:
                raise
        return mark_safe(rendered_html)
