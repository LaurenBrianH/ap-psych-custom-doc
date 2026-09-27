// ============================================================================
// main.typ — MASTER document for the AP Psychology knowledge base.
//
// CONTENT LIVES ONLY IN units/*/_unit.typ — never add entries here.
// The build pipeline (build/build.py) queries this file for <knowledge>
// metadata; keep it compilable at all times.
//
// Note: besides the five College Board units there is a foundational
// "Unit 0 — Research Design (Research Methods)" directory
// (units/00-research-methods), matching the master reference framework and
// the knowledge(unit: 0) default. It is assessed across all five exam units.
// ============================================================================
#import "lib.typ": theme
#show: theme
#include "units/00-research-methods/_unit.typ"
#include "units/01-biological/_unit.typ"
#include "units/02-cognition/_unit.typ"
#include "units/03-development-learning/_unit.typ"
#include "units/04-social-personality/_unit.typ"
#include "units/05-mental-physical-health/_unit.typ"
