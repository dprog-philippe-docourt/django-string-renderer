# Change Log

## 0.6.0 (2026-10-06)

### Breaking changes
* Drop support for Django < 5.2: Django 5.2 (LTS) is now the minimum required version.
* `check_template_syntax()` now checks a template the way `StringTemplateRenderer` builds it, and takes the same arguments. It accepts the comparison operators (`-gte` and the like) and the templates fixed by the cleanup of rich text editor artifacts, and rejects the templates that the renderer cannot build, such as templates extending another one. It returns the error that prevents building the template, which is usually a `TemplateSyntaxError`, but may be another error, e.g. a `RecursionError` for a template nested too deeply. To check a regular Django template, compile it with `django.template.Template`.
* `StringTemplateRenderer.get_prepared_template_string()` returns the template string that the renderer actually builds, which may have been cleaned, so it requires a configured template engine.
* The unused `djangocodemirror` dependency is removed.

### New features
* When a template cannot be built, its tags are cleaned from the artifacts of rich text editors, and it is built again: escaped comparison characters (`&lt;` and `&gt;`), comparison operators, non-breaking spaces, invisible characters, HTML tags (the formatting is removed, the line breaks are replaced by spaces) and typographic quotes around string literals, even when stored as HTML entities. The templates that could be built by the previous versions are rendered exactly as before.
* Add the `spaceless`, `unescape_quotes_in_text`, `remove_block_tag_paragraphs` and `on_error` arguments to `StringTemplateRenderer`, whose defaults keep the previous behavior.
* Add the `allowed_tags` and `allowed_filters` arguments to `StringTemplateRenderer`, which restrict the tags and filters that a template may use.
* Add `TemplateSyntaxValidator`, which checks form and model fields, and reports the line of the error.
* Document a TinyMCE configuration for templates, checked against what TinyMCE stores.
* Add support for Python 3.14.
* Add support for Django 6.0 and 6.1.
* Ship a `py.typed` marker (PEP 561), so that type checkers such as mypy use the type annotations of the package.

### Fixes
* Fix the comparison operators (`-gt`, `-gte`, `-lt`, `-lte`) not being replaced when the same one is used twice in a tag, or when it follows a string literal.
* Fix the error message not being escaped in the HTML error message.
* Fix the syntax error messages mentioning the tags that the renderer adds around the template, e.g. "expected 'endspaceless'".
* Stop installing the `tests` package along with the package.

### Other changes
* A renderer builds its template once, whether the template is checked, rendered or both.
* Packaging is defined in `pyproject.toml`.
* The CI runs on GitHub Actions, and the package is published to PyPI with Trusted Publishing.
