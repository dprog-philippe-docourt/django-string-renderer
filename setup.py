import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name='django-string-renderer',
    version='0.4.0',
    url='https://github.com/dprog-philippe-docourt/django-string-renderer',
    license='MIT',
    author='Philippe Docourt',
    author_email='contact@dprog.net',
    description='A thin wrapper around the Django templating system to render any string as a template. It provides an easy way to render any user inputted string as a regular django template.',
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=setuptools.find_packages(),
    include_package_data=True,
    python_requires='>=3.8',
    install_requires=['django', 'djangocodemirror'],
    classifiers=[
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Framework :: Django",
        "Framework :: Django :: 3.2",
        "Framework :: Django :: 4.0",
        "Framework :: Django :: 4.1",
        "Development Status :: 5 - Production/Stable",
        "Natural Language :: English"
    ],
    keywords='templating django',
)
