import re
from collections.abc import Callable, Iterable
from typing import Any

from django.conf import settings
from django.template import engines, TemplateSyntaxError
from django.template.base import Lexer, Origin, Parser, tag_re, Token, UNKNOWN_SOURCE
from django.utils.html import format_html
from django.utils.safestring import mark_safe, SafeString
from django.utils.translation import gettext as _, ngettext


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

# Block tags that produce no output by themselves, which can be moved out of the paragraphs that contain nothing else.
_STRUCTURAL_TAGS = frozenset((
    'if', 'elif', 'else', 'endif', 'for', 'empty', 'endfor', 'with', 'endwith', 'comment', 'endcomment', 'load',
    'autoescape', 'endautoescape', 'spaceless', 'endspaceless', 'ifchanged', 'endifchanged', 'filter', 'endfilter',
))
# A block tag, which cannot span over the end of another block tag.
_BLOCK_TAG_REGEX = re.compile(r'\{%(?:(?!%\}).)*%\}')
_BLOCK_TAGS_PARAGRAPH_REGEX = re.compile(
    r'<p(?:\s[^<>]*)?>((?:\s|&nbsp;|<br\s*/?>|' + _BLOCK_TAG_REGEX.pattern + ')*)</p>', re.IGNORECASE)

_ON_ERROR_MODES = (None, 'raise', 'html', 'text')


def check_template_syntax(template_string: str, extra_tags: list[str] | None = None, auto_escape: bool = True,
                          engine_name: str = 'django', **options: Any) -> tuple[bool, TemplateSyntaxError | None]:
    """
    Check the syntax of a template the way ``StringTemplateRenderer`` builds it with the same arguments.
    """
    return StringTemplateRenderer(template_string, extra_tags=extra_tags, auto_escape=auto_escape,
                                  engine_name=engine_name, **options).check_template_syntax()


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


def _unescape_quotes(content: str, is_block_tag: bool) -> str:
    return content.replace("&#39;", "'").replace("&quot;", '"')


def _map_template_tags(template_string: str, map_tag_content: Callable[[str, bool], str]) -> str:
    """
    Map the content (without the delimiters) of the variable and block tags of a template.

    The template is split into tags exactly like Django does, so the text, the comments and the content of verbatim
    blocks are left untouched.
    """
    bits = []
    verbatim_end = None
    in_tag = False
    for bit in tag_re.split(template_string):
        if in_tag and bit[:2] in ('{%', '{{'):
            is_block_tag = bit[:2] == '{%'
            mapped_bit = bit[:2] + map_tag_content(bit[2:-2], is_block_tag) + bit[-2:]
            content = mapped_bit[2:-2].strip()
            if verbatim_end:
                if is_block_tag and content == verbatim_end:
                    verbatim_end = None
                    bit = mapped_bit
            else:
                if is_block_tag and content[:9] in ('verbatim', 'verbatim '):
                    verbatim_end = 'end' + content
                bit = mapped_bit
        bits.append(bit)
        in_tag = not in_tag
    return ''.join(bits)


def _get_verbatim_spans(template_string: str) -> list[tuple[int, int]]:
    """
    Get the start and end positions of the content of the verbatim blocks of a template.
    """
    spans = []
    verbatim_end = None
    content_start = 0
    for match in tag_re.finditer(template_string):
        if match.group()[:2] != '{%':
            continue
        content = match.group()[2:-2].strip()
        if verbatim_end:
            if content == verbatim_end:
                spans.append((content_start, match.start()))
                verbatim_end = None
        elif content[:9] in ('verbatim', 'verbatim '):
            verbatim_end = 'end' + content
            content_start = match.end()
    if verbatim_end:
        spans.append((content_start, len(template_string)))
    return spans


def _is_structural_block_tag(block_tag: str) -> bool:
    bits = block_tag[2:-2].split()
    return bool(bits) and (bits[0] in _STRUCTURAL_TAGS or (len(bits) > 2 and bits[-2] == 'as'))


def _remove_block_tag_paragraphs(template_string: str) -> str:
    verbatim_spans = _get_verbatim_spans(template_string)

    def remove_paragraph(match: re.Match) -> str:
        block_tags = _BLOCK_TAG_REGEX.findall(match.group(1))
        in_verbatim_block = any(start < match.end() and match.start() < end for start, end in verbatim_spans)
        if not block_tags or in_verbatim_block or not all(_is_structural_block_tag(tag) for tag in block_tags):
            return match.group()
        # Keep the line breaks, so that the line numbers of the syntax errors stay right.
        return ''.join(block_tags) + '\n' * match.group().count('\n')

    return _BLOCK_TAGS_PARAGRAPH_REGEX.sub(remove_paragraph, template_string)


def _get_error_message(error: Exception) -> str:
    # In some rare cases exc_value.args can be empty or an invalid unicode string.
    try:
        return str(error.args[0])
    except (IndexError, UnicodeDecodeError):
        return '({0})'.format(_("Could not get exception message."))


def _make_error_html(title: str, error: Exception) -> SafeString:
    return format_html('<h3 class="error">[ {0} ]</h3><p><i>{1}</i></p>', title, _get_error_message(error))


class _UsageRecordingTags(dict):
    """
    Compilation functions of the tags known by a parser, which records the tags used by the parsed template.
    """
    def __init__(self, tags: dict, used_tags: dict[str, Token], command_stack: list) -> None:
        super().__init__(tags)
        self.used_tags = used_tags
        self.command_stack = command_stack

    def __getitem__(self, command: str) -> Callable:
        # The parser pushes the tag being compiled on its command stack before looking up its compilation function.
        self.used_tags.setdefault(command, self.command_stack[-1][1])
        return super().__getitem__(command)


class _UsageRecordingParser(Parser):
    """
    Template parser that records the template tags and the filters used by a template.
    """
    tags: dict
    command_stack: list

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Token of the first use of each tag.
        self.used_tags: dict[str, Token] = {}
        self.used_filters: set[str] = set()
        self.tags = _UsageRecordingTags(self.tags, self.used_tags, self.command_stack)

    def find_filter(self, filter_name: str) -> Callable:
        self.used_filters.add(filter_name)
        return super().find_filter(filter_name)


class _BuildError:
    """
    Stands for the template when it cannot be built.
    """
    def __init__(self, error: Exception) -> None:
        self.error = error


class StringTemplateRenderer(object):
    """
    Render a string as a Django template.

    Arguments:
    - extra_tags: names of the template tag libraries to load before the template.
    - auto_escape: whether the variables are escaped.
    - engine_name: name of the Django template engine, as declared in the TEMPLATES setting.
    - spaceless: whether the whitespace between HTML tags is removed (see the "spaceless" tag of Django).
    - unescape_quotes_in_text: the HTML entities of quotes (&quot; and &#39;) are always replaced by quotes inside the
      template tags; whether they are also replaced in the rest of the template, which breaks the HTML attributes that
      contain escaped quotes.
    - remove_block_tag_paragraphs: whether the paragraphs (<p>) that contain nothing but block tags producing no output
      (e.g. {% if %}, {% endfor %} or {% ... as variable %}) are replaced by their block tags, which avoids rendering
      empty paragraphs.
    - on_error: what to do when the template cannot be built or rendered: None renders an HTML error message, unless
      the DEBUG setting is true, in which case the error is raised; "raise" always raises the error; "html" always
      renders an HTML error message; "text" renders a plain text error message (not marked as safe); a callable is
      called with the error, and returns the rendered content.
    - allowed_tags: names of the template tags that the template may use, or None to allow every tag. The closing and
      intermediate tags (e.g. endif or else) do not need to be listed, unlike the tags loaded with extra_tags. A
      template that uses another tag cannot be built.
    - allowed_filters: names of the filters that the template may use, or None to allow every filter. A template that
      uses another filter cannot be built.
    """
    def __init__(self, template_string: str, extra_tags: list[str] | None = None, auto_escape: bool = True,
                 engine_name: str = 'django', *, spaceless: bool = True, unescape_quotes_in_text: bool = True,
                 remove_block_tag_paragraphs: bool = False,
                 on_error: str | Callable[[Exception], str] | None = None,
                 allowed_tags: Iterable[str] | None = None, allowed_filters: Iterable[str] | None = None) -> None:
        if not callable(on_error) and on_error not in _ON_ERROR_MODES:
            raise ValueError(f'Invalid on_error value: {on_error!r}.')
        self.template_string = template_string
        self._template: Any = None
        self.auto_escape = auto_escape
        self.extra_tags = extra_tags or []
        self.engine_name = engine_name
        self.spaceless = spaceless
        self.unescape_quotes_in_text = unescape_quotes_in_text
        self.remove_block_tag_paragraphs = remove_block_tag_paragraphs
        self.on_error = on_error
        self.allowed_tags = None if allowed_tags is None else frozenset(allowed_tags)
        self.allowed_filters = None if allowed_filters is None else frozenset(allowed_filters)

    def render_template(self, context, request=None) -> str:
        template = self._get_or_create_template()
        if isinstance(template, _BuildError):
            return self._handle_error(template.error, _("The template cannot be built!"))
        try:
            rendered_template = template.render(context=context, request=request)
        except Exception as e:
            return self._handle_error(e, _("The template cannot be rendered!"))
        return mark_safe(rendered_template)

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

    def get_prepared_template_string(self) -> str:
        """
        Get the prepared version of the raw template string - passed to the ctor - that the renderer builds, according
        to the renderer configuration.
        """
        _template, prepared_template_string, _error = self._build_template()
        return prepared_template_string

    def _get_or_create_template(self):
        if self._template:
            return self._template
        template, _prepared_template_string, error = self._build_template()
        self._template = template if error is None else _BuildError(error)
        return self._template

    def _build_template(self) -> tuple[Any, str, Exception | None]:
        """
        Build the template, and return it along with the prepared template string and the error raised, if any.

        The template string is first prepared like in version 0.5.0, so that every template that could be built before is
        still rendered the same way. Only when it cannot be built, its tags are cleaned from the artifacts of rich text
        editors, and it is built again.
        """
        template_body = self._prepare_template_body(clean_tags=False)
        prepared_template_string = self._wrap_template_body(template_body)
        try:
            return self._compile_template(template_body, prepared_template_string), prepared_template_string, None
        except Exception as e:
            error = e
        cleaned_template_body = self._prepare_template_body(clean_tags=True)
        cleaned_template_string = self._wrap_template_body(cleaned_template_body)
        if cleaned_template_string == prepared_template_string:
            return None, prepared_template_string, self._get_template_body_error(template_body, error)
        try:
            return self._compile_template(cleaned_template_body, cleaned_template_string), cleaned_template_string, None
        except Exception as e:
            return None, cleaned_template_string, self._get_template_body_error(cleaned_template_body, e)

    def _get_template_body_error(self, template_body: str, error: Exception) -> Exception:
        """
        Get the syntax error of the template body without the tags that wrap it, so that its message does not mention
        them, e.g. "expected 'endspaceless'". The line numbers are the same, since the wrapping tags have no line breaks.
        """
        if not isinstance(error, TemplateSyntaxError):
            return error
        load_tags = '{%load ' + ' '.join(self.extra_tags) + '%}' if self.extra_tags else ''
        try:
            self.template_engine.from_string(load_tags + template_body)
        except TemplateSyntaxError as template_body_error:
            return template_body_error
        return error

    def _compile_template(self, template_body: str, prepared_template_string: str) -> Any:
        template = self.template_engine.from_string(prepared_template_string)
        if self.allowed_tags is not None or self.allowed_filters is not None:
            self._check_allowed_tags_and_filters(template_body)
        return template

    def _check_allowed_tags_and_filters(self, template_body: str) -> None:
        # Parse the template body on its own, since the tags wrapping it are not written by the author of the template.
        engine = self.template_engine.engine
        parser = _UsageRecordingParser(Lexer(template_body).tokenize(), engine.template_libraries,
                                       engine.template_builtins, Origin(UNKNOWN_SOURCE))
        for library_name in self.extra_tags:
            parser.add_library(engine.template_libraries[library_name])
        parser.parse()
        if self.allowed_tags is not None:
            forbidden_tags = [tag for tag in parser.used_tags if tag not in self.allowed_tags]
            if forbidden_tags:
                error = TemplateSyntaxError(ngettext(
                    'The tag %(tags)s is not allowed.', 'The tags %(tags)s are not allowed.', len(forbidden_tags),
                ) % dict(tags=', '.join(f"'{tag}'" for tag in forbidden_tags)))
                error.token = parser.used_tags[forbidden_tags[0]]  # type: ignore[attr-defined]
                raise error
        if self.allowed_filters is not None:
            forbidden_filters = sorted(parser.used_filters - self.allowed_filters)
            if forbidden_filters:
                raise TemplateSyntaxError(ngettext(
                    'The filter %(filters)s is not allowed.', 'The filters %(filters)s are not allowed.',
                    len(forbidden_filters),
                ) % dict(filters=', '.join(f"'{filter_name}'" for filter_name in forbidden_filters)))

    def _prepare_template_body(self, clean_tags: bool) -> str:
        """
        Prepare the template string, without the tags that wrap it.
        """
        prepared_template_string = self.template_string
        if self.unescape_quotes_in_text:
            prepared_template_string = _unescape_quotes(prepared_template_string, is_block_tag=False)
        else:
            prepared_template_string = _map_template_tags(prepared_template_string, _unescape_quotes)
        if self.remove_block_tag_paragraphs:
            prepared_template_string = _remove_block_tag_paragraphs(prepared_template_string)
        if clean_tags:
            prepared_template_string = _map_template_tags(prepared_template_string, _clean_tag_content)
        else:
            for regex in COMPARISON_OP_REGEX:
                prepared_template_string = regex[1].sub(regex[0], prepared_template_string)
        return prepared_template_string

    def _wrap_template_body(self, prepared_template_string: str) -> str:
        if not self.auto_escape:
            prepared_template_string = '{% autoescape off %}' + prepared_template_string + '{% endautoescape %}'
        if self.spaceless:
            prepared_template_string = '{%spaceless%}' + prepared_template_string + '{%endspaceless%}'
        if self.extra_tags:
            prepared_template_string = '{%load ' + ' '.join(self.extra_tags) + '%}' + prepared_template_string
        return prepared_template_string

    def _handle_error(self, error: Exception, title: str) -> str:
        if callable(self.on_error):
            return self.on_error(error)
        if self.on_error == 'raise' or (self.on_error is None and settings.DEBUG):
            raise error
        if self.on_error == 'text':
            return '[ {0} ] {1}'.format(title, _get_error_message(error))
        return _make_error_html(title, error)
