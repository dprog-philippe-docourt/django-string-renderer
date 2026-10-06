import bisect
import html
import re
from collections.abc import Callable, Iterable
from types import TracebackType
from typing import Any, NamedTuple

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.template import engines, TemplateSyntaxError
from django.template.base import DebugLexer, Lexer, Origin, Parser, tag_re, Token, TokenType, UNKNOWN_SOURCE
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
    '‚': ("'", "‘’'"),
}
# HTML entities that may stand for quotes, e.g. &ldquo;, &#8220; or &#x27;: rich text editors store the typographic
# quotes as entities unless they are configured otherwise, and HTML escaping turns the straight quotes into entities.
# The numbers of the entities are short, so that decoding them cannot fail.
_QUOTE_ENTITY_REGEX = re.compile(r'&(?:[lr]dquo|bdquo|[lr]squo|sbquo|quot|apos|#[0-9]{1,8}|#[xX][0-9a-fA-F]{1,8});')

# Outside of string literals, the code of a template tag is cleaned from the HTML tags added by formatting (e.g. bold
# text), from the non-breaking spaces and from the invisible characters inserted by rich text editors.
# The element name of an HTML tag is followed by the end of the tag or by a character that cannot be part of the name.
_HTML_TAG_REGEX = re.compile(r'</?(?P<element>[a-zA-Z][a-zA-Z0-9]*)(?:[^<>a-zA-Z0-9][^<>]*)?>')
# HTML elements that do not separate the text around them, such as bold text: their tags are removed, so that this text
# is joined like the editor displays it. The tags of the other elements, such as line breaks, are replaced by a space.
_INLINE_HTML_ELEMENTS = frozenset((
    'a', 'abbr', 'acronym', 'b', 'bdi', 'bdo', 'big', 'cite', 'code', 'data', 'del', 'dfn', 'em', 'font', 'i', 'ins',
    'kbd', 'label', 'mark', 'nobr', 'q', 's', 'samp', 'small', 'span', 'strike', 'strong', 'sub', 'sup', 'time', 'tt',
    'u', 'var', 'wbr',
))
_TAG_CODE_CLEANUP_REGEX = re.compile(
    r'(?P<html>' + _HTML_TAG_REGEX.pattern + ')'
    r'|(?P<space>&nbsp;|&#160;|&#x[aA]0;|[\u00a0\u2007\u202f])'
    r'|(?P<invisible>[\u200b\ufeff])'
)
_COMPARISON_OPERATOR_REGEX = re.compile(r'(?<!\S)(-gte|-gt|-lte|-lt)(?!\S)')
# Rich text editors escape the "<" and ">" characters typed by their users, even inside template tags.
_ESCAPED_COMPARISON_CHARACTER_REGEX = re.compile(r'&(?:(?P<gt>gt|#62|#x3e)|lt|#60|#x3c);', re.IGNORECASE)

# Block tags that produce no output by themselves, which can be moved out of the paragraphs that contain nothing else:
# the tags opening a block whose other tags (e.g. {% else %} or {% endif %}) produce no output either, and the tags that
# are not part of a block.
_SILENT_BLOCK_OPENING_TAGS = frozenset((
    'if', 'for', 'with', 'comment', 'autoescape', 'spaceless', 'ifchanged', 'filter',
))
_SILENT_TAGS = frozenset(('load', 'resetcycle'))
# Tags continuing the block opened before them.
_INTERMEDIATE_TAGS = frozenset(('elif', 'else', 'empty'))
# A block tag, which can neither span over the end of another block tag nor contain the start of one.
_BLOCK_TAG_REGEX = re.compile(r'\{%(?:(?!%\}|\{%).)*%\}')
# A paragraph that contains nothing but block tags. Its attributes cannot contain template tags, which would be lost.
_BLOCK_TAGS_PARAGRAPH_REGEX = re.compile(
    r'<p(?:\s[^<>{}]*)?>((?:\s|&nbsp;|<br\s*/?>|' + _BLOCK_TAG_REGEX.pattern + ')*)</p>', re.IGNORECASE)
# The opening or the closing tag of any paragraph.
_PARAGRAPH_MARKUP_REGEX = re.compile(r'<(/?)p(?:\s[^<>]*)?>', re.IGNORECASE)

_ON_ERROR_MODES = (None, 'raise', 'html', 'text')


def check_template_syntax(template_string: str, extra_tags: list[str] | None = None, auto_escape: bool = True,
                          engine_name: str = 'django', **options: Any) -> tuple[bool, Exception | None]:
    """
    Check the syntax of a template the way ``StringTemplateRenderer`` builds it with the same arguments.
    """
    return StringTemplateRenderer(template_string, extra_tags=extra_tags, auto_escape=auto_escape,
                                  engine_name=engine_name, **options).check_template_syntax()


def _match_quote_entity(content: str, position: int) -> tuple[str, int] | None:
    """
    Get the quote stored as an HTML entity at a position of the content of a template tag, along with the end position
    of the entity.
    """
    entity = _QUOTE_ENTITY_REGEX.match(content, position)
    if entity is None:
        return None
    quote = html.unescape(entity.group())
    return (quote, entity.end()) if quote in _LITERAL_QUOTES else None


def _clean_tag_code(code: str, is_block_tag: bool) -> str:
    def cleanup(match: re.Match) -> str:
        if match.group('invisible'):
            return ''
        if match.group('html') and match.group('element').lower() in _INLINE_HTML_ELEMENTS:
            return ''
        return ' '

    code = _TAG_CODE_CLEANUP_REGEX.sub(cleanup, code)
    if is_block_tag:
        # The escaped characters are decoded once the HTML tags are removed, so that they cannot be mistaken for them.
        code = _ESCAPED_COMPARISON_CHARACTER_REGEX.sub(lambda match: '>' if match.group('gt') else '<', code)
        code = _COMPARISON_OPERATOR_REGEX.sub(lambda match: _COMPARISON_OPERATORS[match.group(1)], code)
    return code


def _clean_tag_content(content: str, is_block_tag: bool) -> str:
    """
    Clean the content of a template tag (without its delimiters) written in a rich text editor.

    String literals are kept as is, except for their quotes that are replaced by straight ones. The quotes may be
    stored as HTML entities: a literal opened by an entity is closed by an entity or by a straight quote, while a
    literal opened by a character is closed by a character, so that the entities and the apostrophes written inside
    literals are kept.
    """
    cleaned_parts = []
    code_start = 0
    position = 0
    while position < len(content):
        char = content[position]
        opening_entity = _match_quote_entity(content, position) if char == '&' else None
        if opening_entity is not None:
            quote, literal_start = opening_entity
        elif char in _LITERAL_QUOTES:
            quote, literal_start = char, position + 1
        else:
            # The quotes of the attributes of an HTML tag do not delimit string literals.
            html_tag = _HTML_TAG_REGEX.match(content, position) if char == '<' else None
            position = html_tag.end() if html_tag else position + 1
            continue
        straight_quote, closing_quotes = _LITERAL_QUOTES[quote]
        cleaned_parts.append(_clean_tag_code(content[code_start:position], is_block_tag))
        end = literal_start
        literal_end = None
        while end < len(content):
            if content[end] in closing_quotes and (opening_entity is None or content[end] == straight_quote):
                literal_end = end + 1
                break
            closing_entity = _match_quote_entity(content, end) if opening_entity and content[end] == '&' else None
            if closing_entity is not None and closing_entity[0] in closing_quotes:
                literal_end = closing_entity[1]
                break
            # Skip escaped characters, as Django does for string literals.
            end += 2 if content[end] == '\\' else 1
        if literal_end is None:
            # Unterminated literal: keep it untouched.
            cleaned_parts.append(content[position:])
            return ''.join(cleaned_parts)
        cleaned_parts.append(straight_quote + content[literal_start:end] + straight_quote)
        position = code_start = literal_end
    cleaned_parts.append(_clean_tag_code(content[code_start:], is_block_tag))
    return ''.join(cleaned_parts)


def _unescape_quotes(content: str, is_block_tag: bool) -> str:
    return content.replace("&#39;", "'").replace("&quot;", '"')


def _map_template_tags(template_string: str, map_tag_content: Callable[[str, bool], str]) -> str:
    """
    Map the content (without the delimiters) of the variable and block tags of a template.

    The template is split into tags exactly like Django does, so the text, the comments and the content of verbatim
    blocks are left untouched. Unlike the lexer of Django, the end of a verbatim block is found in the mapped tags, since
    Django builds the mapped template.
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


def _is_silent_tag(token: Token) -> bool:
    """
    Whether a block tag that is not part of a block produces no output, e.g. {% load %} or {% url ... as variable %}.
    """
    try:
        bits = token.split_contents()
    except StopIteration:
        # Django cannot split an unterminated translated string either, e.g. {% firstof _("x %}, so the tag cannot be
        # built anyway.
        return False
    if not bits:
        return False
    if bits[0] in _SILENT_TAGS:
        return True
    if bits[0] == 'cycle':
        # A named cycle produces its first value, unless it is silent.
        return len(bits) > 4 and bits[-3] == 'as' and bits[-1] == 'silent'
    return len(bits) > 2 and bits[-2] == 'as'


def _get_silent_tags(template_string: str) -> dict[int, int | None] | None:
    """
    Get the block tags of a template that produce no output by themselves, by start position, along with the number of
    the block they belong to (e.g. the {% if %}, {% else %} and {% endif %} tags of an if block), or None when they are
    not part of a block. Get None when the blocks are not well nested, since the template cannot be built anyway.
    """
    # The lexer of Django tells the block tags from the content of the verbatim blocks.
    tokens = [token for token in DebugLexer(template_string).tokenize() if token.token_type == TokenType.BLOCK]
    commands = [(token.contents.split() or [''])[0] for token in tokens]
    known_commands = set(commands)
    silent_tags: dict[int, int | None] = {}
    # Opening command, number and silence of the blocks opened before the current tag.
    open_blocks: list[tuple[str, int, bool]] = []
    block_count = 0
    for token, command in zip(tokens, commands):
        if open_blocks and open_blocks[-1][0] == 'comment' and command != 'endcomment':
            # Django skips the content of comment blocks.
            continue
        if 'end' + command in known_commands:
            block = (command, block_count, command in _SILENT_BLOCK_OPENING_TAGS)
            open_blocks.append(block)
            block_count += 1
        elif command.startswith('end') and command[3:] in known_commands:
            if not open_blocks or open_blocks[-1][0] != command[3:]:
                return None
            block = open_blocks.pop()
        elif command in _INTERMEDIATE_TAGS:
            if not open_blocks:
                return None
            block = open_blocks[-1]
        else:
            if _is_silent_tag(token):
                silent_tags[token.position[0]] = None
            continue
        if block[2]:
            silent_tags[token.position[0]] = block[1]
    return None if open_blocks else silent_tags


def _get_paragraph_block_tags(paragraph: re.Match, tags: list[re.Match]) -> str:
    # The line breaks are kept where they are, so that the line numbers of the syntax errors stay right.
    parts = []
    position = paragraph.start()
    for tag in tags:
        parts.append('\n' * paragraph.string.count('\n', position, tag.start()))
        parts.append(tag.group())
        position = tag.end()
    parts.append('\n' * paragraph.string.count('\n', position, paragraph.end()))
    return ''.join(parts)


def _remove_block_tag_paragraphs(template_string: str) -> str:
    paragraphs = list(_BLOCK_TAGS_PARAGRAPH_REGEX.finditer(template_string))
    if not paragraphs:
        return template_string
    silent_tags = _get_silent_tags(template_string)
    if silent_tags is None:
        return template_string
    # Tags of the paragraphs that contain nothing but tags producing no output, by paragraph.
    paragraph_tags = {}
    for index, paragraph in enumerate(paragraphs):
        tags = list(_BLOCK_TAG_REGEX.finditer(template_string, paragraph.start(1), paragraph.end(1)))
        if tags and all(tag.start() in silent_tags for tag in tags):
            paragraph_tags[index] = tags
    tag_paragraphs = {tag.start(): index for index, tags in paragraph_tags.items() for tag in tags}
    # Start positions of the opening and closing tags of the paragraphs, and whether they open a paragraph.
    paragraph_markups = [(markup.start(), not markup.group(1))
                         for markup in _PARAGRAPH_MARKUP_REGEX.finditer(template_string)]

    def is_in_kept_paragraph(tag: int) -> bool:
        if tag in tag_paragraphs:
            return False
        previous_markup = bisect.bisect(paragraph_markups, tag, key=lambda markup: markup[0]) - 1
        return previous_markup >= 0 and paragraph_markups[previous_markup][1]

    block_tags: dict[int, list[int]] = {}
    for tag, block in silent_tags.items():
        if block is not None:
            block_tags.setdefault(block, []).append(tag)
    # A block is moved out of its paragraphs only if none of its tags stays inside a paragraph. Otherwise, the
    # paragraphs would not be balanced anymore when the block is skipped, e.g. "<p>{% if a %}</p><p>x {% endif %}</p>".
    # The tags outside of the paragraphs do not prevent it, e.g. "<p>{% for x in xs %}</p><p>{{ x }}</p>{% endfor %}".
    removed_paragraphs = set(paragraph_tags)
    incomplete_blocks = [block for block, tags in block_tags.items() if any(map(is_in_kept_paragraph, tags))]
    known_incomplete_blocks = set(incomplete_blocks)
    while incomplete_blocks:
        for tag in block_tags[incomplete_blocks.pop()]:
            kept_paragraph = tag_paragraphs.get(tag)
            if kept_paragraph is None or kept_paragraph not in removed_paragraphs:
                continue
            removed_paragraphs.remove(kept_paragraph)
            for other_tag in paragraph_tags[kept_paragraph]:
                other_block = silent_tags[other_tag.start()]
                if other_block is not None and other_block not in known_incomplete_blocks:
                    known_incomplete_blocks.add(other_block)
                    incomplete_blocks.append(other_block)
    parts = []
    position = 0
    for index in sorted(removed_paragraphs):
        parts.append(template_string[position:paragraphs[index].start()])
        parts.append(_get_paragraph_block_tags(paragraphs[index], paragraph_tags[index]))
        position = paragraphs[index].end()
    parts.append(template_string[position:])
    return ''.join(parts)


def _get_error_message(error: Exception) -> str:
    # In some rare cases exc_value.args can be empty or an invalid unicode string.
    try:
        return str(error.args[0])
    except (IndexError, UnicodeDecodeError):
        return '({0})'.format(_("Could not get exception message."))


def _make_error_html(title: str, error: Exception) -> SafeString:
    return format_html('<h3 class="error">[ {0} ]</h3><p><i>{1}</i></p>', title, _get_error_message(error))


def _compile_template(engine: Any, template_string: str) -> tuple[Any, Exception | None]:
    try:
        return engine.from_string(template_string), None
    except Exception as error:
        return None, error


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


class _Build(NamedTuple):
    """
    Result of building a template.
    """
    template: Any
    # The template string that is built.
    template_string: str
    # The error that prevents building the template.
    error: Exception | None
    # The traceback and the context of the error, which change when it is raised, so that they are restored to raise it
    # again.
    error_traceback: TracebackType | None = None
    error_context: BaseException | None = None
    # The options of the renderer that the template is built with.
    options: tuple = ()


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
      empty paragraphs. The tags of a block, e.g. {% if %}, {% else %} and {% endif %}, are moved out of their
      paragraphs only if none of them stays inside a paragraph, so that the paragraphs stay balanced.
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
        for argument, names in (('extra_tags', extra_tags), ('allowed_tags', allowed_tags),
                                ('allowed_filters', allowed_filters)):
            if isinstance(names, str):
                raise TypeError(f'{argument} must be an iterable of names, not a string.')
        self.template_string = template_string
        self.auto_escape = auto_escape
        self.extra_tags = list(extra_tags or [])
        self.engine_name = engine_name
        self.spaceless = spaceless
        self.unescape_quotes_in_text = unescape_quotes_in_text
        self.remove_block_tag_paragraphs = remove_block_tag_paragraphs
        self.on_error = on_error
        self.allowed_tags = None if allowed_tags is None else frozenset(allowed_tags)
        self.allowed_filters = None if allowed_filters is None else frozenset(allowed_filters)
        self._build: _Build | None = None

    def render_template(self, context, request=None) -> str:
        build = self._get_build()
        if build.error is not None:
            # The same error is raised by every rendering: its traceback and its context are restored, so that they
            # neither grow nor keep what the previous renderings were doing.
            build.error.__context__ = build.error_context
            error = build.error.with_traceback(build.error_traceback)
            return self._handle_error(error, _("The template cannot be built!"))
        try:
            rendered_template = build.template.render(context=context, request=request)
        except Exception as e:
            return self._handle_error(e, _("The template cannot be rendered!"))
        return mark_safe(rendered_template)

    def check_template_syntax(self) -> tuple[bool, Exception | None]:
        """
        Check that the template can be built the way the renderer builds it, and get the error that prevents it, which is
        usually a TemplateSyntaxError.
        """
        error = self._get_build().error
        return error is None, error

    @property
    def template_engine(self):
        return engines[self.engine_name]

    def get_prepared_template_string(self) -> str:
        """
        Get the prepared version of the raw template string - passed to the ctor - that the renderer builds, according
        to the renderer configuration.
        """
        return self._get_build().template_string

    def _get_build(self) -> _Build:
        # The template is built again when the options of the renderer are changed.
        options = (self.template_string, self.auto_escape, tuple(self.extra_tags), self.engine_name, self.spaceless,
                   self.unescape_quotes_in_text, self.remove_block_tag_paragraphs, self.allowed_tags,
                   self.allowed_filters)
        build = self._build
        if build is None or build.options != options:
            build = self._build_template()
            error = build.error
            build = build._replace(error_traceback=None if error is None else error.__traceback__,
                                   error_context=None if error is None else error.__context__, options=options)
            # The build is stored at once, so that the threads sharing the renderer never get it incomplete.
            self._build = build
        return build

    def _build_template(self) -> _Build:
        """
        Build the template.

        The template string is first prepared like in version 0.5.0, so that every template that could be built before is
        still rendered the same way. Only when it cannot be built, its tags are cleaned from the artifacts of rich text
        editors, and it is built again.
        """
        # The engine and the tag libraries are checked first, so that their configuration errors are raised rather than
        # taken for template errors.
        engine = self.template_engine
        for library_name in self.extra_tags:
            if library_name not in engine.engine.template_libraries:
                raise ImproperlyConfigured(f'Unknown tag library in extra_tags: {library_name!r}.')
        template_string = self.template_string
        try:
            unescaped_template_string = self._unescape_template_quotes()
            prepared_template_string = self._prepare_template_tags(unescaped_template_string, clean_tags=False)
            template_body = self._get_template_body(prepared_template_string)
            template_string = self._wrap_template_body(template_body)
            template, error = _compile_template(engine, template_string)
            if error is not None:
                cleaned_template_string = self._prepare_template_tags(unescaped_template_string, clean_tags=True)
                if cleaned_template_string != prepared_template_string:
                    template_body = self._get_template_body(cleaned_template_string)
                    template_string = self._wrap_template_body(template_body)
                    template, error = _compile_template(engine, template_string)
                if error is not None:
                    return _Build(None, template_string, self._get_template_body_error(engine, template_body, error))
            # The tags and filters are checked once the template is built, since a template that can be built is never
            # cleaned.
            if self.allowed_tags is not None or self.allowed_filters is not None:
                self._check_allowed_tags_and_filters(engine, template_body)
        except Exception as e:
            # Even an error raised while preparing the template string is handled like the errors of the template.
            return _Build(None, template_string, e)
        return _Build(template, template_string, None)

    def _get_template_body_error(self, engine: Any, template_body: str, error: Exception) -> Exception:
        """
        Get the syntax error of the template body without the tags that wrap it, when the error mentions them, e.g.
        "expected 'endspaceless'". The line numbers are the same, since the wrapping tags have no line breaks.
        """
        wrapping_tags = [tag for tag, is_used in (('spaceless', self.spaceless), ('autoescape', not self.auto_escape))
                         if is_used]
        if not isinstance(error, TemplateSyntaxError) or not any(tag in str(error) for tag in wrapping_tags):
            return error
        _template, template_body_error = _compile_template(engine, self._load_tags() + template_body)
        return template_body_error if isinstance(template_body_error, TemplateSyntaxError) else error

    def _check_allowed_tags_and_filters(self, engine: Any, template_body: str) -> None:
        # Parse the template body on its own, since the tags wrapping it are not written by the author of the template.
        parser = _UsageRecordingParser(Lexer(template_body).tokenize(), engine.engine.template_libraries,
                                       engine.engine.template_builtins, Origin(UNKNOWN_SOURCE))
        for library_name in self.extra_tags:
            parser.add_library(engine.engine.template_libraries[library_name])
        parser.parse()
        if self.allowed_tags is not None:
            forbidden_tags = [tag for tag in parser.used_tags if tag not in self.allowed_tags]
            if forbidden_tags:
                error = TemplateSyntaxError(ngettext(
                    'The tag %(tags)s is not allowed.', 'The tags %(tags)s are not allowed.', len(forbidden_tags),
                ) % dict(tags=', '.join(f"'{tag}'" for tag in forbidden_tags)))
                error.token = parser.used_tags[forbidden_tags[0]]
                raise error
        if self.allowed_filters is not None:
            forbidden_filters = sorted(parser.used_filters - self.allowed_filters)
            if forbidden_filters:
                raise TemplateSyntaxError(ngettext(
                    'The filter %(filters)s is not allowed.', 'The filters %(filters)s are not allowed.',
                    len(forbidden_filters),
                ) % dict(filters=', '.join(f"'{filter_name}'" for filter_name in forbidden_filters)))

    def _unescape_template_quotes(self) -> str:
        """
        Unescape the quotes of the template string, which is the first step of its preparation.
        """
        if self.unescape_quotes_in_text:
            return _unescape_quotes(self.template_string, is_block_tag=False)
        return _map_template_tags(self.template_string, _unescape_quotes)

    def _prepare_template_tags(self, unescaped_template_string: str, clean_tags: bool) -> str:
        """
        Prepare the tags of the template string whose quotes are unescaped, by cleaning them or not.
        """
        if clean_tags:
            return _map_template_tags(unescaped_template_string, _clean_tag_content)
        prepared_template_string = unescaped_template_string
        for regex in COMPARISON_OP_REGEX:
            prepared_template_string = regex[1].sub(regex[0], prepared_template_string)
        return prepared_template_string

    def _get_template_body(self, prepared_template_string: str) -> str:
        """
        Get the template body, without the tags that wrap it, from the template string whose tags are prepared.
        """
        if self.remove_block_tag_paragraphs:
            # The paragraphs are removed last, so that their tags are recognized once cleaned.
            return _remove_block_tag_paragraphs(prepared_template_string)
        return prepared_template_string

    def _load_tags(self) -> str:
        return '{%load ' + ' '.join(self.extra_tags) + '%}' if self.extra_tags else ''

    def _wrap_template_body(self, prepared_template_string: str) -> str:
        if not self.auto_escape:
            prepared_template_string = '{% autoescape off %}' + prepared_template_string + '{% endautoescape %}'
        if self.spaceless:
            prepared_template_string = '{%spaceless%}' + prepared_template_string + '{%endspaceless%}'
        return self._load_tags() + prepared_template_string

    def _handle_error(self, error: Exception, title: str) -> str:
        if callable(self.on_error):
            return self.on_error(error)
        if self.on_error == 'raise' or (self.on_error is None and settings.DEBUG):
            raise error
        if self.on_error == 'text':
            return '[ {0} ] {1}'.format(title, _get_error_message(error))
        return _make_error_html(title, error)
