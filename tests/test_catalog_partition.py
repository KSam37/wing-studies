import _paths  # noqa: F401  (repo root on sys.path)
import json
import sqlite3
import unittest
import xml.etree.ElementTree as ET
import zipfile
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from wingstudy import catalog
from wingstudy import catalog_partition as partition
from wingstudy import model
import test_catalog


class PartitionChecks(test_catalog.CatalogChecks):
    def test_workbook_formatting_does_not_block_live_case_writer(self):
        self.saved('20261001_old')
        original=zipfile.ZipFile;formatting=threading.Event();release=threading.Event()
        def slow_template(*args,**kwargs):
            if str(args[0]).endswith('master_template.xlsx'):
                formatting.set()
                if not release.wait(10):raise RuntimeError('Test never released workbook formatting')
            return original(*args,**kwargs)
        with ThreadPoolExecutor(max_workers=1) as pool,patch.object(catalog.zipfile,'ZipFile',side_effect=slow_template):
            future=pool.submit(catalog.export,model)
            try:
                self.assertTrue(formatting.wait(10))
                with sqlite3.connect(self.out.parent/'master_runs.sqlite3',timeout=.2,factory=catalog.ClosingConnection) as db:
                    db.execute("insert or replace into meta values('live_writer_check','saved')")
            finally:release.set()
            future.result()

    def test_live_partition_unifies_history_and_keeps_future_writes_and_cache(self):
        spec,old,row=self.saved('20261001_old');catalog.start_fresh(model)
        self.spec['settings']['speed_mps']=.7
        spec,previous,old2=self.saved('20261020_previous')
        self.spec['settings']['speed_mps']=.8
        spec,current,new=self.saved('20261030_current')
        with catalog.connect(model) as db:
            before=[tuple(r) for r in db.execute('select case_no,signature from cases order by case_no')]
        config=partition.organize(model,current.name)
        self.assertTrue((__import__('pathlib').Path(config['backup_directory'])/'master_runs_old.sqlite3').is_file())
        self.assertEqual({r['_study'] for r in catalog.listing(model)['rows']},{current.name})
        old_view=catalog.generations(model,['old'])
        self.assertEqual({r['_study'] for r in old_view['rows']},{old.name,previous.name})
        self.assertEqual(len(catalog.generations(model,['current','old'])['rows']),3)
        self.assertEqual(catalog.preview(model,spec)['cached_case_count'],1)
        # A worker using the original record() contract can keep writing.
        self.spec['settings']['speed_mps']=.9
        future_spec,future,future_row=self.saved('20261031_future')
        self.assertEqual({r['_study'] for r in catalog.listing(model)['rows']},{current.name,future.name})
        self.assertEqual(len(catalog.generations(model,['old'])['rows']),2)
        with catalog.connect(model) as db:
            after=[tuple(r) for r in db.execute('select case_no,signature from cases order by case_no')]
        self.assertEqual(before,after[:len(before)])
        for filename,expected,title in [('master_runs.xlsx',2,'New master'),('master_runs_old.xlsx',2,'Old master')]:
            catalog.export(model,filename=filename)
            with zipfile.ZipFile(self.out.parent/filename) as z:
                for sheet in (1,2):
                    root=ET.fromstring(z.read(f'xl/worksheets/sheet{sheet}.xml'))
                    body=root.find(f'{{{catalog.NS}}}sheetData')
                    self.assertEqual(len(body)-5,expected)
                    self.assertIn(title,''.join(body[0].itertext()))
        self.assertFalse((self.out.parent/'master_runs_adaptive.xlsx').exists())

    def test_reused_current_case_is_scoped_to_its_new_location(self):
        spec,source,saved=self.saved('20261001_old')
        spec2,current,same=self.saved('20261030_current')
        partition.organize(model,current.name)
        # Point the canonical result back at the historical location, as a
        # cache hit does. New still displays the occurrence in the active run.
        with catalog.connect(model) as db:
            db.execute('update cases set origin_study=?,origin_case=?',(source.name,saved['id']))
        new=catalog.generations(model,['current'])['rows']
        self.assertEqual(len(new),1)
        self.assertEqual(new[0]['_study'],current.name)
        self.assertEqual(new[0]['global_case_no'],saved['global_case_no'])
        self.assertEqual({o['study'] for o in new[0]['occurrences']},{current.name})
        old=catalog.generations(model,['old'])['rows']
        self.assertEqual({o['study'] for o in old[0]['occurrences']},{source.name})
        self.assertEqual(len(catalog.generations(model,['old','current'])['rows']),1)


if __name__=='__main__':unittest.main()
