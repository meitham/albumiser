import argparse
import hashlib
import logging, logging.handlers
import os
import shutil
import sqlite3
import sys
import tempfile

from datetime import datetime, timedelta
from optparse import OptionParser

try:
    import pyexiv2
except ImportError:
    print('Missing dependency: please install pyexiv2 in order to use this script')
    sys.exit(1)

__version__ = '0.05'
IMAGE_EXT = ['.jpg','jpeg','.png']

def get_options():
    """ Creates the options and return a parser object
    """
    #parser = OptionParser(usage='sqlalbumiser.py [options] src dest', version='%s'%__version__)
    parser = argparse.ArgumentParser(prog='albumiser', 
                version=__version__,
                description='Organise your photos as you wish.',
                conflict_handler='resolve')

    # either be too verbose or quite, you cannot be both
    verbose = parser.add_mutually_exclusive_group()
    
    verbose.add_argument('-v', '--verbose', 
            action='store_true', dest='verbose', default=True,
            help='make loads of noise, useful for debugging!')

    verbose.add_argument('-q', '--quiet',
                      action='store_false', dest='verbose',
                      help="unless errors don't output anything.")

    parser.add_argument('-r', '--recursive',
                      action='store_true', dest='recursive',
                      help='operate recursively.')

    parser.add_argument('--rotate',
                      action='store_true', dest='rotate',
                      help='rotate images according to their EXIF rotation tag.')

    parser.add_argument('--dry-link',
                      action='store_true', dest='link',
                      help='creates a tree of symbolic links under destination with date time\
                            hierarchy preserving the original images states.')

    parser.add_argument('-s', '--follow_links',
                      action='store_true', dest='follow_links',
                      help='follow symbolic linked directories.')
    
    parser.add_argument('-m', '--move',
                      action='store_true', dest='move',
                      help='delete original file from SOURCE, by default it makes a copy of the file.')
    
    parser.add_argument('--delete-duplicates',
                      action='store_true', dest='delete_duplicates',
                      help='delete duplicate files from SOURCE, by default it ignores them and keep them intact.')

    parser.add_argument('-d', '--depth',
                      type=int, dest='depth',
                      help='unlimited [default: %default].')
    
    parser.add_argument('-g', '--log',
                      default=None, dest='log',
                      help='log all actions, default is console.')
    parser.add_argument('source', action="store", nargs='?', default=os.getcwd()) 
    parser.add_argument('target', action="store", nargs='?', default=os.getcwd()) 
    # photos with no EXIF dates will either be copied into a special directory 
    # or will assume a UNIX epoch 1970-01-01, latter is default
    no_exif = parser.add_mutually_exclusive_group()
    
    no_exif.add_argument('--process-no-exif',
                      default='undated', dest='process_no_exif',
                      help='copy/moves images with no EXIF data to [default: %default].')
    
    no_exif.add_argument('--ignore-no-exif',
                      action='store_true', dest='ignore_no_exif', default=False,
                      help='ignore photos with missing EXIF date, otherwise use UNIX epoch.')
    return parser

def get_logger(log=None):
    """ returns a logger object
    """
    logger = logging.getLogger('albumiser')
    if log is None:
        # 'sys.stderr'
        logger.addHandler(logging.StreamHandler())
    else:
        logger.addHandler(logging.FileHandler(log))
    return logger

def handle_options():
    parser = get_options()
    ns = parser.parse_args()
    #ipdb.set_trace()
    logger = get_logger(ns.log)
    if ns.source == ns.target:
        ns.target = tempfile.mkdtemp()
        ns.target_is_temp = True
    if ns.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug('verbose mode on')
    else:
        logger.debug('verbose mode off')
    if ns.follow_links:
        logger.debug('following symlinks')
    else:
        logger.debug('ignoring symlinks')
    if ns.link:
        logger.debug('creating a tree of links to photos')
        ns.move = False
    # check for non implemented options
    if ns.rotate:
        raise NotImplementedError('rotating images is not supported yet')
    if ns.depth is None:
        max_depth = ns.depth = None
    else:
        max_depth = ns.depth = int(ns.depth)

    logger.debug('depth is: %r'%ns.depth)
    if max_depth == 0:
        max_depth = None

    return ns


class TreeWalker:
    """provides a functionality similar to os.walk but can do
    pre defined depth when needed.
    """
    def __init__(self, top='/', max_depth=None, *args, **kwargs):
        self._top = top
        self._max_depth = max_depth
        self.logger = kwargs.get('logger', None)
        self._depth = 0 
        
        if self._max_depth is None or self._max_depth>0:
            self._recursive = True 
        else:
            self._recursive = False

        self._follow_links = kwargs.get('follow_links', False)

    def __repr__(self):
        return '<TreeWalker top=%s, max_depth=%r>'%(self._top, self._max_depth)

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
            else:
                # Unknown file type, print a message
                if self.logger:
                    self.logger.info('Skipping %s' % file_path)


def isPhoto(path):
    """return true if image has a known image extension file
    """
    try:
        _, ext = os.path.splitext(path)
        return ext.lower() in IMAGE_EXT 
    except:
        return False

def sha256HexDigest(indata):
    """returns an sha256 hex digest of an input
    """
    h = hashlib.sha256()
    h.update(indata)
    return h.hexdigest()
    

def main():
    ns = handle_options()
    conn = sqlite3.connect('/tmp/albumise.sqlite')
    conn.text_factory = str
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS IMAGES")
    c.execute("""
    CREATE TABLE IMAGES ( 
        HASH TEXT UNIQUE,
        PATH TEXT UNIQUE,
        DESTINATION TEXT,
        STATUS TEXT,
        ERROR TEXT)
    """)
    c.execute("""create index idx1 on images(hash)""")
    c.execute("""create index idx2 on images(path)""")
    c.execute("""create index idx3 on images(status)""")
    conn.commit()
    undated_counter = 0
    logger = logging.getLogger('albumiser')
    logger.debug('about to walk files')
    tree_walker = TreeWalker(ns.source, ns.depth, logger=logger, follow_symlinks=ns.follow_links)
    #ipdb.set_trace()
    for dirpath, filename in tree_walker.walk():
        undated = False
        try:
            path = os.path.join(dirpath, filename)
            _,ext = os.path.splitext(path)
            ext = ext.lower()
            logger.debug('processing %s' %path)
            if not isPhoto(path): 
                # ignore non image extensions
                logger.warning('ignoring non image file %s' %path)
                c.execute("""insert or ignore into images values(?,?,?,?,?)""",
                                (path, path, None, 'IGNORE', 'non image file'))
                continue

            try:
                metadata = pyexiv2.ImageMetadata(path) 
                metadata.read()        
            except(IOError, UnicodeDecodeError) as e:
                logger.error('unable to read image metadata %s' %path)
                # use file digest
                digest = sha256HexDigest(path)
                c.execute("""insert or ignore into images values(?,?,?,?,?)""",
                        (digest, path, None, 'FAILED', str(e)))
                conn.commit()
                continue

            # handle digest
            try:
                logger.debug('trying thumbnail digest')
                digest = sha256HexDigest(metadata.previous[-1].data)
            except: 
                # when metadata is not available use the entire file content hash
                logger.debug('unable to read thumbnails - using file content digest')
                digest = sha256HexDigest(open(path).read())
            # check if we have had this file before
            c.execute("""select * from images where hash=?""",(digest,))
            if len(c.fetchall())>0:
                logger.warning('file %s already processed'%path)
                if ns.delete_duplicates:
                    logger.debug('deleting duplicate file %s'%path)
                    c.execute("""insert or ignore into images values(?,?,?,?,?)""",
                        (digest, path, None, 'DUPLICATE', None))
                    os.remove(path)
                continue # we have this object already

            try:
                imd = metadata['Exif.Image.DateTime'].value
            except KeyError:
                logger.warning('Exif.Image.DateTime key is missing from exif')
                try:
                    # to make my htc android happy
                    imd = metadata['Exif.Photo.DateTimeOriginal'].value
                except KeyError:
                    logger.warning('Exif.Photo.DateTimeOriginal key is missing from exif using UNIX epoch')
            if imd is None or not isinstance(imd, datetime):
                undated = True
                undated_counter+=1
                imd = datetime(1970,1,1)
            yyyy = str(imd.year)
            mm = str(imd.month)
            dd = str(imd.day)

            dstdir = os.path.join(ns.target, yyyy, '%04d-%02d'%(imd.year,imd.month),
                    '%04d-%02d-%02d'%(imd.year,imd.month,imd.day))
            if undated:
                dstdir = os.path.join(dstdir, imd.strftime('%Y_%m_%d-%H_%M_%S-')
                        +str(undated_counter)+ext)
            else:
                dstdir = os.path.join(dstdir, imd.strftime('%Y_%m_%d-%H_%M_%S')+ext)
            c.execute("""insert or ignore into images values(?,?,?,?,?)""", 
                    (digest, path, dstdir, 'READY', None))
            conn.commit()
            logger.info('%s added to DB'%path)
        except Exception as e:
            logger.debug('ATTENTION: unexpected error')
            logger.exception(e)
            continue
    conn.commit()
    #c.close()
    
    # database is now built - process files
    c.execute("""select * from images where status='READY'""")
    for row in c:
        source = row[1]
        target = row[2]
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
    """ main
    """
    main()
