#!/usr/bin/env python
import os
import sys
from subprocess import call

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
    mypy_result = None
    try:
        print("Checking type annotations with mypy...")
        mypy_result = call(['mypy', 'stringrenderer', '--ignore-missing-imports'])
        if mypy_result < 0:
            print("mypy was terminated by signal", -mypy_result, file=sys.stderr)
        elif mypy_result > 0:
            print("mypy check failed! Returned code:", mypy_result, file=sys.stderr)
        else:
            print("mypy check succeeded!", file=sys.stderr)
    except OSError as e:
        print("Execution of mypy failed:", e, file=sys.stderr)
    sys.exit(bool(failures) or mypy_result != 0)
