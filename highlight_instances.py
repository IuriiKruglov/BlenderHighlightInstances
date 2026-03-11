"""
================================================================================
  Highlight Instances — Blender Addon
  Version: 1.0.0

  Created by Claude (Anthropic) under the direction of Kruglov Iurii.

  Development history:
    - Addon use a GPU draw handler overlay (gpu + gpu_extras), avoiding
      any modification of scene materials entirely.
    - Red and blue hue ranges excluded from random color generation for better
      visual contrast against common scene backgrounds and Blender UI colors.
    - Shell thickness added: a second GPU draw pass with vertices offset along
      normals produces a visible colored rim on each highlighted instance.
    - Face culling removed from both draw passes so all faces render regardless
      of normal orientation.
    - Per-group select buttons added to the N-panel instance list, allowing any
      group to be selected directly without requiring a prior viewport click.
================================================================================
"""

bl_info = {
    "name": "Highlight Instances",
    "author": "Claude (Anthropic), directed by Kruglov Iurii",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Instances",
    "description": "Highlight all instances of the same object using viewport overlays",
    "category": "Object",
}

import bpy
import gpu
import random
import colorsys
from gpu_extras.batch import batch_for_shader
from bpy.props import BoolProperty, StringProperty


# ─── Global state ─────────────────────────────────────────────────────────────
# Module-level dicts persist across operator calls within a Blender session.

_draw_handle = None         # Reference to the registered SpaceView3D draw handler
_instance_colors = {}       # Maps data_name -> (r, g, b, a) per instance group
_instance_groups = {}       # Maps data_name -> [obj, ...] per instance group

SHELL_OFFSET = 0.01         # Vertex normal offset in metres for the shell thickness pass


# ─── Stage 1: Color generation ────────────────────────────────────────────────
# Produces vivid random colors while excluding red and blue hue ranges,
# which are too easily confused with Blender's selection and axis indicators.

def random_color(alpha=0.10):
    # HSV hue ranges excluded:
    #   Red:  0.00–0.05  and  0.95–1.00
    #   Blue: 0.55–0.72
    # Allowed bands: yellows, greens, cyans, magentas, purples
    allowed = [(0.05, 0.55), (0.72, 0.95)]
    segment = random.choice(allowed)
    hue = random.uniform(segment[0], segment[1])
    r, g, b = colorsys.hsv_to_rgb(hue, 0.9, 1.0)
    return (r, g, b, alpha)


# ─── Stage 2: Instance collection ─────────────────────────────────────────────
# Scans all scene objects and groups them by shared mesh data-block name.
# Only groups with 2+ members (actual linked duplicates) are retained.

def collect_instances(scene):
    groups = {}
    for obj in scene.objects:
        if obj.type not in ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'VOLUME'):
            continue
        if obj.data is None:
            continue
        groups.setdefault(obj.data.name, []).append(obj)
    return {k: v for k, v in groups.items() if len(v) > 1}


def refresh_groups(scene):
    """Re-scan the scene and assign colors to any newly discovered groups."""
    global _instance_groups, _instance_colors
    _instance_groups = collect_instances(scene)
    # Assign colors to new groups; preserve colors for existing ones
    for key in _instance_groups:
        if key not in _instance_colors:
            _instance_colors[key] = random_color()
    # Drop colors for groups that no longer exist in the scene
    stale = [k for k in _instance_colors if k not in _instance_groups]
    for k in stale:
        del _instance_colors[k]


def randomize_colors():
    """Re-roll all group colors with fresh random values."""
    global _instance_colors
    _instance_colors = {k: random_color() for k in _instance_groups}


# ─── Stage 3: GPU mesh data preparation ───────────────────────────────────────
# Builds world-space vertex coordinates and triangle index lists for a mesh.
# Accepts an optional per-vertex normal offset used by the shell thickness pass.

def _get_mesh_data(obj, offset=0.0):
    mesh = obj.data
    matrix = obj.matrix_world
    mesh.calc_normals()
    mesh.calc_loop_triangles()
    if not mesh.loop_triangles:
        return None, None
    if offset != 0.0:
        # Displace each vertex outward along its averaged vertex normal
        coords = [matrix @ (v.co + v.normal * offset) for v in mesh.vertices]
    else:
        coords = [matrix @ v.co for v in mesh.vertices]
    indices = [tri.vertices[:] for tri in mesh.loop_triangles]
    return coords, indices


# ─── Stage 4: GPU draw callback ───────────────────────────────────────────────
# Registered as a POST_VIEW draw handler on SpaceView3D.
# Runs on every viewport redraw and renders two layered passes per object:
#   Pass 1 — base fill at the original mesh surface (low alpha)
#   Pass 2 — shell pass at SHELL_OFFSET along normals for visible thickness

def draw_callback():
    if not _instance_groups:
        return
    context = bpy.context
    if not hasattr(context, 'scene'):
        return
    props = context.scene.highlight_instances_props
    if not props.is_active:
        return
    if context.region_data is None:
        return

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')

    for data_name, objects in _instance_groups.items():
        color = _instance_colors.get(data_name, (1, 1, 1, 0.3))
        # Shell pass uses a more opaque variant of the same hue
        shell_color = (color[0], color[1], color[2], min(color[3] + 0.3, 0.9))

        for obj in objects:
            if obj.type != 'MESH' or obj.data is None:
                continue
            if not obj.data.polygons:
                continue

            coords, indices = _get_mesh_data(obj, offset=0.0)
            if coords is None:
                continue
            coords_shell, _ = _get_mesh_data(obj, offset=SHELL_OFFSET)

            # Pass 1: base fill — semi-transparent layer at the original surface
            gpu.state.blend_set('ALPHA')
            gpu.state.depth_test_set('LESS_EQUAL')
            gpu.state.face_culling_set('NONE')
            shader.bind()
            shader.uniform_float("color", color)
            batch_for_shader(shader, 'TRIS', {"pos": coords}, indices=indices).draw(shader)

            # Pass 2: shell — denser color on the offset surface for rim thickness
            gpu.state.face_culling_set('NONE')
            shader.uniform_float("color", shell_color)
            batch_for_shader(shader, 'TRIS', {"pos": coords_shell}, indices=indices).draw(shader)

    # Reset all modified GPU state to defaults after drawing
    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('NONE')
    gpu.state.face_culling_set('NONE')


# ─── Stage 5: Draw handler lifecycle ──────────────────────────────────────────
# Registers and unregisters the GPU callback; triggers viewport redraws.

def register_draw_handler():
    global _draw_handle
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback, (), 'WINDOW', 'POST_VIEW'
        )


def unregister_draw_handler():
    global _draw_handle
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None


def redraw_viewports():
    """Tag all 3D viewports for redraw."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


# ─── Stage 6: Operators ───────────────────────────────────────────────────────
# Operators expose all addon functionality to the UI and keyboard shortcuts.

class OBJECT_OT_highlight_instances(bpy.types.Operator):
    bl_idname = "object.highlight_instances"
    bl_label = "Highlight Instances"
    bl_description = "Toggle colored overlay for all instance groups"

    def execute(self, context):
        props = context.scene.highlight_instances_props
        if props.is_active:
            props.is_active = False
            unregister_draw_handler()
            self.report({'INFO'}, "Instance highlight off")
        else:
            refresh_groups(context.scene)
            register_draw_handler()
            props.is_active = True
            self.report({'INFO'}, f"Highlighting {len(_instance_groups)} group(s)")
        redraw_viewports()
        return {'FINISHED'}


class OBJECT_OT_refresh_instance_colors(bpy.types.Operator):
    bl_idname = "object.refresh_instance_colors"
    bl_label = "Randomize Colors"
    bl_description = "Assign new random colors to all instance groups"

    def execute(self, context):
        if not context.scene.highlight_instances_props.is_active:
            self.report({'WARNING'}, "Enable highlight first")
            return {'CANCELLED'}
        refresh_groups(context.scene)
        randomize_colors()
        redraw_viewports()
        self.report({'INFO'}, "Colors randomized")
        return {'FINISHED'}


class OBJECT_OT_refresh_instance_groups(bpy.types.Operator):
    bl_idname = "object.refresh_instance_groups"
    bl_label = "Refresh Groups"
    bl_description = "Re-scan the scene for instance groups"

    def execute(self, context):
        if not context.scene.highlight_instances_props.is_active:
            self.report({'WARNING'}, "Enable highlight first")
            return {'CANCELLED'}
        refresh_groups(context.scene)
        redraw_viewports()
        self.report({'INFO'}, f"Found {len(_instance_groups)} group(s)")
        return {'FINISHED'}


class OBJECT_OT_select_instance_group(bpy.types.Operator):
    bl_idname = "object.select_instance_group"
    bl_label = "Select Active Group"
    bl_description = "Select all objects sharing the active object's data"

    def execute(self, context):
        active = context.active_object
        if active is None or active.data is None:
            self.report({'WARNING'}, "No active object")
            return {'CANCELLED'}
        key = active.data.name
        bpy.ops.object.select_all(action='DESELECT')
        count = 0
        for obj in context.scene.objects:
            if obj.data and obj.data.name == key:
                obj.select_set(True)
                count += 1
        self.report({'INFO'}, f"Selected {count} instance(s) of '{key}'")
        return {'FINISHED'}


class OBJECT_OT_select_instance_group_by_name(bpy.types.Operator):
    bl_idname = "object.select_instance_group_by_name"
    bl_label = "Select Group"
    bl_description = "Select all instances of this group"

    # Receives the target data-block name from the panel button that invoked it
    data_name: StringProperty()

    def execute(self, context):
        if not self.data_name:
            return {'CANCELLED'}
        bpy.ops.object.select_all(action='DESELECT')
        count = 0
        for obj in context.scene.objects:
            if obj.data and obj.data.name == self.data_name:
                obj.select_set(True)
                count += 1
        # Make the first matched object the active object
        for obj in context.scene.objects:
            if obj.data and obj.data.name == self.data_name:
                context.view_layer.objects.active = obj
                break
        self.report({'INFO'}, f"Selected {count} instance(s) of '{self.data_name}'")
        return {'FINISHED'}


# ─── Stage 7: Properties ──────────────────────────────────────────────────────
# Scene-level property group stores the persistent on/off state of the overlay.

class HighlightInstancesProperties(bpy.types.PropertyGroup):
    is_active: BoolProperty(name="Is Active", default=False)


# ─── Stage 8: UI Panel ────────────────────────────────────────────────────────
# Draws the addon interface in the N-panel (View3D sidebar) under "Instances".

class VIEW3D_PT_highlight_instances(bpy.types.Panel):
    bl_label = "Highlight Instances"
    bl_idname = "VIEW3D_PT_highlight_instances"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Instances"

    def draw(self, context):
        layout = self.layout
        props = context.scene.highlight_instances_props

        # Main highlight toggle button
        row = layout.row(align=True)
        if props.is_active:
            row.operator("object.highlight_instances",
                         text="Remove Highlight", icon="HIDE_ON", depress=True)
        else:
            row.operator("object.highlight_instances",
                         text="Highlight Instances", icon="HIDE_OFF")

        # Utility row: re-roll colors and re-scan scene for new instances
        row2 = layout.row(align=True)
        row2.enabled = props.is_active
        row2.operator("object.refresh_instance_colors", icon="FILE_REFRESH")
        row2.operator("object.refresh_instance_groups", icon="LOOP_BACK")

        layout.separator()

        # Instance group list — each row has a per-group select button
        groups = _instance_groups if props.is_active else collect_instances(context.scene)
        if groups:
            box = layout.box()
            box.label(text=f"{len(groups)} instance group(s):", icon="OBJECT_DATA")
            for data_name, objects in sorted(groups.items()):
                row = box.row(align=True)
                row.label(text=f"{data_name}  x{len(objects)}", icon="MESH_DATA")
                op = row.operator(
                    "object.select_instance_group_by_name",
                    text="",
                    icon="RESTRICT_SELECT_OFF",
                )
                op.data_name = data_name
        else:
            layout.label(text="No instances found.", icon="INFO")

        layout.separator()
        # Fallback: select the group of whatever object is currently active
        layout.operator("object.select_instance_group", icon="OBJECT_DATA")


# ─── Stage 9: Registration ────────────────────────────────────────────────────
# Standard Blender register/unregister. Cleans up the draw handler and removes
# scene properties to avoid dangling references on addon disable.

classes = (
    HighlightInstancesProperties,
    OBJECT_OT_highlight_instances,
    OBJECT_OT_refresh_instance_colors,
    OBJECT_OT_refresh_instance_groups,
    OBJECT_OT_select_instance_group,
    OBJECT_OT_select_instance_group_by_name,
    VIEW3D_PT_highlight_instances,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.highlight_instances_props = bpy.props.PointerProperty(
        type=HighlightInstancesProperties
    )


def unregister():
    unregister_draw_handler()
    for scene in bpy.data.scenes:
        if hasattr(scene, 'highlight_instances_props'):
            scene.highlight_instances_props.is_active = False
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.highlight_instances_props


if __name__ == "__main__":
    register()
