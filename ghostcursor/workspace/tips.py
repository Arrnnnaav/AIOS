"""A rotating "did you know" tip -- quiet discoverability so people find Orbyn's
commands by delight rather than reading a manual. Pure and local; shown once at
console start and on /tip.
"""

from __future__ import annotations

import random

TIPS = (
    "Try  /do <task>  -- Orbyn picks the right capability and runs it.",
    'Say  /skill from "<need>"  and Orbyn drafts a reusable skill for it.',
    "/deepresearch <q>  researches in parts and files cited facts to your Brain.",
    "/convert report.pdf txt  turns a PDF into text, entirely on your machine.",
    "/guide  turns your current plan into a shareable step-by-step SOP.",
    "/know private-source 1Password  -- new facts from it stay off every model.",
    "/dictate brain  saves what you say straight into your Company Brain.",
    "/researchdeck <topic>  researches, then builds a grounded slide outline.",
    "Press ESC any time Orbyn is acting -- it stops cleanly between steps.",
    "/doctor  shows what's ready and the one thing to switch on for each gap.",
    "Mistype a /command and Orbyn suggests the closest one -- no manual needed.",
    "/clips  shows recent clipboard history; /clips 2 puts entry 2 back.",
    "/snippet save sig <text>  then  /snippet sig  copies it to the clipboard.",
    "/capture  makes Ctrl+Alt+C grab the clipboard to a log from any app.",
)


def tip(rng: random.Random | None = None) -> str:
    """One random tip. Pass a seeded Random for a deterministic pick."""

    return (rng or random).choice(TIPS)
