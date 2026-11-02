import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import atlas_package


class PortableAtlasChecks(unittest.TestCase):
    def fixture(self):
        return {'rows':[{'key':'one','name':'</script><script>bad()</script>','torque':.5,'thrust':1.,
            'sections':[{'y_m':0,'chord_m':.1},{'y_m':.2,'chord_m':.01}]}],
            'studies':[{'id':'s'}],'cohorts':[],'successful':1,'single_count':1,'paired_count':0}

    def test_embedded_data_roundtrips_and_cannot_close_script(self):
        model=SimpleNamespace(HERE=Path(__file__).parent)
        data=self.fixture();page=atlas_package.html(model,data)
        payload=page.split('id="atlasData">',1)[1].split('</script>',1)[0]
        self.assertEqual(json.loads(payload),data)
        self.assertNotIn('<script>bad()',page)
        self.assertNotIn('<script src=',page)
        self.assertIn('globalThis.WING_ATLAS_OFFLINE=true',page)
        self.assertIn('offline snapshot',page)

    def test_zip_contains_only_self_contained_html_and_instructions(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            model=SimpleNamespace(HERE=Path(__file__).parent,OUTPUTS=Path(tmp))
            with patch.object(atlas_package.wing_atlas,'bundle',return_value=self.fixture()):out=atlas_package.export(model)
            with zipfile.ZipFile(model.OUTPUTS/out['file']) as archive:
                self.assertEqual(set(archive.namelist()),{'All_Wings_Interactive.html','README.txt'})
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read('All_Wings_Interactive.html'),(model.OUTPUTS/out['html']).read_bytes())
            self.assertEqual(out['cases'],1)
            self.assertLess(out['bytes'],out['html_bytes'])


if __name__=='__main__':unittest.main()
