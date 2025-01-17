#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Pre-commit script to ensure that version numbers in `setup.json` and `aiida_codtools/__init__.py` match."""
from __future__ import absolute_import
import os
import json
import sys

import click

FILEPATH_SCRIPT = os.path.split(os.path.realpath(__file__))[0]
FILEPATH_ROOT = os.path.join(FILEPATH_SCRIPT, os.pardir)
FILENAME_SETUP_JSON = 'setup.json'
FILEPATH_SETUP_JSON = os.path.join(FILEPATH_ROOT, FILENAME_SETUP_JSON)


def get_setup_json():
    """Return the `setup.json` as a python dictionary """
    with open(FILEPATH_SETUP_JSON, 'r') as handle:
        setup_json = json.load(handle)

    return setup_json


@click.group()
def cli():
    pass


@cli.command('version')
def validate_version():
    """Check that version numbers in `setup.json` and `aiida_codtools/__init__.py` match."""
    sys.path.insert(0, FILEPATH_ROOT)
    import aiida_codtools  # pylint: disable=wrong-import-position
    version = aiida_codtools.__version__

    setup_content = get_setup_json()

    if version != setup_content['version']:
        click.echo('Version number mismatch detected:')
        click.echo('Version number in `{}`: {}'.format(FILENAME_SETUP_JSON, setup_content['version']))
        click.echo('Version number in `{}/__init__.py`: {}'.format('aiida_codtools', version))
        click.echo('Updating version in `{}` to: {}'.format(FILENAME_SETUP_JSON, version))

        setup_content['version'] = version
        with open(FILEPATH_SETUP_JSON, 'w') as handle:
            # Write with indentation of two spaces and explicitly define separators to not have spaces at end of lines
            json.dump(setup_content, handle, indent=2, separators=(',', ': '))

        sys.exit(1)


if __name__ == '__main__':
    cli()  # pylint: disable=no-value-for-parameter
