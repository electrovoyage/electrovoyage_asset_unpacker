'''
Unpacker for electrovoyage's asset packs.
'''

import gzip
from io import BufferedReader, BytesIO
from os import PathLike, path, makedirs
from .exceptions import *
from typing import overload, Literal
from tqdm import tqdm
from tempfile import TemporaryDirectory, TemporaryFile, NamedTemporaryFile
from shutil import make_archive

FILEPATH_OR_RB_FILE = str | BytesIO | BufferedReader

def ResolveFilepathUnion(filepath_or_file: FILEPATH_OR_RB_FILE) -> BytesIO:
    '''
    If `filepath_or_file` is a file path, open file for reading bytes and return BytesIO with the file's contents.
    Otherwise read the file and return an equivalent BytesIO.
    '''
    if isinstance(filepath_or_file, (BufferedReader, BytesIO)):
        contents = filepath_or_file.read()
        filepath_or_file.seek(0)
        return BytesIO(contents)
    else:
        with open(filepath_or_file, 'rb') as f:
            contents = f.read()
            
        return BytesIO(contents)

DirInfo = dict[str, dict[str, list[str]]]
FileTree = dict[str, bytes]
AllocationData = dict[str, dict[str, int]]

class AssetPack:
    '''
    Asset package.
    '''
    @overload
    def __init__(self, filepath_or_file: FILEPATH_OR_RB_FILE, emulated: bool = False):
        '''
        Read asset bundle.
        If `emulated` is True, the asset pack can be loaded from a BytesIO object but can't be reloaded.
        '''
    @overload
    def __init__(self, filetree: FileTree, dirinfo: DirInfo):
        '''
        Initialize asset bundle from previously loaded data.
        '''
    
    def __init__(self, a: type[BufferedReader | BytesIO | str] | dict[str, bytes], b: bool | dict[str, dict[str, list[str]]]):
        if not isinstance(a, dict):
            file = a
            emulated: bool = b
            
            self.emulated = emulated

            if isinstance(file, str):
                self.path = file
            elif not emulated:
                self.path = file.name

            content = ResolveFilepathUnion(file).read()

            if not content.startswith(b'!PACKED\n'):
                raise MissingHeaderException('file doesn\'t start with "!PACKED"')
            else:
                content = content.replace(b'!PACKED\n', b'')

            dirdict = eval(gzip.decompress(content).decode())

        else:
            dirdict = {'tree': a, 'dirinfo': b}
        
        self.tree: dict[str, bytes] = dirdict['tree']
        self.dirinfo: dict[str, dict[str, list[str]]] = dirdict['dirinfo']

    def getfile(self, filepath: PathLike | str) -> BytesIO:
        '''
        Get file from asset bundle.
        '''
        return BytesIO(self.tree[filepath])
    
    def getDir(self) -> dict['files': list[str], 'dirs': list[str]]:
        '''
        Return dictionary of packfile's directory.
        '''
        return self.dirinfo
    
    def reload(self):
        '''
        Reload file.
        '''
        if not self.emulated:
            self.__init__(self.path)
        else:
            raise IOError('can\'t reload emulated assetpack')
        
    def extract(self, epath: str):
        '''
        Export all files from bundle and recreate directory structure.
        `epath` is the base directory, so for example the asset path 'resources/images/file.png' would be exported as '<`epath`>/resources/images/file.png'.
        '''
        progressbar = tqdm(list(self.getDir().keys()), 'Extracting bundle', len(list(self.getDir().keys())))
        
        for key, value in self.getDir().items():
            makedirs(path.join(epath, *(key.split('/'))), exist_ok=True)
            files, dirs = value['files'], value['dirs']
            for dir in dirs:
                makedirs(path.join(epath, *(key.split('/')), dir), exist_ok=True)
            for file in files:
                self.exportfile(key + '/' + file, path.join(epath, *(key.split('/')), file))
                
            progressbar.update(list(self.getDir().keys()).index(key) + 1)
            
    def extract_tozip(self, efile: str):
        '''
        Extract this bundle to a ZIP file.
        '''
        with TemporaryDirectory(prefix='assets.packed_zipexport_') as tempdir:
            self.extract(tempdir)
            make_archive(path.splitext(efile)[0], 'zip', tempdir)
    
    def exportfile(self, packpath: str, exp_path: str):
        '''
        Export file from asset bundle.
        '''
        with open(exp_path, 'wb') as expfile:
            expfile.write(self.getfile(packpath).read())
        
    def listobjects(self) -> list[str]:
        return list(self.tree.keys())
    
    def getDirList(self) -> list[str]:
        return list(self.dirinfo.keys())
    
    def exportToTempfile(self, packpath: str) -> NamedTemporaryFile:
        '''
        Extract file to temporary file.
        '''
        f = TemporaryFile(prefix='AssetPackTempFile', suffix='.'+packpath.split('.')[-1])
        f.write(self.getfile(packpath).read())
        return f
    
def _GetInterleavedFile(filedata: bytes, allocation: dict[str, int], filecount: int) -> bytes:
    '''
    Get file from interleaved asset bundle.
    '''
    offset = allocation['offset']
    size = allocation['size']
    
    return filedata[offset::filecount][:size]
    
def InterleavedAssetPack(filepath_or_file: FILEPATH_OR_RB_FILE) -> AssetPack:
    '''
    Load interleaved asset pack.
    Converted to a normal asset pack at runtime for compatibility.
    '''
    contents = ResolveFilepathUnion(filepath_or_file).read().replace(b'!PACKED_INTERLEAVE\n', b'')
    
    contents = gzip.decompress(contents)
    data: dict[str, AllocationData | DirInfo | bytes | int] = eval(contents.decode())
    
    allocations: AllocationData = data['allocations']
    filedata: bytes = data['data']
    dirinfo: DirInfo = data['dirinfo']
    filecount: int = data['filecount']
    
    ftree: FileTree = {}
    
    for path, allocation in allocations.items():
        ftree[path] = _GetInterleavedFile(filedata, allocation, filecount)
        
    return AssetPack(ftree, dirinfo)

AssetPackType = Literal['normal', 'split', 'interleaved', 'unknown']

def IdentifyAssetPack(filepath_or_file: FILEPATH_OR_RB_FILE) -> AssetPackType:
    '''
    Attempt to identify asset pack's type.
    '''
    contents = ResolveFilepathUnion(filepath_or_file).read()
    
    header = contents.split(b'\n')[0]
    
    match header:
        case b'!PACKED':
            return 'normal'
        case b'!PACKED_INTERLEAVE':
            return 'interleaved'
        case _:
            return 'unknown'
        
def identifyAndReadAssetPack(filepath_or_file: FILEPATH_OR_RB_FILE, emulated: bool = False) -> AssetPack:
    '''
    Load asset pack and automatically use the correct method of loading it based on its header.
    '''
    f = ResolveFilepathUnion(filepath_or_file)
    _type = IdentifyAssetPack(f)
    
    match _type:
        case 'normal':
            return AssetPack(f, emulated)
        case 'interleaved':
            return InterleavedAssetPack(f)
        case 'unknown':
            raise IOError('invalid asset pack; are you sure it\'s not empty or corrupt and its header is valid?')