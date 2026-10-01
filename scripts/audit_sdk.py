"""Read official installed type libraries. No CAD documents are modified."""
import json
import sys
from pathlib import Path

import pythoncom

ROOT = Path(__file__).resolve().parents[1]
SDK = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('C:/Program Files/ASCON/KOMPAS-3D v25 Study/Bin')
OUT = ROOT / 'artifacts' / 'sdk'
OUT.mkdir(parents=True, exist_ok=True)
pythoncom.CoInitialize()
try:
    for filename in ('kAPI5.tlb', 'kAPI2D5COM.tlb', 'kAPI3D5COM.tlb', 'kAPI7.tlb',
                     'ksConstants.tlb', 'ksConstants3D.tlb'):
        lib = pythoncom.LoadTypeLib(str(SDK / filename))
        entries = {}
        for index in range(lib.GetTypeInfoCount()):
            info = lib.GetTypeInfo(index)
            attr = info.GetTypeAttr()
            name, doc, *_ = lib.GetDocumentation(index)
            entry = {'guid': str(attr.iid), 'typekind': attr.typekind, 'doc': doc,
                     'methods': [], 'properties': []}
            for i in range(attr.cFuncs):
                f = info.GetFuncDesc(i)
                names = info.GetNames(f[0])
                entry['methods'].append({'names': list(names), 'invkind': f[4],
                                         'desc': repr(f), 'doc': info.GetDocumentation(f[0])[1]})
            for i in range(attr.cVars):
                v = info.GetVarDesc(i)
                entry['properties'].append({'name': info.GetNames(v.memid)[0],
                                            'value': v.value, 'desc': repr(v)})
            entries[name] = entry
        path = OUT / (Path(filename).stem + '.json')
        path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
        print(filename, len(entries), 'types ->', path)
finally:
    pythoncom.CoUninitialize()
