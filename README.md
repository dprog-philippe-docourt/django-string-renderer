# django-string-renderer
A thin wrapper around the Django templating system to render any string as a template. It provides an easy way to render any user inputted string as a regular django template.

This wrapper uses no models and requires no settings. There is no need to register this app in your INSTALLED_APPS.

# Usage

```python
import stringrenderer

template_string = "Hello {{ recipient.first_name }} {{ recipient.last_name }}!"
renderer = StringTemplateRenderer(template_string)

rendered_content = renderer.render_template(context=dict(recipient=recipient_1), request=request)
rendered_content = renderer.render_template(context=dict(recipient=recipient_2), request=None)
```

When the first rendering request occurs on a given `StringTemplateRenderer` instance, a `Template` object is built from the string passed to `__init__()`, and cached for the next rendering operations with other contexts.

You may check the template syntax ike this:
```python
import stringrenderer

template_string = "Hello {{ recipient.first_name }} {{ recipient.last_name }}!"
is_valid, syntax_error = check_template_syntax(template_string)
```