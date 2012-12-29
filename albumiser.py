#!/usr/bin/env python
import argparse
import functools
import hashlib
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import traceback

from datetime import datetime

try:
    import pyexiv2
except ImportError:
    print("Missing dependency: pyexiv2 is required.")
    sys.exit(1)

__version__ = '0.05'
IMAGE_EXT = ('.jpg', 'jpeg', '.png')


def get_options():
    """CLI interface
    """
    parser = argparse.ArgumentParser(prog='albumiser',
                version=__version__,
                description="Organise your photos the way they should be",
                conflict_handler='resolve')
    # either be too verbose or quite, you cannot be both
    verbose = parser.add_mutually_exclusive_group()
    verbose.add_argument('-v', '--verbose',
            action='count', dest='verbose',
            default=2,  # 1 being debug, 2 info, 3 warning, etc ...
            help="make loads of noise, useful for debugging!")
    verbose.add_argument('-q', '--quiet',
            action='store_false', dest='verbose',
            help="unless errors don't output anything.")
    parser.add_argument('-r', '--recursive',
            action='store_true', dest='recursive',
            help="operate recursively.")
    parser.add_argument('--rotate',
            action='store_true', dest='rotate',
            help="rotate images according to their EXIF rotation tag.")
    parser.add_argument('--dry-link',
            action='store_true', dest='link',
            help="creates a tree of symbolic links under destination with "
                "date time hierarchy preserving the original images states.")
    parser.add_argument('-s', '--follow_links',
            action='store_true', dest='follow_links',
            help="follow symbolic linked directories.")
    parser.add_argument('-m', '--move',
            action='store_true', dest='move',
            help="delete original file from SOURCE, by default it makes a copy"
                    " of the file.")
    parser.add_argument('--delete-duplicates',
            action='store_true', dest='delete_duplicates',
            help="delete duplicate files from SOURCE, by default it ignores "
                    "them and keep them intact.")
    parser.add_argument('-d', '--depth',
            dest='depth',
            help="default is unlimited.")
    parser.add_argument('-g', '--log',
            default=None, dest='log',
            help="log all actions, default is console.")
    parser.add_argument('--ignore-no-exif',
            action='store_true', dest='ignore_no_exif',
            default=False,
            help="ignore photos with missing EXIF date, otherwise use epoch.")
    parser.add_argument('source', action="store")
    parser.add_argument('target', action="store")
    ns = parser.parse_args()
    # handle options
    logger = logging.getLogger('')
    if ns.log:
        hdlr = logging.FileHandler(ns.log)
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        hdlr.setFormatter(formatter)
        logger.addHandler(hdlr)
    else:
        logger.addHandler(logging.StreamHandler())
    if ns.verbose:
        # I wish Python used 0, 1, 2 rather than 0, 10, 20 for level numerics
        level = ns.verbose * 10
        logger.setLevel(level)
        logger.debug("verbose mode on")
    else:
        logger.debug("verbose mode off")
    if ns.source == ns.target:
        ns.target = tempfile.mkdtemp()
        ns.target_is_temp = True
        logger.info("using temp dir at %(target)s" % {'target': ns.target})
    if ns.follow_links:
        logger.debug("following symlinks")
    else:
        logger.debug("ignoring symlinks")
    if ns.link:
        logger.debug("creating a tree of links to photos")
        ns.move = False
    # check for non implemented options
    if ns.rotate:
        raise NotImplementedError("rotating images is not supported yet")
    if ns.depth is not None:
        ns.depth = int(ns.depth)
    logger.debug("depth is: %(depth)r" % {'depth': ns.depth})
    return ns


class TreeWalker(object):
    """provides a functionality similar to os.walk but can do
    pre defined depth when needed.
    """
    def __init__(self, top='/', max_depth=None, *args, **kwargs):
        self._top = top
        self._max_depth = max_depth
        self.logger = kwargs.get('logger', logging.getLogger(''))
        self._follow_links = kwargs.get("follow_links", False)
        self._depth = 0
        self._recursive = self._max_depth is None or self._max_depth > 0

    def __repr__(self):
        return ("TreeWalker(top='%'top)s', max_depth='%(depth)r')" %
                {'top': self._top, 'depth': self._max_depth})

    def walk(self, top=None, depth=0):
        if not top:
            top = self._top
        if self._max_depth is not None and depth > self._max_depth:
            return
        for f in os.listdir(top):
            file_path = os.path.join(top, f)
            if os.path.isdir(file_path) and self._recursive:
                # its a dir recurse into it
                is_link = os.path.islink(file_path)
                if is_link and not self._follow_links:
                    continue  # we won't follow links
                for dir_path, file_name in self.walk(file_path, depth + 1):
                    yield dir_path, file_name
            elif os.path.isfile(file_path):
                yield top, f
            else:
                # Unknown file type, print a message
                self.logger.warning("Skipping %(path)s" % {'path': file_path})


def is_image_file(path):
    """Return true if image has a known image extension file
    """
    try:
        _, ext = os.path.splitext(path)
        return ext.lower() in IMAGE_EXT
    except:
        return False

def sha_digest(indata):
    """returns an sha256 hex digest of an input
    """
    h = hashlib.sha256()
    h.update(indata)
    return h.hexdigest()


def main():
    ns = get_options()
    conn = sqlite3.connect('/tmp/albumise.sqlite')
    conn.text_factory = str
    c = conn.cursor()
    c.execute("drop table if exists images")
    #TODO add a new column for the year/month/day/hour/minute/second
    c.execute("""
    create table images (
        hash text unique,
        path text unique,
        created text,
        destination text,
        status text,
        error text)
    """)
    #TODO add a new index for the new column
    c.execute("create index idx_hash on images(hash)")
    c.execute("create index idx_path on images(path)")
    c.execute("create index idx_status on images(status)")
    c.execute("create index idx_created on images(created)")
    conn.commit()
    undated_counter = 0
    logger = logging.getLogger('')
    logger.debug("about to walk files")
    tree_walker = TreeWalker(ns.source, ns.depth, logger=logger,
            follow_symlinks=ns.follow_links)
    for dir_path, file_name in tree_walker.walk():
        undated = False
        imd = None
        try:
            path = os.path.join(dir_path, file_name)
            _,ext = os.path.splitext(path)
            ext = ext.lower()
            logger.debug("processing %(path)s" % locals())
            if not is_image_file(path):
                # ignore non image extensions
                logger.warning("ignoring non image file %(path)s" % locals())
                c.execute("insert or ignore into images values(?,?,?,?,?,?)",
                        (path, path, None, None, "IGNORE", "non image file"))
                continue
            try:
                metadata = pyexiv2.ImageMetadata(path)
                metadata.read()
            except(IOError, UnicodeDecodeError) as e:
                logger.error("unable to get EXIF from %(path)s" % locals())
                # use file digest
                digest = sha_digest(path)
                c.execute("insert or ignore into images values(?,?,?,?,?,?)",
                        (digest, path, None, None, "FAILED", str(e)))
                conn.commit()
                continue
            # handle digest
            try:
                # reading thumbnails
                logger.debug("trying thumbnail digest")
                if len(metadata.previews) > 0:
                    largest = metadata.previews[-1]
                    data = largest.data
                else:  # no thumbnails available
                    data = metadata.buffer
            except Exception as e:
                # when metadata is not available use the file content hash
                logger.exception(e)
                logger.debug("unable to use metadata - using file digest")
                with open(path) as f:
                    data = f.read()
            finally:
                digest = sha_digest(data)
            # check if we have had this file before
            c.execute("""select * from images where hash=?""",(digest,))
            if len(c.fetchall())>0:
                logger.warning("file %(path)s is a duplicate" % locals())
                if not ns.delete_duplicates:
                    continue
                # delete duplicate file
                logger.debug('deleting duplicate file %(path)s' % locals())
                c.execute("insert or ignore into images values(?,?,?,?,?,?)",
                            (digest, path, None, None, "DUPLICATE", None))
                os.remove(path)
                continue
            # fix images fucked up by fspot/picasa, always favour original ones
            try:
                software = metadata['Exif.Image.Software'].value.lower()
            except KeyError:
                software = ''
            if software and ('f-spot' in software or 'picasa' in software):
                # avoid using creation date time and rely on digitized tag
                # as these software messup with EXIF details
                try:
                    imd = metadata['Exif.Photo.DateTimeDigitized'].value
                except KeyError:
                    logger.warning("Digitized date unavailable for %(path)s." %
                            locals())
            if imd is None:
                tag = metadata.get('Exif.Photo.DateTimeOriginal', None)
                if tag is None:
                    tag = metadata.get('Exif.Image.DateTime', None)
                if tag is not None:
                    imd = tag.value
            if imd is None or not isinstance(imd, datetime):
                logger.warning("Exif Date Tags are missing - using UNIX epoch")
                undated = True
                undated_counter+=1
                imd = datetime(1970,1,1)
            yyyy = str(imd.year)
            mm = str(imd.month)
            dd = str(imd.day)
            dstdir = os.path.join(ns.target,
                    yyyy,
                    '%(y)04d-%(m)02d' % {'y': imd.year, 'm': imd.month},
                    '%(y)04d-%(m)02d-%(d)02d' %
                            {'y': imd.year, 'm': imd.month, 'd': imd.day})
            # ospj is short for os.path.join where dstdir is already in
            ospj = functools.partial(os.path.join, dstdir)
            dtmf = '%Y_%m_%d-%H_%M_%S'
            if undated:
                dstdir = ospj(''.join([imd.strftime(dtmf), '_',
                        str(undated_counter), ext]))
            else:  # dated
                c.execute("select * from images where created=?", (str(imd),))
                images_in_second = len(c.fetchall())
                if images_in_second > 0:
                    # we have more than one image in this second
                    dstdir = ospj(''.join([imd.strftime(dtmf), '.',
                            str(images_in_second), ext]))
                else:
                    dstdir = ospj(''.join([imd.strftime(dtmf), ext]))
                # TODO
                # check here if the dated image already exists in the database
                # select * from images where path like dstdir
                # use the count of the query result
            c.execute("insert or ignore into images values(?,?,?,?,?,?)",
                        (digest, path, str(imd), dstdir, "READY", None))
            conn.commit()
            logger.info("%(path)s added to DB" % locals())
        except Exception as e:
            logger.exception(traceback.print_exc())
            continue
    conn.commit()
    # database is now built - process files
    c.execute("""select * from images where status='READY'""")
    for row in c:
        source = row[1]
        target = row[3]
        target_dir = os.path.dirname(target)
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
        if ns.move:
            shutil.move(source, target)
        elif ns.link:
            if os.path.islink(source):
                source = os.readlink(source)
            os.symlink(source, target)
        else:
            shutil.copy2(source, target)

if __name__=='__main__':
    main()
