'''
Unpacker for electrovoyage's asset packs.
'''

import gzip
from io import BufferedReader, BytesIO
from os import path, makedirs
from .exceptions import *
from typing import Callable
from tqdm import tqdm
from tempfile import TemporaryDirectory, TemporaryFile, NamedTemporaryFile
from shutil import make_archive
import struct

DirInfo = dict[str, dict[str, list[str]]]
FileTree = dict[str, bytes]
AllocationData = dict[str, dict[str, int]]
FilePath_or_RBModeFile = type[BufferedReader | BytesIO] | str

def validated_assetpack(header: bytes, aptype: str) -> Callable[[bytes], tuple[DirInfo, FileTree]]:
    def _validated_assetpack(func: Callable[[bytes], tuple[DirInfo, FileTree]]) -> Callable[[bytes], tuple[DirInfo, FileTree]]:
        def newfunc(data: bytes) -> tuple[DirInfo, FileTree]:
            if not data.strip().startswith(header):
                raise MissingHeaderException(f'{aptype} missing header')

            # get rid of header
            data = data[data.find(header) + len(header):]

            decoded = gzip.decompress(data)

            return func(decoded)

        return newfunc
    
    return _validated_assetpack

class AssetPackType:
    '''
    Dummy class.
    '''
    @staticmethod
    def read(data: bytes) -> tuple[DirInfo, FileTree]:
        raise NotImplementedError('base AssetPackType does not implement read(), use an actual assetpack type')

class BinaryAssetPack(AssetPackType):
    '''
    Fully-binary assetpack.
    '''
    @staticmethod
    @validated_assetpack(b'!PACKEDB\n', 'BinaryAssetPack')
    def read(data: bytes) -> tuple[DirInfo, FileTree]:
        #if not data.strip().startswith(b'!PACKEDB\n'):
        #    raise MissingHeaderException('BinaryAssetPack missing header')
        #
        #data = data[data.find(b'!PACKEDB\n') + len(b'!PACKEDB\n'):]
        #
        #decoded = gzip.decompress(data)
        io = BytesIO(data)
        
        dirinfolen = struct.unpack('<I', io.read(4))[0]
        dirinfo = eval(io.read(dirinfolen))
        
        #print(dirinfo, dirinfolen)
        
        filetree = {}
        while (fnlenb := io.read(4)):
            fnlen = struct.unpack('<I', fnlenb)[0]
            fname = io.read(fnlen).decode()
            
            flen = struct.unpack('<I', io.read(4))[0]
            file = io.read(flen)
            
            filetree[fname] = file
            
        return (dirinfo, filetree)
    
class InterleavedAssetPack(AssetPackType):
    '''
    Interleaved assetpack.
    '''
    @staticmethod
    @validated_assetpack(b'!PACKED_INTERLEAVE\n', 'InterleavedAssetPack')
    def read(data: bytes) -> tuple[DirInfo, FileTree]:
        dat: dict[str, AllocationData | DirInfo | bytes | int] = eval(data.decode())
        
        alloc: AllocationData = dat['allocations']
        filedata: bytes = dat['data']
        dirinfo: DirInfo = dat['dirinfo']
        filecount: int = dat['filecount']
        
        ftree: FileTree = {}
        
        for path, allocation in alloc.items():
            # get data of specific file
            fdat = filedata[allocation['offset']::filecount][:allocation['size']]
            ftree[path] = fdat
            
        return (dirinfo, ftree)
    
class RegularAssetPack(AssetPackType):
    '''
    Regular asset pack.
    '''
    @staticmethod
    @validated_assetpack(b'!PACKED\n', 'RegularAssetPack')
    def read(data: bytes) -> tuple[DirInfo, FileTree]:
        dat = eval(data.decode())
        
        return (dat['dirinfo'], dat['tree'])
    
def _ResolveFilePathOrFileUnion(fp: FilePath_or_RBModeFile) -> BytesIO:
    if isinstance(fp, (BufferedReader, BytesIO)):
        data = fp.read()
        fp.seek(0)
        
        return BytesIO(data)
    else:
        with open(fp, 'rb') as f:
            data = f.read()
        return BytesIO(data)
    
class AssetPack:
    '''
    Universal asset pack.
    '''
    def __init__(self, file: FilePath_or_RBModeFile, plugin: AssetPackType = RegularAssetPack):
        '''
        Initialize a new assetpack.
        `file` is either a string path, or a file in `rb` mode.
        `plugin` is a class that implements a `read()` method for decoding the assetpack, e.g.  `RegularAssetPack`, `BinaryAssetPack` or `InterleavedAssetPack`.
        '''
        data = _ResolveFilePathOrFileUnion(file).read()
        
        self.dirinfo, self.filetree = plugin.read(data)
        
    def getfile(self, filepath: str) -> BytesIO:
        '''
        Get file from assetpack.
        '''
        return BytesIO(self.filetree[filepath])
    
    def getdirectory(self) -> dict['files': list[str], 'dirs': list[str]]:
        '''
        Return directory of assetpack.
        '''
        return self.dirinfo
    
    def listobjects(self) -> list[str]:
        '''
        Get list of all objects (files) in assetpack.
        '''
        return list(self.filetree.keys())
    
    def listdirectories(self) -> list[str]:
        '''
        Get list of all the directories in this assetpack.
        '''
        return list(self.dirinfo.keys())