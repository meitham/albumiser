#!/usr/bin/env python
#Meitham 01 July 2011

__version__ = "0.101"

from optparse import OptionParser
from datetime import datetime, timedelta
import sys
import os
import shutil
import hashlib
import logging, logging.handlers
try:
    import pyexiv2
except ImportError:
    print "Missing dependency: please install pyexiv2 in order to use this script"
import sqlite3

IMAGE_EXT = ['.jpg','jpeg','.png']

def get_options():
    ''' creates the options and return a parser object
    '''
    parser = OptionParser(usage="%prog [options] src dest", version="%prog %s"%__version__)
    parser.add_option("-v", "--verbose",
                      action="store_true", dest="verbose",
                      default=True,
                      help="make lots of noise, mainly used for debugging")
    parser.add_option("-q", "--quiet",
                      action="store_false", dest="verbose",
                      help="unless errors don't output anything.")
    parser.add_option("-r", "--recursive",
                      action="store_true", dest="recursive",
                      help="operate recursively.")
    parser.add_option("-R", "--rotate",
                      action="store_true", dest="rotate",
                      help="rotate images according to their EXIF rotation tag.")
    parser.add_option("-k", "--dry-link",
                      action="store_true", dest="link",
                      help="creates a tree of symbolic links under destination with date time\
                            hierarchy preserving the original images states.")
    parser.add_option("-s", "--symlink",
                      action="store_true", dest="symlink",
                      help="follow symbolic linked directories.")
    parser.add_option("-m", "--move",
                      action="store_true", dest="move",
                      help="delete original file from SOURCE, by default it makes a copy of the file.")
    parser.add_option("-d", "--depth",
                      default="0", type='int', dest="depth",
                      help="unlimited [default: %default].")
    parser.add_option("-g", "--log",
                      default=None, dest="log",
                      help="log all actions, default is console.")
    # parser.add_option("-i", "--ignore",
                      # action="store_true", dest="ignore", default=True,
                      # help="ignore photos with missing EXIF header.")
    parser.add_option("-p", "--process-no-exif",
                      default="undated", dest="noExifPath",
                      help="copy/moves images with no EXIF data to [default: %default].")
    return parser

def get_logger(log=None):
    ''' returns a logger class, call first when used in shell, otherwise
    all objects complain of missing logger
    '''
    logger = logging.getLogger('')
    if log == None:
        # "sys.stderr"
        console = logging.StreamHandler()
        logger.addHandler(console)
    else:
        file_handler = logging.FileHandler(log)
        logger.addHandler(file_handler)
    return logger

def treewalk(top, recursive=False, followlinks=False, depth=0):
    ''' generator similar to os.walk(), but with limited subdirectory depth
    '''
    global logger
    if maxdepth is not None:
        if  depth > maxdepth:
            return
    for f in os.listdir(top):
        file_path = os.path.join(top, f)
        if os.path.isdir(file_path):
            # its a dir recurse into it
            if recursive:
                islink = os.path.islink(file_path)
                if (islink and followlinks) or not islink:
                    for dirpath, filename in treewalk(file_path, recursive, followlinks, depth+1):
                        yield dirpath, filename
        elif os.path.isfile(file_path):
            yield top, f
        else:
            # Unknown file type, print a message
            logger.info('Skipping %s' % pathname)

def isPhoto(path):
    '''return true if image has a known image extension file
    '''
    try:
        _, ext = os.path.splitext(path)
        return ext.lower() in IMAGE_EXT 
    except:
        return False

def sha256HexDigest(indata):
    '''returns an sha256 hex digest of an input
    '''
    h = hashlib.sha256()
    h.update(indata)
    return h.hexdigest()
    

#    def move(self, base, deleteOriginal=False, link=False):
#        try:
#            if self.getUniquePath(base) is None:
#                self.logger.info("unknown destination for image %s " %self.srcfilepath)
#                return
#        except DuplicateImage, e:
#            self.logger.info(e)
#            if deleteOriginal:
#                os.remove(self.srcfilepath)
#            return 
#        dstdir = os.path.dirname(self.dstfilename)
#        if not (os.path.exists(dstdir) and os.path.isdir(dstdir)):
#            self.logger.info("creating dir %s" %dstdir)
#            os.makedirs(dstdir)
#        if link:
#            self.logger.info("linking %s ==> %s " %(self.srcfilepath, self.dstfilename))
#            if os.path.islink(self.srcfilepath):
#                self.srcfilepath = os.readlink(self.srcfilepath)
#            os.symlink(self.srcfilepath, self.dstfilename)
#            return
#        if deleteOriginal:
#            self.logger.info("moving %s ==> %s " %(self.srcfilepath, self.dstfilename))
#            shutil.move(self.srcfilepath, self.dstfilename)
#        else:
#            self.logger.info("copying %s ==> %s " %(self.srcfilepath, self.dstfilename))
#            shutil.copy2(self.srcfilepath, self.dstfilename)

    

if __name__=='__main__':
    ''' main
    '''
    parser = get_options()
    (options, args) = parser.parse_args()
    global logger
    logger = get_logger(options.log)
    if len(args) == 1:
        src = dst = args[0]
        # this needs to build the tree under temp and move it to dest when done
    elif len(args) == 2:
        src = args[0]
        dst = args[1]
    else:
        logger.error("invalid number of arguments")
        parser.print_help()
        sys.exit()
    if options.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug('verbose mode on')
    else:
        logger.debug('verbose mode off')
    if options.symlink:
        logger.debug("following symlinks")
    else:
        logger.debug("ignoring symlinks")
    if options.link:
        logger.debug("creating a tree of links to photos")
        options.move = False
    # check for non implemented options
    if options.rotate:
        raise NotImplementedError('rotating images is not supported yet')
    maxdepth = options.depth = int(options.depth)
    logger.debug("depth is: "+ str(options.depth))
    if maxdepth == 0:
        maxdepth = None
    conn = sqlite3.connect('/tmp/albumise.sqlite')
    conn.text_factory = str
    c = conn.cursor()
    c.execute('''
    create table images ( 
        hash text unique,
        path text unique,
        destination text,
        status text,
        error text)
    ''')
    c.execute('''create index idx1 on images(hash)''')
    c.execute('''create index idx2 on images(path)''')
    c.execute('''create index idx3 on images(status)''')
    conn.commit()
    undated_counter = 0
    for dirpath, filename in treewalk(src, options.recursive, options.symlink, options.depth):
        undated = False
        try:
            path = os.path.join(dirpath, filename)
            _,ext = os.path.splitext(path)
            ext = ext.lower()
            logger.debug("processing %s" %path)
            if not isPhoto(path): # ignore non image extensions
                logger.warning("ignoring non image file %s" %path)
                c.execute('''insert or ignore into images values(?,?,?,?,?)''',
                (path, path, None, 'ignored', 'non image file'))
                continue
            try:
                metadata = pyexiv2.ImageMetadata(path) 
            except UnicodeDecodeError, e:
                logger.warning('unable to handle unicode filenames %s' %path)
                continue 
            try:
                metadata.read()        
            except IOError, e:
                logger.error('invalid image file %s' %path)
                digest = sha256HexDigest(path)
                c.execute('''insert or ignore into images values(?,?,?,?,?)''',
                (digest, path, None, 'failed', str(e)))
                conn.commit()
                continue
            # handle digest
            try:
                digest = sha256HexDigest(metadata.previous[-1].data)
                logger.debug("using thumbnail digest")
            except: 
                # when metadata is not available use the entire file content hash
                digest = sha256HexDigest(open(path).read())
                logger.debug("using file content digest")
            # check if we have had this file before
            c.execute('''select * from images where hash=?''',(digest,))
            if len(c.fetchall())>0:
                logger.warning("file already processed")
                continue # we have this object already
            try:
                imd = metadata['Exif.Image.DateTime'].value
            except KeyError:
                logger.warning("Exif.Image.DateTime key is missing from exif")
                try:
                    # to make my htc android happy
                    imd = metadata['Exif.Photo.DateTimeOriginal'].value
                except KeyError:
                    logger.info("using epoch")
            if imd is None or not isinstance(imd, datetime):
                undated = True
                undated_counter+=1
                imd = datetime(1970,1,1)

            dstdir = os.path.join(dst, str(imd.year), str(imd.month), str(imd.day))
            if undated:
                dstdir = os.path.join(dstdir, imd.strftime('%Y_%m_%d-%H_%M_%S-')+str(undated_counter)+ext)
            else:
                dstdir = os.path.join(dstdir, imd.strftime('%Y_%m_%d-%H_%M_%S-')+ext)
            c.execute('''insert or ignore into images values(?,?,?,?,?)''', (digest, path, dstdir, None, None))
            conn.commit
            logger.info('%s added to DB'%path)
        except Exception, e:
            logger.exception(e)
            continue
    conn.commit
    c.close()
