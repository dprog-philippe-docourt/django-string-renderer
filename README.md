[![Latest PyPI version](https://badge.fury.io/py/django-string-renderer.svg)](https://badge.fury.io/py/django-string-renderer)
[![Build and Test](https://github.com/dprog-philippe-docourt/django-string-renderer/actions/workflows/ci.yml/badge.svg)](https://github.com/dprog-philippe-docourt/django-string-renderer/actions)

# django-string-renderer
Render Django templates written by the users of your site, typically in a rich text editor such as TinyMCE: e-mails, notifications, page snippets...

Rendering a string with Django takes two lines. Rendering a string that a non-developer wrote in a WYSIWYG editor is another story: the editor escapes `<` and `>`, inserts non-breaking spaces, wraps tags in formatting or in paragraphs, and a broken template must not break the page or the e-mail that displays it. This package takes care of that:

* comparison operators that survive rich text editors: `{% if recipient.age -gte 18 %}`;
* automatic cleanup of the artifacts left by editors inside template tags;
* errors rendered as a readable message instead of an exception, or handled the way you choose;
* a validator for form and model fields, which reports the line of the error;
* optional allowlists of template tags and filters;
* a recommended TinyMCE configuration, checked against what TinyMCE actually stores.

## Requirements
This package is tested against Python 3.10 to 3.14 and Django 5.2 to 6.1. It uses no models, and requires no other settings than a `django` engine in the `TEMPLATES` setting.

## Installation
```bash
pip install django-string-renderer
```
Then add `stringrenderer` to your `INSTALLED_APPS` setting, which provides the translations of its messages:
```python
INSTALLED_APPS = [
    ...,
    'stringrenderer',
]
```

## Usage
Build a renderer from a string, then render it with the context of your choice:
```python
from stringrenderer import StringTemplateRenderer

renderer = StringTemplateRenderer("Hello {{ recipient.first_name }} {{ recipient.last_name }}!")
rendered_content = renderer.render_template(context=dict(recipient=recipient_1), request=request)
rendered_content = renderer.render_template(context=dict(recipient=recipient_2))
```
The template is built from the string the first time it is rendered, and cached by the renderer for the next renderings.

Check the syntax of a template, with the same arguments as the renderer:
```python
from stringrenderer import check_template_syntax

is_valid, syntax_error = check_template_syntax("{% if recipient.age -gte 18 %}Adult{% endif %}")
```

Or validate a form or model field:
```python
from django.db import models
from stringrenderer.validators import TemplateSyntaxValidator


class Newsletter(models.Model):
    subject = models.CharField(max_length=200, validators=[TemplateSyntaxValidator(auto_escape=False)])
    body = models.TextField(validators=[TemplateSyntaxValidator(extra_tags=['i18n'])])
```
The validator takes the arguments of the renderer, which must match the ones used to render the field. Its error message gives the line of the error when it is known: `This template is not valid (line 3): Unclosed tag on line 3: 'if'. Looking for one of: elif, else, endif.`

### Arguments
| Argument | Default | Effect |
|---|---|---|
| `extra_tags` | `None` | Names of the template tag libraries loaded before the template, e.g. `['i18n']`. |
| `auto_escape` | `True` | Whether the variables are escaped. Use `False` for plain text, such as the subject of an e-mail. |
| `engine_name` | `'django'` | Name of the template engine in the `TEMPLATES` setting. |
| `spaceless` | `True` | Whether the whitespace between HTML tags is removed, like the `spaceless` tag does. Beware that `<b>John</b> <i>Doe</i>` is then rendered as "JohnDoe". |
| `unescape_quotes_in_text` | `True` | The HTML entities of quotes (`&quot;` and `&#39;`) are always replaced by quotes inside the template tags. Whether they are also replaced in the rest of the template, which breaks the HTML attributes that contain escaped quotes. |
| `remove_block_tag_paragraphs` | `False` | Whether the paragraphs that contain nothing but block tags producing no output (e.g. `<p>{% if ... %}</p>`, `<p>{% endfor %}</p>` or `<p>{% ... as variable %}</p>`) are replaced by their tags, so that no empty paragraphs are rendered. |
| `on_error` | `None` | What to do when the template cannot be built or rendered, see [Errors](#errors). |
| `allowed_tags` | `None` | Names of the template tags that the template may use, see [Restricting tags and filters](#restricting-tags-and-filters). |
| `allowed_filters` | `None` | Names of the filters that the template may use. |

The defaults keep the behavior of the previous versions. For a new project, `spaceless=False`, `unescape_quotes_in_text=False` and `remove_block_tag_paragraphs=True` are better choices for templates written in a rich text editor.

### Errors
By default, a template that cannot be built or rendered is rendered as an HTML error message, unless the `DEBUG` setting is true, in which case the error is raised. The `on_error` argument changes this:

| `on_error` | Behavior |
|---|---|
| `None` | HTML error message, or the error is raised when `DEBUG` is true. |
| `'raise'` | The error is always raised. |
| `'html'` | HTML error message, even when `DEBUG` is true. |
| `'text'` | Plain text error message, which is not marked as safe. |
| A callable | Called with the error; its result is rendered. |

The error messages are escaped, and never mention the tags that the renderer adds around the template.

### Restricting tags and filters
The authors of the templates may not need every tag and filter, and some of them give access to more than intended: `{% include %}` renders any template of the site, and `|safe` disables escaping. The `allowed_tags` and `allowed_filters` arguments restrict them:
```python
renderer = StringTemplateRenderer(
    template_string,
    allowed_tags=['if', 'for', 'with', 'firstof', 'now'],
    allowed_filters=['date', 'default', 'length', 'lower', 'upper', 'title'],
)
```
The closing and intermediate tags, such as `endif` or `else`, do not need to be listed, unlike the tags of the libraries loaded with `extra_tags`. A template that uses another tag or filter cannot be built: the error is handled like any syntax error, and reported by `check_template_syntax()` and by the validator.

Keep in mind that the variables of a template can call the methods of the objects of its context that take no arguments (except the ones marked with `alters_data`). Give the templates written by users a context that only holds what they may access.

## Templates written in a rich text editor

### Comparison operators
Rich text editors escape the `<` and `>` characters, even inside template tags: `{% if recipient.age >= 18 %}` is stored as `{% if recipient.age &gt;= 18 %}`, which Django cannot parse. Use these operators instead, in any block tag:

| Operator | Meaning |
|---|---|
| `-lt` | `<` |
| `-lte` | `<=` |
| `-gt` | `>` |
| `-gte` | `>=` |

```django
{% if recipient.age is None or recipient.age -lt 18 %}Please ask your parents to confirm your participation.{% endif %}
```

### Automatic cleanup
When a template cannot be built, the renderer cleans its tags from the artifacts of rich text editors, and builds it again. Inside the tags, outside of the string literals, the cleanup:
* replaces the comparison operators above, even when the same one is used twice, or after a string literal;
* replaces the non-breaking spaces by spaces, and removes the invisible characters;
* removes the HTML tags added by formatting, e.g. `{{ <strong>recipient.first_name</strong> }}`;
* replaces the typographic quotes around string literals by straight ones, e.g. `{% if recipient.first_name == “John” %}`.

The text, the comments and the content of the `verbatim` blocks are never changed. Since the cleanup only applies to the templates that cannot be built otherwise, the templates that worked with the previous versions are rendered exactly as before.

### Recommended TinyMCE configuration
TinyMCE alters some template code with its default configuration. With [django-tinymce](https://github.com/jazzband/django-tinymce), use the following settings:
```python
TINYMCE_DEFAULT_CONFIG = {
    # Store characters as is, rather than as named HTML entities.
    "entity_encoding": "raw",
    # Do not rewrite URLs, which may contain template code.
    "convert_urls": False,
    "relative_urls": False,
    "remove_script_host": False,
    # ... the rest of your configuration.
}
```
Here is what TinyMCE 7.8 stores with its default configuration, compared to the recommended one:

| Content | Default configuration | Recommended configuration |
|---|---|---|
| `{% if recipient.first_name == "Hélène" %}` | `{% if recipient.first_name == "H&eacute;l&egrave;ne" %}`: the comparison is always false, without any error. | Unchanged. |
| `<a href="https://example.com/events/?id={{ event.pk }}">` edited on `https://example.com/notifications/add/` | `<a href="../../events/?id={{ event.pk }}">`: a broken link in an e-mail. | Unchanged. |
| Two spaces typed in a tag | `&nbsp;`, removed by the cleanup. | A non-breaking space character, which Django handles. |
| `>=` typed in a tag | `&gt;=`: use `-gte`. | `&gt;=`: use `-gte`. |

Do not use the `protect` option of TinyMCE to keep the template tags untouched: it hides them in the editor.

Run `scripts/capture_tinymce_fixtures.py` to capture what another version of TinyMCE stores; the tests use these captures.

## Help for template authors
You may adapt this summary for the help of your site.

* **Variables** are written between double curly braces, and replaced by their value: `Hello {{ recipient.first_name }}!`.
* **Filters** change the display of a variable, after a vertical bar: `{{ event.start_date|date:"d.m.Y" }}`, `{{ recipient.nickname|default:"friend" }}`.
* **Conditions** show content depending on a value: `{% if recipient.age -gte 18 %}Adult{% else %}Minor{% endif %}`. Use `-lt`, `-lte`, `-gt` and `-gte` to compare values, `==` and `!=` to test equality, and `and`, `or`, `not` to combine conditions.
* **Loops** repeat content for each item of a list: `{% for event in events %}{{ event.title }}{% empty %}No event.{% endfor %}`.
* The names of the variables and of the tags are case-sensitive, and are always in English.

## Testing
Get the source code from [GitHub](https://github.com/dprog-philippe-docourt/django-string-renderer), then run:
```bash
pip install -r requirements.txt -r requirements-dev.txt
python runtests.py
```
This runs the test suite and checks the type annotations with `mypy`, with the locally installed versions of Python and Django.

The tests check that every template that version 0.5.0 could build is still prepared exactly the same way. You can run this check against the templates of your own project, with its settings, so that its template tag libraries are available:
```bash
DJANGO_SETTINGS_MODULE=myproject.settings PYTHONPATH=.:/path/to/myproject python -m tests.compatibility corpus.json
```
where `corpus.json` holds a list of objects with a `template` key, and the `auto_escape` and `extra_tags` keys used to render it.

## Projects Using this App
This app is used in the following projects:
* [MyGym Web](https://mygym-web.ch/): a web platform for managing sports clubs. django-string-renderer is used to render the messages and emails addressed to the members.
