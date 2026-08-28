"""Identity recognition (Mode 1) -- optional, off by default, and
deliberately not built out beyond this seam yet.

A real Mode 1 needs encrypted embedding storage, an explicit
consent-driven enrollment flow, and secure deletion of enrolled
profiles. None of that is worth building before the anonymous-mode
pipeline it plugs into is solid -- see the project proposal's scope
recommendations, which cut full Mode 1 from the required MVP path.

Anonymous mode (the default) needs none of this: PersonTracker already
gives every visible person a stable, non-identifying track ID for as
long as they're in frame, and that's what the rest of the pipeline
uses when no resolver is configured.
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np

# (frame, bbox) -> enrolled person's name, or None if not recognized.
IdentityResolver = Callable[[np.ndarray, tuple[float, float, float, float]], Optional[str]]


def anonymous_resolver(_frame: np.ndarray, _bbox: tuple[float, float, float, float]) -> Optional[str]:
    """The default resolver: never resolves an identity. Kept as an
    explicit function (rather than just passing None around) so the
    pipeline's identity lookup always goes through one code path,
    whether or not a real Mode 1 resolver is ever plugged in.
    """
    return None
