#!/opt/local/bin/python
"""
Usage: exivfind [-H] [-L] [-P] [-Olevel] [-D help|tree|search|stat|rates|opt|exec] [path...] [expression]


default path is the current directory; default expression is -print
expression may consist of: operators, options, tests, and actions:

operators (decreasing precedence; -and is implicit where no others are given):
      ( EXPR ) ! EXPR -not EXPR EXPR1 -a EXPR2 EXPR1 -and EXPR2
      EXPR1 -o EXPR2 EXPR1 -or EXPR2 EXPR1 , EXPR2

positional options (always true): -daystart -follow -regextype

normal options (always true, specified before other expressions):
      -depth --help -maxdepth LEVELS -mindepth LEVELS -mount -noleaf
      --version -xdev -ignore_readdir_race -noignore_readdir_race

tests (N can be +N or -N or N): -amin N -anewer FILE -atime N -cmin N
      -cnewer FILE -ctime N -empty -false -fstype TYPE -gid N -group NAME
      -ilname PATTERN -iname PATTERN -inum N -iwholename PATTERN -iregex PATTERN
      -links N -lname PATTERN -mmin N -mtime N -name PATTERN -newer FILE
      -nouser -nogroup -path PATTERN -perm [+-]MODE -regex PATTERN
      -readable -writable -executable
      -wholename PATTERN -size N[bcwkMG] -true -type [bcdpflsD] -uid N
      -used N -user NAME -xtype [bcdpfls]

actions: -delete -print0 -printf FORMAT -fprintf FILE FORMAT -print
      -fprint0 FILE -fprint FILE -ls -fls FILE -prune -quit
      -exec COMMAND ; -exec COMMAND {} + -ok COMMAND ;
      -execdir COMMAND ; -execdir COMMAND {} + -okdir COMMAND ;


find all the pictures taken by a canon camera that are RGB

exivfind . -idevice-make Canon -idevice-model "canon eos d30" -color-space RGB

exivfind . -make "HTC" -cdatime-between "2012-12-30"

or you could combine long tags together such as

or you could combine long tags together such as
"""
import fnmatch
import argparse
import os
import traceback
import pyexiv2
from collections import OrderedDict
from functools32 import lru_cache
try:
    import ipdb as pdb
except ImportError:
    import pdb


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
    pattern = kwargs['name']
    return fnmatch.fnmatch(fname, pattern)


def make(fpath, fname, *args, **kwargs):
    """Checks whether the exiv image maker matches a given string
    """
    manufacturer = kwargs['make']
    metadata = read_exiv(fpath, fname)
    if metadata is None:
        return False
    try:
        return metadata['Exif.Image.Make'].value == manufacturer
    except KeyError:  # make is not available
        return None


tests = {
        'name': name_match,
        'make': make,
#        'imake': partial(make, case_sensitive=False),
#        'rmake': rmake,
#        'orientation': orientation,
#        'software': software,
#        'date-time': exiv_datetime,
#        'date-time-newer': exiv_datetime_newer,
#        'compression': compression,
#        'x-resolution': x_resolution,  # accepts expressions e.g. ">3000"
}


def parse_args():
    """
    """
    class PreserveOrderAction(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            if not 'ordered_args' in namespace:
                setattr(namespace, 'ordered_args', OrderedDict())
            namespace.ordered_args[self.dest] = values

    parser = argparse.ArgumentParser(description="extensible pure python "
            "gnu file like tool.")
    parser = argparse.ArgumentParser()
    parser.add_argument('path', action='store', nargs='?', default=os.getcwd())
    parser.add_argument('-name', dest='name', action=PreserveOrderAction)
    parser.add_argument('-make', dest='make', action=PreserveOrderAction)
    return parser.parse_args()

def evaluate(fpath, fname, args):
    result = True
    for filter_name, values in args.ordered_args.iteritems():
        if values is None:
            continue  # unused test
        #if filter_name not in tests:
        #    continue  # not all provided options are filters
        filter_func = tests[filter_name]
        if not filter_func(fpath, fname, **{filter_name: values}):
            return False
    return True


@lru_cache(maxsize=128)
def read_exiv(fpath, fname):
    path = os.path.join(fpath, fname)
    try:
        metadata = pyexiv2.ImageMetadata(path)
        metadata.read()
        return metadata
    except(IOError, UnicodeDecodeError) as e:
        traceback.print_exc()
        return None

def main():
    args = parse_args()
    tw = TreeWalker(top=args.path)
    for fpath, fname in tw.walk():
        if not evaluate(fpath, fname, args):
            continue
        print os.path.join(fpath, fname)


if __name__ == '__main__':
    main()
