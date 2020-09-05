import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name='django-string-renderer',
    version='0.2.1',
    url='https://github.com/dprog-philippe-docourt/django-string-renderer',
    license='MIT',
    author='Philippe Docourt',
    author_email='contact@dprog.net',
    description='A thin wrapper around the Django templating system to render any string as a template. It provides an easy way to render any user inputted string as a regular django template.',
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=setuptools.find_packages(),
    include_package_data=True,
    python_requires='>=3.6',
    install_requires=['django', 'djangocodemirror'],
    classifiers=[
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Framework :: Django",
        "Development Status :: 5 - Production/Stable",
        "Natural Language :: English"
    ],
    keywords='templating django',
)
