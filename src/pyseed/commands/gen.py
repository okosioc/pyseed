# -*- coding: utf-8 -*-
"""
    gen
    ~~~~~~~~~~~~~~

    Command gen.

    :copyright: (c) 2021 by weiminfeng.
    :date: 2021/9/1
"""

import argparse
import importlib.util
import os
import shutil
import sys
from typing import List, IO

from pyseed import registered_models


def _gen(models_dir: str, seeds_dir: str, grows_dir: str, template_names: List[str],
         output_stream: IO[str] = sys.stdout):
    """ Gen. """
    output_stream.write(f'gen {models_dir} and {seeds_dir} to {grows_dir}, using {template_names}\n')
    if not os.path.exists(models_dir):
        output_stream.write('No models folder.\n')
        return False
    if not os.path.exists(seeds_dir):
        output_stream.write('No seeds folder.\n')
        return False
    if not os.path.exists(grows_dir):  # TODO: Should download templates to grows dir firstly
        output_stream.write('No grows folder.\n')
        return False
    #
    # Reset grows folder
    #
    templates = []
    for g in os.listdir(grows_dir):
        p = os.path.join(grows_dir, g)
        if os.path.isdir(p):
            if g.startswith('.'):  # Skip the download templates folder
                if g[1:] in template_names:
                    templates.append(g[1:])
            else:
                shutil.rmtree(p)
        else:
            os.remove(p)
    #
    if not templates:
        output_stream.write(f'Can not find any available templates by {template_names}.\n')
        return False
    #
    # Import models package
    # 1. Find all the models definition in models package, please import all models in __init__.py
    #
    module_name = os.path.basename(models_dir)
    module_spec = importlib.util.spec_from_file_location(module_name, os.path.join(models_dir, '__init__.py'))
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    module_spec.loader.exec_module(module)
    #
    # Load registered model schemas
    #
    models = {m.__name__: m.schema() for m in registered_models}
    output_stream.write(f'Found {len(models)} registered models: {list(models.keys())}\n')
    #
    # Create context using folder structure of seeds_dir
    # 1. Only contains one level sub folders and each folder will be generated to a view
    # 2. Files in seeds_dir root folder are used as layouts
    #
    context = {
        'layouts': [],  # [layouts]
        'views': {},  # {view: [seeds]}
    }
    for v in os.listdir(seeds_dir):
        p = os.path.join(seeds_dir, v)
        if os.path.isdir(p):
            context['views'].update({v: [s for s in os.listdir(p)]})
        else:
            context['layouts'].append(v)
    #
    output_stream.write(f'Generation context {context}\n')
    #
    # Process views one by one
    # 1. Views python sources are generated into views subfolder
    # 2. lines in !key=value format will be updated into context for speicial processing
    #

    #
    # Iterate each template
    #
    for template in templates:
        #
        # Create output folder for this template
        #
        out = os.path.join(grows_dir, template)
        os.mkdir(out)


def main(args: List[str]) -> bool:
    """ Main. """
    parser = argparse.ArgumentParser(prog="pyseed gen")
    parser.add_argument(
        "models",
        nargs='?',
        default='./models',
        help="Specify the models folder, default value is ./models",
    )
    parser.add_argument(
        "seeds",
        nargs='?',
        default='./seeds',
        help="Specify the seeds folder, default value is ./seeds",
    )
    parser.add_argument(
        "grows",
        nargs='?',
        default='./grows',
        help="Specify the generation output folder, default value is ./grows",
    )
    parser.add_argument(
        "templates",
        nargs='+',
        help="Specify the templates",
    )
    parsed_args = parser.parse_args(args)
    return _gen(parsed_args.models, parsed_args.seeds, parsed_args.grows, parsed_args.templates)
