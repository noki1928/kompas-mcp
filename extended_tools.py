"""Semantic tool catalog, isolated from transport and native implementations."""
from typing import Any, Literal
from mcp.server.fastmcp import Image
from diagnostics import error_info, tool_result


def register(mcp,worker):
    def run(method,*args,**kwargs):
        try:
            result=worker.call(method,*args,**kwargs)
            return tool_result({'success':True,**result} if isinstance(result,dict) else {'success':True,'result':result})
        except Exception as exc:
            return tool_result(error_info(exc,method))

    @mcp.tool()
    def get_kompas_state() -> dict:
        """Synchronize document list and model update stamps. Return active document,
        API root handles, topology generations and editing state. Call before work
        and after manual edits. Lengths are mm, angles degrees, sketch coordinates local.
        """
        return run('get_kompas_state')

    @mcp.tool()
    def show_application(visible:bool=True,restore_window:bool=True) -> dict:
        """Set KOMPAS visibility, optionally restore minimized window for screenshots.
        Does not focus/click UI, modify documents, or launch another application.
        """
        return run('show_application',visible,restore_window)

    @mcp.tool()
    def sdk_catalog(query:str='',interface:str='',library:str='',limit:int=30) -> dict:
        """Discover exact interfaces/members/signatures in installed official SDK TLBs.
        query filters member/interface names, interface selects exact name, library
        e.g. kAPI3D5COM.tlb/kAPI7.tlb. Does not invoke CAD. Published != live-tested.
        """
        return run('sdk_catalog',query,interface,library,limit)

    @mcp.tool()
    def api_constants(names:list[str]=[],query:str='',limit:int=100) -> dict:
        """Read exact enum values from installed SDK. Supply names or substring query;
        never guess o3d_* operation types, projection types or export format values.
        """
        return run('api_constants',names,query,limit)

    @mcp.tool()
    def describe_object(target:str) -> dict:
        """Describe a root (api7/api5/document/doc2d/doc3d/part) or object_id using
        runtime ITypeInfo: type, GUID, public members, parameters, invocation kinds.
        Use before generic calls. Some TLB members may be absent at runtime.
        """
        return run('describe_object',target)

    @mcp.tool()
    def kompas_api_call(target:str,operation:Literal['get','set','call','cast']='get',member:str='',
                        arguments:list[Any]=[],value:Any=None,interface:str='',allow_mutation:bool=False) -> dict:
        """Universal public COM dispatch, without executing Python. target is a root
        or object_id; get reads one property; set assigns value; call invokes one
        exact SDK method; cast uses an API7 interface name. Calls/set require explicit
        allow_mutation=true (even read methods). Arguments accept JSON scalars/arrays,
        {object_id:'...'} for COM objects, {missing:true} for optional/byref defaults.
        COM results become reusable handles, tuples become JSON lists. No eval or
        member paths. Lifecycle, converter file I/O and process shutdown are blocked:
        use managed tools. Not a security sandbox: allowed CAD methods can be destructive.
        Inspect describe_object, checkpoint before edits, verify geometry afterwards.
        Failures include HRESULT, excepinfo, target and suggested actions.
        """
        return run('kompas_api_call',target,operation,member,arguments,value,interface,allow_mutation)

    @mcp.tool()
    def api_batch(calls:list[dict]) -> dict:
        """Run up to 100 kompas_api_call argument dictionaries sequentially. Stops on
        first success=false. NOT atomic; preceding calls remain applied. Returned
        handles cannot be referred to by symbolic placeholders; use successive calls.
        """
        return run('api_batch',calls)

    @mcp.tool()
    def get_object_properties(target:str,members:list[str]) -> dict:
        """Read specified public properties, returning a separate result/error per
        member. No speculative method execution; use describe_object to pick members.
        """
        return run('get_object_properties',target,members)

    @mcp.tool()
    def release_objects(object_ids:list[str]) -> dict:
        """Release server handles, not CAD entities. Reduces registry memory usage."""
        return run('release_objects',object_ids)

    @mcp.tool()
    def list_documents() -> dict:
        """List open documents with native reference, path, type and unsaved flag."""
        return run('list_documents')

    @mcp.tool()
    def activate_document(document_reference:int) -> dict:
        """Activate one open document by native reference from list_documents.
        Does not open files; mutations act on active document unless otherwise stated.
        """
        return run('activate_document',document_reference)

    @mcp.tool()
    def close_document(document_reference:int,discard_changes:bool=False) -> dict:
        """Close an explicitly identified document. Reject unsaved changes unless
        discard_changes=true. No prompt, no application Quit, no implicit saving.
        """
        return run('close_document',document_reference,discard_changes)

    @mcp.tool()
    def save_current_document(confirm_overwrite:bool=False) -> dict:
        """Save to current path; requires confirm_overwrite=true. For a new document
        or protecting original use save_document(path=new_path) instead.
        """
        return run('save_current_document',confirm_overwrite)

    @mcp.tool()
    def create_checkpoint() -> dict:
        """Save current state to server-owned working copy and immutable snapshot.
        WARNING: native SaveAs changes current document's file association to working
        copy. Original file is NOT overwritten. Not in-place Undo/transaction.
        """
        return run('create_checkpoint')

    @mcp.tool()
    def restore_checkpoint(checkpoint_id:str) -> dict:
        """Open NEW recovered copy of a process-local checkpoint. Does not close or
        discard the edited document; old handles don't apply to recovered copy.
        """
        return run('restore_checkpoint',checkpoint_id)

    @mcp.tool()
    def get_model_tree(name:str='',type_id:int|None=None,limit:int=1000) -> dict:
        """Read all non-topological API5 entities in top part, not only extrusions.
        Includes names, type IDs, feature handles, suppression/validity/error/update
        stamp and owner handle. Filter by name/type. Assemblies use get_assembly_tree.
        Dependencies beyond owner are inspectable via native IFeature generic API.
        """
        return run('get_model_tree',name,type_id,limit)

    @mcp.tool()
    def create_sketch(plane:Literal['XY','XZ','YZ']='XY',plane_object_id:str|None=None,name:str='') -> dict:
        """Create EMPTY 3D sketch on origin plane or planar API5 face/plane handle.
        Returns sketch_id. Then begin_sketch_edit, create_sketch_entities, end_sketch_edit.
        For an atomic simple profile prefer sketch3d. Coordinates in sketch-local mm.
        """
        return run('create_sketch',plane,plane_object_id,name)

    @mcp.tool()
    def get_sketch_frame(sketch_id:str) -> dict:
        """Read actual native sketch origin, X/Y axes and normal in model coordinates.
        Never assume XZ/YZ local coordinates or normal signs from plane names.
        """
        return run('get_sketch_frame',sketch_id)

    @mcp.tool()
    def transform_sketch_points(sketch_id:str,points:list[list[float]],to:Literal['model','sketch']='model',tolerance:float=1e-7) -> dict:
        """Transform sketch-local [u,v] to world [x,y,z], or world to sketch.
        World points outside support plane are rejected, not silently projected.
        """
        return run('transform_sketch_points',sketch_id,points,to,tolerance)

    @mcp.tool()
    def create_closed_profile(contours:list[list[dict]],plane:Literal['XY','XZ','YZ']='XY',
                              plane_object_id:str|None=None,origin:list[float]|None=None,
                              x_axis:list[float]|None=None,y_axis:list[float]|None=None,
                              name:str='',tolerance:float=1e-7) -> dict:
        """Create complete new sketch with validated closed line/arc/circle contours.
        line: kind,start:[u,v],end:[u,v]. arc: kind,center,radius,start_angle,
        end_angle,direction=+1 CCW/-1 CW. circle occupies its own contour.
        Optional origin and BOTH model-space X/Y axes define input coordinates;
        axes/origin must lie on selected native plane or planar face support.
        Rejects gaps, crossing/touching boundaries and overlaps before geometry.
        Ends edit internally; on failure cleans only new sketch, reporting outcome.
        """
        return run('create_closed_profile',contours,plane,plane_object_id,origin,x_axis,y_axis,name,tolerance)

    @mcp.tool()
    def cut_through_all(sketch_id:str,direction:list[float],both_sides:bool=False,name:str='',expected:dict|None=None,
                        target_body_ids:list[str]|None=None,cleanup_sketch:bool=False) -> dict:
        """Native etThroughAll cut of ALL top-part bodies, no guessed depth.
        Explicit world normal direction; both_sides cuts both directions.
        Checks volume decrease and optional geometric contract. Does not retry
        opposite direction. Cleanup of only new feature (plus sketch if cleanup_sketch)
        is verified and reported. Only NEW invalid features fail the operation.
        Optional fresh body IDs select native targets; by default ALL top-part bodies.
        Preserves body count unless expected explicitly requests a different count.
        """
        return run('cut_through_all',sketch_id,direction,both_sides,name,expected,target_body_ids,cleanup_sketch)

    @mcp.tool()
    def delete_feature(object_id:str|None=None,name:str='') -> dict:
        """Delete one 3D feature or sketch of the active part by fresh handle or exact
        unique tree name, rebuild, and report removed_features (native delete may also
        remove dependents), volume delta and remaining feature errors. Not undoable.
        """
        return run('delete_feature',object_id,name)

    @mcp.tool()
    def check_model_contract(expected:dict|None=None) -> dict:
        """Read-only check of body_count, bounds_mm=[minXYZ,maxXYZ], volume_mm3,
        absolute tolerance(default 1e-6), relative_tolerance(default 1e-6), native
        feature errors and solidity. Failed checks return actual/expected values.
        """
        return run('check_model_contract',expected)

    @mcp.tool()
    def change_begin(label:str,intent:str='') -> dict:
        """Open a labelled change stage in the active PART. While open, model mutations are
        refused in any other document, and the stage document cannot be closed. Each
        mutation result still carries its own effect. One stage at a time, process-local.
        """
        return run('change_begin',label,intent)

    @mcp.tool()
    def change_status() -> dict:
        """Report the open stage: added/removed features, parameter edits, operation log,
        cumulative effect (volume delta, body count, new errors, assertion failures).
        """
        return run('change_status')

    @mcp.tool()
    def change_end(force:bool=False) -> dict:
        """Close the stage with its cumulative effect. Refused (stage stays open) when the
        verdict is broken (new feature errors/non-solid) or a stored assertion fails, unless force.
        """
        return run('change_end',force)

    @mcp.tool()
    def change_abort() -> dict:
        """Revert the open stage: delete every feature appended since change_begin (newest
        first), restore parameters edited via set_feature_parameters, rebuild, and verify
        body count/volume/bounds equal the stage start. Refused if pre-existing features were
        deleted/renamed/reordered. Not KOMPAS Undo; generic API side effects are not reverted.
        """
        return run('change_abort')

    @mcp.tool()
    def assert_register(name:str,kind:Literal['contract','bounds_within','volume_range'],spec:dict) -> dict:
        """Store a named requirement for the active 3D document, re-checked in every mutation
        effect and at change_end. contract: body_count/bounds_mm/volume_mm3/tolerances;
        bounds_within: bounds_mm=[minXYZ,maxXYZ] the model must stay inside (tolerance);
        volume_range: min_mm3/max_mm3. Same name replaces. Reports whether it holds now.
        """
        return run('assert_register',name,kind,spec)

    @mcp.tool()
    def assert_list() -> dict:
        """List stored assertions of the active document."""
        return run('assert_list')

    @mcp.tool()
    def assert_remove(name:str) -> dict:
        """Remove one stored assertion of the active document by name."""
        return run('assert_remove',name)

    @mcp.tool()
    def assert_check() -> dict:
        """Evaluate all stored assertions and native feature errors of the active document now."""
        return run('assert_check')

    @mcp.tool()
    def begin_sketch_edit(sketch_id:str) -> dict:
        """Begin managed sketch editing, return API5 edit_context handle for generic
        geometry/constraints. Only one managed edit at a time; end before features.
        """
        return run('begin_sketch_edit',sketch_id)

    @mcp.tool()
    def create_sketch_entities(entities:list[dict]) -> dict:
        """Batch up to 500 entities in managed edit: kind=line (x1,y1,x2,y2),
        circle (x,y,radius), arc (x,y,radius,start_angle,end_angle,direction), point
        (x,y), rectangle (x,y,width,height), polygon(points). style=1 solid,3 axis,
        6 auxiliary. Not atomic: failure returns failed_index and partial references.
        Splines/trimming/constraints are available via edit_context generic methods.
        """
        return run('create_sketch_entities',entities)

    @mcp.tool()
    def end_sketch_edit() -> dict:
        """Finish managed sketch edit. Returns sketch_id, invalidates topology handles."""
        return run('end_sketch_edit')

    @mcp.tool()
    def revolve(sketch_id:str,angle:float=360,cut:bool=False,reverse:bool=False,name:str='',expected:dict|None=None) -> dict:
        """Rotate sketch by 0<angle<=360 degrees. Sketch must contain a closed
        half-profile and ONE axis line (style=3), drawn in its own local coordinates.
        cut=true removes material. Verify volume and image; kernel determines intersection.
        Default boss requires one solid body, cut preserves count. Optional geometric
        contract; volume sign/native validity checked, new failed feature cleaned.
        """
        return run('revolve',sketch_id,angle,cut,reverse,name,expected)

    @mcp.tool()
    def edge_operation(edge_ids:list[str],operation:Literal['chamfer','fillet'],size:float,
                       distance2:float|None=None,tangent:bool=False,name:str='',expected:dict|None=None) -> dict:
        """Apply chamfer/fillet to fresh API5 edge handles from find_edges. size is
        fillet radius or first chamfer distance in mm. distance2 defaults to size
        (equal distances give 45-degree chamfer). Rebuild invalidates edge/face IDs.
        Body count/solidity/native validity and optional geometric contract checked.
        """
        return run('edge_operation',edge_ids,operation,size,distance2,tangent,name,expected)

    @mcp.tool()
    def get_feature_parameters(feature_id:str) -> dict:
        """Return semantic extrusion/rotation/chamfer/fillet parameters plus definition
        handle for all other native operations. API5 byref side arrays include status
        followed by values; use describe_object on definition before interpreting them.
        """
        return run('get_feature_parameters',feature_id)

    @mcp.tool()
    def set_feature_parameters(feature_id:str,parameters:dict) -> dict:
        """Edit depth/reverse (extrusion), angle/reverse (rotation), distance1/distance2/
        tangent (chamfer), radius/tangent (fillet), then Update and rebuild. Make a
        checkpoint first: failed edits may be partial; previous_parameters are returned.
        """
        return run('set_feature_parameters',feature_id,parameters)

    @mcp.tool()
    def rebuild_model() -> dict:
        """Native rebuild of active part/assembly; invalidate topology references."""
        return run('rebuild_model')

    @mcp.tool()
    def get_model_properties() -> dict:
        """All top-part bodies: solid flag, bbox mm, area mm², volume mm³, center mm,
        native mass grams using stored material density. Does not assign material.
        """
        return run('get_model_properties')

    @mcp.tool()
    def find_faces(surface_type:str='',radius:float|None=None,tolerance:float=0.01,
                   limit:int=100,largest_first:bool=False) -> dict:
        """Inspect/filter API5 faces by plane/cylinder/cone/sphere/torus/nurbs and
        cylinder radius mm±tolerance. Return fresh face IDs, areas, surface bounds,
        sample normals and diagnostics. Surface bounds may be untrimmed; not a face bbox.
        largest_first sorts by area. Reacquire after every rebuild/manual change.
        """
        return run('find_faces',surface_type,radius,tolerance,limit,largest_first)

    @mcp.tool()
    def find_edges(curve_type:str='',min_length:float=0,max_length:float|None=None,limit:int=100) -> dict:
        """Inspect/filter line/circle/arc/ellipse/nurbs edges, lengths in mm, endpoints
        and curve bounds. Use returned IDs for chamfer/fillet; IDs stale after rebuild.
        """
        return run('find_edges',curve_type,min_length,max_length,limit)

    @mcp.tool()
    def validate_document() -> dict:
        """Collect native validity/error/suppression and body metrics. Not engineering
        approval. 2D validation is accessibility only; inspect dimensions and exports.
        """
        return run('validate_document')

    @mcp.tool()
    def set_standard_view(view:str='isometric') -> dict:
        """Activate native front/back/top/bottom/left/right/isometric/dimetric projection,
        fit model. Uses projection type enums, not localized names or mouse clicks.
        """
        return run('set_standard_view',view)

    @mcp.tool()
    def set_camera(origin:list[float],x_axis:list[float],y_axis:list[float],scale:float|None=None) -> dict:
        """Set current projection placement via origin mm and orthogonal normalized
        view X/Y axes in model coordinates; view Z is right-handed X cross Y.
        Optional positive native projection scale. Generic IPlacement for other rotations.
        """
        return run('set_camera',origin,x_axis,y_axis,scale)

    @mcp.tool()
    def create_model_projection(name:str,origin:list[float],x_axis:list[float],y_axis:list[float]) -> dict:
        """Create durable named projection in active MODEL, preserving existing names.
        Not deleted by set_camera. Save model explicitly before drawing lookup.
        Does not save/overwrite files. Duplicate names are rejected.
        """
        return run('create_model_projection',name,origin,x_axis,y_axis)

    @mcp.tool()
    def fit_view() -> dict:
        """Fit active 2D/3D document to its viewport without changing model geometry."""
        return run('fit_view')

    @mcp.tool()
    def capture_viewport(path:str|None=None,overwrite:bool=False):
        """PNG capture of current viewport, or main-window fallback if no View child.
        Unminimized window required. With path saves file and returns metadata;
        without path returns image to vision model. Does not capture whole desktop.
        """
        try:
            result=worker.call('capture_viewport',path,overwrite)
            return Image(data=result,format='png') if isinstance(result,bytes) else result
        except Exception as exc:
            return tool_result(error_info(exc,'capture_viewport'))

    @mcp.tool()
    def capture_views(views:list[str]=['isometric','front','top','right'],directory:str|None=None) -> dict:
        """Save several native projection viewport PNGs. New output directory by
        default; existing files protected. Return file list, camera remains at last view.
        """
        return run('capture_views',views,directory)

    @mcp.tool()
    def export_model(path:str,format:Literal['step','stl','iges','parasolid']='step',overwrite:bool=False) -> dict:
        """Export active part/assembly via native neutral-format converter. Check
        returned nonempty file; exporter availability depends on KOMPAS installation/license.
        """
        return run('export_model',path,format,overwrite)

    @mcp.tool()
    def drawing_sheet(sheet:int=1,format:str|None=None,portrait:bool|None=None,stamp:dict|None=None) -> dict:
        """Read/update 1-based drawing sheet format A0..A5, orientation, stamp text
        (cell-number keys: 1 name,2 designation,6 scale for standard stamp). Format mm.
        """
        return run('drawing_sheet',sheet,format,portrait,stamp)

    @mcp.tool()
    def create_model_view(model_path:str,view:str='front',x:float=100,y:float=150,scale:float=1,name:str='',
                          projection_name:str='',x_axis:list[float]|None=None,y_axis:list[float]|None=None,
                          origin:list[float]|None=None) -> dict:
        """Create associative standard view of SAVED M3D/A3D in active drawing.
        x/y in sheet mm, scale positive. Projection resolved from actual model.
        Existing source documents are preserved; temporary lookup documents are closed.
        Choose native view OR durable projection_name OR explicit model-space X/Y
        axes and origin. Explicit axes use drawing ProjectionMatrix without modifying
        source file. Native GetProjectionPoint readback verifies requested orientation.
        """
        return run('create_model_view',model_path,view,x,y,scale,name,projection_name,x_axis,y_axis,origin)

    @mcp.tool()
    def project_model_points(view_id:str,points:list[list[float]],to_sheet:bool=False) -> dict:
        """Native GetProjectionPoint converts model XYZ to actual view-local UV.
        Optional sheet coordinates include view scale, rotation and translation.
        Coordinate projection, not automatic edge association or visibility testing.
        """
        return run('project_model_points',view_id,points,to_sheet)

    @mcp.tool()
    def add_model_dimension(view_id:str,points:list[list[float]],position:list[float],
                            orientation:Literal['horizontal','vertical','parallel']='horizontal',prefix:str='',suffix:str='') -> dict:
        """Create real LINEAR dimension by projecting two model XYZ points and label
        XYZ through actual view. Nominal value is checked. Not edge-associated.
        """
        return run('add_model_dimension',view_id,points,position,orientation,prefix,suffix)

    @mcp.tool()
    def set_drawing_view(view_id:str,x:float|None=None,y:float|None=None,
                         scale:float|None=None,active:bool=True) -> dict:
        """Change drawing view placement/scale and optionally make it current.
        Subsequent geometry coordinates are VIEW-LOCAL, not sheet coordinates.
        """
        return run('set_drawing_view',view_id,x,y,scale,active)

    @mcp.tool()
    def add_dimension(kind:Literal['linear','diameter','radius']='linear',view_id:str|None=None,
                      points:list[list[float]]=[],position:list[float]=[],orientation:str='horizontal',
                      center:list[float]=[],radius:float|None=None,angle:float=45,prefix:str='',suffix:str='') -> dict:
        """Create REAL API7 dimension in view-local mm. Linear: 2 points and label/
        dimension-line position, orientation horizontal/vertical/parallel. Diameter/
        radius: center, radius, angle degrees. Nominal value auto-computed; no fake text.
        Coordinate-driven dimensions are not automatically bound to model edges.
        """
        return run('add_dimension',kind,view_id,points,position,orientation,center,radius,angle,prefix,suffix)

    @mcp.tool()
    def get_document_structure(include_objects:bool=True,limit:int=500) -> dict:
        """Read drawing sheets/views, geometry and annotation coordinates/text/dimensions
        with handles and per-collection warnings. limit caps total 2D objects. For 3D
        returns model tree. View-local coordinates require position/scale transform.
        """
        return run('get_document_structure',include_objects,limit)

    @mcp.tool()
    def find_drawing_objects(collection:str='',text:str='',limit:int=100) -> dict:
        """Filter structurally read drawing objects by collection (Circles,
        LineDimensions, etc.) or text/property substring. Returns view and object IDs.
        """
        return run('find_drawing_objects',collection,text,limit)

    @mcp.tool()
    def export_drawing_image(path:str,dpi:int=300,sheet:int=1,overwrite:bool=False) -> dict:
        """Native PNG/JPEG of selected 1-based drawing sheet, dpi=72..600, scale 1:1.
        High resolution for reading dimensions. Whole sheet, independent of viewport size.
        """
        return run('export_drawing_image',path,dpi,sheet,overwrite)

    @mcp.tool()
    def export_drawing_pdf(path:str,overwrite:bool=False) -> dict:
        """Native Pdf2d conversion of saved unchanged drawing, all sheets.
        Save current edits to a new CDW path first. Verify PDF scale before manufacture.
        """
        return run('export_drawing_pdf',path,overwrite)

    @mcp.tool()
    def capture_drawing_tiles(directory:str|None=None,sheet:int=1,rows:int=2,columns:int=3,dpi:int=300) -> dict:
        """Native high-resolution sheet render, split into rows×columns PNG tiles.
        Returns whole image and tile pixel bounds for vision-model reasoning.
        Directory must not contain conflicting output files. No model analysis inside MCP.
        """
        return run('capture_drawing_tiles',directory,sheet,rows,columns,dpi)

    @mcp.tool()
    def get_assembly_tree(max_depth:int=10,limit:int=1000) -> dict:
        """Read recursive API7 assembly components, paths, names, placement origins,
        fixed/hidden status and handles. Placements parent-local, limits prevent huge trees.
        """
        return run('get_assembly_tree',max_depth,limit)

    @mcp.tool()
    def add_component(path:str,position:list[float]=[0,0,0],external:bool=True) -> dict:
        """Insert saved part/assembly file into active assembly and set translation mm.
        external=true retains source link. Does not modify the component source file.
        """
        return run('add_component',path,position,external)

    @mcp.tool()
    def set_component_placement(component_id:str,position:list[float],x_axis:list[float]|None=None,
                                 y_axis:list[float]|None=None,fixed:bool|None=None) -> dict:
        """Set component parent-local translation and optional X/Y axes; optional
        fixed flag. Axes must be nonzero and orthogonal and are normalized. Native mates
        may constrain movement; inspect result and assembly tree.
        """
        return run('set_component_placement',component_id,position,x_axis,y_axis,fixed)

    @mcp.tool()
    def selection(operation:Literal['get','clear','select']='get',object_ids:list[str]=[]) -> dict:
        """API7 3D selection read/clear/select. Requires API7 model-object handles
        (e.g. components). API5 geometric entities may require conversion via generic API.
        """
        return run('selection',operation,object_ids)
