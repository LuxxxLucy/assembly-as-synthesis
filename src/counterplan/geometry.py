"""2D polygonal block geometry and contact detection."""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from shapely.geometry import Polygon, LineString
from shapely.ops import nearest_points


@dataclass
class Block:
    """A 2D polygonal block with an ID and vertices."""
    id: int
    vertices: np.ndarray  # (n, 2) CCW-ordered polygon vertices
    mass: float = 1.0

    @property
    def polygon(self) -> Polygon:
        return Polygon(self.vertices)

    @property
    def centroid(self) -> np.ndarray:
        c = self.polygon.centroid
        return np.array([c.x, c.y])

    @property
    def area(self) -> float:
        return self.polygon.area

    def translated(self, dx: float, dy: float) -> Block:
        """Return a copy with vertices shifted by (dx, dy)."""
        return Block(
            id=self.id,
            vertices=self.vertices + np.array([dx, dy]),
            mass=self.mass,
        )

    def with_vertex_displacement(self, displacements: np.ndarray) -> Block:
        """Return a copy with vertex positions displaced."""
        return Block(
            id=self.id,
            vertices=self.vertices + displacements,
            mass=self.mass,
        )


@dataclass
class Contact:
    """A contact between two blocks."""
    block_a: int  # block ID
    block_b: int  # block ID (-1 = ground)
    point: np.ndarray  # (2,) contact point
    normal: np.ndarray  # (2,) outward normal from block_b surface (pointing into block_a)

    def __post_init__(self):
        # Normalize
        n = np.linalg.norm(self.normal)
        if n > 0:
            self.normal = self.normal / n


@dataclass
class Structure:
    """A collection of blocks with ground plane."""
    blocks: list[Block]
    ground_y: float = 0.0
    _contact_cache: list[Contact] | None = field(default=None, repr=False)

    def block_by_id(self, block_id: int) -> Block:
        for b in self.blocks:
            if b.id == block_id:
                return b
        raise ValueError(f"No block with id {block_id}")

    def detect_contacts(self, placed_ids: list[int] | None = None, tol: float = 1e-4) -> list[Contact]:
        """Detect contacts between placed blocks and with the ground.

        A contact exists where two block edges overlap or are within `tol` distance.
        For ground contacts, any vertex at y <= ground_y + tol creates a contact.
        """
        if placed_ids is None:
            placed_ids = [b.id for b in self.blocks]

        blocks = [self.block_by_id(i) for i in placed_ids]
        contacts: list[Contact] = []

        # Ground contacts
        for b in blocks:
            verts_on_ground = b.vertices[b.vertices[:, 1] <= self.ground_y + tol]
            if len(verts_on_ground) >= 2:
                # Use leftmost and rightmost ground vertices as contact points
                left = verts_on_ground[np.argmin(verts_on_ground[:, 0])]
                right = verts_on_ground[np.argmax(verts_on_ground[:, 0])]
                contacts.append(Contact(
                    block_a=b.id, block_b=-1,
                    point=left.copy(),
                    normal=np.array([0.0, 1.0]),
                ))
                if np.linalg.norm(left - right) > tol:
                    contacts.append(Contact(
                        block_a=b.id, block_b=-1,
                        point=right.copy(),
                        normal=np.array([0.0, 1.0]),
                    ))
            elif len(verts_on_ground) == 1:
                contacts.append(Contact(
                    block_a=b.id, block_b=-1,
                    point=verts_on_ground[0].copy(),
                    normal=np.array([0.0, 1.0]),
                ))

        # Block-block contacts via shared edges
        for i, ba in enumerate(blocks):
            for bb in blocks[i + 1:]:
                block_contacts = _detect_block_contacts(ba, bb, tol)
                contacts.extend(block_contacts)

        return contacts


def _detect_block_contacts(ba: Block, bb: Block, tol: float) -> list[Contact]:
    """Detect contact points between two blocks.

    Strategy: find edges of ba and bb that are nearly collinear and overlapping.
    The contact normal is perpendicular to the shared edge, pointing from the
    lower block toward the upper block.
    """
    contacts = []
    edges_a = _edges(ba.vertices)
    edges_b = _edges(bb.vertices)

    for ea_start, ea_end in edges_a:
        for eb_start, eb_end in edges_b:
            # Check if edges are nearly collinear and overlapping
            shared = _shared_edge_segment(ea_start, ea_end, eb_start, eb_end, tol)
            if shared is not None:
                p1, p2 = shared
                # Normal: perpendicular to edge, pointing from lower centroid to upper
                edge_dir = ea_end - ea_start
                edge_dir = edge_dir / np.linalg.norm(edge_dir)
                normal = np.array([-edge_dir[1], edge_dir[0]])

                # Orient normal so it points from bb toward ba (into the upper block)
                mid = (p1 + p2) / 2
                ca = ba.centroid
                cb = bb.centroid
                if np.dot(normal, ca - mid) < 0:
                    normal = -normal

                contacts.append(Contact(block_a=ba.id, block_b=bb.id, point=p1.copy(), normal=normal.copy()))
                if np.linalg.norm(p1 - p2) > tol:
                    contacts.append(Contact(block_a=ba.id, block_b=bb.id, point=p2.copy(), normal=normal.copy()))

    return contacts


def _edges(vertices: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """Return list of (start, end) edge pairs from CCW vertices."""
    n = len(vertices)
    return [(vertices[i], vertices[(i + 1) % n]) for i in range(n)]


def _shared_edge_segment(
    a0: np.ndarray, a1: np.ndarray,
    b0: np.ndarray, b1: np.ndarray,
    tol: float,
) -> tuple[np.ndarray, np.ndarray] | None:
    """If edges (a0,a1) and (b0,b1) are collinear and overlap, return the shared segment endpoints."""
    # Edge direction of a
    da = a1 - a0
    la = np.linalg.norm(da)
    if la < tol:
        return None
    da_hat = da / la

    # Check b endpoints are close to line through a
    def dist_to_line(p):
        v = p - a0
        proj = np.dot(v, da_hat)
        perp = v - proj * da_hat
        return np.linalg.norm(perp)

    if dist_to_line(b0) > tol or dist_to_line(b1) > tol:
        return None

    # Project all 4 points onto the a-edge direction
    t_a0 = 0.0
    t_a1 = la
    t_b0 = np.dot(b0 - a0, da_hat)
    t_b1 = np.dot(b1 - a0, da_hat)

    t_b_min = min(t_b0, t_b1)
    t_b_max = max(t_b0, t_b1)

    # Overlap
    t_start = max(t_a0, t_b_min)
    t_end = min(t_a1, t_b_max)

    if t_end - t_start < tol:
        return None

    p_start = a0 + t_start * da_hat
    p_end = a0 + t_end * da_hat
    return (p_start, p_end)
