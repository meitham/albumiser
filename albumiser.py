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

__version__ = "0.101"

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

def isPhoto(path):
    '''return true if image has a known image extension file
    '''
    knownPhotoExt = [".jpg",".jpeg",".png"]
    _, ext = os.path.splitext(path)
    return string.lower(ext) in knownPhotoExt

def isExact(file1, file2):
    ''' checks if two files have exactly same content
    '''
    hash1 = hashlib.sha256()
    hash2 = hashlib.sha256()
    hash1.update(open(file1).read())
    hash2.update(open(file2).read())
    return hash1.hexdigest() == hash2.hexdigest()

class ImageDate:
    ''' a date and time class
    '''
    def __init__(self, img_dt_tm=None):
        ''' creates an instance using the given file img_dt_tm
        '''
        if img_dt_tm is None:
            raise InvalidDateTag('No datetime stamp - None')
        try:
            if isinstance(img_dt_tm, str):
                self.img_dt_tm = datetime.strptime(img_dt_tm, '%Y:%m:%d %H:%M:%S')
                self.microsecond = 0
        except ValueError:
            raise InvalidDateTag('invalid date/time stamp %s accepted format is %s'%(img_dt_tm, '%Y:%m:%d %H:%M:%S'))

    def getPath(self, base, filename):
        ''' returns a string that describes a path as a date such as
        year/month/day/hour_minute_second_microsecond.
        '''
        _, fileExt = os.path.splitext(filename)
        fileName = self.img_dt_tm.strftime('%Y_%m_%d-%H_%M_%S')
        if self.microsecond:
            fileName+='_%0.0f'%self.microsecond
        fileName += fileExt.lower()
        return os.path.join(base,
                            str(self.img_dt_tm.year),
                            str(self.img_dt_tm.month),
                            str(self.img_dt_tm.day), fileName)

    def __str__(self):
        return str(self.img_dt_tm)+'_%0.0f'%self.microsecond
        
    def __repr__(self):
        return str(self)

    def incMicrosecond(self):
        self.microsecond += 1

class ImageFile:
    ''' a file that contains valid image format
    '''
    def __init__(self, fullfilepath):
        ''' creates an instance of the ImageFile
        '''
        global logger
        if not os.path.exists(fullfilepath): # file missing
            raise MissingImageFile('file not found %s' %fullfilepath)
        try:
            im = Image.open(fullfilepath)
            self.srcfilepath = fullfilepath
        except IOError, e:
            raise InvalidImageFile('invalid image file %s' %fullfilepath)
        if not hasattr(im, '_getexif'):
            raise MissingDateTag('image file has no date %s' %fullfilepath)
        else:
            try:
                exifdata = im._getexif()
            except KeyError, e:
                self.imagedate = None
                logging.debug(e)
                raise MissingDateTag('image file has no date %s' %fullfilepath)
            logging.debug("type of object is %s" %type(exifdata))
            if exifdata is None:
                raise InvalidDateTag('exif date of type None')
            try:
                ctime = exifdata[0x9003]
                self.imagedate = ImageDate(ctime)
            except InvalidDateTag, e:
                self.imagedate = None
                logging.debug(e)
            except KeyError, e:
                self.imagedate = None
                logging.debug(e)

    def getFileName(self, base):
        ''' gets a proper name and path with no duplications
        '''
        global logger
        if self.imagedate is None:
            # i should handle images with no date here
            logger.info("no image date for file %s " %self.srcfilepath)
            # i could either return the file creation date
            # or just a string.
            return None
        while True:
            self.dstfilename = self.imagedate.getPath(base, self.srcfilepath)
            if os.path.exists(self.dstfilename):
                logger.info("image with similar date/time stamp already exists %s " %self.dstfilename)
                if isExact(self.srcfilepath, self.dstfilename):
                    logger.info(".. this appars to be a duplicate %s " %self.dstfilename)
                    raise DuplicateImage('image %s already exists - duplicate'%self.dstfilename)
                else:
                    logger.info(".. this is not a duplicate %s " %self.dstfilename)
                    self.imagedate.incMicrosecond()
            else:
                return self.dstfilename

    def move(self, base, deleteOriginal=False, link=False):
        global logger
        try:
            if self.getFileName(base) is None:
                logger.info("unknown destination for image %s " %self.srcfilepath)
                return
        except DuplicateImage, e:
            logger.info(e)
            if deleteOriginal:
                os.remove(self.srcfilepath)
            return 
        dstdir = os.path.dirname(self.dstfilename)
        if not (os.path.exists(dstdir) and os.path.isdir(dstdir)):
            logger.info("creating dir %s" %dstdir)
            os.makedirs(dstdir)
        if link:
            logger.info("linking %s ==> %s " %(self.srcfilepath, self.dstfilename))
            if os.path.islink(self.srcfilepath):
                self.srcfilepath = os.readlink(self.srcfilepath)
            os.symlink(self.srcfilepath, self.dstfilename)
            return
        if deleteOriginal:
            logger.info("moving %s ==> %s " %(self.srcfilepath, self.dstfilename))
            shutil.move(self.srcfilepath, self.dstfilename)
        else:
            logger.info("copying %s ==> %s " %(self.srcfilepath, self.dstfilename))
            shutil.copy2(self.srcfilepath, self.dstfilename)

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

class FilesTree:
    def __init__(self):
        pass

    def __next__(self):
        pass

    def __iter__(self):
        pass

def treewalk(top, recursive=False, followlinks=False, depth=0):
    ''' generator similar to os.walk(), but with limited subdirectory depth
    '''
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
            logging.info('Skipping %s' % pathname)

def makeLogger(log="sys.stderr"):
    ''' returns a logger class, call first when used in shell, otherwise
    all objects complain of missing logger
    '''
    logger = logging.getLogger('')
    if log == "sys.stderr":
        console = logging.StreamHandler()
        logger.addHandler(console)
    else:
        fileHandler = logging.FileHandler(log)
        logger.addHandler(fileHandler)
    return logger
    
if __name__=='__main__':
    ''' main
    '''
    parser = getOptions()
    (options, args) = parser.parse_args()

    logger = makeLogger(options.log)
    if len(args) == 1:
        src = dst = args[0]
        # this needs to build the tree under temp and move it to dest when done
    elif len(args) == 2:
        src = args[0]
        dst = args[1]
    else:
        logging.error("invalid number of arguments")
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
        logger.debug("rotating images isn't imeplemented yet.")
        sys.exit(0)
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
        imagefile.move(dst, options.move, options.link)
