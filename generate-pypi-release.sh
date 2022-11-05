#!/usr/bin/env bash
(
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    pip install --upgrade -r requirements-dev.txt
    cd stringrenderer && python ../manage.py compilemessages && cd ..
    rm -r build/ dist/ *.egg-info/
    python setup.py check && python setup.py sdist && python setup.py bdist_wheel && twine upload dist/*
)
