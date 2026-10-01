import math
import unittest
from unittest.mock import Mock

from geometry import frame,to_world,to_local,closed_profiles,projection_matrix,profile_world_bounds
from safe_modeling import validate_contract,check_contract
from kompas import Kompas


def rectangle(x=0,y=0,w=10,h=5):
    p=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]]
    return [{'kind':'line','start':a,'end':b} for a,b in zip(p,p[1:]+p[:1])]


class GeometryTests(unittest.TestCase):
    def test_frames_roundtrip_all_planes(self):
        for x,y in (([1,0,0],[0,1,0]),([1,0,0],[0,0,1]),([0,1,0],[0,0,1])):
            f=frame([5,7,9],x,y); p=[-3,4]
            self.assertEqual(to_local(f,to_world(f,p)),p)
            with self.assertRaises(ValueError): to_local(f,[5+f['normal'][0],7+f['normal'][1],9+f['normal'][2]])

    def test_invalid_axes(self):
        for x,y in (([0,0,0],[0,1,0]),([1,0,0],[1,0,0]),([float('nan'),0,0],[0,1,0])):
            with self.assertRaises(ValueError): frame([0,0,0],x,y)

    def test_projection_matrix(self):
        f=frame([10,20,30],[1,0,0],[0,0,1]); m=projection_matrix(f)
        p=[2,5,-79,1]
        q=[sum(p[i]*m[4*i+j] for i in range(4)) for j in range(4)]
        self.assertEqual(q,[12,99,35,1])

    def test_profile_rectangle_and_hole(self):
        loops=closed_profiles([rectangle(),[{'kind':'circle','center':[5,2.5],'radius':1}]])
        self.assertEqual(len(loops),2)

    def test_ear_lines_arc(self):
        ear=[{'kind':'line','start':[-20,0],'end':[20,0]},
             {'kind':'line','start':[20,0],'end':[20,15]},
             {'kind':'arc','center':[0,15],'radius':20,'start_angle':0,'end_angle':180},
             {'kind':'line','start':[-20,15],'end':[-20,0]}]
        self.assertEqual(len(closed_profiles([ear])[0]),4)

    def test_disconnected_rejected(self):
        loop=rectangle(); loop[1]['start']=[11,0]
        with self.assertRaisesRegex(ValueError,'not closed'): closed_profiles([loop])

    def test_crossed_lines_rejected(self):
        p=[[0,0],[10,10],[0,10],[10,0]]
        with self.assertRaises(ValueError): closed_profiles([[{'kind':'line','start':a,'end':b} for a,b in zip(p,p[1:]+p[:1])]])

    def test_crossed_line_circle_rejected(self):
        with self.assertRaises(ValueError): closed_profiles([rectangle(),[{'kind':'circle','center':[0,2],'radius':1}]])

    def test_crossed_and_tangent_circles_rejected(self):
        for c in ([1,0],[2,0],[0,0]):
            with self.assertRaises(ValueError): closed_profiles([[{'kind':'circle','center':[0,0],'radius':1}],[{'kind':'circle','center':c,'radius':1}]])

    def test_complementary_arcs_valid(self):
        a={'kind':'arc','center':[0,0],'radius':1,'start_angle':0,'end_angle':180}
        b={**a,'start_angle':180,'end_angle':360}
        self.assertEqual(len(closed_profiles([[a,b]])[0]),2)

    def test_overlap_and_zero_length_rejected(self):
        with self.assertRaises(ValueError): closed_profiles([[{'kind':'line','start':[0,0],'end':[0,0]}]])
        with self.assertRaises(ValueError): closed_profiles([rectangle(),rectangle(2,0,5,5)])

    def test_invalid_profile_never_calls_com(self):
        k=Kompas(); k.create_sketch=Mock()
        with self.assertRaises(ValueError): k.create_closed_profile([rectangle()[:-1]])
        k.create_sketch.assert_not_called()

    def test_contract_validation(self):
        for expected in ({'body_count':True},{'body_count':-1},{'volume_mm3':-1},
                         {'bounds_mm':[10,0,0,0,1,1]},{'unknown':1},{'tolerance':-1}):
            with self.assertRaises(ValueError): validate_contract(expected)

    def test_contract_failures_are_specific(self):
        metrics={'body_count':2,'all_solid':True,'volume_mm3':50,'bounds_mm':[0,0,0,10,10,10]}
        failures=check_contract(metrics,{'body_count':1,'volume_mm3':100,'bounds_mm':[0,0,0,10,10,20]})
        self.assertEqual({f['check'] for f in failures},{'body_count','volume_mm3','bounds_mm'})

    def test_bad_extrusion_contract_precedes_com(self):
        k=Kompas(); k.doc3d=Mock()
        with self.assertRaises(ValueError): k.extrusion3d('s',10,expected={'body_count':1.1})
        with self.assertRaises(ValueError): k.extrusion3d('s',10,direction=[0,0,0])
        k.doc3d.assert_not_called()

    def test_arc_world_bounds_do_not_include_missing_half(self):
        ear=[{'kind':'arc','center':[0,0],'radius':20,'start_angle':0,'end_angle':180},
             {'kind':'line','start':[-20,0],'end':[20,0]}]
        f=frame([10,5,3],[1,0,0],[0,0,1]); bounds=profile_world_bounds(closed_profiles([ear]),f)
        for a,b in zip(bounds,[-10,5,3,30,5,23]): self.assertAlmostEqual(a,b)

    def test_cleanup_failure_is_explicit(self):
        k=Kompas(); k._part3d=Mock(side_effect=RuntimeError('lost native session'))
        result=k._cleanup_created(Mock())
        self.assertFalse(result['success']); self.assertIn('lost native session',result['message'])

    def test_projection_uses_native_points_and_sheet_transform(self):
        k=Kompas(); view=Mock(X=100,Y=200,Scale=2,Angle=90)
        view.GetProjectionPoint.return_value=(True,3.,4.)
        k._view7=Mock(return_value=view)
        from unittest.mock import patch
        with patch('win32com.client.CastTo',return_value=view):
            r=k.project_model_points('view',[[1,2,3]],True)
        for a,b in zip(r['points'][0],[92,206]): self.assertAlmostEqual(a,b)
        view.GetProjectionPoint.assert_called_once_with(1.,2.,3.)

    def test_short_coincident_arc_overlap_rejected(self):
        from geometry import intersections
        def arc(a,b):
            from geometry import arc_point
            s={'kind':'arc','center':[0,0],'radius':10,'start_angle':a,'end_angle':b,'direction':1}
            return {**s,'start':arc_point(s,a),'end':arc_point(s,b)}
        with self.assertRaisesRegex(ValueError,'Overlapping'): intersections(arc(0,180),arc(179.9,270),1e-7)
