#!/usr/bin/env python
#Meitham 01 July 2011
__doc__ = """Organise your photos.

NAME
    albumiser.py - flexable images organiser based on EXIF details.

SYNOPSIS
    [python] albumiser.py [OPTION]... [SOURCE] [DESTINATION]

EXAMPLE
    [python] albumiser.py -r -v

DESCRIPTION
    A flexiable python script that can operate on a tree of images and copy or
    move the files into directories based on the image EXIF details. It can detect
    duplicates using either MD5 or SHA, it can based the duplication on the entire
    image or just the thumbnails. It has the ability to build or fix EXIF details
    from images that has wrong EXIF details, such as it can correct picture taken
    date on images.

    The script can build a symlink of date based hierarchical directories. So you 
    can have your images sorted in date based folders, a photo file that was taken 
    at YYYY/MM/DD will end up in a folder of YYYY/MM/DD (posix) YYYY\MM\DD (win)

Options:
  --version             show program's version number and exit
  -h, --help            show this help message and exit
  -v, --verbose         make lots of noise [default]
  -q, --quiet           unless errors don't output anything
  -r, --recursive       operate recursively [default]
  -s, --symlink         follow symbolic linked directories
  -m, --move            delete original file from SOURCE
  -d DEPTH, --depth=DEPTH
                        unlimited [default: 0]
  -g LOG, --log=LOG     log all actions [default: sys.stderr]
  -i, --ignore          ignore photos with missing EXIF header [default]
  -p NOEXIFPATH, --process-no-exif=NOEXIFPATH
                        copy/moves images with no EXIF data to [default:
                        undated]
"""
from optparse import OptionParser
from datetime import datetime, timedelta
import Image
import sys
import os
import shutil
import string
import hashlib
import logging, logging.handlers
try:
    import pyexiv2
except ImportError:
    print "Missing dependency: please install pyexiv2 in order to use this script"

__version__ = "0.101"

IMAGE_EXT = ['.jpg','jpeg','.png']

class ImageException(Exception):
    pass

class InvalidImageFile(ImageException):
    pass

class InvalidDateTag(ImageException):
    pass

class MissingDateTag(ImageException):
    pass

class MissingImageFile(ImageException):
    pass
    
class DuplicateImage(ImageException):
    pass

class NoThumbnailFound(ImageException):
    pass

def getOptions():
    ''' creates the options and return a parser object
    '''
    parser = OptionParser(usage="%prog [options] src dest", version="%prog 0.1")
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
                      default="sys.stderr", dest="log",
                      help="log all actions [default: %default].")
    # parser.add_option("-i", "--ignore",
                      # action="store_true", dest="ignore", default=True,
                      # help="ignore photos with missing EXIF header.")
    parser.add_option("-p", "--process-no-exif",
                      default="undated", dest="noExifPath",
                      help="copy/moves images with no EXIF data to [default: %default].")
    return parser

def makeLogger(log=None):
    ''' returns a logger class, call first when used in shell, otherwise
    all objects complain of missing logger
    '''
    logger = logging.getLogger('')
    if log == None:
        # "sys.stderr"
        console = logging.StreamHandler()
        logger.addHandler(console)
    else:
        fileHandler = logging.FileHandler(log)
        logger.addHandler(fileHandler)
    return logger

def treewalk(top, recursive=False, followlinks=False, depth=0):
    ''' generator similar to os.walk(), but with limited subdirectory depth
    '''
    global logger
    if not maxdepth is None:
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
        return string.lower(ext) in IMAGE_EXT 
    except:
        return False

def isDuplicate(file1, file2, func=None):
    ''' checks if two files have exactly same content
    '''
    if func == None:
        func = thumbDigest
    try:
        # lets try thumbnail 
        return func(file1) == func(file2) 
    except NoThumbnailFound:
        # resort to full file digest
        func = sha256HexDigest
        return func(file1) == func(file2) 

def sha256HexDigest(filename):
    '''returns an sha256 hex digest of an input
    '''
    buf = open(filename).read()
    h = hashlib.sha256()
    h.update(buf)
    return h.hexdigest()

def thumbDigest(filename):
    '''returns a digest of the thumb image
    '''
    metadata = pyexiv2.ImageMetadata(filename)
    metadata.read()
    if not metadata.previews:
        raise NoThumbnailFound(filename)
    h = hashlib.sha256()
    h.update(metadata.previews[-1].data)
    return h.hexdigest()
    
class ImageFile:
    ''' an image file object handler 
    '''
    def __init__(self, fullfilepath):
        ''' constructor 
        '''
        global logger # use global logger / should really argument this
        self.logger = logger

        # file existance
        if not os.path.exists(fullfilepath): # file missing
            raise MissingImageFile('file not found %s' %fullfilepath)

        # file extension
        self.basename, self.ext = os.path.splitext(fullfilepath)
        self.ext = self.ext.lower() # i hate uppercased extensions
        if not self.ext in IMAGE_EXT:
            raise InvalidImageFile('invalid image file %s' %fullfilepath)
        
        self.metadata = pyexiv2.ImageMetadata(fullfilepath) 
        try:
            self.metadata.read()        
        except IOError:
            raise InvalidImageFile('invalid image file %s' %fullfilepath)
            
        if not self.metadata:
            raise MissingImageFile('missing exif info %s' %fullfilepath)

        self.srcfilepath = fullfilepath
        try:
            self.imagedate = self.metadata['Exif.Image.DateTime'].value
        except KeyError:
            self.logger.debug("Exif.Image.DateTime key is missing from exif")
            try:
                # to make my htc android happy
                self.imagedate = self.metadata['Exif.Photo.DateTimeOriginal'].value
            except KeyError:
                # here we handle images that has no date, this will come later
                raise InvalidDateTag('Exif.Photo.DateTimeOriginal key is missing from exif')
        self.datedFileName = self.imagedate.strftime('%Y_%m_%d-%H_%M_%S')

    def getUniquePath(self, base):
        ''' gets a proper name and path with no duplications
        '''
        if self.imagedate is None:
            # i should handle images with no date here
            self.logger.info("no image date for file %s " %self.srcfilepath)
            # i could either return the file creation date
            # or just a string.
            return None
        seq = 0
        imd = self.imagedate 
        self.dstdir = os.path.join(base, str(imd.year), str(imd.month), str(imd.day))
        while True:
            fileName = self.datedFileName
            if seq:
                fileName+='_%0.0f'%seq
            fileName += self.ext
            self.dstfilename = os.path.join(self.dstdir, fileName)
            if os.path.exists(self.dstfilename):
                self.logger.info("image with similar date/time stamp already exists %s " %self.dstfilename)
                if isDuplicate(self.srcfilepath, self.dstfilename):
                    self.logger.info(".. this appars to be a duplicate %s " %self.dstfilename)
                    raise DuplicateImage('image %s already exists - duplicate'%self.dstfilename)
                else:
                    self.logger.info(".. this is not a duplicate %s " %self.dstfilename)
                    seq+=1
                    continue
            else:
                return self.dstfilename

    def move(self, base, deleteOriginal=False, link=False):
        try:
            if self.getUniquePath(base) is None:
                self.logger.info("unknown destination for image %s " %self.srcfilepath)
                return
        except DuplicateImage, e:
            self.logger.info(e)
            if deleteOriginal:
                os.remove(self.srcfilepath)
            return 
        dstdir = os.path.dirname(self.dstfilename)
        if not (os.path.exists(dstdir) and os.path.isdir(dstdir)):
            self.logger.info("creating dir %s" %dstdir)
            os.makedirs(dstdir)
        if link:
            self.logger.info("linking %s ==> %s " %(self.srcfilepath, self.dstfilename))
            if os.path.islink(self.srcfilepath):
                self.srcfilepath = os.readlink(self.srcfilepath)
            os.symlink(self.srcfilepath, self.dstfilename)
            return
        if deleteOriginal:
            self.logger.info("moving %s ==> %s " %(self.srcfilepath, self.dstfilename))
            shutil.move(self.srcfilepath, self.dstfilename)
        else:
            self.logger.info("copying %s ==> %s " %(self.srcfilepath, self.dstfilename))
            shutil.copy2(self.srcfilepath, self.dstfilename)

    
if __name__=='__main__':
    ''' main
    '''
    parser = getOptions()
    (options, args) = parser.parse_args()
    global logger
    logger = makeLogger(options.log)
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
    for dirpath, filename in treewalk(src, options.recursive, options.symlink, options.depth):
        fullfilepath = os.path.join(dirpath, filename)
        logger.debug("processing %s" %fullfilepath)
        if not isPhoto(fullfilepath): # ignore non image extensions
            logger.debug("ignoring non image file %s" %fullfilepath)
            continue
        try:
            imagefile = ImageFile(fullfilepath)
        except ImageException, e:
            logger.debug(e)
            continue
        except Exception, e:
            logger.debug(e)
            continue
        imagefile.move(dst, options.move, options.link)
