"""Local USD Preview Surface materials for standard and packed PBR textures."""

from pxr import Gf, Sdf, Usd, UsdShade

from scale_bench.config.models.scene import PbrMaterialConfig


def bind_pbr_material(stage: Usd.Stage, mesh_prim: Usd.Prim, spec: PbrMaterialConfig) -> None:
    # Author below each environment's surface so overrides cannot affect siblings.
    path = mesh_prim.GetParent().GetPath().AppendChild("PBR")
    material = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, path.AppendChild("Shader"))
    shader.CreateIdAttr("UsdPreviewSurface")
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    coordinates = UsdShade.Shader.Define(stage, path.AppendChild("Coordinates"))
    coordinates.CreateIdAttr("UsdPrimvarReader_float2")
    coordinates.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
    for name, texture_path, channel, color_space in (
        ("diffuseColor", spec.base_color_texture, "rgb", "sRGB"),
        ("normal", spec.normal_texture, "rgb", "raw"),
        ("roughness", spec.roughness.path, spec.roughness.channel, "raw"),
        ("metallic", spec.metallic.path, spec.metallic.channel, "raw"),
    ):
        texture = UsdShade.Shader.Define(stage, path.AppendChild(name))
        texture.CreateIdAttr("UsdUVTexture")
        texture.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(texture_path)
        texture.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set(color_space)
        for wrap in ("wrapS", "wrapT"):
            texture.CreateInput(wrap, Sdf.ValueTypeNames.Token).Set("repeat")
        texture.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
            coordinates.ConnectableAPI(), "result",
        )
        if name == "normal":
            texture.CreateInput("scale", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(2, 2, 2, 1))
            texture.CreateInput("bias", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(-1, -1, -1, 0))
        value_type = Sdf.ValueTypeNames.Float3 if channel == "rgb" else Sdf.ValueTypeNames.Float
        texture.CreateOutput(channel, value_type)
        shader.CreateInput(name, value_type).ConnectToSource(texture.ConnectableAPI(), channel)
    UsdShade.MaterialBindingAPI.Apply(mesh_prim).Bind(material)
