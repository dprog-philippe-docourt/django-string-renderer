# django-string-renderer
A thin wrapper around the Django templating system to render any string as a template.

# Usage

```python
import stringrenderer

template = "Hello {{ recipient.first_name }} {{ recipient.last_name }}!"
renderer = StringTemplateRenderer(template)

rendered_content = renderer.render_template(context=dict(recipient=recipient_1), request=request)
rendered_content = renderer.render_template(context=dict(recipient=recipient_2), request=None)
```

When the first rendering request occurs on a given StringTemplateRenderer instance, a Template object is built from given string passed to `__init__()`, and cached for the next rendering operations with other contexts.