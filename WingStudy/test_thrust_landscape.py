import copy
import csv
from pathlib import Path
import tempfile
import unittest
import numpy as np
from scipy.spatial import Delaunay
import model
import thrust_landscape
import test_catalog


class ThrustLandscapeChecks(unittest.TestCase):
    def rows(self):
        rows=test_catalog.LandscapeChecks().rows()
        for i,r in enumerate(rows):
            r.update(comparison_key=f'current:{i+1}',torque_status='Within limit',single_wing_mean_thrust_N=10.*(i+1))
        return rows

    def test_axes_use_actual_thrust_and_single_wing_descriptors(self):
        rows=self.rows();spec=thrust_landscape.data(model,rows)
        self.assertEqual(spec['axes'],['area_m2','aspect_ratio','single_wing_mean_thrust_N'])
        self.assertEqual([p['coords'] for p in spec['points']],[[r['area_m2'],r['aspect_ratio'],r['single_wing_mean_thrust_N']] for r in rows])
        self.assertEqual(len({p['case_id'] for p in spec['points']}),3)
        self.assertEqual([p['source_case'] for p in spec['points']],['case_0001']*3)
        self.assertTrue(spec['fixed_span']);self.assertFalse(spec['triangles']);self.assertTrue(spec['curve'])
        curve=np.asarray(spec['curve'])
        np.testing.assert_allclose(curve[:,0]*curve[:,1],.04)
        self.assertGreaterEqual(curve[:,2].min(),10);self.assertLessEqual(curve[:,2].max(),30)

    def test_duplicate_locations_keep_every_wing_and_highest_thrust_envelope(self):
        rows=self.rows();duplicate=copy.deepcopy(rows[0]);duplicate.update(comparison_key='old:99',single_wing_mean_thrust_N=99.)
        spec=thrust_landscape.data(model,rows+[duplicate])
        self.assertEqual(len(spec['points']),4);self.assertEqual(spec['duplicate_locations'],1)
        self.assertIn('old:99',spec['vertex_case_ids']);self.assertNotIn('current:1',spec['vertex_case_ids'])

    def test_mixed_conditions_show_measured_points_only(self):
        rows=self.rows();rows[1]['_settings']['frequency_hz']=123
        spec=thrust_landscape.data(model,rows)
        self.assertFalse(spec['triangles']);self.assertFalse(spec['curve']);self.assertFalse(spec['vertex_case_ids'])
        self.assertIn('settings differ',spec['note'])

    def test_surface_stays_inside_measured_hull_and_thrust_bounds(self):
        rows=[]
        for i,(area,ar) in enumerate([(.02,1),(.06,1),(.02,3),(.06,3),(.04,2)]):
            row=copy.deepcopy(self.rows()[0]);row.update(comparison_key=str(i),area_m2=area,aspect_ratio=ar,single_wing_mean_thrust_N=float((i+1)**2));rows.append(row)
        spec=thrust_landscape.data(model,rows)
        self.assertTrue(spec['triangles']);self.assertFalse(spec['fixed_span'])
        vertices=np.asarray(spec['vertices']);coords=np.array([p['coords'] for p in spec['points']])
        self.assertTrue(np.all(Delaunay(coords[:,:2]).find_simplex(vertices[:,:2],tol=1e-10)>=0))
        self.assertGreaterEqual(vertices[:,2].min(),coords[:,2].min()-1e-10)
        self.assertLessEqual(vertices[:,2].max(),coords[:,2].max()+1e-10)

    def test_export_labels_data_and_formats(self):
        rows=self.rows();spec=thrust_landscape.data(model,rows)
        export=[{**r,'id':r['comparison_key']} for r in rows]
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp:
            report=model.shape_landscape(Path(temp),True,True,selected_rows=export,selected_spec=spec)
            folder=Path(temp)/'comparisons'
            self.assertEqual({p.suffix for p in folder.iterdir()},{'.png','.csv'})
            with (folder/'wing_area_aspect_thrust.csv').open(encoding='utf-8',newline='') as f:data=list(csv.DictReader(f))
            self.assertEqual([float(r['single_wing_mean_thrust_N']) for r in data],[10,20,30])
            self.assertNotIn(model.OBJECTIVE,data[0])
            self.assertEqual(report['color_label'],'Mean single-wing thrust (N)')


if __name__=='__main__':unittest.main()
