"""
Check that the current version prepares - and therefore renders - templates exactly like version 0.5.0, for every
template that version 0.5.0 could build.

The check can be run against the templates of a project, with the settings of that project, so that its template tag
libraries are available:

    DJANGO_SETTINGS_MODULE=myproject.settings PYTHONPATH=/path/to/myproject:. python -m tests.compatibility corpus.json

where corpus.json holds a list of objects with a "template" key, and optional "auto_escape" and "extra_tags" keys,
matching the arguments given to StringTemplateRenderer by the project.
"""
import dataclasses
import json
import sys

from django.template import engines

from stringrenderer import StringTemplateRenderer
from tests import legacy


@dataclasses.dataclass
class CompatibilityReport:
    # Templates that version 0.5.0 could build, which must be prepared identically.
    checked: int = 0
    # Templates that version 0.5.0 could build, and that the current version prepares differently.
    differences: list[dict] = dataclasses.field(default_factory=list)
    # Templates that version 0.5.0 could not build, and that the current version builds.
    fixed: list[dict] = dataclasses.field(default_factory=list)
    # Templates that neither version can build, with the error raised by the current version.
    invalid: list[dict] = dataclasses.field(default_factory=list)

    def __str__(self):
        return (f'{self.checked} templates built by version 0.5.0, {len(self.differences)} of them prepared differently; '
                f'{len(self.fixed)} templates fixed; {len(self.invalid)} invalid templates.')


def check_compatibility(entries, engine_name='django'):
    engine = engines[engine_name]
    report = CompatibilityReport()
    for entry in entries:
        template_string = entry['template']
        auto_escape = entry.get('auto_escape', True)
        extra_tags = entry.get('extra_tags') or []
        renderer = StringTemplateRenderer(template_string, extra_tags=extra_tags, auto_escape=auto_escape,
                                          engine_name=engine_name)
        legacy_prepared_template_string = legacy.prepare_template_string(template_string, extra_tags, auto_escape)
        try:
            engine.from_string(legacy_prepared_template_string)
        except Exception:
            _template, _prepared_template_string, error = renderer._build_template()
            if error is None:
                report.fixed.append(entry)
            else:
                report.invalid.append(dict(entry, error=str(error)))
            continue
        report.checked += 1
        prepared_template_string = renderer.get_prepared_template_string()
        if prepared_template_string != legacy_prepared_template_string:
            report.differences.append(dict(
                entry, legacy_prepared_template_string=legacy_prepared_template_string,
                prepared_template_string=prepared_template_string))
    return report


def main(corpus_path):
    import django
    django.setup()
    with open(corpus_path, encoding='utf-8') as corpus_file:
        report = check_compatibility(json.load(corpus_file))
    for title, entries in (('Prepared differently', report.differences), ('Fixed', report.fixed),
                           ('Invalid', report.invalid)):
        for entry in entries:
            print(f'--- {title}:', json.dumps(entry, ensure_ascii=False, indent=2))
    print(report)
    return 1 if report.differences else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
