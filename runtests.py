#!/usr/bin/env python
import os
import sys

import django
from django.conf import settings
from django.test.utils import get_runner

# Run Django test runner in standalone mode for this app.
# https://docs.djangoproject.com/en/2.2/topics/testing/advanced/#using-the-django-test-runner-to-test-reusable-applications

if __name__ == "__main__":
    os.environ['DJANGO_SETTINGS_MODULE'] = 'tests.test_settings'
    django.setup()
    TestRunner = get_runner(settings)
    test_runner = TestRunner()
    failures = test_runner.run_tests(["tests"])
    sys.exit(bool(failures))
