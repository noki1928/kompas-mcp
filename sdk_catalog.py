"""Query installed official TLBs, not a guessed list of CAD methods."""
import os
from pathlib import Path


def sdk_directory():
    explicit = os.getenv('KOMPAS_SDK_DIR')
    if explicit:
        path = Path(explicit)
        if not (path / 'kAPI7.tlb').is_file():
            raise FileNotFoundError('KOMPAS_SDK_DIR must contain kAPI7.tlb')
        return path
    # Resolve the installed COM server first, then search vendor directories.
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'KOMPAS.Application.7\CLSID') as key:
            clsid = winreg.QueryValue(key, None)
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf'CLSID\{clsid}\LocalServer32') as key:
            command = winreg.QueryValue(key, None)
        import re
        match = re.search(r'"([^"]+\.exe)"|(.+?\.exe)', command, re.IGNORECASE)
        if match:
            path = Path(match.group(1) or match.group(2)).parent
            if (path / 'kAPI7.tlb').is_file():
                return path
    except OSError:
        pass
    paths = list((Path(os.getenv('ProgramFiles', 'C:/Program Files')) / 'ASCON').glob('KOMPAS*/Bin/kAPI7.tlb'))
    if len(paths) == 1:
        return paths[0].parent
    raise FileNotFoundError('Set KOMPAS_SDK_DIR explicitly; multiple/no SDK installations found')


class SdkCatalog:
    def __init__(self):
        self.interfaces = None
        self.constants = None

    def load(self):
        if self.interfaces is not None:
            return
        import pythoncom
        interfaces, constants = {}, {}
        for filename in ('kAPI5.tlb', 'kAPI2D5COM.tlb', 'kAPI3D5COM.tlb', 'kAPI7.tlb',
                         'ksConstants.tlb', 'ksConstants3D.tlb'):
            lib = pythoncom.LoadTypeLib(str(sdk_directory() / filename))
            for index in range(lib.GetTypeInfoCount()):
                info = lib.GetTypeInfo(index)
                attr = info.GetTypeAttr()
                name, doc, *_ = lib.GetDocumentation(index)
                if attr.typekind == pythoncom.TKIND_ENUM:
                    for j in range(attr.cVars):
                        var = info.GetVarDesc(j)
                        constants[info.GetNames(var.memid)[0]] = var.value
                    continue
                entry = {'library': filename, 'interface': name, 'guid': str(attr.iid),
                         'doc': doc, 'members': []}
                for j in range(attr.cFuncs):
                    f = info.GetFuncDesc(j)
                    entry['members'].append({'name': info.GetNames(f[0])[0],
                                             'parameters': list(info.GetNames(f[0])[1:]),
                                             'invkind': f[4], 'signature': repr(f)})
                for j in range(attr.cVars):
                    v = info.GetVarDesc(j)
                    entry['members'].append({'name': info.GetNames(v.memid)[0], 'property': True})
                interfaces[f'{filename}:{name}'] = entry
        self.interfaces, self.constants = interfaces, constants

    def query(self, query='', interface='', library='', limit=30):
        self.load()
        if not 1 <= limit <= 100:
            raise ValueError('limit must be 1..100')
        rows = []
        for entry in self.interfaces.values():
            if interface and entry['interface'] != interface:
                continue
            if library and entry['library'] != library:
                continue
            matches = [m for m in entry['members'] if query.lower() in m['name'].lower()]
            if query and query.lower() not in entry['interface'].lower() and not matches:
                continue
            rows.append({**entry, 'members': matches if query and query.lower() not in entry['interface'].lower() else entry['members']})
        return {'success': True, 'sdk_directory': str(sdk_directory()), 'matches': rows[:limit],
                'total': len(rows), 'truncated': len(rows) > limit}

    def enums(self, names=(), query='', limit=100):
        if not 1<=limit<=1000:
            raise ValueError('limit must be 1..1000')
        self.load()
        if names:
            missing = [n for n in names if n not in self.constants]
            if missing:
                raise ValueError(f'Unknown SDK constants: {missing}')
            values = {n: self.constants[n] for n in names}
        else:
            values = {n: v for n, v in self.constants.items() if query.lower() in n.lower()}
        return {'success': True, 'constants': dict(list(values.items())[:limit]),
                'total': len(values), 'truncated': len(values) > limit}
