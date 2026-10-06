"""
Frozen copy of the template string preparation of version 0.5.0.

It is the reference of the compatibility tests: every template that version 0.5.0 could build must be prepared - and
therefore rendered - exactly the same way by the current version. Never change this module.
"""
import re

COMPARISON_OP_REGEX = [
            (r'{%\1>=', re.compile("\\{%([^\"\'\\}]+)-gte")),
            (r'{%\1>', re.compile("\\{%([^\"\'\\}]+)-gt")),
            (r'{%\1<=', re.compile("\\{%([^\"\'\\}]+)-lte")),
            (r'{%\1<', re.compile("\\{%([^\"\'\\}]+)-lt")),
        ]


def prepare_template_string(template_string, extra_tags=None, auto_escape=True):
    prepared_template_string = template_string.replace("&#39;", "'").replace("&quot;", '"')
    for regex in COMPARISON_OP_REGEX:
        prepared_template_string = regex[1].sub(regex[0], prepared_template_string)
    if extra_tags:
        load_tags = '{%load ' + ' '.join(extra_tags) + '%}'
    else:
        load_tags = ''
    prepared_template_string = prepared_template_string if auto_escape else '{% autoescape off %}' + prepared_template_string + '{% endautoescape %}'
    prepared_template_string = load_tags + '{%spaceless%}' + prepared_template_string + '{%endspaceless%}'
    return prepared_template_string
