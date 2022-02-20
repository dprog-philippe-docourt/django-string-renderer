[![Latest PyPI version](https://badge.fury.io/py/django-string-renderer.svg)](https://badge.fury.io/py/django-string-renderer)
[![Build Status](https://travis-ci.com/dprog-philippe-docourt/django-string-renderer.svg?branch=master)](https://travis-ci.com/dprog-philippe-docourt/django-string-renderer)

# django-string-renderer
A thin wrapper around the Django templating system to render any string as a template. It provides an easy way to render any user inputted string as a regular django template.

## Requirements
This wrapper uses no models and requires no other settings than a `django` engine in the `TEMPLATES` setting where the app is used.

This package uses type annotations and `mypy` to check those annotations.
 
This package is only tested against Python >= 3.6 and Django >= 3.2.

## Installation

### Binary Package from PyPi
In order to use this app in a Django project, the simplest way is to install it from [PyPi](https://pypi.python.org/pypi/django-string-renderer):
```bash
pip install django-string-renderer
```

### From the Source Code
In order to modify or test this app you may want to install it from the source code.

Clone the [GitHub repository](https://github.com/dprog-philippe-docourt/django-string-renderer) and then run:
```bash
pip install -r requirements.txt -r requirements-dev.txt
```

## Usage
Start by adding `stringrenderer` to your `INSTALLED_APPS` setting like this:
```python
INSTALLED_APPS = (
    ...,
    'stringrenderer',
)
```
Then use the `StringTemplateRenderer` class to build a Django template instance from a string et render the string with the context of your choice:
```python
import stringrenderer

template_string = "Hello {{ recipient.first_name }} {{ recipient.last_name }}!"
renderer = StringTemplateRenderer(template_string)

rendered_content = renderer.render_template(context=dict(recipient=recipient_1), request=request)
rendered_content = renderer.render_template(context=dict(recipient=recipient_2), request=None)
```

When the first rendering request occurs on a given `StringTemplateRenderer` instance, a `Template` object is built from the string passed to `__init__()`, and cached for the next rendering operations with other contexts.

You may check the template syntax of a string like this:
```python
import stringrenderer

template_string = "Hello {{ recipient.first_name }} {{ recipient.last_name }}!"
is_valid, syntax_error = check_template_syntax(template_string)
```

## Testing
Get the source code from [GitHub](https://github.com/dprog-philippe-docourt/django-string-renderer), follow the [installation instructions](#from-the-source-code) above, and run the following command:
```bash
python runtests.py
```
This will run the test suite with the locally installed version of Python and Django.

## Projects Using this App
This app is used in the following projects:
* [MyGym Web](https://mygym-web.ch/): a web platform for managing sports clubs. django-string-renderer is used to render the messages and emails addressed to the members.
