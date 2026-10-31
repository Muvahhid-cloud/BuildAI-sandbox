"""Component catalog records: families, types, assemblies, role mappings (Phase 3.5 K2).

These are catalog records with the same provenance and review lifecycle as knowledge items.
The layout engine never reads them: `catalog.resolver` turns APPROVED records into a
`building.types.TypeSet` (snapshots) that the generation pipeline passes to the engine.

Type parameters reuse the model's typed shapes (`building.types.TypeParams`), so a catalog type
and the snapshot copied into a model can never disagree on structure. Lengths are meters.
"""

from typing import Annotated

from pydantic import Field, StringConstraints

from app.modules.building.design import (
    DesignFacade,
    DesignFinishes,
    DesignRoof,
    DesignWindows,
    FurniturePalette,
)
from app.modules.building.specification import (
    ArchitecturalStyle,
    DesignSystemRef,
    InteriorStyle,
)
from app.modules.building.types import (
    AssemblyId,
    AssemblyKind,
    Layer,
    TypeId,
    TypeParams,
)
from app.modules.catalog.provenance import (
    KnowledgeModel,
    Paraphrase,
    Provenanced,
    ShortText,
    Usage,
)
from app.modules.catalog.schemas import ItemId

FamilyId = Annotated[str, StringConstraints(pattern=r"^family\.[a-z0-9_]+(\.[a-z0-9_]+)*$")]
MappingId = Annotated[str, StringConstraints(pattern=r"^mapping\.[a-z0-9_]+(\.[a-z0-9_]+)*$")]
ItemRef = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*@[1-9][0-9]*:[a-z][a-z0-9_.]*$")
]


class FamilyRecord(Provenanced):
    id: FamilyId
    name: ShortText
    element_type: ShortText  # a BuildingModel element type (checked by integrity)
    class_ref: ItemId  # ontology class
    description: Paraphrase | None = None


class DerivedFrom(KnowledgeModel):
    """What a type's values come from. Knowledge refs gate resolution: every referenced item
    must be approved before the type can be used."""

    knowledge: list[ItemRef] = Field(default_factory=list)
    layout_config: list[ShortText] = Field(default_factory=list)  # migrated engine defaults


class TypeRecord(Provenanced):
    id: TypeId
    family: FamilyId
    name: ShortText
    params: TypeParams
    assembly: AssemblyId | None = None
    derived_from: DerivedFrom = Field(default_factory=DerivedFrom)
    usage: Usage = Usage.RUNTIME_CANDIDATE


class AssemblyRecord(Provenanced):
    id: AssemblyId
    kind: AssemblyKind
    name: ShortText
    layers: list[Layer] = Field(min_length=1)
    total_thickness: float = Field(ge=0)
    derived_from: DerivedFrom = Field(default_factory=DerivedFrom)


class RoleMapping(Provenanced):
    """Which type fills each layout role (the seam K3 design systems build on)."""

    id: MappingId
    name: ShortText
    roles: dict[str, TypeId]


class DesignSystemRecord(Provenanced):
    """A coherent, editorial set of compatible choices (K3; resolution in design_systems.py).

    Allow-lists plus defaults; types come only through `role_mapping`. Region-neutral, not a
    building code and not engineering data."""

    id: DesignSystemRef
    name: ShortText
    description: Paraphrase
    style_tags: list[ArchitecturalStyle] = Field(min_length=1)
    interior_styles: list[InteriorStyle] = Field(min_length=1)
    role_mapping: MappingId
    roof: DesignRoof
    windows: DesignWindows
    facade: DesignFacade
    finishes: DesignFinishes
    furniture: FurniturePalette


class ComponentsDocument(KnowledgeModel):
    families: list[FamilyRecord] = Field(default_factory=list)
    types: list[TypeRecord] = Field(default_factory=list)
    assemblies: list[AssemblyRecord] = Field(default_factory=list)
    role_mappings: list[RoleMapping] = Field(default_factory=list)
    design_systems: list[DesignSystemRecord] = Field(default_factory=list)
