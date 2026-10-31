"""Closed vocabularies of the building model (serialized as snake_case strings)."""

from enum import StrEnum


class Layer(StrEnum):
    """Discipline layer. Every element belongs to exactly one.

    Phase 1 populates architecture, structure and furniture; the others are reserved so the
    viewer's layer manager and the schema don't change when MEP/site work lands.
    """

    ARCHITECTURE = "architecture"
    STRUCTURE = "structure"
    FURNITURE = "furniture"
    PLUMBING = "plumbing"
    ELECTRICAL = "electrical"
    HVAC = "hvac"
    FIRE_SAFETY = "fire_safety"
    LANDSCAPING = "landscaping"


class Origin(StrEnum):
    GENERATED = "generated"  # produced by the layout / MEP engines
    USER = "user"  # authored by a person (incl. hand-authored fixtures)


class RelationshipKind(StrEnum):
    HOSTED_BY = "hosted_by"  # door/window -> wall
    BOUNDS = "bounds"  # wall -> room
    ADJACENT_TO = "adjacent_to"  # room -> room (shared boundary edge)
    CONNECTS = "connects"  # door -> room
    SUPPORTS = "supports"  # wall/column/beam -> slab/roof
    LOCATED_IN = "located_in"  # furniture/stair -> room
    SERVES = "serves"  # fixture/terminal/equipment -> room (MEP, later)
    CONNECTED_TO = "connected_to"  # MEP network topology (later)
    PART_OF_SYSTEM = "part_of_system"  # MEP element -> system (later)


class WallKind(StrEnum):
    EXTERIOR = "exterior"
    INTERIOR = "interior"
    PARTITION = "partition"


class WallAlignment(StrEnum):
    CENTER = "center"
    LEFT = "left"
    RIGHT = "right"


class RoomType(StrEnum):
    ENTRANCE = "entrance"
    HALL = "hall"
    CORRIDOR = "corridor"
    STAIRCASE = "staircase"
    LIVING = "living"
    DINING = "dining"
    KITCHEN = "kitchen"
    OPEN_KITCHEN_LIVING = "open_kitchen_living"
    BEDROOM = "bedroom"
    BATHROOM = "bathroom"
    WC = "wc"
    EN_SUITE = "en_suite"
    STUDY = "study"
    LAUNDRY = "laundry"
    UTILITY = "utility"
    STORAGE = "storage"
    WALK_IN_CLOSET = "walk_in_closet"
    GARAGE = "garage"
    PLANT_ROOM = "plant_room"
    BALCONY = "balcony"
    TERRACE = "terrace"


class Zone(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    SERVICE = "service"
    CIRCULATION = "circulation"
    EXTERIOR = "exterior"


class DoorKind(StrEnum):
    ENTRANCE = "entrance"
    INTERIOR = "interior"
    SLIDING = "sliding"
    GARAGE = "garage"


class DoorSwing(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    DOUBLE = "double"
    SLIDING = "sliding"


class WindowKind(StrEnum):
    FIXED = "fixed"
    CASEMENT = "casement"
    SLIDING = "sliding"
    PANORAMIC = "panoramic"


class SlabKind(StrEnum):
    GROUND = "ground"
    FLOOR = "floor"
    BALCONY = "balcony"


class RoofType(StrEnum):
    FLAT = "flat"
    GABLE = "gable"
    HIP = "hip"


class StairType(StrEnum):
    STRAIGHT = "straight"


class RailingKind(StrEnum):
    GLASS = "glass"
    BARS = "bars"


class FurnitureKind(StrEnum):
    SOFA = "sofa"
    ARMCHAIR = "armchair"
    COFFEE_TABLE = "coffee_table"
    TV_UNIT = "tv_unit"
    DINING_TABLE = "dining_table"
    CHAIR = "chair"
    BED = "bed"
    NIGHTSTAND = "nightstand"
    WARDROBE = "wardrobe"
    BOOKSHELF = "bookshelf"
    DESK = "desk"
    KITCHEN_COUNTER = "kitchen_counter"
    KITCHEN_ISLAND = "kitchen_island"
    FRIDGE = "fridge"
    TOILET = "toilet"
    BASIN = "basin"
    BATHTUB = "bathtub"
    SHOWER = "shower"
