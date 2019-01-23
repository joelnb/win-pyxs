#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os.path
from setuptools import setup

README = ''
if os.path.exists('README.md'):
    with open('README.md') as readme_file:
        README = readme_file.read()

REQUIREMENTS = [
    'pyxs'
]

TEST_REQUIREMENTS = [
    'mock',
]

setup(
    name='win_pyxs',
    version='0.1.0',
    description='Windows compatibility for pyxs',
    long_description=README,
    author='Joel Noyce Barnham',
    author_email='joelnbarnham@gmail.com',
    url='https://github.com/joelnb/win-pyxs',
    packages=['win_pyxs'],
    package_dir={
        'win_pyxs': 'win_pyxs',
    },
    include_package_data=True,
    install_requires=REQUIREMENTS,
    zip_safe=True,
    keywords='pyxs xenstore xen',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],
    test_suite='tests',
    tests_require=TEST_REQUIREMENTS,
    extras_requires={
        ':sys_platform == "win32" and (python_version < "3.5")': [
            'backports.socketpair',
        ]
    }
)
