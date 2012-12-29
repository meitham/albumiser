#!/usr/bin/env python
"""
examples
--------

exivfind . -idevice-make Canon -idevice-model "canon eos d30" -color-space RGB

exivfind . -make "HTC" -cdatime-between "2012-12-30"
"""
from __future__ import print_function

import argparse
import fnmatch
import os
import subprocess
import traceback
from functools import partial
from collections import OrderedDict

try:
    import ipdb as pdb
except ImportError:
    import pdb

import pyexiv2
from functools32 import lru_cache


exiv_tags = {
        'make': 'Exif.Image.Make',
        'model': 'Exif.Image.Model',
        'software': 'Exif.Image.Software',
}


class TreeWalker:
    """provides a functionality similar to os.walk but can do
    pre defined depth when needed.
    """
    def __init__(self, top='/', max_depth=None, *args, **kwargs):
        self._top = top
        self._max_depth = max_depth
        self._depth = 0
        if self._max_depth is None or self._max_depth > 0:
            self._recursive = True
        else:
            self._recursive = False
        self._follow_links = kwargs.get('follow_links', False)

    def __repr__(self):
        return 'TreeWalker(top=%(_top)s, max_depth=%(_max_depth)r)' % locals()

    def walk(self, top=None, depth=0):
        if not top:
            top = self._top
        if self._max_depth is not None:
            if depth > self._max_depth:
                return
        for f in os.listdir(top):
            file_path = os.path.join(top, f)
            if os.path.isdir(file_path):
                # its a dir recurse into it
                if self._recursive:
                    islink = os.path.islink(file_path)
                    if (islink and self._follow_links) or not islink:
                        for dirpath, filename in self.walk(file_path, depth+1):
                            yield dirpath, filename
            elif os.path.isfile(file_path):
                yield top, f


def name_match(fpath, fname, *args, **kwargs):
    """Returns whether a filename matches a pattern or not
    """
    pattern = kwargs['filter_value']
    return fnmatch.fnmatch(fname, pattern)


def tag_match(fpath, fname, *args, **kwargs):
    """Matches an exiv tag from a file against a porposed one from a user
    """
    verbosity = kwargs.get('verbosity', 0)
    case_match = kwargs.get('case_sensitive', True)
    user_tag = kwargs['tag']
    user_tag_value = kwargs['filter_value']
    exiv_tag = exiv_tags[user_tag]
    metadata = read_exiv(fpath, fname, verbosity)
    if metadata is None:
        return False
    try:
        exiv_tag_value = metadata[exiv_tag].value
        if verbosity > 2:
            print("%(exiv_tag)s: %(exiv_tag_value)s" % locals())
        if case_match:
            return user_tag_value == exiv_tag_value
        return user_tag_value.lower() == exiv_tag_value.lower()
    except KeyError:  # tag is not available
        if verbosity > 2:
            traceback.print_exc()
        return None


def act_print(fpath, fname, *args, **kwargs):
    if 'null' in kwargs:
        print(os.path.join(fpath, fname), end='\x00')
    else:
        print(os.path.join(fpath, fname))


def act_print_tag(fpath, fname, *args, **kwargs):
    verbosity = kwargs.get('verbosity', 0)
    tag = kwargs['print_tag']
    metadata = read_exiv(fpath, fname, verbosity)
    try:
        exiv_tag = exiv_tags[tag]
    except KeyError:
        exiv_tag = tag
    if metadata is None:
        return
    try:
        exiv_tag_value = metadata[exiv_tag].value
        print(exiv_tag_value)
    except KeyError:  # tag is not available
        if verbosity > 2:
            traceback.print_exc()


def act_print_all_tags(fpath, fname, *args, **kwargs):
    verbosity = kwargs.get('verbosity', 0)
    metadata = read_exiv(fpath, fname, verbosity)
    if not metadata:
        return
    for k in metadata.exif_keys:
        print("%(k)s: %(v)s" % {'k': k, 'v': metadata[k].raw_value})


def act_exec(fpath, fname, *args, **kwargs):
    path = os.path.join(fpath, fname)
    action = kwargs['exec']
    action = [path if t == '{}' else t for t in action]
    #print(' '.join(action))
    subprocess.call(action[:-1])


tests = {
        'name': name_match,
        'make': partial(tag_match, tag='make'),
        'imake': partial(tag_match, tag='make', case_sensitive=False),
        'model': partial(tag_match, tag='model'),
        'imodel': partial(tag_match, tag='model', case_sensitive=False),
#        'rmake': rmake,
#        'orientation': orientation,
        'software': partial(tag_match, tag='software'),
#        'date-time': exiv_datetime,
#        'date-time-newer': exiv_datetime_newer,
#        'compression': compression,
#        'x-resolution': x_resolution,  # accepts expressions e.g. ">3000"
}


actions = {
        'print': act_print,
        'print0': partial(act_print, null=True),
        'exec': act_exec,
        'print_tag': act_print_tag,
        'print_all_tags': act_print_all_tags,
}


class TestAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if not 'tests' in namespace:
            setattr(namespace, 'tests', OrderedDict())
        namespace.tests[self.dest] = values


class ActionAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if not 'actions' in namespace:
            setattr(namespace, 'actions', [])
        namespace.actions.append((self.dest, values))


def parse_args():
    """
    """
    parser = argparse.ArgumentParser(description="extensible pure python "
            "gnu file like tool.")
    parser = argparse.ArgumentParser()
    parser.add_argument('path', action='store', nargs='?', default=os.getcwd())
    parser.add_argument('--verbose', '-v', action='count')
    parser.add_argument('-name', dest='name', action=TestAction)
    parser.add_argument('-make', dest='make', action=TestAction)
    parser.add_argument('-imake', dest='imake', action=TestAction)
    parser.add_argument('-model', dest='model', action=TestAction)
    parser.add_argument('-imodel', dest='imodel', action=TestAction)
    parser.add_argument('-true', dest='true', action=TestAction, nargs=0)
    parser.add_argument('-print', dest='print', action=ActionAction, nargs=0)
    parser.add_argument('-print0', dest='print0', action=ActionAction, nargs=0)
    parser.add_argument('-print-tag', dest='print_tag', action=ActionAction)
    parser.add_argument('-print-all-tags', dest='print_all_tags',
            action=ActionAction, nargs=0)
    parser.add_argument('-exec', dest='exec', action=ActionAction, nargs='+')
    return parser.parse_args()


def evaluate(fpath, fname, args):
    """Evaluates a user test and return True or False, like GNU find tests
    """
    args_tests = getattr(args, 'tests', {})
    for filter_name, values in args_tests.iteritems():
        if values is None:
            continue  # unused test
        #if filter_name not in tests:
        #    continue  # not all provided options are filters
        filter_func = tests[filter_name]
        if not filter_func(fpath, fname, **{
                'filter_value': values,
                'verbosity': args.verbose}):
            return False
    return True


def act_on(fpath, fname, args):
    """Applies an action on a file, like GNU find action
    """
    args_actions = getattr(args, 'actions', [])
    if not args_actions:
        act_print(fpath, fname)
    for action, options in args_actions:
        if action in actions:
            func = actions[action]
            func(fpath, fname, **{action: options})


@lru_cache(maxsize=128)
def read_exiv(fpath, fname, verbosity=0):
    """Returns an EXIF metadata from a file
    """
    path = os.path.join(fpath, fname)
    try:
        metadata = pyexiv2.ImageMetadata(path)
        metadata.read()
        return metadata
    except(IOError, UnicodeDecodeError) as e:
        if verbosity > 1:
            traceback.print_exc()
        return None


def main():
    args = parse_args()
    tw = TreeWalker(top=args.path)
    for fpath, fname in tw.walk():
        if not evaluate(fpath, fname, args):
            continue
        act_on(fpath, fname, args)


if __name__ == '__main__':
    main()
