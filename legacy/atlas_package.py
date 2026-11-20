"""Portable read-only atlas snapshot: one HTML, no runtime or remote assets."""
from pathlib import Path
import hashlib
import json
import zipfile
from datetime import datetime,timezone
from wingstudy import wing_atlas

LEGACY = Path(__file__).resolve().parent  # this app's own pages and scripts

README='''ALL TESTED WINGS - INTERACTIVE RESULTS

1. Extract this ZIP (right-click > Extract All on Windows).
2. Open All_Wings_Interactive.html in your browser.

No installation, Python, Ptera, server or internet connection is needed.
The HTML file can also be shared by itself.

Scroll to zoom at the cursor; drag to pan. Use Reset view to fit all data.
Filter by saved study, simulation conditions, span or chord width.
Hover a result to see its wing; click to inspect dimensions and loads.
Choose color/axes to compare geometry and performance.
Export a CSV of the visible cases, a PNG snapshot, or all embedded data as JSON.

The snapshot includes every retained successful simulation's plot metrics,
wing sections/outlines, identifiers, source-study memberships, and saved
driving/numerical condition groups. Exact repeated simulations are merged.
Failed/deleted runs are excluded. No wing is designated an overall winner.
Compare matched conditions before attributing differences to wing shape.

Large simulation histories, force/moment image files, flapping/evolution
animations, and the Ptera runtime are intentionally not included.
This file is a saved snapshot, not a live connection to the master catalog.
PNG export is a browser snapshot; paper-resolution exports remain in the app.
'''


def html(model,bundle):
    payload=json.dumps(bundle,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    payload=payload.replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e')
    page=(LEGACY/'wing_atlas.html').read_text(encoding='utf-8')
    code=(LEGACY/'wing_atlas.js').read_text(encoding='utf-8').replace('</script','<\\/script')
    page=page.replace('<title>All tested wings</title>','<title>All tested wings · offline snapshot</title>')
    page=page.replace('</style>','.online-only{display:none!important}</style>')
    page=page.replace('PNG and CSV exports include the cases in the current view.','CSV and PNG snapshots include the current view. Paper-resolution PNG exports remain available in the full app.')
    tag='<script src="/atlas.js"></script>'
    if tag not in page:raise ValueError('Atlas script marker missing.')
    return page.replace(tag,'<script type="application/json" id="atlasData">'+payload+'</script><script>globalThis.WING_ATLAS_OFFLINE=true;\n'+code+'</script>')


def export(model):
    data=wing_atlas.bundle(model)
    data['snapshot_utc']=datetime.now(timezone.utc).isoformat(timespec='seconds')
    data['snapshot_version']=1
    data['note']='Offline snapshot. All retained successful simulations; exact repeats merged. Original simulation files and animations are not included.'
    content=html(model,data).encode('utf-8')
    digest=hashlib.sha256(content).hexdigest()[:12]
    directory=model.OUTPUTS/('shared-atlas-'+digest);directory.mkdir(exist_ok=True)
    file=directory/'All_Wings_Interactive.zip'
    with zipfile.ZipFile(file,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        archive.writestr('All_Wings_Interactive.html',content)
        archive.writestr('README.txt',README.encode('utf-8'))
    (directory/'All_Wings_Interactive.html').write_bytes(content)
    return {'file':str(file.relative_to(model.OUTPUTS)).replace('\\','/'),
        'html':str((directory/'All_Wings_Interactive.html').relative_to(model.OUTPUTS)).replace('\\','/'),
        'bytes':file.stat().st_size,'html_bytes':len(content),'cases':len(data['rows']),
        'studies':len(data['studies']),'snapshot_utc':data['snapshot_utc']}
