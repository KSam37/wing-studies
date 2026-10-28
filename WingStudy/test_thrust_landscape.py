import copy
import csv
from pathlib import Path
import tempfile
import unittest
import numpy as np
from scipy.spatial import Delaunay
import model
import catalog
import thrust_landscape
import test_catalog


class ThrustLandscapeChecks(unittest.TestCase):
    def test_custom_leading_edge_and_torque_axes_and_zero_torque(self):
        rows=self.rows();axes=['leading_edge_length_m','single_wing_peak_abs_roll_moment_Nm','single_wing_mean_thrust_N']
        spec=thrust_landscape.data(model,rows,axes)
        self.assertEqual(spec['axes'],axes)
        self.assertEqual(spec['points'][0]['coords'],[.2,1.,10.])
        self.assertEqual(spec['points'][0]['area_m2'],.02)
        rows[0]['single_wing_peak_abs_roll_moment_Nm']=0
        self.assertEqual(thrust_landscape.data(model,rows,axes)['points'][0]['coords'][1],0)
        reversed_axes=['area_m2','single_wing_mean_thrust_N','single_wing_peak_abs_roll_moment_Nm']
        changed=thrust_landscape.data(model,rows,reversed_axes)
        self.assertEqual(changed['points'][0]['value'],0)
        self.assertEqual(changed['color_label'],thrust_landscape.AXIS_PARAMETERS[reversed_axes[-1]])
        for invalid in [[],['area_m2']*3,['area_m2','unknown','single_wing_mean_thrust_N']]:
            with self.assertRaises(ValueError):thrust_landscape.data(model,rows,invalid)

    def test_leading_edge_length_includes_sweep_and_bending_but_not_zero_suffix(self):
        from wing_dimensions import dimensions
        row={'sections':[{'y_m':0,'x_m':0,'chord_m':.2,'roll_deg':45.},
             {'y_m':.3,'x_m':.4,'chord_m':.1,'roll_deg':0.},
             {'y_m':1.,'x_m':2.,'chord_m':0}], 'span_m':.64,'_settings':{'gap_m':.04}}
        self.assertAlmostEqual(dimensions(row)['leading_edge_length_m'],(.3**2+.4**2+.3**2)**.5)
        self.assertEqual(dimensions(row)['single_wing_span_m'],.3)

    def test_custom_axis_export_does_not_mislabel_length_as_area(self):
        rows=self.rows();axes=['leading_edge_length_m','single_wing_peak_abs_roll_moment_Nm','single_wing_mean_thrust_N']
        spec=thrust_landscape.data(model,rows,axes)
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp:
            export=[{**r,'id':r['comparison_key']} for r in rows]
            model.shape_landscape(Path(temp),True,True,selected_rows=export,selected_spec=spec)
            with (Path(temp)/'comparisons'/(spec['export_stem']+'.csv')).open(encoding='utf-8',newline='') as f:records=list(csv.DictReader(f))
            self.assertEqual(float(records[0]['area_m2']),.02)
            self.assertEqual(float(records[0]['leading_edge_length_m']),.2)
            self.assertEqual(float(records[0]['plot_x']),.2)
            self.assertEqual(records[0]['plot_y_parameter'],axes[1])

    def rows(self):
        rows=test_catalog.LandscapeChecks().rows()
        for i,r in enumerate(rows):
            r.update(comparison_key=f'current:{i+1}',torque_status='Within limit',single_wing_mean_thrust_N=10.*(i+1))
        return rows

    def test_axes_use_actual_thrust_and_single_wing_descriptors(self):
        rows=self.rows();spec=thrust_landscape.data(model,rows)
        self.assertEqual(spec['axes'],['area_m2',catalog.OBJECTIVE,'single_wing_mean_thrust_N'])
        self.assertEqual([p['coords'] for p in spec['points']],[[r['area_m2'],r['single_wing_mean_thrust_N']/r['single_wing_peak_abs_roll_moment_Nm'],r['single_wing_mean_thrust_N']] for r in rows])
        self.assertEqual(len({p['case_id'] for p in spec['points']}),3)
        self.assertEqual([p['source_case'] for p in spec['points']],['case_0001']*3)
        self.assertFalse(spec['triangles']);self.assertTrue(spec['curve'])
        curve=np.asarray(spec['curve'])
        np.testing.assert_allclose(curve[:,1],curve[:,2])
        self.assertGreaterEqual(curve[:,2].min(),10-1e-12);self.assertLessEqual(curve[:,2].max(),30+1e-12)

    def test_duplicate_locations_keep_every_wing_and_highest_thrust_envelope(self):
        rows=self.rows();duplicate=copy.deepcopy(rows[0]);duplicate.update(comparison_key='old:99',single_wing_mean_thrust_N=99.,single_wing_peak_abs_roll_moment_Nm=9.9)
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
            row=copy.deepcopy(self.rows()[0]);row.update(comparison_key=str(i),area_m2=area,aspect_ratio=ar,single_wing_mean_thrust_N=float((i+1)**2),single_wing_peak_abs_roll_moment_Nm=float((i+1)**2)/ar);rows.append(row)
        spec=thrust_landscape.data(model,rows)
        self.assertTrue(spec['triangles'])
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
            with (folder/'wing_area_ratio_thrust.csv').open(encoding='utf-8',newline='') as f:data=list(csv.DictReader(f))
            self.assertEqual([float(r['single_wing_mean_thrust_N']) for r in data],[10,20,30])
            self.assertEqual([float(r[model.OBJECTIVE]) for r in data],[10,20,30])
            self.assertEqual([float(r['single_wing_span_m']) for r in data],[.2]*3)
            self.assertEqual(report['color_label'],'Mean single-wing thrust (N)')

    def test_zero_torque_is_not_an_infinite_axis_coordinate(self):
        rows=self.rows();rows[0]['single_wing_peak_abs_roll_moment_Nm']=0
        with self.assertRaisesRegex(ValueError,'positive peak root torque'):thrust_landscape.data(model,rows)

    def test_zero_chords_override_stale_span_metadata(self):
        from wing_dimensions import dimensions
        row=self.rows()[0]
        row.update(span_m=.8,single_wing_span_m=.38,requested_sections=[{'y_m':0,'chord_m':.2},{'y_m':.1,'chord_m':.1},{'y_m':.2,'chord_m':0},{'y_m':.38,'chord_m':0}])
        result=dimensions(row)
        self.assertEqual(result['single_wing_span_m'],.1)
        self.assertAlmostEqual(result['effective_total_span_m'],.24)
        self.assertEqual(result['reference_total_span_m'],.8)
        self.assertEqual(result['omitted_zero_chord_count'],2)
        self.assertTrue(result['span_shortened_by_zero_chords'])
        self.assertEqual(thrust_landscape.data(model,[row])['points'][0]['single_wing_span_m'],.1)
        import torque_study
        self.assertEqual(torque_study.rank([row],2.)['winner']['effective_total_span_m'],result['effective_total_span_m'])


if __name__=='__main__':unittest.main()
