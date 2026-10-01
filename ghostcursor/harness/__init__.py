"""The application-agnostic harness (D164): bind several exact windows, observe
their real controls as one frame, and let a model refer to them only by
frame-local ids. Step 2 of the harness track; no UI is wired yet."""

from ghostcursor.harness.binding import (
    DENYLIST,
    MAX_WINDOWS,
    BindableWindow,
    BindingError,
    Identity,
    WindowBinding,
    bind,
    bindable_windows,
    still_bound,
)
from ghostcursor.harness.frame import (
    ALLOWED_TYPES,
    MAX_CANDIDATES,
    Candidate,
    ObservationFrame,
    RawControl,
    WindowObservation,
    build_frame,
    region_of,
    resolve,
)

__all__ = [
    "ALLOWED_TYPES",
    "BindableWindow",
    "BindingError",
    "Candidate",
    "DENYLIST",
    "Identity",
    "MAX_CANDIDATES",
    "MAX_WINDOWS",
    "ObservationFrame",
    "RawControl",
    "WindowBinding",
    "WindowObservation",
    "bind",
    "bindable_windows",
    "build_frame",
    "region_of",
    "resolve",
    "still_bound",
]
