#!/usr/bin/env bash
(
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    pip install --upgrade -r requirements-dev.txt
    cd stringrenderer && python ../manage.py compilemessages && cd ..
    rm -rf build/ dist/ *.egg-info/
    python -m build && twine check dist/* && twine upload dist/*
)
